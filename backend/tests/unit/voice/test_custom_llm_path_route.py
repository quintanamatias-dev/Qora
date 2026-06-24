"""Unit tests for the path-based tenant resolution route (CAP-1).

Tests for:
- T01: _process_custom_llm_request helper exists with correct signature
- T04: Happy path SSE stream via POST /voice/{client_id}/custom-llm/chat/completions
- T06: Unknown tenant → 404
- T07: Inactive tenant → 403
- T09: client_id mismatch — path wins, warning logged
- T11: custom_llm_path_request log event emitted
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import inspect
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# T01 — RED: _process_custom_llm_request helper exists with correct signature
# ---------------------------------------------------------------------------


def test_process_custom_llm_request_helper_exists():
    """_process_custom_llm_request must exist with signature (body, client_id, request)."""
    from app.voice import webhook

    assert hasattr(
        webhook, "_process_custom_llm_request"
    ), "_process_custom_llm_request helper not found in webhook module"

    helper = webhook._process_custom_llm_request
    sig = inspect.signature(helper)
    params = list(sig.parameters.keys())

    assert "body" in params, f"'body' param missing from signature. Got: {params}"
    assert (
        "client_id" in params
    ), f"'client_id' param missing from signature. Got: {params}"
    assert "request" in params, f"'request' param missing from signature. Got: {params}"


# ---------------------------------------------------------------------------
# Helpers — SSE stream builders
# ---------------------------------------------------------------------------


def _make_sse_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
) -> bytes:
    """Build a fake OpenAI SSE data line."""
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if content is not None:
        choice["delta"]["content"] = content
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "choices": [choice],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _make_sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def _build_simple_stream(*tokens: str) -> bytes:
    chunks = b""
    for token in tokens:
        chunks += _make_sse_chunk(content=token)
    chunks += _make_sse_chunk(finish_reason="stop")
    chunks += _make_sse_done()
    return chunks


# ---------------------------------------------------------------------------
# App fixture (unit-level — isolated SQLite)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(tmp_path: Path):
    """Create a test app with isolated SQLite and a seeded active tenant."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/path_route_test.db",
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


@pytest_asyncio.fixture
async def app_client_with_inactive(tmp_path: Path):
    """Create a test app with an inactive tenant to verify 403 behavior."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/inactive_test.db",
    )

    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import create_client

        # Create an inactive tenant
        await create_client(
            sess,
            id="inactive-tenant",
            name="Inactive Corp",
            agent_name="Bot",
            voice_id="pNInz6obpgDQGcFmaJgB",
            is_active=False,
        )
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
# Valid body builder
# ---------------------------------------------------------------------------


def _valid_body(
    client_id: str | None = None,
    lead_id: str = "lead-quintana-001",
    message: str = "Hola, ¿me podés contar sobre el seguro?",
    conversation_id: str = "conv-path-001",
) -> dict:
    body: dict = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": message}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": lead_id,
            "conversation_id": conversation_id,
        },
    }
    if client_id is not None:
        body["elevenlabs_extra_body"]["client_id"] = client_id
    return body


# ---------------------------------------------------------------------------
# T04 — RED: Happy path SSE via path-based route
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_happy_path_returns_sse(app_client: AsyncClient):
    """POST /voice/{client_id}/custom-llm/chat/completions returns 200 + SSE stream."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola,", " ¿cómo estás?"),
            headers={"content-type": "text/event-stream"},
        )
    )

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    assert "text/event-stream" in response.headers.get(
        "content-type", ""
    ), f"Expected text/event-stream, got: {response.headers.get('content-type')}"
    assert (
        "[DONE]" in response.text
    ), f"Expected [DONE] in stream, got: {response.text[:300]}"


# ---------------------------------------------------------------------------
# T06 — RED: Unknown tenant → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_route_unknown_tenant_returns_404(app_client: AsyncClient):
    """POST /voice/{client_id}/... with unknown client_id returns 404."""
    response = await app_client.post(
        "/api/v1/voice/ghost-client/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    data = response.json()
    assert (
        data["detail"]["error"] == "client not found"
    ), f"Expected 'client not found', got: {data}"


# ---------------------------------------------------------------------------
# T07 — RED: Inactive tenant → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_route_inactive_tenant_returns_403(
    app_client_with_inactive: AsyncClient,
):
    """POST /voice/{client_id}/... with is_active=False tenant returns 403."""
    response = await app_client_with_inactive.post(
        "/api/v1/voice/inactive-tenant/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert (
        response.status_code == 403
    ), f"Expected 403, got {response.status_code}: {response.text}"
    data = response.json()
    assert (
        data["detail"]["error"] == "Tenant disabled"
    ), f"Expected 'Tenant disabled', got: {data}"


