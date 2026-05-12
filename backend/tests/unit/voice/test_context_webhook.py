"""Unit tests for webhook cached context path — VSC-6.

TDD RED phase for Tasks 4.1, 4.2, 4.3, 4.4.
Covers spec scenarios:
- Cached context used (PromptLoader NOT called) — VSC-6 happy path
- Lazy fallback: conv_state exists but context is None
- Browser/demo no-state: session created with context
- Content parity between cached and per-turn paths
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_voice_context(
    system_prompt: str = "You are Aria. Cached system prompt.",
    skills_content: str | None = None,
    misc_notes: str = "",
    lead_profile: str = "",
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools: list | None = None,
    skills_index: str | None = None,
):
    from app.voice.context import VoiceSessionContext

    return VoiceSessionContext(
        system_prompt=system_prompt,
        skills_content=skills_content,
        misc_notes=misc_notes,
        lead_profile=lead_profile,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        skills_index=skills_index,
    )


def make_sse_stream(*tokens: str) -> bytes:
    """Build a fake OpenAI SSE response."""
    chunks = b""
    for token in tokens:
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
        }
        chunks += f"data: {json.dumps(payload)}\n\n".encode()
    payload_stop = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    chunks += f"data: {json.dumps(payload_stop)}\n\n".encode()
    chunks += b"data: [DONE]\n\n"
    return chunks


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def webhook_app_client(tmp_path: Path):
    """Test app with isolated SQLite and seeded quintana-seguros data."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/webhook_context_test.db",
    )

    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from app.voice import session as session_module
    from fastapi import FastAPI

    # Clean session store before each test
    session_module.session_store._sessions.clear()

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    import respx

    with respx.mock(assert_all_mocked=False):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            yield client, session_module.session_store, settings

    await db_module.close_db()
    session_module.session_store._sessions.clear()


# ---------------------------------------------------------------------------
# Task 4.1 — Cached context used: PromptLoader NOT called, system_message = cached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_uses_cached_context_skips_render_for_agent(webhook_app_client):
    """VSC-6: When conv_state.context is set, PromptLoader.render_for_agent is NOT called.

    GIVEN initiation was called and conv_state.context is set
    WHEN the webhook receives a turn
    THEN PromptLoader.render_for_agent is not invoked (cached prompt is used instead)
    AND the response is HTTP 200
    """
    http_client, store, settings = webhook_app_client

    cached_prompt = "CACHED: You are Aria. Do not query DB for this."
    ctx = make_voice_context(system_prompt=cached_prompt, model="gpt-4o", temperature=0.7, max_tokens=300)

    # Pre-seed session store with a context
    conversation_id = "cached-conv-001"
    store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-001",
        context=ctx,
    )

    import respx
    import httpx

    render_was_called = []

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=make_sse_stream("OK"))
        )

        # Track if render_for_agent is called
        original_render = None

        async def tracking_render(*args, **kwargs):
            render_was_called.append(True)
            if original_render:
                return await original_render(*args, **kwargs)
            return "fallback"

        from app.prompts import loader as loader_module
        original_render = loader_module.PromptLoader.render_for_agent

        with patch.object(loader_module.PromptLoader, "render_for_agent", tracking_render):
            response = await http_client.post(
                "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hola"}],
                    "stream": True,
                    "elevenlabs_extra_body": {
                        "client_id": "quintana-seguros",
                        "conversation_id": conversation_id,
                    },
                },
            )
            # Consume the response body to ensure the stream is processed
            _ = response.content

    assert response.status_code == 200
    assert len(render_was_called) == 0, (
        f"PromptLoader.render_for_agent must NOT be called when cached context is present. "
        f"Called {len(render_was_called)} time(s)"
    )


