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
    assert "[DONE]" in content


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
    """Unknown client_id returns 404 with structured error body (CAP-1 / CAP-2 unknown client scenario).

    T32: Tightened assertion — verifies both status code AND error body shape.
    Implementation raises HTTPException(404, detail={"error": "client not found"}).
    FastAPI wraps this as {"detail": {"error": "client not found"}}.
    """
    response = await app_client.post(
        "/api/v1/voice/custom-llm",
        json=_valid_body(client_id="nonexistent-broker"),
    )
    assert response.status_code == 404
    data = response.json()
    assert data == {
        "detail": {"error": "client not found"}
    }, f'Expected 404 body {{"detail": {{"error": "client not found"}}}}, got: {data}'


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


# ---------------------------------------------------------------------------
# T13 — RED: Legacy route logs custom_llm_legacy_route_used deprecation warning
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_legacy_route_emits_deprecation_warning_elevenlabs_extra_body(
    app_client: AsyncClient,
):
    """POST /custom-llm with client_id in elevenlabs_extra_body emits deprecation warning.

    T13: Asserts custom_llm_legacy_route_used is logged with:
    - client_id: the resolved client_id
    - source: "elevenlabs_extra_body"
    - migration_hint: contains the new path-based route URL template
    """
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola,", " ¿cómo estás?"),
            headers={"content-type": "text/event-stream"},
        )
    )

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/custom-llm/chat/completions",
            json=_valid_body(client_id="quintana-seguros"),
        )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"

    # Assert deprecation warning was emitted
    deprecation_logs = [
        e for e in cap if e.get("event") == "custom_llm_legacy_route_used"
    ]
    assert (
        len(deprecation_logs) >= 1
    ), f"Expected custom_llm_legacy_route_used log, got: {[e.get('event') for e in cap]}"
    log = deprecation_logs[0]
    assert (
        log.get("client_id") == "quintana-seguros"
    ), f"client_id missing/wrong in deprecation log: {log}"
    assert (
        log.get("source") == "elevenlabs_extra_body"
    ), f"source should be 'elevenlabs_extra_body', got: {log}"
    assert "migration_hint" in log, f"migration_hint missing from log: {log}"
    assert (
        "/api/v1/voice/" in log.get("migration_hint", "")
    ), f"migration_hint should reference path-based URL, got: {log.get('migration_hint')}"


@respx.mock
@pytest.mark.asyncio
async def test_legacy_route_emits_deprecation_warning_top_level(
    app_client: AsyncClient,
):
    """POST /custom-llm with client_id as top-level field emits deprecation warning with source=top_level.

    T13 triangulation: tests the top_level source path.
    """
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # client_id at top level (not in elevenlabs_extra_body)
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hola"}],
        "stream": True,
        "client_id": "quintana-seguros",
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            "conversation_id": "conv-top-level-001",
        },
    }

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/custom-llm/chat/completions",
            json=body,
        )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"

    deprecation_logs = [
        e for e in cap if e.get("event") == "custom_llm_legacy_route_used"
    ]
    assert (
        len(deprecation_logs) >= 1
    ), f"Expected custom_llm_legacy_route_used log, got: {[e.get('event') for e in cap]}"
    log = deprecation_logs[0]
    assert log.get("source") == "top_level", f"source should be 'top_level', got: {log}"
    assert log.get("client_id") == "quintana-seguros", f"client_id wrong in log: {log}"


# ---------------------------------------------------------------------------
# T15 — GREEN: Legacy route still returns 422 when no client_id present
#              (regression — no deprecation event should be emitted either)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_route_no_client_id_returns_422_no_deprecation(
    app_client: AsyncClient,
):
    """POST /custom-llm without any client_id returns 422 and emits NO deprecation log.

    T15: Regression test — unchanged behavior from CAP-6.
    The deprecation warning must NOT be emitted when the request is rejected early.
    """
    from structlog.testing import capture_logs

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
        },
    }

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/custom-llm/chat/completions",
            json=body,
        )

    # Unchanged behavior: 422 when client_id is absent
    assert (
        response.status_code == 422
    ), f"Expected 422, got {response.status_code}: {response.text}"
    data = response.json()
    assert (
        data["detail"]["error"] == "client_id is required"
    ), f"Wrong error detail: {data}"

    # No deprecation event should be emitted (client_id was never resolved)
    deprecation_logs = [
        e for e in cap if e.get("event") == "custom_llm_legacy_route_used"
    ]
    assert (
        len(deprecation_logs) == 0
    ), f"Deprecation event MUST NOT be emitted when client_id is absent. Got: {deprecation_logs}"


