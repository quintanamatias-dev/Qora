"""Tests for CorrelationMiddleware — B9 Observability PR1.

Spec: sdd/b9-observability/spec — capability: correlation-middleware

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after backend/app/middleware/correlation.py is created.
"""

from __future__ import annotations

import re
import uuid

import pytest
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Minimal test app factory
# ---------------------------------------------------------------------------


def make_app_with_correlation() -> FastAPI:
    """Build a tiny FastAPI app wrapped by CorrelationMiddleware."""
    from app.middleware.correlation import CorrelationMiddleware

    mini = FastAPI()

    @mini.get("/echo")
    async def echo():
        # Capture current structlog contextvars
        ctx = structlog.contextvars.get_contextvars()
        return {"request_id": ctx.get("request_id", None)}

    @mini.get("/stream")
    async def stream_endpoint():
        async def _gen():
            ctx = structlog.contextvars.get_contextvars()
            rid = ctx.get("request_id", "missing")
            yield f"request_id={rid}".encode()

        return StreamingResponse(_gen(), media_type="text/plain")

    # Wrap with raw ASGI correlation middleware
    return CorrelationMiddleware(mini)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_contextvars():
    """Clear structlog contextvars before and after each test."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Task 1.1 — Request ID generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_without_x_request_id_gets_uuid4(clean_contextvars):
    """Scenario: Request without X-Request-ID — middleware generates a UUID4."""
    app = make_app_with_correlation()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/echo")

    assert response.status_code == 200
    rid_header = response.headers.get("x-request-id")
    assert rid_header is not None, "X-Request-ID header must be set in response"
    # Must be a valid UUID4
    parsed = uuid.UUID(rid_header, version=4)
    assert str(parsed) == rid_header


@pytest.mark.asyncio
async def test_request_with_existing_x_request_id_is_echoed(clean_contextvars):
    """Scenario: Request with existing X-Request-ID — middleware echoes it."""
    app = make_app_with_correlation()
    existing_id = "abc-123"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/echo", headers={"X-Request-ID": existing_id})

    assert response.status_code == 200
    assert response.headers.get("x-request-id") == existing_id
    body = response.json()
    assert body["request_id"] == existing_id


@pytest.mark.asyncio
async def test_request_id_bound_to_structlog_contextvars(clean_contextvars):
    """Scenario: request_id is bound to structlog contextvars during handling."""
    app = make_app_with_correlation()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/echo")

    assert response.status_code == 200
    body = response.json()
    rid_header = response.headers.get("x-request-id")
    # The endpoint reads contextvars — request_id must match the header
    assert body["request_id"] == rid_header


@pytest.mark.asyncio
async def test_malformed_request_id_empty_string_replaced(clean_contextvars):
    """Scenario: empty X-Request-ID is rejected and a new UUID4 is generated."""
    app = make_app_with_correlation()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/echo", headers={"X-Request-ID": ""})

    assert response.status_code == 200
    rid_header = response.headers.get("x-request-id")
    assert rid_header is not None
    # Must be a valid UUID4 (not empty)
    parsed = uuid.UUID(rid_header, version=4)
    assert str(parsed) == rid_header


@pytest.mark.asyncio
async def test_malformed_request_id_too_long_replaced(clean_contextvars):
    """Scenario: X-Request-ID > 128 chars is rejected and a new UUID4 is generated."""
    app = make_app_with_correlation()
    too_long = "x" * 129
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/echo", headers={"X-Request-ID": too_long})

    assert response.status_code == 200
    rid_header = response.headers.get("x-request-id")
    assert rid_header != too_long
    parsed = uuid.UUID(rid_header, version=4)
    assert str(parsed) == rid_header


# ---------------------------------------------------------------------------
# Task 1.1 — Raw ASGI + SSE / StreamingResponse contextvars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_streaming_response_has_request_id_in_contextvars(clean_contextvars):
    """Scenario: StreamingResponse endpoint reads request_id from contextvars.

    This verifies that raw ASGI (NOT BaseHTTPMiddleware) preserves contextvars
    across the full streaming response lifecycle.
    """
    app = make_app_with_correlation()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/stream")

    assert response.status_code == 200
    content = response.text
    # The SSE generator must have found a valid UUID4 in contextvars
    assert content.startswith("request_id=")
    rid = content.split("=", 1)[1]
    parsed = uuid.UUID(rid, version=4)
    assert str(parsed) == rid


@pytest.mark.asyncio
async def test_contextvars_cleared_after_request(clean_contextvars):
    """Scenario: request_id is cleared from contextvars after the response."""
    app = make_app_with_correlation()
    structlog.contextvars.clear_contextvars()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/echo")

    # After the request, structlog contextvars should be empty (or not have request_id)
    ctx = structlog.contextvars.get_contextvars()
    assert "request_id" not in ctx, (
        f"request_id should be cleared after request, but found: {ctx}"
    )
