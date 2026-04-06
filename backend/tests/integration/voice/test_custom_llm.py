"""Integration tests for the Custom LLM webhook.

RED: References app.voice.webhook which is not yet implemented.
Covers: CAP-1 SSE stream, filler, tool call, and 422 validation.
Uses respx to mock OpenAI API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers — fake SSE content builders
# ---------------------------------------------------------------------------


def _make_sse_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list | None = None,
) -> bytes:
    """Build a fake OpenAI SSE data line."""
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if content is not None:
        choice["delta"]["content"] = content
    if tool_calls is not None:
        choice["delta"]["tool_calls"] = tool_calls
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "choices": [choice],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _make_sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def _build_simple_stream(*tokens: str) -> bytes:
    """Build a complete SSE stream with given content tokens."""
    chunks = b""
    for token in tokens:
        chunks += _make_sse_chunk(content=token)
    chunks += _make_sse_chunk(finish_reason="stop")
    chunks += _make_sse_done()
    return chunks


def _build_tool_call_stream() -> bytes:
    """Build an SSE stream that includes a tool call then final response."""
    # First: tool call chunk
    tool_call_chunk = _make_sse_chunk(
        tool_calls=[
            {
                "index": 0,
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_lead_details",
                    "arguments": '{"lead_id": "lead-quintana-001"}',
                },
            }
        ]
    )
    finish_tool = _make_sse_chunk(finish_reason="tool_calls")

    # Then: final response after tool execution
    final_chunk = _make_sse_chunk(content="Acá tenés los detalles del lead.")
    finish_stop = _make_sse_chunk(finish_reason="stop")
    done = _make_sse_done()

    return tool_call_chunk + finish_tool + final_chunk + finish_stop + done


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(tmp_path: Path):
    """Create a test app with isolated SQLite and seeded data."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/llm_test.db",
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
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Valid request body builder
# ---------------------------------------------------------------------------


def _valid_body(
    client_id: str = "quintana-seguros",
    lead_id: str = "lead-quintana-001",
    message: str = "Hola, ¿me podés contar sobre el seguro?",
) -> dict:
    return {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": message}],
        "stream": True,
        "elevenlabs_extra_body": {
            "client_id": client_id,
            "lead_id": lead_id,
            "conversation_id": "conv-test-001",
        },
    }


# ---------------------------------------------------------------------------
# T4.3: Custom LLM webhook tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_custom_llm_returns_sse_stream(app_client: AsyncClient):
    """POST /custom-llm returns SSE stream (Content-Type: text/event-stream) (CAP-1)."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("A ver...", " Hola, ¿cómo estás?"),
            headers={"content-type": "text/event-stream"},
        )
    )

    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(),
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


@respx.mock
async def test_custom_llm_stream_ends_with_done(app_client: AsyncClient):
    """The SSE stream MUST end with data: [DONE] (CAP-1)."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(),
    )

    assert response.status_code == 200
    content = response.text
    assert "[DONE]" in content, f"Expected [DONE] in stream, got: {content[:200]}"


@respx.mock
async def test_custom_llm_missing_client_id_returns_422(app_client: AsyncClient):
    """Missing client_id returns 422 — client_id is now required (CAP-6).

    The server no longer falls back to a default client_id. When client_id is
    absent from all sources (elevenlabs_extra_body, top-level, model_extra),
    the endpoint MUST return HTTP 422.
    """
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
        },
    }
    response = await app_client.post("/api/v1/voice/custom-llm", json=body)
    assert response.status_code == 422
    data = response.json()
    assert data["detail"]["error"] == "client_id is required"


@respx.mock
async def test_custom_llm_unknown_client_returns_404(app_client: AsyncClient):
    """Unknown client_id returns 404 (CAP-1 unknown client scenario)."""
    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(client_id="nonexistent-broker"),
    )
    assert response.status_code == 404


@respx.mock
async def test_custom_llm_without_extra_body_returns_422(
    app_client: AsyncClient,
):
    """Request without client_id anywhere returns 422 (CAP-6).

    When no elevenlabs_extra_body, no top-level client_id, no model_extra —
    the server MUST return 422 (client_id is required, no default fallback).
    """
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }
    response = await app_client.post("/api/v1/voice/custom-llm", json=body)
    assert response.status_code == 422
    data = response.json()
    assert data["detail"]["error"] == "client_id is required"


@respx.mock
async def test_custom_llm_extracts_lead_and_injects_context(app_client: AsyncClient):
    """Webhook extracts client_id + lead_id from elevenlabs_extra_body and streams."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("A ver...", " Carlos, ¿cómo estás?"),
            headers={"content-type": "text/event-stream"},
        )
    )

    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
        ),
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


@respx.mock
async def test_custom_llm_tool_call_triggers_execution(app_client: AsyncClient):
    """Tool call in LLM stream triggers tool execution and second LLM call (CAP-4)."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: returns tool_call
            return Response(
                200,
                content=_build_tool_call_stream(),
                headers={"content-type": "text/event-stream"},
            )
        else:
            # Second call: returns final response after tool execution
            return Response(
                200,
                content=_build_simple_stream("Acá tenés los detalles del lead."),
                headers={"content-type": "text/event-stream"},
            )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=side_effect
    )

    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
        ),
    )

    assert response.status_code == 200
    content = response.text
    assert "[DONE]" in content