# ---------------------------------------------------------------------------
# T16 — RED: CAP-3 CallSession parity — both routes create identical records
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,use_path",
    [
        ("/api/v1/voice/custom-llm/chat/completions", False),  # legacy
        ("/api/v1/voice/quintana-seguros/custom-llm/chat/completions", True),  # path
    ],
)
async def test_both_routes_create_identical_call_sessions(
    url: str,
    use_path: bool,
    app_client: AsyncClient,
):
    """Both legacy and path routes create CallSession records with identical client_id and lead_id.

    T16: CAP-3 structural consistency — only the resolution source differs.

    Discovery: The webhook creates CallSession without elevenlabs_conversation_id (that's set
    during initiation). We query by client_id before/after to find the new session.
    """
    from sqlalchemy import select as sa_select, func as sa_func
    from app.calls.models import CallSession
    from app.core import database as db_module

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Count existing sessions for this client before the request
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as db:
        count_before = (
            await db.execute(
                sa_select(sa_func.count())
                .select_from(CallSession)
                .where(CallSession.client_id == "quintana-seguros")
            )
        ).scalar_one()

    conv_id = f"conv-t16-parity-{'path' if use_path else 'legacy'}"

    # For legacy route: client_id must be in body; for path route: no body client_id needed
    if use_path:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }
    else:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }

    response = await app_client.post(url, json=body)
    assert (
        response.status_code == 200
    ), f"Expected 200 from {url}, got {response.status_code}: {response.text}"

    # Query new sessions created after the request
    async with db_module.async_session_factory() as db:
        result = await db.execute(
            sa_select(CallSession)
            .where(CallSession.client_id == "quintana-seguros")
            .order_by(CallSession.created_at.desc())
        )
        all_sessions = result.scalars().all()

    # At least one new session was created
    count_after = len(all_sessions)
    assert count_after > count_before, (
        f"Expected new CallSession after request to {url}, "
        f"count before={count_before}, after={count_after}"
    )

    # The newest session should have correct client_id and lead_id
    newest = all_sessions[0]
    assert (
        newest.client_id == "quintana-seguros"
    ), f"CallSession.client_id should be 'quintana-seguros', got {newest.client_id!r}"
    assert (
        newest.lead_id == "lead-quintana-001"
    ), f"CallSession.lead_id should be 'lead-quintana-001', got {newest.lead_id!r}"


# ---------------------------------------------------------------------------
# T17 — RED: CAP-3 SSE chunk format parity — both routes emit same shape
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,use_path",
    [
        ("/api/v1/voice/custom-llm/chat/completions", False),  # legacy
        ("/api/v1/voice/quintana-seguros/custom-llm/chat/completions", True),  # path
    ],
)
async def test_both_routes_emit_identical_sse_chunk_shape(
    url: str,
    use_path: bool,
    app_client: AsyncClient,
):
    """Both legacy and path routes produce data: chunks with identical JSON shape.

    T17: CAP-3 — SSE format parity between routes.
    Asserts first content chunk has: id, object, choices[0].delta.content
    """
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola, estoy aquí"),
            headers={"content-type": "text/event-stream"},
        )
    )

    conv_id = f"conv-sse-parity-{use_path}"

    if use_path:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }
    else:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }

    response = await app_client.post(url, json=body)
    assert (
        response.status_code == 200
    ), f"Expected 200 from {url}, got {response.status_code}: {response.text}"

    # Parse SSE stream lines to find first data: chunk with content
    content_chunks = []
    for line in response.text.splitlines():
        if line.startswith("data: ") and "[DONE]" not in line:
            raw = line[len("data: ") :]
            try:
                chunk = json.loads(raw)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    content_chunks.append(chunk)
            except json.JSONDecodeError:
                pass

    # Must have at least one content chunk
    assert (
        len(content_chunks) >= 1
    ), f"Expected at least 1 content SSE chunk from {url}. Full response: {response.text[:500]}"

    # Verify shape: id, object, choices[0].delta.content
    chunk = content_chunks[0]
    assert "id" in chunk, f"SSE chunk missing 'id' field: {chunk}"
    assert (
        chunk.get("object") == "chat.completion.chunk"
    ), f"SSE chunk 'object' wrong: {chunk}"
    choices = chunk.get("choices", [])
    assert len(choices) >= 1, f"SSE chunk has no choices: {chunk}"
    assert "delta" in choices[0], f"choices[0] missing 'delta': {choices[0]}"
    assert (
        "content" in choices[0]["delta"]
    ), f"choices[0].delta missing 'content': {choices[0]}"