# ---------------------------------------------------------------------------
# T09 — RED: client_id mismatch — path wins, warning logged
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_client_id_mismatch_path_wins(app_client: AsyncClient, caplog):
    """When path client_id differs from body client_id, path wins and warning is logged."""
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Ok"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Body has "other-client", path has "quintana-seguros"
    body = _valid_body()
    body["elevenlabs_extra_body"]["client_id"] = "other-client"

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json=body,
        )

    # Path wins — quintana-seguros is valid → 200
    assert (
        response.status_code == 200
    ), f"Expected 200 (path wins), got {response.status_code}: {response.text}"

    # Warning must be logged
    mismatch_logs = [e for e in cap if e.get("event") == "client_id_mismatch"]
    assert (
        len(mismatch_logs) >= 1
    ), f"Expected client_id_mismatch warning, got events: {[e.get('event') for e in cap]}"
    mismatch = mismatch_logs[0]
    assert (
        mismatch.get("path_client_id") == "quintana-seguros"
    ), f"path_client_id wrong: {mismatch}"
    assert (
        mismatch.get("body_client_id") == "other-client"
    ), f"body_client_id wrong: {mismatch}"


# ---------------------------------------------------------------------------
# T11 — RED: custom_llm_path_request log event emitted
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_emits_custom_llm_path_request_log(app_client: AsyncClient):
    """Path route emits custom_llm_path_request log with client_id, conversation_id, message_count, model."""
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Buenas"),
            headers={"content-type": "text/event-stream"},
        )
    )

    body = _valid_body(conversation_id="conv-log-test-001")

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json=body,
        )

    assert response.status_code == 200

    path_logs = [e for e in cap if e.get("event") == "custom_llm_path_request"]
    assert (
        len(path_logs) >= 1
    ), f"Expected custom_llm_path_request log, got: {[e.get('event') for e in cap]}"
    log = path_logs[0]
    assert log.get("client_id") == "quintana-seguros", f"client_id missing/wrong: {log}"
    assert "message_count" in log, f"message_count missing: {log}"
    assert "model" in log, f"model missing: {log}"
    # conversation_id should be present (either from body or generated)
    assert "conversation_id" in log, f"conversation_id missing: {log}"


# ---------------------------------------------------------------------------
# T24 — RED: Missing /chat/completions suffix → 404 by FastAPI routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_route_missing_chat_completions_suffix_returns_404(
    app_client: AsyncClient,
):
    """POST /voice/{client_id}/custom-llm (no /chat/completions) must return 404.

    FastAPI has no route for this path — routing returns 404 with no server error.
    Verifies S5: 'Missing /chat/completions suffix — 404 via routing'.
    """
    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm",
        json=_valid_body(),
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 (no route match), got {response.status_code}: {response.text}"
    # Must not trigger a server-side error (no 500)
    assert response.status_code != 500, "Route returned 500 — routing bug"