@pytest.mark.asyncio
async def test_webhook_cached_context_skips_db_queries(webhook_app_client):
    """VSC-6 triangulation: with cached context, DB is not queried for lead/agent/client.

    The fast-path should ONLY query what's strictly needed (e.g. not re-render the prompt).
    We verify this by asserting PromptLoader.render_for_agent is never called.
    """
    http_client, store, settings = webhook_app_client

    ctx = make_voice_context(system_prompt="Fast path prompt — no DB needed")
    conversation_id = "cached-conv-002"
    store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id=None,
        session_id="sess-002",
        context=ctx,
    )

    import respx
    import httpx

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=make_sse_stream("Respuesta"))
        )

        render_call_count = []

        original_render = None

        async def spy_render(*args, **kwargs):
            render_call_count.append(1)
            if original_render:
                return await original_render(*args, **kwargs)
            return "Fallback"

        from app.prompts import loader as loader_module
        original_render = loader_module.PromptLoader.render_for_agent

        with patch.object(loader_module.PromptLoader, "render_for_agent", spy_render):
            response = await http_client.post(
                "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hola"}],
                    "stream": True,
                    "elevenlabs_extra_body": {
                        "client_id": "quintana-seguros",
                        "conversation_id": conversation_id,
                    },
                },
            )

    assert response.status_code == 200
    assert len(render_call_count) == 0, (
        f"PromptLoader.render_for_agent must NOT be called when cached context is present. "
        f"Called {len(render_call_count)} time(s)"
    )


# ---------------------------------------------------------------------------
# Task 4.2 — Lazy fallback: conv_state exists but context is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_lazy_fallback_builds_context_when_none(webhook_app_client):
    """VSC-6 lazy fallback: when conv_state.context is None, build_voice_context called once.

    GIVEN conv_state exists but conv_state.context is None
    WHEN the webhook receives a turn
    THEN build_voice_context is called and context is assigned
    """
    http_client, store, settings = webhook_app_client

    # Session with context=None (initiation failed or wasn't called)
    conversation_id = "lazy-conv-001"
    state = store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-lazy",
        context=None,
    )
    assert state.context is None

    import respx
    import httpx

    lazy_ctx = make_voice_context(system_prompt="Lazily built context")

    with respx.mock:
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, content=make_sse_stream("OK"))
        )

        with patch("app.voice.webhook.build_voice_context", new_callable=AsyncMock, return_value=lazy_ctx) as mock_build:
            response = await http_client.post(
                "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hola"}],
                    "stream": True,
                    "elevenlabs_extra_body": {
                        "client_id": "quintana-seguros",
                        "lead_id": "lead-quintana-001",
                        "conversation_id": conversation_id,
                    },
                },
            )

    assert response.status_code == 200
    # build_voice_context must have been called (lazy build)
    assert mock_build.called, "build_voice_context must be called for lazy fallback"
    assert mock_build.call_count == 1, (
        f"build_voice_context must be called exactly once. Called: {mock_build.call_count}"
    )


# ---------------------------------------------------------------------------
# Task 4.4 — Content parity between cached and fresh paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_cached_context_content_matches_fresh_render(webhook_app_client):
    """VSC-6 parity: cached context system prompt matches what fresh render would produce.

    This is a structural test — both paths produce the SAME system prompt for the same agent.
    """
    http_client, store, settings = webhook_app_client

    # Simulate what build_voice_context would return for quintana-seguros
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    from app.core import database as db_module

    assert db_module.async_session_factory is not None

    # Get a fresh-rendered prompt
    async with db_module.async_session_factory() as db:
        from app.tenants.service import get_client, get_default_agent
        from app.leads.service import get_lead

        client_orm = await get_client(db, "quintana-seguros")
        agent_orm = await get_default_agent(db, "quintana-seguros")
        lead_orm = await get_lead(db, "lead-quintana-001")

        if agent_orm is not None and client_orm is not None:
            fresh_prompt = await PromptLoader().render_for_agent(
                agent_orm, lead_orm, db=db, client=client_orm
            )

            # Build a context and verify the system_prompt matches
            built_ctx = await build_voice_context(
                agent=agent_orm,
                lead=lead_orm,
                db=db,
                client=client_orm,
            )

    assert built_ctx.system_prompt == fresh_prompt, (
        "build_voice_context.system_prompt must equal PromptLoader.render_for_agent() output"
    )


# ---------------------------------------------------------------------------
# Task VSC-6 fix — ALL 4 components must reach the LLM system message
# ---------------------------------------------------------------------------
# These tests intercept _stream_llm_response to capture the `messages` list
# that would be sent to the LLM. This avoids the need to mock the OpenAI
# SDK's internal httpx client (which isn't interceptable via respx).
# ---------------------------------------------------------------------------


def _get_system_content(messages: list[dict]) -> str:
    """Extract system message content from a messages list."""
    for msg in messages:
        if msg.get("role") == "system":
            return msg.get("content", "")
    return ""