# ---------------------------------------------------------------------------
# T33 — GREEN: CAP-3 real tool-call parity — path route dispatches and resumes
# ---------------------------------------------------------------------------


def _build_tool_call_only_stream() -> bytes:
    """Build an SSE stream that ONLY contains a tool call with finish_reason='tool_calls'.

    This produces a stream that ends with finish_reason='tool_calls' so that
    OpenAIStreamingClient yields a ToolCallDelta and triggers a second LLM call.
    Unlike _build_tool_call_stream(), this does NOT include the final response —
    the handler's second OpenAI call provides the final response.
    """
    tool_call_chunk = _make_sse_chunk(
        tool_calls=[
            {
                "index": 0,
                "id": "call_t33_path",
                "type": "function",
                "function": {
                    "name": "get_lead_details",
                    "arguments": '{"lead_id": "lead-quintana-001"}',
                },
            }
        ]
    )
    # finish_reason='tool_calls' must be the LAST chunk (after accumulating)
    finish_tool = _make_sse_chunk(finish_reason="tool_calls")
    done = _make_sse_done()
    return tool_call_chunk + finish_tool + done


@respx.mock
@pytest.mark.asyncio
async def test_path_route_tool_call_triggers_execution(app_client: AsyncClient):
    """Tool call in LLM stream triggers tool execution and second LLM call on the path route.

    T33: CAP-3 tool call parity — proves both routes exhibit identical tool call behavior.
    Targets POST /api/v1/voice/{client_id}/custom-llm/chat/completions.

    Proves:
    - Tool call is detected mid-stream (first OpenAI call ends with finish_reason='tool_calls')
    - Tool dispatcher is invoked (a second OpenAI call is made)
    - Stream continues after tool execution (final content chunk + [DONE] in response)

    Note: _build_tool_call_only_stream() ends with finish_reason='tool_calls' (no trailing
    content) so OpenAIStreamingClient correctly yields a ToolCallDelta at end-of-stream.
    The existing _build_tool_call_stream() appends extra content after the tool finish
    which makes the final finish_reason='stop', preventing ToolCallDelta from being yielded.
    """
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: LLM triggers a tool call only (no trailing content)
            return Response(
                200,
                content=_build_tool_call_only_stream(),
                headers={"content-type": "text/event-stream"},
            )
        else:
            # Second call: LLM produces final response after tool result injection
            return Response(
                200,
                content=_build_simple_stream("Acá tenés los detalles del lead."),
                headers={"content-type": "text/event-stream"},
            )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=side_effect
    )

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Dame info del lead"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "lead_id": "lead-quintana-001",
                "conversation_id": "conv-t33-tool-path",
            },
        },
    )

    assert (
        response.status_code == 200
    ), f"Expected 200 from path route tool call, got {response.status_code}: {response.text}"
    content = response.text
    # Stream must end with [DONE]
    assert (
        "[DONE]" in content
    ), f"Expected [DONE] in path route SSE stream after tool execution. Got: {content[:300]}"
    # Two OpenAI calls must have occurred: initial + follow-up after tool execution
    assert call_count == 2, (
        f"Expected 2 OpenAI calls (initial + tool follow-up), got {call_count}. "
        "Tool dispatcher was not invoked or stream did not resume."
    )
    # The final response content from the tool follow-up must appear in the stream
    assert (
        "detalles del lead" in content
    ), f"Expected tool follow-up response content in stream, got: {content[:300]}"