# ---------------------------------------------------------------------------
# T25 — RED: Invalid tenant format in path → 404 (defensive behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_route_invalid_tenant_special_chars_returns_404(
    app_client: AsyncClient,
):
    """POST /voice/INVALID!!TENANT/... with special chars → 404 (client not found).

    Verifies S6: invalid/special-char tenant format must return exactly 404.
    FastAPI accepts any string path param; the tenant lookup finds no record and
    the handler returns 404 with {"error": "client not found"}.
    Must NOT return 422 (Pydantic validation error) or 500 (unhandled exception).
    """
    response = await app_client.post(
        "/api/v1/voice/INVALID!!TENANT/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 for invalid tenant format, got {response.status_code}: {response.text}"
    assert (
        response.status_code != 500
    ), "Invalid tenant format caused 500 — security risk"


@pytest.mark.asyncio
async def test_path_route_path_traversal_tenant_does_not_return_500(
    app_client: AsyncClient,
):
    """POST /voice/../etc/passwd/... must return 404 and not leak traversal errors.

    The client_id `../etc/passwd` is not a valid tenant ID in the DB — must return 404.
    httpx percent-encodes the slashes (%2F) before sending; FastAPI's URL normalization
    handles path segment isolation so no actual traversal occurs. The tenant lookup
    finds no record and returns 404 safely.
    Verifies S6: path traversal input must return exactly 404 (not 422, not 500).
    """
    # FastAPI URL decodes path params — this goes through tenant lookup, finds nothing
    # Note: httpx will URL-encode this, reaching the handler as literal "../etc/passwd"
    response = await app_client.post(
        "/api/v1/voice/..%2Fetc%2Fpasswd/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 for path traversal input, got {response.status_code}: {response.text}"
    assert response.status_code != 500, "Path traversal input caused 500 — security bug"


@pytest.mark.asyncio
async def test_path_route_very_long_tenant_returns_404(
    app_client: AsyncClient,
):
    """POST /voice/{300-char-string}/... must return exactly 404 — no tenant registered.

    Verifies S6: very long string must return 404 (not 422, not 500).
    FastAPI accepts arbitrary string path params with no length validation; the
    tenant lookup receives the full string, finds no matching record, and the handler
    returns 404 with {"error": "client not found"}.
    """
    long_tenant = "a" * 300
    response = await app_client.post(
        f"/api/v1/voice/{long_tenant}/custom-llm/chat/completions",
        json=_valid_body(),
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 for very long tenant, got {response.status_code}: {response.text}"
    assert response.status_code != 500, "Very long tenant input caused 500 — safety bug"


# ---------------------------------------------------------------------------
# Two-tenant fixture for concurrency tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_tenant_app_client(tmp_path: Path):
    """Create a test app with TWO active tenants for concurrency isolation tests.

    AD-3: Uses inline create_client() for the second tenant instead of the removed
    seed_demo_inmobiliaria(). The test-tenant-b fixture is self-contained and isolated.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/two_tenant_test.db",
    )

    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana, create_client
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        # Inline factory — isolated test-only tenant replacing removed demo-inmobiliaria seed
        await create_client(
            sess,
            id="test-tenant-b",
            name="Test Broker B",
            agent_name="TestAgent",
            voice_id="v-test-b",
        )
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
# T26 — RED: Concurrent requests — different tenants, same conversation_id
#             session_store must NOT leak state between tenants
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_concurrent_tenants_same_conversation_id_no_cross_contamination(
    two_tenant_app_client: AsyncClient,
):
    """Two concurrent requests from different tenants sharing the same conversation_id
    must each complete with 200 and their session_store entries must retain correct
    client_id (no cross-tenant leakage).

    Verifies S7: Concurrent requests for different tenants — no cross-contamination.

    RED CONDITION: Before the fix, session_store is keyed only by conversation_id.
    When two tenants use the same conversation_id, the second create() call overwrites
    the first entry, corrupting the first tenant's session state.
    After the fix (composite key), each tenant keeps its own entry.
    """
    shared_conv_id = "conv_shared_id_race"

    # Mock OpenAI for both tenant requests
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola desde el tenant"),
            headers={"content-type": "text/event-stream"},
        )
    )

    body_quintana = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hola quintana"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            "conversation_id": shared_conv_id,
        },
    }
    body_tenant_b = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hola tenant b"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "conversation_id": shared_conv_id,
        },
    }

    # Run both concurrently
    resp_quintana, resp_tenant_b = await asyncio.gather(
        two_tenant_app_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json=body_quintana,
        ),
        two_tenant_app_client.post(
            "/api/v1/voice/test-tenant-b/custom-llm/chat/completions",
            json=body_tenant_b,
        ),
    )

    # Both must succeed
    assert (
        resp_quintana.status_code == 200
    ), f"quintana-seguros expected 200, got {resp_quintana.status_code}: {resp_quintana.text}"
    assert (
        resp_tenant_b.status_code == 200
    ), f"test-tenant-b expected 200, got {resp_tenant_b.status_code}: {resp_tenant_b.text}"

    # Verify session_store isolation: each tenant's session must have the right client_id
    from app.voice.session import session_store

    # After the fix, composite key (client_id, conversation_id) means both entries coexist
    state_quintana = session_store.get(("quintana-seguros", shared_conv_id))
    state_tenant_b = session_store.get(("test-tenant-b", shared_conv_id))

    assert state_quintana is not None, (
        "session_store has no entry for (quintana-seguros, conv_shared_id_race). "
        "Fix: change session_store key to (client_id, conversation_id) tuple."
    )
    assert state_tenant_b is not None, (
        "session_store has no entry for (test-tenant-b, conv_shared_id_race). "
        "Fix: change session_store key to (client_id, conversation_id) tuple."
    )
    assert (
        state_quintana.client_id == "quintana-seguros"
    ), f"session_store contamination: quintana entry has client_id={state_quintana.client_id!r}"
    assert (
        state_tenant_b.client_id == "test-tenant-b"
    ), f"session_store contamination: tenant-b entry has client_id={state_tenant_b.client_id!r}"


# ---------------------------------------------------------------------------
# T01 — RED: Session creation stores elevenlabs_conversation_id (CAP-3 REQ-3.1)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_creates_session_with_conversation_id(app_client: AsyncClient):
    """POST to path route with conversation_id → CallSession.elevenlabs_conversation_id persisted."""
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            "conversation_id": "conv_abc123",
        },
        "conversation_id": "conv_abc123",
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )
    assert response.status_code == 200

    # Verify session was created with elevenlabs_conversation_id
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(
                CallSession.elevenlabs_conversation_id == "conv_abc123"
            )
        )
        cs = result.scalar_one_or_none()
        assert (
            cs is not None
        ), "No CallSession found with elevenlabs_conversation_id='conv_abc123'"
        assert cs.elevenlabs_conversation_id == "conv_abc123"


# ---------------------------------------------------------------------------
# T02 — RED: Session creation stores lead_id (CAP-3 REQ-3.2)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_creates_session_with_lead_id(app_client: AsyncClient):
    """POST with elevenlabs_extra_body.lead_id → CallSession.lead_id persisted."""
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test lead_id"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            "conversation_id": "conv_lead_id_test",
        },
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )
    assert response.status_code == 200

    # Verify session was created with lead_id
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(
                CallSession.elevenlabs_conversation_id == "conv_lead_id_test"
            )
        )
        cs = result.scalar_one_or_none()
        assert cs is not None, "No CallSession found for conv_lead_id_test"
        assert (
            cs.lead_id == "lead-quintana-001"
        ), f"Expected lead_id='lead-quintana-001', got {cs.lead_id!r}"


# ---------------------------------------------------------------------------
# T03 — RED: Empty strings coerced to NULL (CAP-3 REQ-3.3)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_coerces_empty_strings_to_null(app_client: AsyncClient):
    """POST with empty-string lead_id in elevenlabs_extra_body → CallSession.lead_id IS NULL.

    Also verifies that when a real conversation_id is provided alongside an empty lead_id,
    the session is found by elevenlabs_conversation_id with lead_id=NULL.
    This test is RED because: (a) elevenlabs_conversation_id is not yet stored (T01 fix needed),
    and (b) when T01-T02 fix is applied, empty lead_id must NOT be stored as "" but as NULL.
    """
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Ok"),
            headers={"content-type": "text/event-stream"},
        )
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test coercion"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "",
            "conversation_id": "conv_coerce_test_001",
        },
        "conversation_id": "conv_coerce_test_001",
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )
    assert response.status_code == 200

    # Verify: session found by elevenlabs_conversation_id AND lead_id is NULL
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(
                CallSession.elevenlabs_conversation_id == "conv_coerce_test_001"
            )
        )
        cs = result.scalar_one_or_none()
        assert cs is not None, (
            "No CallSession found with elevenlabs_conversation_id='conv_coerce_test_001'. "
            "Fix T04/T05 to store conversation_id on session creation."
        )
        assert (
            cs.lead_id is None
        ), f"Expected lead_id=NULL (empty string coerced to None), got {cs.lead_id!r}"


# ---------------------------------------------------------------------------
# T34 — CAP-1 same-value precedence test
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_same_client_id_in_both_path_and_body(app_client: AsyncClient):
    """CAP-1: When path and body client_id are EQUAL, request succeeds with no mismatch warning.

    Triangulation: test_path_route_client_id_mismatch_path_wins covers DIFFERENT values;
    this test covers IDENTICAL values. Ensures the mismatch detection logic ONLY fires on
    actual disagreement — not when path and body happen to carry the same client_id.
    """
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola desde same-value"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Body has SAME client_id as path — should NOT trigger mismatch warning
    body = _valid_body(conversation_id="conv_same_value_test")
    body["elevenlabs_extra_body"]["client_id"] = "quintana-seguros"  # same as path

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
            json=body,
        )

    # Same-value match — path tenant is valid → 200
    assert (
        response.status_code == 200
    ), f"Expected 200 (same-value client_id), got {response.status_code}: {response.text}"
    assert (
        "[DONE]" in response.text
    ), f"Expected [DONE] in SSE stream, got: {response.text[:300]}"

    # Mismatch warning MUST NOT be emitted — values are equal, no disagreement
    mismatch_logs = [e for e in cap if e.get("event") == "client_id_mismatch"]
    assert len(mismatch_logs) == 0, (
        f"client_id_mismatch MUST NOT be emitted when path == body client_id. "
        f"Got {len(mismatch_logs)} mismatch log(s): {mismatch_logs}"
    )


# ---------------------------------------------------------------------------
# T29 — GREEN: Path route accepts request without custom_llm_extra_body (REQ-1.3)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_accepts_request_without_custom_llm_extra_body(
    app_client: AsyncClient,
):
    """POST to path route with NO elevenlabs_extra_body at all → 200, session created with lead_id=NULL.

    REQ-1.3: Backend must tolerate absent custom_llm_extra_body. The frontend may not
    expose a "no-lead" UI mode (product decision), but the backend contract must accept it.
    This test proves the backend contract is satisfied independently of frontend choices.
    """
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Demo mode response"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Body with NO elevenlabs_extra_body key at all (demo/no-lead mode)
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test no extra body"}],
        "stream": True,
        # Deliberately omit elevenlabs_extra_body entirely
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert response.status_code == 200, (
        f"Expected 200 when elevenlabs_extra_body is absent (REQ-1.3), "
        f"got {response.status_code}: {response.text}"
    )
    assert "[DONE]" in response.text, "Expected SSE stream with [DONE]"

    # Session must be created with lead_id=NULL (no lead selected)
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).order_by(CallSession.started_at.desc()).limit(1)
        )
        cs = result.scalar_one_or_none()
        assert cs is not None, "No CallSession was created"
        assert (
            cs.lead_id is None
        ), f"Expected lead_id=NULL when no elevenlabs_extra_body is sent, got {cs.lead_id!r}"


# ---------------------------------------------------------------------------
# T27 — RED: Absent conversation_id must be stored as NULL (CAP-3 / REQ-3.3)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_path_route_absent_conversation_id_stores_null_in_db(
    app_client: AsyncClient,
):
    """POST to path route without any conversation_id → CallSession.elevenlabs_conversation_id IS NULL.

    RED condition: currently webhook.py generates demo-* when conversation_id is falsy,
    then persists it as elevenlabs_conversation_id in DB. After the fix, the demo-* value
    is only used as a session_store key (in-memory); DB column remains NULL.
    """
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Body with NO conversation_id anywhere — neither in root nor in extra_body
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test absent conv_id"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            # NO conversation_id
        },
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )
    assert response.status_code == 200

    # The most-recently created CallSession must have elevenlabs_conversation_id IS NULL
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).order_by(CallSession.started_at.desc()).limit(1)
        )
        cs = result.scalar_one_or_none()
        assert cs is not None, "No CallSession was created"
        assert cs.elevenlabs_conversation_id is None, (
            f"Expected elevenlabs_conversation_id=NULL when no conversation_id is sent, "
            f"got {cs.elevenlabs_conversation_id!r}. "
            f"Fix: split demo-* fallback — use it only for session_store key, not DB."
        )


@respx.mock
@pytest.mark.asyncio
async def test_path_route_empty_string_conversation_id_stores_null_in_db(
    app_client: AsyncClient,
):
    """POST with empty-string conversation_id → CallSession.elevenlabs_conversation_id IS NULL.

    Triangulation: test_path_route_absent_conversation_id_stores_null_in_db covers absent key;
    this covers explicit empty string. Both must coerce to NULL in DB.
    """
    from app.calls.models import CallSession
    from app.core import database as db_module
    from sqlalchemy import select

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Ok"),
            headers={"content-type": "text/event-stream"},
        )
    )

    # Body with conversation_id: "" (empty string)
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Test empty conv_id"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": "lead-quintana-001",
            "conversation_id": "",
        },
        "conversation_id": "",
    }

    response = await app_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )
    assert response.status_code == 200

    # Most-recently created CallSession must have elevenlabs_conversation_id IS NULL
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).order_by(CallSession.started_at.desc()).limit(1)
        )
        cs = result.scalar_one_or_none()
        assert cs is not None, "No CallSession was created"
        assert cs.elevenlabs_conversation_id is None, (
            f"Expected elevenlabs_conversation_id=NULL when conversation_id='' is sent, "
            f"got {cs.elevenlabs_conversation_id!r}. "
            f"Fix: coerce empty string to None before persisting."
        )
