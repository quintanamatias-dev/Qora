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

import json
import time
import uuid
from typing import Any, AsyncGenerator

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
from app.calls.service import add_transcript_turn, create_session
from app.core.database import get_session as db_session
from app.leads.service import get_lead
from app.prompts.loader import PromptLoader
from app.tenants.service import get_client
from app.voice.filler import FALLBACK_FILLER, select_filler, session_store

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
# Tool execution (dispatches to tools module)
# ---------------------------------------------------------------------------


async def _execute_tool(
    tool_name: str,
    tool_args: dict,
    client_id: str,
    lead_id: str | None,
) -> dict:
    """Execute a tool by name and return the result dict.

    For Phase 0, tools are dispatched directly from here.
    Phase 1 can introduce a full registry.
    """
    try:
        from app.tools.dispatcher import dispatch_tool

        return await dispatch_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            client_id=client_id,
            lead_id=lead_id,
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
) -> AsyncGenerator[str, None]:
    """Generate SSE chunks from GPT-4o, handling tool calls mid-stream.

    Flow:
    1. Start streaming GPT-4o.
    2. Yield content tokens as SSE.
    3. If tool_call detected: execute tool, re-call GPT-4o, stream final reply.
    4. Persist transcript turn.
    5. Yield [DONE].
    """
    full_response_text = ""
    tool_executed = False

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
            # Tool call detected — execute and continue
            tool_executed = True
            try:
                args = json.loads(event.function_args) if event.function_args else {}
            except json.JSONDecodeError:
                args = {}

            tool_result = await _execute_tool(
                event.function_name,
                args,
                client_id=client_id,
                lead_id=lead_id,
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

    # Persist transcript turn if we have a session
    if session_id and full_response_text:
        try:
            async with db_session() as db:
                await add_transcript_turn(db, session_id, "agent", full_response_text)
        except Exception:
            pass  # Don't fail the SSE stream on persistence errors

    # Update filler tracking
    if conversation_id:
        conv_state = session_store.get(conversation_id)
        if conv_state:
            session_store.increment_turn(conversation_id)

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
    """Handle ElevenLabs Custom LLM webhook.

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
    client_id = (
        extra.client_id or body.client_id or (body.model_extra or {}).get("client_id")
    )
    if not client_id:
        raise HTTPException(
            status_code=422,
            detail={"error": "client_id is required"},
        )
    lead_id = extra.lead_id or body.lead_id or (body.model_extra or {}).get("lead_id")
    conversation_id = (
        extra.conversation_id
        or body.conversation_id
        or (body.model_extra or {}).get("conversation_id")
    )

    # Always ensure conversation_id exists for session tracking
    if not conversation_id:
        conversation_id = f"demo-{uuid.uuid4().hex[:12]}"

    # Get OpenAI API key from app state or settings
    try:
        settings = request.app.state.settings
        api_key = settings.openai_api_key.get_secret_value()
    except AttributeError:
        # Fallback for tests without app.state.settings
        from app.core.config import Settings

        s = Settings()
        api_key = s.openai_api_key.get_secret_value()

    # Load tenant config
    async with db_session() as db:
        client = await get_client(db, client_id)
        if client is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "client not found"},
            )

        # Load lead context (optional)
        lead = None
        if lead_id:
            lead = await get_lead(db, lead_id)

    # Build system prompt (inject lead context if available)
    # Use explicit None check so empty string override ("") is respected
    system_content = (
        client.system_prompt_override
        if client.system_prompt_override is not None
        else PromptLoader().render(client, lead)
    )

    # Build messages with system prompt prepended
    messages = [{"role": "system", "content": system_content}] + list(body.messages)

    # If lead context available, inject as context note
    if lead is not None:
        lead_context = (
            f"\n[CONTEXTO DEL LEAD]\n"
            f"Nombre: {lead.name}\n"
            f"Auto: {lead.car_make or ''} {lead.car_model or ''} {lead.car_year or ''}\n"
            f"Seguro actual: {lead.current_insurance or 'No especificado'}\n"
            f"Estado: {lead.status}\n"
            f"Notas: {lead.notes or ''}\n"
        )
        messages[0]["content"] += lead_context

    # Set up streaming client
    streaming_client = OpenAIStreamingClient(
        api_key=api_key,
        model=client.model,
    )

    # Parse tools from client config
    tools = None
    if client.tools_enabled:
        try:
            enabled_tool_names = json.loads(client.tools_enabled)
            tools = _build_tool_definitions(enabled_tool_names)
        except (json.JSONDecodeError, TypeError):
            tools = None

    # Create or reuse session ID
    # First pass: check existing conv_state
    conv_state = session_store.get(conversation_id)
    session_id: str | None = None
    if conversation_id and conv_state:
        session_id = conv_state.session_id
    elif conversation_id and not conv_state:
        # Browser flow: initiation was not called, create DB session + store entry now
        async with db_session() as db:
            new_session = await create_session(
                db,
                client_id=client_id,
                lead_id=lead_id or "unknown",
            )
        new_session_id = (
            str(new_session.id) if hasattr(new_session, "id") else str(new_session)
        )
        session_store.create(
            conversation_id=conversation_id,
            client_id=client_id,
            lead_id=lead_id or "unknown",
            session_id=new_session_id,
        )
        session_id = new_session_id
        conv_state = session_store.get(conversation_id)

    # Select filler AFTER session creation so conv_state is populated
    filler = select_filler(conv_state) if conv_state else FALLBACK_FILLER

    if conversation_id and conv_state:
        session_store.update_filler(conversation_id, filler)

    async def generate():
        # Emit filler immediately as first SSE chunk (before LLM responds)
        if filler:
            yield _sse_chunk(filler + " ")

        try:
            async for chunk in _stream_llm_response(
                client=streaming_client,
                messages=messages,
                tools=tools,
                temperature=client.temperature,
                max_tokens=client.max_tokens,
                client_id=client_id,
                lead_id=lead_id,
                session_id=session_id,
                conversation_id=conversation_id,
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


# ---------------------------------------------------------------------------
# Helper: build tool definitions
# ---------------------------------------------------------------------------


QORA_TOOL_DEFINITIONS = {
    "get_lead_details": {
        "type": "function",
        "function": {
            "name": "get_lead_details",
            "description": "Obtenés los datos completos del lead del CRM",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string", "description": "ID del lead"}
                },
                "required": ["lead_id"],
            },
        },
    },
    "register_interest": {
        "type": "function",
        "function": {
            "name": "register_interest",
            "description": "Registrás el interés del lead y lo marcás para cotización",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "car_make": {"type": "string"},
                    "car_model": {"type": "string"},
                    "car_year": {"type": "integer"},
                    "current_insurance": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["lead_id", "car_make", "car_model", "car_year"],
            },
        },
    },
    "mark_not_interested": {
        "type": "function",
        "function": {
            "name": "mark_not_interested",
            "description": "Marcás al lead como no interesado con una razón",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "reason": {"type": "string", "description": "Razón del rechazo"},
                },
                "required": ["lead_id", "reason"],
            },
        },
    },
    "schedule_followup": {
        "type": "function",
        "function": {
            "name": "schedule_followup",
            "description": "Agendás un seguimiento para el lead en una fecha específica",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "followup_date": {
                        "type": "string",
                        "description": "Fecha ISO 8601",
                    },
                    "note": {"type": "string"},
                },
                "required": ["lead_id", "followup_date"],
            },
        },
    },
}


def _build_tool_definitions(tool_names: list[str]) -> list[dict] | None:
    """Build OpenAI tool definitions for the given tool names."""
    tools = [
        QORA_TOOL_DEFINITIONS[name]
        for name in tool_names
        if name in QORA_TOOL_DEFINITIONS
    ]
    return tools if tools else None
