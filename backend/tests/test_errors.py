"""Tests for canonical ErrorEnvelope — B9 Observability PR1.

Spec: sdd/b9-observability/spec — capability: canonical-error-envelope

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after backend/app/core/errors.py is created and wired.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helpers — minimal app with global exception handlers registered
# ---------------------------------------------------------------------------


def make_error_app() -> FastAPI:
    """Build a tiny FastAPI app with canonical error handlers registered."""
    from app.core.errors import register_error_handlers

    mini = FastAPI()

    # Register global handlers
    register_error_handlers(mini)

    @mini.get("/raise-404")
    async def raise_404():
        raise HTTPException(status_code=404, detail="Call session not found")

    @mini.get("/raise-400-dict")
    async def raise_400_dict():
        raise HTTPException(status_code=400, detail={"error": "lead not found"})

    @mini.get("/raise-422-list")
    async def raise_422_list():
        raise HTTPException(
            status_code=422, detail=[{"loc": ["body"], "msg": "required"}]
        )

    @mini.get("/raise-500")
    async def raise_500():
        raise RuntimeError("unexpected boom")

    class Item(BaseModel):
        name: str
        value: int

    @mini.post("/validate")
    async def validate_body(item: Item):
        return item.model_dump()

    return mini


# ---------------------------------------------------------------------------
# Task 1.3 — ErrorEnvelope model
# ---------------------------------------------------------------------------


def test_error_envelope_model_exists():
    """ErrorEnvelope Pydantic model exists and has correct shape."""
    from app.core.errors import ErrorEnvelope

    env = ErrorEnvelope(error={"code": 404, "message": "not found", "request_id": "abc"})
    assert env.error.code == 404
    assert env.error.message == "not found"
    assert env.error.request_id == "abc"


def test_build_error_response_returns_json_response():
    """build_error_response() returns a JSONResponse with canonical shape."""
    from app.core.errors import build_error_response
    from fastapi.responses import JSONResponse

    resp = build_error_response(status_code=404, detail="Not found", request_id="req-xyz")
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 404

    import json
    body = json.loads(resp.body)
    assert body == {
        "error": {
            "code": 404,
            "message": "Not found",
            "request_id": "req-xyz",
        }
    }


def test_build_error_response_dict_detail_extracts_message():
    """build_error_response() extracts message from dict detail."""
    from app.core.errors import build_error_response

    import json
    resp = build_error_response(
        status_code=400,
        detail={"error": "lead not found"},
        request_id="req-abc",
    )
    body = json.loads(resp.body)
    assert body["error"]["message"] == "lead not found"


def test_build_error_response_dict_detail_message_key():
    """build_error_response() extracts message from dict with 'message' key."""
    from app.core.errors import build_error_response

    import json
    resp = build_error_response(
        status_code=400,
        detail={"message": "something bad"},
        request_id="req-abc",
    )
    body = json.loads(resp.body)
    assert body["error"]["message"] == "something bad"


def test_build_error_response_list_detail_serialized():
    """build_error_response() serializes list detail as string."""
    from app.core.errors import build_error_response

    import json
    resp = build_error_response(
        status_code=422,
        detail=[{"loc": ["body"], "msg": "required"}],
        request_id="req-list",
    )
    body = json.loads(resp.body)
    message = body["error"]["message"]
    # Must be a string representation of the list
    assert isinstance(message, str)
    assert len(message) > 0


def test_build_error_response_no_request_id_uses_empty_string():
    """build_error_response() with no request_id produces empty string, not absent."""
    from app.core.errors import build_error_response

    import json
    resp = build_error_response(status_code=500, detail="Internal error", request_id=None)
    body = json.loads(resp.body)
    # request_id must be present but can be empty string or "unknown"
    assert "request_id" in body["error"]
    assert body["error"]["request_id"] is not None


# ---------------------------------------------------------------------------
# Task 1.3 — Global handlers via integration (mini FastAPI app)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_exception_string_detail_canonical_envelope():
    """Scenario: HTTPException with string detail → canonical envelope."""
    app = make_error_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/raise-404")

    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == 404
    assert body["error"]["message"] == "Call session not found"
    assert "request_id" in body["error"]


@pytest.mark.asyncio
async def test_http_exception_dict_detail_canonical_envelope():
    """Scenario: HTTPException with dict detail → message extracted from 'error' key."""
    app = make_error_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/raise-400-dict")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == 400
    assert body["error"]["message"] == "lead not found"


@pytest.mark.asyncio
async def test_http_exception_list_detail_canonical_envelope():
    """Scenario: HTTPException with list detail → serialized to string."""
    app = make_error_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/raise-422-list")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == 422
    assert isinstance(body["error"]["message"], str)
    assert len(body["error"]["message"]) > 0


@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_500_canonical_envelope():
    """Scenario: unhandled_exception_handler produces a 500 canonical envelope response.

    Tests the handler function directly — Starlette's ServerErrorMiddleware re-raises
    after sending the response, which causes httpx ASGITransport to propagate the exception.
    The handler itself is verified to produce the correct shape.
    """
    from app.core.errors import unhandled_exception_handler
    from fastapi import Request
    from starlette.datastructures import Headers
    import json

    # Build a minimal mock request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/raise-500",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    exc = RuntimeError("unexpected boom")

    response = await unhandled_exception_handler(request, exc)

    assert response.status_code == 500
    assert "application/json" in response.headers.get("content-type", "")
    body = json.loads(response.body)
    assert body["error"]["code"] == 500
    assert body["error"]["message"] == "Internal server error"
    # Must not contain HTML
    assert "<html" not in response.body.decode().lower()


@pytest.mark.asyncio
async def test_request_validation_error_canonical_envelope():
    """Scenario: RequestValidationError (422) → canonical envelope."""
    app = make_error_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Post invalid body — missing required fields
        response = await client.post("/validate", json={"name": "test"})  # missing value

    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == 422
    assert isinstance(body["error"]["message"], str)


@pytest.mark.asyncio
async def test_error_content_type_is_json():
    """Scenario: HTTPException error responses have Content-Type: application/json."""
    app = make_error_app()
    # Only test HTTPException paths — RuntimeError re-raises via ServerErrorMiddleware
    # in test context (Starlette design). The handler's content-type is verified directly.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in ["/raise-404", "/raise-400-dict"]:
            response = await client.get(path)
            ct = response.headers.get("content-type", "")
            assert "application/json" in ct, (
                f"{path} returned Content-Type: {ct!r}, expected application/json"
            )


@pytest.mark.asyncio
async def test_request_id_in_error_envelope_when_correlation_active():
    """Scenario: request_id from correlation middleware appears in error envelope."""
    from app.middleware.correlation import CorrelationMiddleware
    from app.core.errors import register_error_handlers

    mini = FastAPI()
    register_error_handlers(mini)

    @mini.get("/fail")
    async def fail():
        raise HTTPException(status_code=400, detail="test error")

    # Wrap with raw ASGI correlation middleware
    wrapped = CorrelationMiddleware(mini)

    import structlog
    structlog.contextvars.clear_contextvars()

    async with AsyncClient(transport=ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/fail")

    assert response.status_code == 400
    body = response.json()
    rid_header = response.headers.get("x-request-id")
    assert rid_header is not None

    # The error envelope request_id should match the correlation header
    envelope_rid = body["error"]["request_id"]
    assert envelope_rid == rid_header, (
        f"Error envelope request_id {envelope_rid!r} != X-Request-ID {rid_header!r}"
    )
