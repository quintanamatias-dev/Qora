"""Unit tests for session fragmentation fix — VSC-8.

TDD RED phase for Fix A+B+C:
- Fix A: Webhook reuses existing session when no conversation_id (find_by_client_lead)
- Fix B: Webhook builds context on new session creation (first turn)
- Fix C: Stable conversation_id for session (generated once, not random every turn)

Covers spec scenarios:
- Turn 2+ reuses same session found via find_by_client_lead (no fragmentation)
- First turn creates new session + builds context immediately
- When conversation_id IS provided, existing path still works (backward compat)
- build_voice_context failure → session created without context (graceful degradation)
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
    skills_content: str = "",
    misc_notes: str = "",
    lead_profile: str = "",
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools: list | None = None,
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
async def frag_app_client(tmp_path: Path):
    """Test app with isolated SQLite and seeded quintana-seguros data."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/frag_test.db",
    )

    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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
# Fix A: Turn 2+ reuses same session via find_by_client_lead (no fragmentation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_turn_reuses_existing_session_no_conversation_id(frag_app_client):
    """VSC-8 Fix A: When no conversation_id provided, Turn 2 reuses session from Turn 1.

    GIVEN Turn 1 created a session for (client_id="quintana-seguros", lead_id="lead-quintana-001")
    WHEN Turn 2 arrives with NO conversation_id
    THEN the webhook finds and reuses the existing session (session_count stays at 1)
    AND does NOT create a second session (no fragmentation)
    """
    http_client, store, settings = frag_app_client

    ctx = make_voice_context(system_prompt="Existing session context")
    existing_conversation_id = "stable-conv-turn1"
    store.create(
        conversation_id=existing_conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-turn1",
        context=ctx,
    )

    assert store.session_count() == 1

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    # Turn 2: NO conversation_id — ElevenLabs signed URL flow
    with patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Turn 2"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    # NO conversation_id — simulates ElevenLabs signed URL flow
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    # Critical: still only 1 session — no fragmentation
    assert store.session_count() == 1, (
        f"Session fragmentation detected: expected 1 session, found {store.session_count()}. "
        "Turn 2 must reuse the existing session, not create a new one."
    )
    # The found session should be the one we pre-seeded
    assert captured_messages, "_stream_llm_response must have been called"


@pytest.mark.asyncio
async def test_second_turn_uses_cached_context_from_reused_session(frag_app_client):
    """VSC-8 Fix A triangulation: reused session uses its cached context (no render).

    GIVEN an existing session with a cached VoiceSessionContext
    WHEN Turn 2 arrives with NO conversation_id and find_by_client_lead finds it
    THEN the cached context is used (render_for_agent NOT called)
    """
    http_client, store, settings = frag_app_client

    ctx = make_voice_context(system_prompt="STABLE CONTEXT: Do not rebuild me.")
    store.create(
        conversation_id="stable-conv-cached",
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-cached",
        context=ctx,
    )

    render_calls = []

    async def spy_render(*args, **kwargs):
        render_calls.append(True)
        return "Should not be called"

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    from app.prompts import loader as loader_module

    with patch.object(loader_module.PromptLoader, "render_for_agent", spy_render), \
         patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Turn 2 cached"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    # NO conversation_id
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert len(render_calls) == 0, (
        "render_for_agent must NOT be called when reused session has cached context"
    )
    assert captured_messages
    system_content = next(
        (m["content"] for m in captured_messages[0] if m.get("role") == "system"), ""
    )
    assert "STABLE CONTEXT" in system_content, (
        f"Cached context system prompt must appear in system message. Got: {system_content!r}"
    )


# ---------------------------------------------------------------------------
# Fix B: First turn (no existing session) builds context on creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_turn_no_existing_session_builds_context_on_creation(frag_app_client):
    """VSC-8 Fix B: When no session exists, new session is created with context built immediately.

    GIVEN no session exists for (client_id, lead_id)
    AND no conversation_id is provided (ElevenLabs signed URL flow)
    WHEN Turn 1 arrives
    THEN a new session is created
    AND build_voice_context is called to populate context at creation
    AND the session has context set (not None)
    """
    http_client, store, settings = frag_app_client

    assert store.session_count() == 0

    built_ctx = make_voice_context(system_prompt="Built at creation context")

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch(
        "app.voice.webhook.build_voice_context",
        new_callable=AsyncMock,
        return_value=built_ctx,
    ) as mock_build, patch(
        "app.voice.webhook._stream_llm_response", side_effect=capturing_stream
    ):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "First turn"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    # NO conversation_id
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert mock_build.called, (
        "build_voice_context must be called on first turn when no session exists"
    )
    # Session was created
    assert store.session_count() == 1, "A new session must be created on first turn"
    # The session must have context set
    sessions = list(store._sessions.values())
    assert sessions[0].context is built_ctx, (
        "New session must have context set after build_voice_context call"
    )


@pytest.mark.asyncio
async def test_first_turn_build_context_failure_session_still_created(frag_app_client):
    """VSC-8 Fix B triangulation: build_voice_context failure → session created without context.

    GIVEN no session exists for (client_id, lead_id)
    AND build_voice_context raises an exception
    WHEN Turn 1 arrives
    THEN the exception is caught and logged
    AND the session is still created (without context)
    AND the response is HTTP 200 (graceful degradation)
    """
    http_client, store, settings = frag_app_client

    assert store.session_count() == 0

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch(
        "app.voice.webhook.build_voice_context",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB unavailable during context build"),
    ), patch(
        "app.voice.webhook._stream_llm_response", side_effect=capturing_stream
    ):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "First turn — fail context"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    # NO conversation_id
                },
            },
        )
        _ = response.content

    assert response.status_code == 200, (
        "build_voice_context failure must NOT cause HTTP 500 — must degrade gracefully"
    )
    # Session should still be created (graceful degradation)
    assert store.session_count() == 1, (
        "Session must be created even when build_voice_context fails"
    )
    # Context may be None (graceful degradation path) — that's acceptable
    # The key requirement is: HTTP 200, session exists, response streams


