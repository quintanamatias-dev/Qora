"""Integration tests for custom-LLM webhook memory wiring (CAP-3).

T25 — RED: Webhook renders prompt with prior session memory (call_history injected).
T26 — RED: Graceful fallback when build_memory_context raises RuntimeError.
T27 — RED: No lead → empty memory, no crash.

These tests are RED until webhook.py passes ``db`` to PromptLoader().render(),
so that _build_variables calls build_memory_context with a live DB session.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response
from pydantic import SecretStr
from sqlalchemy import select


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _make_sse_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
) -> bytes:
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if content is not None:
        choice["delta"]["content"] = content
    payload = {
        "id": "chatcmpl-mem-test",
        "object": "chat.completion.chunk",
        "choices": [choice],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _build_simple_stream(*tokens: str) -> bytes:
    chunks = b""
    for token in tokens:
        chunks += _make_sse_chunk(content=token)
    chunks += _make_sse_chunk(finish_reason="stop")
    chunks += b"data: [DONE]\n\n"
    return chunks


# ---------------------------------------------------------------------------
# App fixture — isolated SQLite + seeded data with a completed CallSession
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_app_client(tmp_path: Path):
    """Create a test app with isolated SQLite, one lead with a completed session."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/custom_llm_memory_test.db",
    )

    await db_module.init_db(settings)

    LEAD_ID = "lead-memory-test-001"

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.models import CallSession
        from app.leads.models import Lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Roberto Perez",
            phone="+5411155501",
            car_make="Toyota",
            car_model="Corolla",
            car_year=2020,
            current_insurance="Mapfre",  # Different from summary content "La Caja"
            lead_id=LEAD_ID,
        )
        await sess.flush()

        # Seed a completed CallSession with a summary referencing "La Caja"
        completed_session = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=LEAD_ID,
            status="completed",
            summary="El cliente mencionó que ya tiene seguro con La Caja",
            started_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 1, 10, 30, 0, tzinfo=timezone.utc),
        )
        sess.add(completed_session)
        await sess.flush()

        # Update lead call_count to reflect 1 completed call
        lead_result = await sess.execute(select(Lead).where(Lead.id == LEAD_ID))
        lead_obj = lead_result.scalar_one_or_none()
        if lead_obj is not None:
            lead_obj.call_count = 1
            lead_obj.extracted_facts = {
                "current_insurance": "La Caja",
                "interest_level": 75,
            }

        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, db_module, LEAD_ID

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T25 — RED: Webhook renders prompt containing call_history from prior session
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_custom_llm_webhook_renders_prompt_with_prior_session_memory(
    memory_app_client,
):
    """CAP-3: Webhook passes DB to render — system prompt contains 'Llamada del' from call_history.

    'Llamada del' is ONLY produced by memory.py _format_call_history() when called via
    build_memory_context(db, lead). It will NOT appear if db=None is passed to render().

    The lead's current_insurance is 'Mapfre' (not 'La Caja') so any occurrence of
    'La Caja' or 'Llamada del' must come from memory (call_history), not lead fields.

    RED until webhook.py moves render() call inside db_session() block and passes db=db.
    """
    client, db_module, LEAD_ID = memory_app_client

    # Intercept the messages sent to OpenAI to capture the system prompt
    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola Roberto"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": "conv-memory-t25-001",
        },
        "client_id": "quintana-seguros",
    }

    resp = await client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert len(captured_messages) > 0, "OpenAI was never called"

    # The system message is messages[0]["content"]
    system_content = captured_messages[0][0]["content"]

    # 'Llamada del' is ONLY produced by build_memory_context via call_history.
    # This assertion FAILS when webhook.py does NOT pass db=db to render()
    # (because then _build_variables skips memory and call_history stays "").
    assert "Llamada del" in system_content, (
        f"System prompt must contain 'Llamada del' from call_history memory injection. "
        f"This requires webhook.py to pass db=db to PromptLoader().render(). "
        f"System prompt starts with: {system_content[:300]!r}"
    )


# ---------------------------------------------------------------------------
# T26 — RED: Graceful fallback when build_memory_context raises RuntimeError
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_custom_llm_webhook_falls_back_to_empty_when_memory_build_fails(
    memory_app_client,
):
    """CAP-3: If build_memory_context raises RuntimeError, response is 200 and
    'memory_context_failed' is logged with error_type='RuntimeError'.

    RED: This test patching fails because webhook.py doesn't pass db → render
    doesn't call build_memory_context at all. Once T28 is done, the patch will
    work and we need the fallback handling to be correct.
    """
    client, db_module, LEAD_ID = memory_app_client

    log_events: list[dict] = []

    import structlog.testing

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Patch build_memory_context in the loader module where it's imported
    with patch(
        "app.memory.build_memory_context",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with structlog.testing.capture_logs() as cap_logs:
            body = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hola"}],
                "stream": True,
                "elevenlabs_extra_body": {
                    "lead_id": LEAD_ID,
                    "conversation_id": "conv-memory-fallback-001",
                },
                "client_id": "quintana-seguros",
            }

            resp = await client.post(
                "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
                json=body,
            )
        log_events = list(cap_logs)

    # Must NOT crash — 200 SSE even on memory failure
    assert (
        resp.status_code == 200
    ), f"Expected 200 (graceful fallback), got {resp.status_code}: {resp.text}"

    # Response must be a valid SSE stream
    assert (
        "data:" in resp.text
    ), "Response should be SSE stream even after memory failure"

    # The 'memory_context_failed' event must be logged (from _build_variables fallback)
    # This only fires when db IS passed (so build_memory_context is actually called)
    failed_events = [e for e in log_events if e.get("event") == "memory_context_failed"]
    assert len(failed_events) > 0, (
        f"Expected 'memory_context_failed' log event. "
        f"Got log events: {[e.get('event') for e in log_events]}. "
        f"This fires only when db is passed to render() — requires T28 to be done first."
    )
    assert failed_events[0].get("error_type") == "RuntimeError"
    assert failed_events[0].get("error_msg") == "boom"


# ---------------------------------------------------------------------------
# T27 — RED: No lead → empty memory, no crash
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_custom_llm_webhook_with_no_lead_renders_empty_memory(
    memory_app_client,
):
    """CAP-3: lead_id absent → render with db but lead=None → empty memory defaults, 200.

    This should pass even before T28 (webhook already handles no-lead gracefully),
    but explicitly verifies the 200 response and absence of 'Llamada del' in the prompt.
    """
    client, db_module, _ = memory_app_client

    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "conversation_id": "conv-no-lead-001",
            # No lead_id intentionally
        },
        "client_id": "quintana-seguros",
    }

    resp = await client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert (
        resp.status_code == 200
    ), f"Expected 200 (no-lead path), got {resp.status_code}: {resp.text}"

    # The SSE stream should contain data
    assert "data:" in resp.text, "Response should be SSE stream"

    # System prompt should NOT contain call_history content (no lead → empty memory)
    if captured_messages:
        system_content = captured_messages[0][0]["content"]
        assert "Llamada del" not in system_content, (
            "System prompt should not contain 'Llamada del' when no lead is provided. "
            f"System prompt: {system_content[:200]!r}"
        )
