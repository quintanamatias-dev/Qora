"""QORA Voice — Custom LLM webhook (the core of QORA).

ElevenLabs sends a full OpenAI-compatible chat completion request here.
This endpoint:
1. Extracts client_id + lead_id from elevenlabs_extra_body.
2. Loads tenant config.
3. Loads lead context.
4. Streams GPT-4o via SSE.
5. Handles tool calls mid-stream (intercepts, executes, re-calls GPT-4o).
6. Persists transcript turns.
7. Ends with data: [DONE].

Covers: CAP-1 SSE stream, CAP-4 tool calls, CAP-5 filler, CAP-6 tenant routing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

if TYPE_CHECKING:
    from app.voice.context import VoiceSessionContext
    from app.voice.session import ConversationState

import httpx as _httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai.llm_streaming import (
    ContentDelta,
    OpenAIStreamingClient,
    StreamDone,
    ToolCallDelta,
)
from app.calls.service import (
    add_transcript_turn,
    create_session,
    schedule_user_turn_persist,
)
from app.core.database import get_session as db_session
from app.leads.service import get_lead
from app.prompts.loader import PromptLoader
from app.tenants.service import get_client, get_default_agent
from app.tools.registry import (
    TOOL_DEFINITIONS,
    TOOL_FILLER_PHRASES,
    DEFAULT_FILLER,
    build_tool_definitions as _build_tool_definitions,
)
from app.voice.context import build_voice_context
from app.voice.session import session_store

QORA_TOOL_DEFINITIONS = TOOL_DEFINITIONS

router = APIRouter(prefix="/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Signed URL endpoint — generates a WebSocket signed URL for the demo
# ---------------------------------------------------------------------------


@router.get("/signed-url")
async def get_signed_url(request: Request):
    """Generate a signed URL for ElevenLabs WebSocket connection.

    Using signed URL forces WebSocket (not WebRTC) regardless of agent settings.
    """
    try:
        settings = request.app.state.settings
        api_key = settings.elevenlabs_api_key.get_secret_value()
        agent_id = settings.elevenlabs_agent_id
    except AttributeError:
        from app.core.config import Settings

        s = Settings()
        api_key = s.elevenlabs_api_key.get_secret_value()
        agent_id = s.elevenlabs_agent_id

    if not agent_id:
        raise HTTPException(
            status_code=400, detail="ELEVENLABS_AGENT_ID not configured in .env"
        )

    async with _httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id={agent_id}",
            headers={"xi-api-key": api_key},
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code, detail=f"ElevenLabs error: {resp.text}"
            )

        data = resp.json()
        return {"signed_url": data.get("signed_url")}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ElevenLabsExtraBody(BaseModel):
    """Extra fields injected by ElevenLabs into the custom LLM request.

    When using the ElevenLabs WebSocket native protocol (no SDK customLlmExtraBody),
    ElevenLabs does NOT send this field. client_id defaults to None; the endpoint
    tries elevenlabs_extra_body → top-level field → model_extra in that order and
    returns HTTP 422 if client_id is not found in any source.
    """

    client_id: str | None = None
    lead_id: str | None = None
    conversation_id: str | None = None


class CustomLLMRequest(BaseModel):
    """OpenAI-compatible chat completion request from ElevenLabs."""

    model: str = "gpt-4o"
    messages: list[dict[str, Any]]
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = 300
    tools: list[dict] | None = None
    # ElevenLabs sends this when customLlmExtraBody is configured in the agent
    # Falls back to empty ElevenLabsExtraBody when not present
    elevenlabs_extra_body: ElevenLabsExtraBody = Field(
        default_factory=ElevenLabsExtraBody
    )
    client_id: str | None = None
    lead_id: str | None = None
    conversation_id: str | None = None

    model_config = {"extra": "allow"}  # Accept any extra fields ElevenLabs sends


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_chunk(content: str) -> str:
    """Format a content token as an OpenAI-compatible SSE chunk."""
    payload = {
        "id": "chatcmpl-qora",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse_done() -> str:
    """SSE stream terminator."""
    return "data: [DONE]\n\n"


def _sse_stop() -> str:
    """SSE stop chunk with finish_reason=stop."""
    payload = {
        "id": "chatcmpl-qora",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# Filler speech config — emitted to SSE stream BEFORE tool execution
# ---------------------------------------------------------------------------
# TOOL_FILLER_PHRASES and DEFAULT_FILLER are imported from app.tools.registry above.

# Pause between filler TTS emission and tool execution (seconds).
# Gives the TTS engine time to begin speaking before the tool call blocks.
FILLER_PAUSE_SECONDS = 0.7


# ---------------------------------------------------------------------------
# Tool execution (dispatches to tools module)
# ---------------------------------------------------------------------------


async def _execute_tool(
    tool_name: str,
    tool_args: dict,
    client_id: str,
    lead_id: str | None,
    *,
    agent_slug: str | None = None,
    registry_entries: list | None = None,
    clients_dir: Any | None = None,
    agent_tool_config: dict | None = None,
) -> dict:
    """Execute a tool by name and return the result dict.

    For Phase 0, tools are dispatched directly from here.
    Phase 2 adds load_skill support via agent_slug + registry_entries.
    """
    try:
        from app.tools.dispatcher import dispatch_tool

        return await dispatch_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            client_id=client_id,
            lead_id=lead_id,
            agent_slug=agent_slug,
            registry_entries=registry_entries or [],
            clients_dir=clients_dir,
            agent_tool_config=agent_tool_config,
        )
    except ImportError:
        # Tools module not yet implemented — return safe stub
        return {"error": f"tool_not_implemented: {tool_name}"}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Core streaming generator
# ---------------------------------------------------------------------------


async def _stream_llm_response(
    *,
    client: OpenAIStreamingClient,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
    client_id: str,
    lead_id: str | None,
    session_id: str | None,
    conversation_id: str | None,
    agent_slug: str | None = None,
    registry_entries: "list | None" = None,
    conv_state: "ConversationState | None" = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE chunks from GPT-4o, handling tool calls mid-stream.

    Flow:
    1. Start streaming GPT-4o.
    2. Yield content tokens as SSE.
    3. If tool_call detected:
       a. Check if load_skill result is already cached in conv_state.loaded_skills.
          If cached: skip filler, sleep, and tool execution; inject cached content directly.
       b. If not cached: emit filler speech tokens, await asyncio.sleep(FILLER_PAUSE_SECONDS),
          execute tool, and store successful load_skill results in conv_state.loaded_skills.
       c. Re-call GPT-4o with tool result, stream final reply.
    4. Persist transcript turn.
    5. Yield [DONE].

    Args:
        registry_entries: Parsed registry entries for this session. Used to look up
            per-skill filler_text for load_skill calls. Pass [] when not applicable.
        conv_state: Optional ConversationState for the current session. Used to cache
            load_skill results and skip duplicate tool calls on subsequent turns.
    """
    full_response_text = ""

    try:
        async with asyncio.timeout(60.0):  # 60 second max per LLM turn
            async for event in client.stream_events(
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if isinstance(event, ContentDelta):
                    full_response_text += event.text
                    yield _sse_chunk(event.text)

                elif isinstance(event, ToolCallDelta):
                    # Tool call detected — emit filler FIRST, then execute
                    try:
                        args = (
                            json.loads(event.function_args)
                            if event.function_args
                            else {}
                        )
                    except json.JSONDecodeError:
                        args = {}

                    # --- Cache short-circuit for load_skill ---
                    # If this is a load_skill call and the skill is already cached in
                    # conv_state.loaded_skills, skip filler, sleep, and tool execution
                    # entirely — inject the cached content directly into the follow-up.
                    _skill_name_for_cache = (
                        args.get("skill_name", "")
                        if event.function_name == "load_skill"
                        else ""
                    )
                    _cached_skill: str | None = None
                    if (
                        event.function_name == "load_skill"
                        and conv_state is not None
                        and _skill_name_for_cache
                    ):
                        _cached_skill = conv_state.loaded_skills.get(_skill_name_for_cache)

                    if _cached_skill is not None:
                        # Use cached content — no filler, no sleep, no tool call
                        # dispatcher returns raw string for load_skill; match that shape here
                        tool_result = _cached_skill
                    else:
                        # --- Filler speech: emitted BEFORE tool execution ---
                        # For load_skill: use the registry entry's filler_text.
                        # For other tools: use per-tool default from TOOL_FILLER_PHRASES.
                        filler_text: str | None = None
                        if event.function_name == "load_skill":
                            skill_name = args.get("skill_name", "")
                            # Build a fast name→entry lookup
                            _entries = registry_entries or []
                            _reg_by_name = {e.name: e for e in _entries}
                            entry = _reg_by_name.get(skill_name)
                            if entry is not None:
                                filler_text = entry.filler_text
                            else:
                                filler_text = TOOL_FILLER_PHRASES.get("load_skill", DEFAULT_FILLER)
                        else:
                            # For non-load_skill tools: use per-tool phrase if configured,
                            # fall back to DEFAULT_FILLER so the caller always hears something.
                            filler_text = TOOL_FILLER_PHRASES.get(event.function_name, DEFAULT_FILLER)

                        if filler_text:
                            yield _sse_chunk(filler_text)
                            # Pause after filler so TTS has time to begin speaking
                            # before the tool call blocks the stream.
                            await asyncio.sleep(FILLER_PAUSE_SECONDS)

                        tool_result = await _execute_tool(
                            event.function_name,
                            args,
                            client_id=client_id,
                            lead_id=lead_id,
                            agent_slug=agent_slug,
                            registry_entries=registry_entries or [],
                            agent_tool_config=(
                                getattr(conv_state.context, "agent_tool_config", None)
                                if conv_state is not None and conv_state.context is not None
                                else None
                            ),
                        )

                        # After a successful load_skill, store the content in conv_state
                        # so subsequent turns can skip the tool call entirely (AC-2).
                        # dispatch_tool returns a raw string for load_skill:
                        # success → plain markdown string; failure → "Error: ..." string.
                        if (
                            event.function_name == "load_skill"
                            and conv_state is not None
                            and _skill_name_for_cache
                            and isinstance(tool_result, str)
                            and not tool_result.startswith("Error:")
                        ):
                            conv_state.loaded_skills[_skill_name_for_cache] = tool_result

                    # Persist tool_call and tool_result turns BEFORE follow-up LLM call
                    if session_id:
                        try:
                            async with db_session() as db:
                                await add_transcript_turn(
                                    db,
                                    session_id,
                                    "tool_call",
                                    json.dumps(
                                        {"function": event.function_name, "args": args}
                                    ),
                                )
                                await add_transcript_turn(
                                    db,
                                    session_id,
                                    "tool_result",
                                    json.dumps(tool_result),
                                )
                        except Exception as exc:  # noqa: BLE001
                            structlog.get_logger().warning(
                                "tool_turn_persist_failed",
                                error=str(exc),
                                session_id=session_id,
                            )

                    # Build follow-up messages with tool result
                    follow_up_messages = list(messages) + [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": event.tool_call_id or "call_001",
                                    "type": "function",
                                    "function": {
                                        "name": event.function_name,
                                        "arguments": event.function_args,
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": event.tool_call_id or "call_001",
                            "content": json.dumps(tool_result),
                        },
                    ]

                    # Second GPT-4o call for final response
                    async for follow_event in client.stream_events(
                        messages=follow_up_messages,
                        tools=None,  # No more tool calls on follow-up
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ):
                        if isinstance(follow_event, ContentDelta):
                            full_response_text += follow_event.text
                            yield _sse_chunk(follow_event.text)
                        elif isinstance(follow_event, StreamDone):
                            break

                elif isinstance(event, StreamDone):
                    break
    except asyncio.TimeoutError:
        structlog.get_logger().warning(
            "llm_stream_timeout",
            session_id=session_id,
        )
        # Persist any partial transcript accumulated before the timeout
        if session_id and full_response_text:
            try:
                async with db_session() as db:
                    await add_transcript_turn(
                        db, session_id, "agent", full_response_text
                    )
            except Exception as exc:  # noqa: BLE001
                structlog.get_logger().warning(
                    "transcript_persist_failed",
                    error=str(exc),
                    session_id=session_id,
                )
        yield _sse_stop()
        yield _sse_done()
        return

    # Persist transcript turn if we have a session
    if session_id and full_response_text:
        try:
            async with db_session() as db:
                await add_transcript_turn(db, session_id, "agent", full_response_text)
        except Exception as exc:  # noqa: BLE001
            structlog.get_logger().warning(
                "transcript_persist_failed",
                error=str(exc),
                session_id=session_id,
            )

    # Update turn tracking
    if conversation_id and client_id:
        session_store.increment_turn(client_id, conversation_id)

    yield _sse_stop()
    yield _sse_done()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/custom-llm")
@router.post(
    "/custom-llm/chat/completions"
)  # ElevenLabs appends /chat/completions to base URL
@router.post("/chat/completions")  # If base URL is /api/v1/voice
async def custom_llm_webhook(body: CustomLLMRequest, request: Request):
    """Handle ElevenLabs Custom LLM webhook (legacy route).

    Extracts client_id + lead_id from elevenlabs_extra_body.
    Streams GPT-4o response as SSE, handling tool calls mid-stream.

    Returns:
        StreamingResponse with Content-Type: text/event-stream.

    Raises:
        422: If client_id is missing (Pydantic validation).
        404: If client_id does not match any registered tenant.
    """
    # Log the full raw body so we can see exactly what ElevenLabs sends
    structlog.get_logger().info(
        "elevenlabs_request_received",
        body_keys=list(body.model_dump(exclude_unset=False).keys()),
        extra_body=body.elevenlabs_extra_body.model_dump(),
        top_level_client_id=body.client_id,
        model_fields_set=list(body.model_fields_set),
        extra_fields={k: v for k, v in body.model_extra.items()}
        if body.model_extra
        else {},
    )

    # Resolve client_id — try multiple sources.
    # Sources tried in order: elevenlabs_extra_body → top-level field → model_extra.
    # If not found in any source, return 422 (client_id is required).
    extra = body.elevenlabs_extra_body
    client_id: str | None = None
    client_id_source: str | None = None

    if extra.client_id:
        client_id = extra.client_id
        client_id_source = "elevenlabs_extra_body"
    elif body.client_id:
        client_id = body.client_id
        client_id_source = "top_level"
    elif (body.model_extra or {}).get("client_id"):
        client_id = (body.model_extra or {}).get("client_id")
        client_id_source = "model_extra"

    if not client_id:
        raise HTTPException(
            status_code=422,
            detail={"error": "client_id is required"},
        )

    # Resolve conversation_id for deprecation log
    conversation_id = (
        extra.conversation_id
        or body.conversation_id
        or (body.model_extra or {}).get("conversation_id")
    )

    # Emit deprecation warning — every successful legacy route call is logged
    structlog.get_logger().warning(
        "custom_llm_legacy_route_used",
        client_id=client_id,
        conversation_id=conversation_id,
        source=client_id_source,
        migration_hint=f"Use path-based route: /api/v1/voice/{client_id}/custom-llm/chat/completions",
    )

    return await _process_custom_llm_request(
        body=body, client_id=client_id, request=request
    )


# ---------------------------------------------------------------------------
# Path-based route — CAP-1
# ---------------------------------------------------------------------------


@router.post("/{client_id}/custom-llm/chat/completions")
async def custom_llm_path_route(
    client_id: str, body: CustomLLMRequest, request: Request
):
    """Handle ElevenLabs Custom LLM webhook with client_id in URL path (CAP-1).

    Extracts client_id from the URL path parameter (takes precedence over body).
    Streams GPT-4o response as SSE, handling tool calls mid-stream.

    Returns:
        StreamingResponse with Content-Type: text/event-stream.

    Raises:
        404: If client_id does not match any registered tenant.
        403: If the tenant exists but is inactive.
    """
    logger = structlog.get_logger()

    # Detect client_id mismatch between path and body
    extra = body.elevenlabs_extra_body
    body_client_id = (
        extra.client_id or body.client_id or (body.model_extra or {}).get("client_id")
    )
    if body_client_id and body_client_id != client_id:
        logger.warning(
            "client_id_mismatch",
            path_client_id=client_id,
            body_client_id=body_client_id,
        )

    # Resolve conversation_id for the log event
    conversation_id = (
        body.conversation_id
        or extra.conversation_id
        or (body.model_extra or {}).get("conversation_id")
    )

    # Resolve lead_id for the log event (CAP-3 design: log includes lead_id)
    extra_for_log = body.elevenlabs_extra_body
    lead_id_for_log = (
        extra_for_log.lead_id or body.lead_id or (body.model_extra or {}).get("lead_id")
    ) or None

    # Emit structured log for path-based requests
    logger.info(
        "custom_llm_path_request",
        client_id=client_id,
        conversation_id=conversation_id,
        lead_id=lead_id_for_log,
        message_count=len(body.messages),
        model=body.model,
    )

    return await _process_custom_llm_request(
        body=body, client_id=client_id, request=request
    )


# ---------------------------------------------------------------------------
# Context assembly helper — pure function
# ---------------------------------------------------------------------------


def _assemble_context_system_content(
    ctx: "VoiceSessionContext",
    loaded_skills: "dict[str, str] | None" = None,
) -> str:
    """Assemble the full system message content from VoiceSessionContext components.

    Assembly order:
    1. system_prompt (always included)
    2. skills_index (## Available Skills block, when not None/empty)
    3. misc_notes (when not empty)
    4. lead_profile (when not empty and skip_lead_profile_in_assembly is False)
    5. Loaded skill blocks (## Loaded Skill: {name} + content, one per entry)

    Empty components are skipped so no trailing whitespace or stray separators
    are added.

    When ctx.skip_lead_profile_in_assembly is True, the lead_profile block is omitted.
    This happens when the agent uses template vars ({{lead_name}}, etc.) — render_for_agent()
    already substituted lead data into system_prompt, so appending lead_profile would
    duplicate it (Issue #21).

    Note: skills_index replaces the old skills_content field. skills_content is kept
    in the dataclass for backward compatibility but is never injected here.

    Args:
        ctx: The cached VoiceSessionContext for this session.
        loaded_skills: Optional dict of already-loaded skills — keyed by skill_name,
            value is raw skill markdown. When present, each entry is appended as a
            fenced ## Loaded Skill: {name} block after the skills index. Injected in
            insertion order for deterministic output. None or empty dict → no blocks added.

    Returns:
        A single string ready to be used as the system message content.
    """
    parts = [ctx.system_prompt]
    if ctx.skills_index:
        parts.append(ctx.skills_index)
    if ctx.misc_notes:
        parts.append(ctx.misc_notes)
    if ctx.lead_profile and not ctx.skip_lead_profile_in_assembly:
        parts.append(ctx.lead_profile)
    if loaded_skills:
        for skill_name, skill_content in loaded_skills.items():
            parts.append(f"## Loaded Skill: {skill_name}\n{skill_content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Shared helper — ALL business logic lives here
# ---------------------------------------------------------------------------


async def _process_custom_llm_request(
    *, body: CustomLLMRequest, client_id: str, request: Request
) -> StreamingResponse:
    """Shared handler for both legacy and path-based routes.

    Performs tenant lookup, prompt loading, session management, and SSE streaming.
    Both routes call this after resolving client_id.

    Args:
        body: Parsed CustomLLMRequest from ElevenLabs.
        client_id: Resolved tenant identifier (from path or body).
        request: FastAPI Request object (for settings access).

    Returns:
        StreamingResponse with SSE chunks.

    Raises:
        404: If client_id does not match any registered tenant.
        403: If the tenant is inactive.
    """
    extra = body.elevenlabs_extra_body
    lead_id = extra.lead_id or body.lead_id or (body.model_extra or {}).get("lead_id")
    # Real EL conversation_id — coerce falsy values to None so DB stores NULL (CAP-3 REQ-3.3)
    raw_conversation_id = (
        extra.conversation_id
        or body.conversation_id
        or (body.model_extra or {}).get("conversation_id")
    )
    # persisted_conversation_id: what goes in DB (None when absent/empty)
    persisted_conversation_id = raw_conversation_id or None

    # Get OpenAI API key from app state or settings
    try:
        settings = request.app.state.settings
        api_key = settings.openai_api_key.get_secret_value()
    except AttributeError:
        # Fallback for tests without app.state.settings
        from app.core.config import Settings

        s = Settings()
        api_key = s.openai_api_key.get_secret_value()

    # ---------------------------------------------------------------------------
    # VSC-8: Stable session lookup — Fix A
    # ---------------------------------------------------------------------------
    # When ElevenLabs does NOT send conversation_id (signed-URL flow), every turn
    # previously generated a new random ID → session fragmentation (4 turns = 4 sessions).
    #
    # Fix: when conversation_id is absent, use find_by_client_lead to look up an
    # existing session for this (client_id, lead_id) pair first. If found, reuse its
    # conversation_id so the existing session (and its cached context) are reused.
    # If not found, generate one stable ID for the new session (Fix C).
    if persisted_conversation_id:
        # ElevenLabs provided a conversation_id — use it directly (existing path)
        conversation_id = persisted_conversation_id
        conv_state = session_store.get((client_id, conversation_id))
    elif lead_id:
        # No conversation_id from ElevenLabs — try to find an existing session
        existing = session_store.find_by_client_lead(client_id, lead_id)
        if existing is not None:
            # Reuse the existing session — all subsequent turns of this call join it
            conversation_id = existing.conversation_id
            conv_state = existing
        else:
            # First turn of a new call — generate ONE stable ID for this session
            conversation_id = f"demo-{uuid.uuid4().hex[:12]}"
            conv_state = None
    else:
        # No conversation_id and no lead_id — cannot look up; generate stable ID
        conversation_id = f"demo-{uuid.uuid4().hex[:12]}"
        conv_state = session_store.get((client_id, conversation_id))

    # Declare variables populated by either the cached or per-turn path
    agent = None
    system_content: str = ""
    tools: list[dict] | None = None
    _model: str = "gpt-4o"
    _temperature: float = 0.7
    _max_tokens: int = 300
    lead = None
    client_orm = None
    # Pre-built context for new sessions (set by the NEW SESSION PATH branch below)
    _new_session_context: "VoiceSessionContext | None" = None
    # True when build_voice_context was used (not the per-turn render_for_agent fallback)
    _used_voice_context = False
    # agent_slug + registry_entries for load_skill tool routing (Phase 2)
    _agent_slug: str | None = None
    _registry_entries: "list" = []

    if conv_state is not None and conv_state.context is not None:
        # -----------------------------------------------------------------------
        # FAST PATH: Use cached VoiceSessionContext — zero DB queries
        # -----------------------------------------------------------------------
        ctx = conv_state.context
        system_content = _assemble_context_system_content(ctx, loaded_skills=conv_state.loaded_skills)
        tools = ctx.tools
        _model = ctx.model
        _temperature = ctx.temperature
        _max_tokens = ctx.max_tokens
        _used_voice_context = True
        # Extract skill routing data from context (Phase 2)
        _agent_slug = ctx.agent_slug
        _registry_entries = list(ctx.skill_registry_entries)

        # Still need a valid api_key — already retrieved above
        # Validate tenant is accessible (minimal check — context was already built)
        # We trust the cached context was built from a valid tenant at initiation.

    else:
        # -----------------------------------------------------------------------
        # PER-TURN PATH: Load tenant config + resolve Agent from DB (legacy/lazy)
        # -----------------------------------------------------------------------
        async with db_session() as db:
            client_orm = await get_client(db, client_id)
            if client_orm is None:
                structlog.get_logger().warning(
                    "tenant_lookup_failed",
                    client_id=client_id,
                    reason="not_found",
                )
                raise HTTPException(
                    status_code=404,
                    detail={"error": "client not found"},
                )
            if not client_orm.is_active:
                structlog.get_logger().warning(
                    "tenant_lookup_failed",
                    client_id=client_id,
                    reason="inactive",
                )
                raise HTTPException(
                    status_code=403,
                    detail={"error": "Tenant disabled"},
                )

            # Phase 7: resolve default Agent for this client (DD-6)
            agent = await get_default_agent(db, client_id)

            # Load lead context (optional)
            if lead_id:
                lead = await get_lead(db, lead_id)

            if conv_state is not None and conv_state.context is None:
                # LAZY BUILD: session exists but context was never built (e.g. initiation failed)
                # Build context now and cache it on conv_state for subsequent turns.
                if agent is not None:
                    try:
                        lazy_ctx = await build_voice_context(
                            agent=agent,
                            lead=lead,
                            db=db,
                            client=client_orm,
                        )
                        conv_state.context = lazy_ctx
                        system_content = _assemble_context_system_content(lazy_ctx, loaded_skills=conv_state.loaded_skills)
                        tools = lazy_ctx.tools
                        _model = lazy_ctx.model
                        _temperature = lazy_ctx.temperature
                        _max_tokens = lazy_ctx.max_tokens
                        _used_voice_context = True
                        # Phase 2: extract skill routing data
                        _agent_slug = getattr(agent, "slug", None)
                        _registry_entries = list(lazy_ctx.skill_registry_entries)
                    except Exception as exc:
                        structlog.get_logger().warning(
                            "voice_context_lazy_build_failed",
                            client_id=client_id,
                            conversation_id=conversation_id,
                            error_type=type(exc).__name__,
                            error_msg=str(exc),
                        )
                        # Fall through to the original per-turn path below

            elif conv_state is None and agent is not None:
                # NEW SESSION PATH: Build context FIRST so this turn benefits too.
                # This is the first turn of a new call. By building context here (inside the
                # same DB session), we set system_content immediately — the fallback
                # render_for_agent path below is skipped, eliminating the duplicate
                # build_memory_context() call (VSC-8 Fix B was after messages were already
                # built, causing 8 redundant DB queries on every first turn).
                try:
                    new_ctx = await build_voice_context(
                        agent=agent,
                        lead=lead,
                        db=db,
                        client=client_orm,
                    )
                    system_content = _assemble_context_system_content(new_ctx)
                    tools = new_ctx.tools
                    _model = new_ctx.model
                    _temperature = new_ctx.temperature
                    _max_tokens = new_ctx.max_tokens
                    _used_voice_context = True
                    # Store the built context for use during session creation below
                    # (will be attached to the new session_store entry)
                    _new_session_context = new_ctx
                    # Phase 2: extract skill routing data
                    _agent_slug = getattr(agent, "slug", None)
                    _registry_entries = list(new_ctx.skill_registry_entries)
                except Exception as exc:
                    structlog.get_logger().warning(
                        "voice_context_new_session_build_failed",
                        client_id=client_id,
                        conversation_id=conversation_id,
                        error_type=type(exc).__name__,
                        error_msg=str(exc),
                    )
                    _new_session_context = None
                    # Fall through to the render_for_agent fallback below

            # If context is still not set (lazy build failed, no agent, or new session build
            # failed), use per-turn render_for_agent as fallback
            if not system_content:
                # Build system prompt inside the DB session block so render() can query
                # memory (call_history, confirmed_facts) via build_memory_context(db, lead).
                #
                # Phase 7 prompt resolution priority:
                # 1. agent.system_prompt (DB) via render_for_agent()
                # 2. client.system_prompt_override (legacy, kept for backward compat)
                # 3. Filesystem prompt.md / JAUMPABLO template
                #
                # Use explicit None check so empty string override ("") is respected.
                if agent is not None:
                    system_content = await PromptLoader().render_for_agent(
                        agent, lead, db=db, client=client_orm
                    )
                else:
                    # No Agent yet (pre-migration path) — fall back to client-based rendering
                    system_content = (
                        client_orm.system_prompt_override
                        if client_orm.system_prompt_override is not None
                        else await PromptLoader().render(client_orm, lead, db=db)
                    )

                # Parse tools from agent config (Phase 7) or client config (legacy)
                _tools_enabled_str = (
                    agent.tools_enabled if agent is not None else client_orm.tools_enabled
                )
                if _tools_enabled_str:
                    try:
                        enabled_tool_names = json.loads(_tools_enabled_str)
                        tools = _build_tool_definitions(enabled_tool_names)
                    except (json.JSONDecodeError, TypeError):
                        tools = None

                # Set up model/temp/tokens from agent config
                _model = agent.model if agent is not None else client_orm.model
                _temperature = agent.temperature if agent is not None else client_orm.temperature
                _max_tokens = agent.max_tokens if agent is not None else client_orm.max_tokens

        # client_orm holds the tenant reference; used in per-turn path above

    # Build messages with system prompt prepended.
    # Issue #21: Do NOT append [CONTEXTO DEL LEAD] block on the TEMPLATE path —
    # the template already includes all lead data via {{lead_name}}, {{car_make}},
    # {{confirmed_facts}}, etc. Appending it was reinforcing stale values 3x.
    #
    # OVERRIDE PATH: When system_prompt_override is set and no Agent exists,
    # the template is NOT rendered, so {{lead_name}}, etc. are never substituted.
    # Append [CONTEXTO DEL LEAD] to give the LLM access to lead context.
    #
    # AGENT PATH: render_for_agent() now renders DB-backed templates with variable
    # substitution. Only append [CONTEXTO DEL LEAD] if the raw agent.system_prompt
    # does NOT contain {{variable}} placeholders — meaning it's a static override
    # that was not designed as a template and won't have lead data substituted.
    # NOTE: When build_voice_context was used (fast path, lazy path, or new session path),
    # lead_profile is already assembled inside system_content — no [CONTEXTO DEL LEAD]
    # appending needed. Only append in the per-turn render_for_agent fallback path.
    if not _used_voice_context:
        # Only apply lead context appending in the per-turn render_for_agent fallback path
        _agent_has_template_vars = (
            agent is not None and agent.system_prompt and "{{" in agent.system_prompt
        )
        _has_static_prompt = (
            # Legacy client.system_prompt_override (no Agent)
            (agent is None and client_orm is not None and client_orm.system_prompt_override is not None)
            # Agent with static system_prompt (no {{variable}} placeholders)
            or (agent is not None and agent.system_prompt and not _agent_has_template_vars)
        )
        if _has_static_prompt and lead is not None:
            lead_context = (
                f"\n[CONTEXTO DEL LEAD]\n"
                f"Nombre: {lead.name}\n"
                f"Auto: {lead.car_make or ''} {lead.car_model or ''} {lead.car_year or ''}\n"
                f"Seguro actual: {lead.current_insurance or 'No especificado'}\n"
                f"Estado: {lead.status}\n"
                f"Notas: {lead.notes or ''}\n"
            )
            system_content = system_content + lead_context

    messages = [{"role": "system", "content": system_content}] + list(body.messages)

    # Set up streaming client — use resolved model config
    streaming_client = OpenAIStreamingClient(
        api_key=api_key,
        model=_model,
    )

    # Create or reuse session ID
    # Keyed by (client_id, conversation_id) to prevent cross-tenant state leakage
    session_id: str | None = None
    if conversation_id and conv_state:
        session_id = conv_state.session_id
    elif conversation_id and not conv_state:
        # Browser flow: initiation was not called, create DB session + store entry now
        # Use persisted_conversation_id (NULL when absent/empty) for DB — CAP-3 REQ-3.3
        # Use conversation_id (demo-* fallback) as session_store key (always non-null)
        coerced_lead_id = lead_id or None
        _agent_id_for_session = agent.id if agent is not None else None
        try:
            async with db_session() as db:
                new_session = await create_session(
                    db,
                    client_id=client_id,
                    lead_id=coerced_lead_id,
                    elevenlabs_conversation_id=persisted_conversation_id,
                    agent_id=_agent_id_for_session,
                )
        except ValueError as exc:
            # CRITICAL 1: No default agent for this client — return graceful SSE instead of 500 ISE
            structlog.get_logger().error(
                "webhook_create_session_failed",
                client_id=client_id,
                error=str(exc),
            )

            async def _error_stream():
                yield _sse_chunk(
                    "Lo siento, no hay agente configurado para este cliente."
                )
                yield _sse_stop()
                yield _sse_done()

            return StreamingResponse(
                _error_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        new_session_id = (
            str(new_session.id) if hasattr(new_session, "id") else str(new_session)
        )

        # VSC-8 Fix B (restructured): Use context already built inside the DB session above.
        # build_voice_context was called earlier (NEW SESSION PATH branch) and the result
        # stored in _new_session_context — no second call needed here. This eliminates the
        # duplicate build_memory_context() that caused 8 redundant DB queries on first turn.
        # When the earlier build failed, _new_session_context is None (graceful degradation).
        initial_context: "VoiceSessionContext | None" = _new_session_context

        session_store.create(
            conversation_id=conversation_id,
            client_id=client_id,
            lead_id=coerced_lead_id,
            session_id=new_session_id,
            context=initial_context,
        )
        session_id = new_session_id
        conv_state = session_store.get((client_id, conversation_id))

    async def generate():
        # Fire-and-forget: persist user turn (CAP-1)
        # Must not block the SSE stream — schedule_user_turn_persist uses asyncio.create_task
        if session_id:
            schedule_user_turn_persist(session_id, body.messages)

        # _temperature and _max_tokens are pre-resolved above (from cached context or agent config)
        try:
            async for chunk in _stream_llm_response(
                client=streaming_client,
                messages=messages,
                tools=tools,
                temperature=_temperature,
                max_tokens=_max_tokens,
                client_id=client_id,
                lead_id=lead_id,
                session_id=session_id,
                conversation_id=conversation_id,
                agent_slug=_agent_slug,
                registry_entries=_registry_entries,
                conv_state=conv_state,
            ):
                yield chunk
        except Exception as exc:
            structlog.get_logger().error("stream_error", error=str(exc))
            yield _sse_stop()
            yield _sse_done()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# QORA_TOOL_DEFINITIONS and _build_tool_definitions are imported from
# app.tools.registry at the top of this module.