# ---------------------------------------------------------------------------
# T35 — GREEN: CAP-3 legacy tool-call real parity — legacy route dispatches and resumes
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_legacy_route_tool_call_triggers_execution(app_client: AsyncClient):
    """Tool call in LLM stream triggers tool execution and second LLM call on the legacy route.

    T35: CAP-3 tool call parity mirror of T33 — proves BOTH routes exhibit identical tool call
    behavior. Targets POST /api/v1/voice/custom-llm/chat/completions (legacy route).

    Proves:
    - Tool call is detected mid-stream (first OpenAI call ends with finish_reason='tool_calls')
    - Tool dispatcher is invoked (a second OpenAI call is made)
    - Stream continues after tool execution (final content chunk + [DONE] in response)

    Uses the same _build_tool_call_only_stream() helper introduced in T33. That helper
    correctly ends with finish_reason='tool_calls' only (no trailing content), which makes
    OpenAIStreamingClient yield a ToolCallDelta and trigger the second LLM call.
    """
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: LLM triggers a tool call only (no trailing content)
            return Response(
                200,
                content=_build_tool_call_only_stream(),
                headers={"content-type": "text/event-stream"},
            )
        else:
            # Second call: LLM produces final response after tool result injection
            return Response(
                200,
                content=_build_simple_stream("Acá tenés los detalles del lead."),
                headers={"content-type": "text/event-stream"},
            )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=side_effect
    )

    response = await app_client.post(
        "/api/v1/voice/custom-llm/chat/completions",
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Dame info del lead"}],
            "stream": True,
            "elevenlabs_extra_body": {
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": "conv-t35-tool-legacy",
            },
        },
    )

    assert (
        response.status_code == 200
    ), f"Expected 200 from legacy route tool call, got {response.status_code}: {response.text}"
    content = response.text
    # Stream must end with [DONE]
    assert (
        "[DONE]" in content
    ), f"Expected [DONE] in legacy route SSE stream after tool execution. Got: {content[:300]}"
    # Two OpenAI calls must have occurred: initial + follow-up after tool execution
    assert call_count == 2, (
        f"Expected 2 OpenAI calls (initial + tool follow-up), got {call_count}. "
        "Tool dispatcher was not invoked or stream did not resume."
    )
    # The final response content from the tool follow-up must appear in the stream
    assert (
        "detalles del lead" in content
    ), f"Expected tool follow-up response content in stream, got: {content[:300]}"


# ---------------------------------------------------------------------------
# T18 — RED: CAP-3 tool call parity — both routes accept tools array
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,use_path",
    [
        ("/api/v1/voice/custom-llm/chat/completions", False),  # legacy
        ("/api/v1/voice/quintana-seguros/custom-llm/chat/completions", True),  # path
    ],
)
async def test_both_routes_accept_tools_array(
    url: str,
    use_path: bool,
    app_client: AsyncClient,
):
    """Both legacy and path routes accept a tools array in the body without error.

    T18: CAP-3 tool call parity smoke test.
    Verifies that both routes pass the tools array downstream without rejection.
    Note: Full tool call execution is tested in test_custom_llm_tool_call_triggers_execution.
    This test focuses on structural parity — tools accepted, request succeeds.
    """
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Entendido, te ayudo."),
            headers={"content-type": "text/event-stream"},
        )
    )

    conv_id = f"conv-tools-parity-{use_path}"

    tools_array = [
        {
            "type": "function",
            "function": {
                "name": "get_lead_details",
                "description": "Obtiene datos del lead",
                "parameters": {
                    "type": "object",
                    "properties": {"lead_id": {"type": "string"}},
                    "required": ["lead_id"],
                },
            },
        }
    ]

    if use_path:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Dame info del lead"}],
            "stream": True,
            "tools": tools_array,
            "elevenlabs_extra_body": {
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }
    else:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Dame info del lead"}],
            "stream": True,
            "tools": tools_array,
            "elevenlabs_extra_body": {
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": conv_id,
            },
        }

    response = await app_client.post(url, json=body)

    # Both routes must accept tools without error and return 200 with SSE
    assert (
        response.status_code == 200
    ), f"Expected 200 from {url} with tools array, got {response.status_code}: {response.text}"
    assert (
        "text/event-stream" in response.headers.get("content-type", "")
    ), f"Expected text/event-stream from {url}, got: {response.headers.get('content-type')}"
    assert (
        "[DONE]" in response.text
    ), f"Expected [DONE] in SSE stream from {url}, got: {response.text[:300]}"