async def _fake_stream(*args, **kwargs):
    """Minimal async generator to stub _stream_llm_response."""
    yield "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_cached_path_includes_all_4_components(webhook_app_client):
    """VSC-6 critical: cached path must assemble ALL 4 context components.

    GIVEN a cached VoiceSessionContext with non-empty skills_content,
          misc_notes, and lead_profile
    WHEN webhook processes a turn using the fast path
    THEN the messages list passed to _stream_llm_response must contain a system
         message with ALL 4 components: system_prompt, skills_content,
         misc_notes, lead_profile.
    """
    http_client, store, settings = webhook_app_client

    ctx = make_voice_context(
        system_prompt="Base system prompt.",
        skills_content=None,
        misc_notes="Lead menciona que ya tiene seguro con Mapfre.",
        lead_profile="[CONTEXTO DEL LEAD]\nNombre: Juan García\nAuto: Toyota Corolla 2020",
        skills_index="## Skill: Objeción precio\nSi dicen caro, responder con valor.",
    )

    conversation_id = "all-components-conv-001"
    store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-ac-001",
        context=ctx,
    )

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hola"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "conversation_id": conversation_id,
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert captured_messages, "_stream_llm_response must have been called"

    system_content = _get_system_content(captured_messages[0])

    assert "Base system prompt." in system_content, (
        f"system_prompt missing from system message. Got:\n{system_content!r}"
    )
    assert "Skill: Objeción precio" in system_content, (
        f"skills_index missing from system message. Got:\n{system_content!r}"
    )
    assert "Lead menciona que ya tiene seguro con Mapfre." in system_content, (
        f"misc_notes missing from system message. Got:\n{system_content!r}"
    )
    assert "Juan García" in system_content, (
        f"lead_profile missing from system message. Got:\n{system_content!r}"
    )


@pytest.mark.asyncio
async def test_cached_path_empty_components_not_appended(webhook_app_client):
    """VSC-6 triangulation: when optional components are empty, no separators are added.

    GIVEN a cached context where skills_content, misc_notes, lead_profile are all empty
    WHEN webhook processes a turn
    THEN the system message equals exactly the system_prompt (no trailing separators).
    """
    http_client, store, settings = webhook_app_client

    ctx = make_voice_context(
        system_prompt="Only base prompt.",
        skills_content="",
        misc_notes="",
        lead_profile="",
    )

    conversation_id = "empty-components-conv-001"
    store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id=None,
        session_id="sess-ec-001",
        context=ctx,
    )

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hola"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "conversation_id": conversation_id,
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert captured_messages, "_stream_llm_response must have been called"

    system_content = _get_system_content(captured_messages[0])
    assert system_content == "Only base prompt.", (
        f"When all optional components are empty, system message must equal system_prompt exactly. "
        f"Got:\n{system_content!r}"
    )


@pytest.mark.asyncio
async def test_lazy_fallback_path_includes_all_4_components(webhook_app_client):
    """VSC-6 critical: lazy fallback path must also assemble ALL 4 context components.

    GIVEN conv_state.context is None (lazy build triggered)
    AND build_voice_context returns a context with all 4 components populated
    WHEN webhook processes a turn via lazy fallback
    THEN the messages list passed to _stream_llm_response must contain a system
         message with ALL 4 components.
    """
    http_client, store, settings = webhook_app_client

    conversation_id = "lazy-all-components-conv-001"
    store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-laz-ac",
        context=None,
    )

    lazy_ctx = make_voice_context(
        system_prompt="Lazy base prompt.",
        skills_content=None,
        misc_notes="Notas de llamada anterior.",
        lead_profile="[CONTEXTO DEL LEAD]\nNombre: María López",
        skills_index="## Skill: Lazy skill content",
    )

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch(
        "app.voice.webhook.build_voice_context",
        new_callable=AsyncMock,
        return_value=lazy_ctx,
    ), patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hola"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    "conversation_id": conversation_id,
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert captured_messages, "_stream_llm_response must have been called"

    system_content = _get_system_content(captured_messages[0])

    assert "Lazy base prompt." in system_content, (
        f"system_prompt missing from lazy fallback system message. Got:\n{system_content!r}"
    )
    assert "Lazy skill content" in system_content, (
        f"skills_index missing from lazy fallback system message. Got:\n{system_content!r}"
    )
    assert "Notas de llamada anterior." in system_content, (
        f"misc_notes missing from lazy fallback system message. Got:\n{system_content!r}"
    )
    assert "María López" in system_content, (
        f"lead_profile missing from lazy fallback system message. Got:\n{system_content!r}"
    )