# ---------------------------------------------------------------------------
# Fix C: Stable conversation_id (generated once, reused)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stable_conversation_id_across_turns_no_el_id(frag_app_client):
    """VSC-8 Fix C: When ElevenLabs provides no conversation_id, turns reuse the same stable ID.

    GIVEN Turn 1 created a session with a generated stable conversation_id
    WHEN Turn 2 arrives with no conversation_id
    THEN find_by_client_lead finds the session and the conversation_id does not change
    AND session_count remains 1 (no new session created)
    """
    http_client, store, settings = frag_app_client

    built_ctx = make_voice_context(system_prompt="Stable ID context")
    captured: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    # Turn 1
    with patch(
        "app.voice.webhook.build_voice_context",
        new_callable=AsyncMock,
        return_value=built_ctx,
    ), patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        r1 = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "T1"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                },
            },
        )
        _ = r1.content

    assert r1.status_code == 200
    assert store.session_count() == 1
    sessions_after_t1 = list(store._sessions.values())
    stable_id = sessions_after_t1[0].conversation_id

    # Turn 2 — no conversation_id again
    with patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        r2 = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "T2"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                },
            },
        )
        _ = r2.content

    assert r2.status_code == 200
    # Still 1 session — no fragmentation
    assert store.session_count() == 1, (
        f"After Turn 2, session_count must still be 1. Got {store.session_count()}. "
        "Session fragmentation detected."
    )
    sessions_after_t2 = list(store._sessions.values())
    assert sessions_after_t2[0].conversation_id == stable_id, (
        "The conversation_id must remain stable across turns. "
        f"Turn 1: {stable_id!r}, Turn 2: {sessions_after_t2[0].conversation_id!r}"
    )


# ---------------------------------------------------------------------------
# Backward compat: conversation_id IS provided → existing path still works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_id_provided_still_works(frag_app_client):
    """VSC-8 backward compat: When ElevenLabs provides conversation_id, existing path works.

    GIVEN ElevenLabs provides a conversation_id (future update or SDK flow)
    WHEN the webhook receives the request
    THEN the session is keyed by that conversation_id as before
    AND the response is HTTP 200
    """
    http_client, store, settings = frag_app_client

    ctx = make_voice_context(system_prompt="EL-provided conversation_id path")
    el_conversation_id = "el-provided-conv-xyz"
    store.create(
        conversation_id=el_conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="sess-el-provided",
        context=ctx,
    )

    captured: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch("app.voice.webhook._stream_llm_response", side_effect=capturing_stream):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "With conv ID"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    "conversation_id": el_conversation_id,
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert captured, "_stream_llm_response must have been called"
    system_content = next(
        (m["content"] for m in captured[0] if m.get("role") == "system"), ""
    )
    assert "EL-provided conversation_id path" in system_content, (
        "When conversation_id IS provided, the existing cached session must be used"
    )


# ---------------------------------------------------------------------------
# Fix: No duplicate build_voice_context on first turn (was called twice via
# render_for_agent fallback + VSC-8 Fix B — 8 redundant DB queries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_turn_build_voice_context_called_exactly_once(frag_app_client):
    """Regression: build_voice_context must be called ONCE on first turn, not twice.

    GIVEN no session exists (first turn)
    AND no conversation_id is provided
    WHEN Turn 1 arrives
    THEN build_voice_context is called exactly once
         (the fallback render_for_agent path must NOT trigger a second call)

    Root cause (pre-fix): the per-turn fallback at `if not system_content:` called
    render_for_agent() which internally calls build_memory_context(); then VSC-8 Fix B
    also called build_voice_context() which calls render_for_agent() again — 2x.
    After the fix: build_voice_context is called FIRST, its result sets system_content,
    so the fallback render_for_agent path is never reached.
    """
    http_client, store, settings = frag_app_client

    assert store.session_count() == 0

    built_ctx = make_voice_context(system_prompt="Single-build context")

    captured_messages: list[list[dict]] = []

    async def capturing_stream(**kwargs):
        captured_messages.append(kwargs.get("messages", []))
        yield "data: [DONE]\n\n"

    with patch(
        "app.voice.webhook.build_voice_context",
        new_callable=AsyncMock,
        return_value=built_ctx,
    ) as mock_build, patch(
        "app.voice.webhook._stream_llm_response", side_effect=capturing_stream
    ):
        response = await http_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "First turn"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "client_id": "quintana-seguros",
                    "lead_id": "lead-quintana-001",
                    # NO conversation_id — simulates ElevenLabs signed URL flow
                },
            },
        )
        _ = response.content

    assert response.status_code == 200
    assert mock_build.call_count == 1, (
        f"build_voice_context must be called EXACTLY ONCE on the first turn. "
        f"Called {mock_build.call_count} time(s). "
        "Duplicate call detected — render_for_agent fallback was triggered unnecessarily."
    )
    # The system message should use the built context
    assert captured_messages, "_stream_llm_response must have been called"
    system_content = next(
        (m["content"] for m in captured_messages[0] if m.get("role") == "system"), ""
    )
    assert "Single-build context" in system_content, (
        f"system_content must come from build_voice_context result. Got: {system_content!r}"
    )
