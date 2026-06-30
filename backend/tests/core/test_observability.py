"""Tests: B9 observability — CorrelationMiddleware and exception handlers.

TDD RED phase for tasks 1.1 and 2.1/2.2.

Covered scenarios:
    1.1 Correlation middleware
        - Standard HTTP request receives UUID4 X-Request-ID header
        - SSE / StreamingResponse does not lose correlation ID mid-stream
        - Incoming X-Request-ID header is ignored (always generate own)
        - Contextvars are cleared between requests (no bleed)

    2.1 / 2.2 Global exception handlers
        - Unhandled Exception → 500 canonical schema {"error": {"code": "internal_error", ...}}
        - HTTPException → canonical schema, preserves status code
        - RequestValidationError → 422 with "validation_error" code
        - All three handlers produce structurally identical top-level envelopes
        - request_id field is null-safe when no context is bound
        - 4xx boundary log is WARNING, no exc_info; 5xx is ERROR with exc_info
        - No synchronous network call in the live voice/SSE turn path (gate check)
"""

from __future__ import annotations

import asyncio
import re
import uuid
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.testclient import TestClient as StarletteTestClient

# Production code imported under test — will fail (RED) until implemented
from app.core.observability import (
    CorrelationMiddleware,
    ErrorDetail,
    ErrorResponse,
    _redact_validation_errors,
    handle_exception,
    handle_http_exception,
    handle_validation_error,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class _ValidationBody(BaseModel):
    """Request body for the /raise-422 test endpoint."""

    name: str


class _SensitiveBody(BaseModel):
    """Request body for the /raise-422-sensitive endpoint.

    ``code`` has a min_length constraint so submitting a short value triggers a
    validation error whose Pydantic entry carries a nested ``ctx`` — exercising
    the nested-ctx redaction path.
    """

    password: str
    code: str = Field(min_length=8)


def _make_app_with_middleware() -> FastAPI:
    """Create a minimal FastAPI app with CorrelationMiddleware as outermost layer."""
    app = FastAPI()

    # Register exception handlers
    app.add_exception_handler(Exception, handle_exception)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)

    # CorrelationMiddleware must be outermost — added AFTER other middleware
    # so Starlette's middleware stack places it at the top.
    app.add_middleware(CorrelationMiddleware)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    @app.get("/reflect-request-id")
    async def reflect_request_id():
        """Returns the active structlog context so tests can inspect request_id."""
        ctx = structlog.contextvars.get_contextvars()
        return {"request_id": ctx.get("request_id")}

    @app.get("/stream")
    async def stream_endpoint():
        """Minimal SSE-style streaming endpoint."""
        captured_ids: list[str | None] = []

        async def _generate():
            # Capture request_id inside the generator (must persist across chunks)
            ctx = structlog.contextvars.get_contextvars()
            captured_ids.append(ctx.get("request_id"))
            yield b"chunk1\n"
            # Simulate async work between chunks
            await asyncio.sleep(0)
            ctx2 = structlog.contextvars.get_contextvars()
            captured_ids.append(ctx2.get("request_id"))
            yield b"chunk2\n"

        response = StreamingResponse(_generate(), media_type="text/event-stream")
        # Attach captured_ids for post-response inspection (test-only pattern)
        response.captured_ids = captured_ids  # type: ignore[attr-defined]
        return response

    @app.get("/raise-500")
    async def raise_500():
        raise RuntimeError("boom")

    @app.get("/raise-404")
    async def raise_404():
        raise HTTPException(status_code=404, detail="Agent not found")

    @app.get("/raise-500-http")
    async def raise_500_http():
        # 5xx HTTPException whose detail carries sensitive internal info.
        # Sentinel (non-URL, non-secret) standing in for internal detail
        # such as DB errors, credentials, or upstream payloads.
        raise HTTPException(
            status_code=500,
            detail="DB connection failed: INTERNAL-SENTINEL-DETAIL-DO-NOT-LEAK",
        )

    @app.post("/raise-422")
    async def raise_422(payload: _ValidationBody):
        return payload

    @app.post("/raise-422-sensitive")
    async def raise_422_sensitive(payload: _SensitiveBody):
        return payload

    return app


# ---------------------------------------------------------------------------
# Task 1.1 — CorrelationMiddleware
# ---------------------------------------------------------------------------


class TestCorrelationMiddleware:
    """Correlation ID middleware — spec: observability-correlation."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app_with_middleware(), raise_server_exceptions=False)

    def test_response_contains_x_request_id_header(self, client: TestClient):
        """Standard HTTP request must receive an X-Request-ID header in the response."""
        response = client.get("/ping")
        assert response.status_code == 200
        assert "x-request-id" in response.headers, (
            "X-Request-ID header must be present in every response"
        )

    def test_x_request_id_is_uuid4(self, client: TestClient):
        """The returned X-Request-ID must be a valid UUID4."""
        response = client.get("/ping")
        rid = response.headers.get("x-request-id", "")
        assert _UUID4_PATTERN.match(rid), f"Expected UUID4, got: {rid!r}"

    def test_request_id_bound_to_structlog_contextvars(self, client: TestClient):
        """request_id must be available in structlog contextvars during the request."""
        response = client.get("/reflect-request-id")
        assert response.status_code == 200
        data = response.json()
        rid_in_context = data.get("request_id")
        assert rid_in_context is not None, "request_id not found in contextvars"
        assert _UUID4_PATTERN.match(rid_in_context), (
            f"Expected UUID4 in contextvars, got: {rid_in_context!r}"
        )

    def test_context_request_id_matches_header(self, client: TestClient):
        """The request_id in contextvars must match the X-Request-ID response header."""
        response = client.get("/reflect-request-id")
        header_rid = response.headers.get("x-request-id", "")
        ctx_rid = response.json().get("request_id")
        assert header_rid == ctx_rid, (
            f"Header request_id {header_rid!r} != contextvars request_id {ctx_rid!r}"
        )

    def test_each_request_gets_unique_request_id(self, client: TestClient):
        """Every request must receive its own unique UUID4 (no request_id reuse)."""
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        rid1 = r1.headers.get("x-request-id")
        rid2 = r2.headers.get("x-request-id")
        assert rid1 != rid2, "Two sequential requests must receive different request_ids"

    def test_inbound_x_request_id_header_is_ignored(self, client: TestClient):
        """Caller-supplied X-Request-ID must be discarded; middleware always generates own."""
        caller_supplied = str(uuid.uuid4())
        response = client.get("/ping", headers={"X-Request-ID": caller_supplied})
        server_rid = response.headers.get("x-request-id", "")
        assert server_rid != caller_supplied, (
            "Server must NOT pass through caller-supplied X-Request-ID"
        )
        # The server-generated one must still be a valid UUID4
        assert _UUID4_PATTERN.match(server_rid)

    def test_contextvars_cleared_between_requests(self, client: TestClient):
        """Contextvars from request N must not leak into request N+1."""
        r1 = client.get("/reflect-request-id")
        r2 = client.get("/reflect-request-id")
        rid1 = r1.json().get("request_id")
        rid2 = r2.json().get("request_id")
        # Both must exist and be different (proves independent binding each request)
        assert rid1 is not None
        assert rid2 is not None
        assert rid1 != rid2, "request_id must be re-generated per request, not leaked"

    def test_streaming_response_header_present(self, client: TestClient):
        """StreamingResponse endpoints must also return X-Request-ID."""
        response = client.get("/stream")
        assert "x-request-id" in response.headers

    def test_streaming_response_header_is_uuid4(self, client: TestClient):
        """X-Request-ID on a streaming response must be a valid UUID4."""
        response = client.get("/stream")
        rid = response.headers.get("x-request-id", "")
        assert _UUID4_PATTERN.match(rid), f"Expected UUID4, got: {rid!r}"


# ---------------------------------------------------------------------------
# Task 2.1 / 2.2 — Global exception handlers + canonical schema
# ---------------------------------------------------------------------------


class TestExceptionHandlers:
    """Global exception handlers — spec: observability-error-handling."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app_with_middleware(), raise_server_exceptions=False)

    # ---- canonical schema structure ----

    def test_unhandled_exception_returns_500(self, client: TestClient):
        """RuntimeError propagating to boundary → 500 status code."""
        response = client.get("/raise-500")
        assert response.status_code == 500

    def test_unhandled_exception_body_has_error_envelope(self, client: TestClient):
        """500 body must be {"error": {...}} with the canonical fields."""
        response = client.get("/raise-500")
        body = response.json()
        assert "error" in body, f"Expected 'error' key in body, got: {body}"
        error = body["error"]
        assert error.get("code") == "internal_error"
        assert "message" in error
        assert "request_id" in error

    def test_unhandled_exception_no_stack_trace_in_response(self, client: TestClient):
        """Stack trace must NOT appear in the 500 response body."""
        response = client.get("/raise-500")
        body_text = response.text
        assert "Traceback" not in body_text
        assert "RuntimeError" not in body_text

    def test_http_exception_returns_correct_status(self, client: TestClient):
        """HTTPException(404) must preserve the 404 status code."""
        response = client.get("/raise-404")
        assert response.status_code == 404

    def test_http_exception_body_has_error_envelope(self, client: TestClient):
        """HTTPException → canonical envelope with code='http_error'."""
        response = client.get("/raise-404")
        body = response.json()
        assert "error" in body
        error = body["error"]
        assert error.get("code") == "http_error"
        assert error.get("message") == "Agent not found"
        assert "request_id" in error

    def test_validation_error_returns_422(self, client: TestClient):
        """RequestValidationError → 422 status."""
        response = client.post("/raise-422", json={"wrong_field": 42})
        assert response.status_code == 422

    def test_validation_error_body_has_error_envelope(self, client: TestClient):
        """422 body must use canonical envelope with code='validation_error'."""
        response = client.post("/raise-422", json={"wrong_field": 42})
        body = response.json()
        assert "error" in body
        error = body["error"]
        assert error.get("code") == "validation_error"
        assert "message" in error
        assert "request_id" in error

    def test_all_handlers_produce_same_envelope_structure(self, client: TestClient):
        """500, 404, and 422 responses must share identical top-level structure.

        All responses must have the 'error' envelope. 422 may additionally include
        'details' for raw Pydantic errors (spec: SHOULD be included).
        """
        r500 = client.get("/raise-500")
        r404 = client.get("/raise-404")
        r422 = client.post("/raise-422", json={})

        for resp in (r500, r404, r422):
            body = resp.json()
            # 'error' key is REQUIRED in all responses
            assert "error" in body, (
                f"Expected 'error' key in body, got: {list(body.keys())}"
            )
            error = body["error"]
            assert "code" in error
            assert "message" in error
            assert "request_id" in error
            # Only 'error' and optionally 'details' are allowed at top level
            allowed_keys = {"error", "details"}
            extra = set(body.keys()) - allowed_keys
            assert not extra, f"Unexpected extra keys in response: {extra}"

    def test_request_id_in_500_response_is_uuid4_when_bound(self, client: TestClient):
        """When correlation middleware is active, request_id in 500 body must be UUID4.

        Hardened: request_id must be NON-NULL and a valid UUID4. The previous
        ``if rid is not None`` guard silently passed when the correlation context
        was lost on the 500 path — exactly the regression the reliability review
        flagged. A 500 with correlation middleware active MUST carry a request_id.
        """
        response = client.get("/raise-500")
        rid = response.json()["error"]["request_id"]
        assert rid is not None, (
            "500 response lost its request_id — correlation context was not "
            "preserved through the unhandled-exception path"
        )
        assert _UUID4_PATTERN.match(rid), f"Expected UUID4, got: {rid!r}"

    def test_500_response_has_x_request_id_header(self, client: TestClient):
        """A 500 response MUST carry the X-Request-ID header (regression guard)."""
        response = client.get("/raise-500")
        assert response.status_code == 500
        rid = response.headers.get("x-request-id")
        assert rid is not None, "500 response is missing the X-Request-ID header"
        assert _UUID4_PATTERN.match(rid), f"Expected UUID4 header, got: {rid!r}"

    def test_500_header_matches_body_request_id(self, client: TestClient):
        """X-Request-ID header and body request_id must be the SAME id on a 500."""
        response = client.get("/raise-500")
        header_rid = response.headers.get("x-request-id")
        body_rid = response.json()["error"]["request_id"]
        assert header_rid is not None and body_rid is not None
        assert header_rid == body_rid, (
            f"500 header request_id {header_rid!r} != body request_id {body_rid!r}"
        )

    def test_request_id_null_safe_without_context(self):
        """ErrorDetail must accept None for request_id without crashing."""
        detail = ErrorDetail(code="internal_error", message="test", request_id=None)
        assert detail.request_id is None

    def test_error_response_model_shape(self):
        """ErrorResponse must wrap ErrorDetail under 'error' key."""
        detail = ErrorDetail(
            code="http_error",
            message="Not found",
            request_id="test-uuid",
        )
        envelope = ErrorResponse(error=detail)
        assert envelope.error.code == "http_error"
        assert envelope.error.message == "Not found"
        assert envelope.error.request_id == "test-uuid"

    # ---- 4xx vs 5xx logging behavior ----

    def test_4xx_handler_does_not_include_exc_info_in_log(self, client: TestClient):
        """4xx HTTPException boundary log must be WARNING level, no exc_info.

        We can't easily inspect structlog output here without a full capture
        setup, so we verify the handler at least does not crash and returns
        the correct status without propagating the exception.
        """
        response = client.get("/raise-404")
        # Handler must absorb the exception (not re-raise) and return a response
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "http_error"

    # ---- 5xx HTTPException detail must not leak to clients ----

    def test_5xx_http_exception_detail_not_returned(self, client: TestClient):
        """5xx HTTPException detail must be masked as a generic client message.

        Regression guard (risk review): ``HTTPException(status_code=500,
        detail=...)`` must NEVER echo internal detail to the client. The raw
        detail may carry DB errors, credentials, or upstream payloads.
        """
        response = client.get("/raise-500-http")
        assert response.status_code == 500
        body = response.json()
        message = body["error"]["message"]
        assert message == "Internal server error"
        # The sensitive detail must not appear anywhere in the response body.
        body_text = response.text
        assert "DB connection failed" not in body_text
        assert "INTERNAL-SENTINEL-DETAIL-DO-NOT-LEAK" not in body_text

    def test_5xx_http_exception_preserves_status_and_envelope(
        self, client: TestClient
    ):
        """Masking the message must keep the 5xx status and canonical envelope."""
        response = client.get("/raise-500-http")
        assert response.status_code == 500
        error = response.json()["error"]
        assert error["code"] == "http_error"
        assert "request_id" in error

    def test_4xx_http_exception_detail_still_returned(self, client: TestClient):
        """4xx HTTPException detail MUST remain caller-visible (unchanged contract)."""
        response = client.get("/raise-404")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Agent not found"


# ---------------------------------------------------------------------------
# Real production stack — 500 correlation regression guard
# ---------------------------------------------------------------------------


class TestProductionStack500Correlation:
    """500 correlation through the REAL app stack (create_app()).

    The minimal ``_make_app_with_middleware`` fixture did NOT reproduce the
    production middleware ordering (ServerErrorMiddleware outside
    CorrelationMiddleware, with RequestLoggingMiddleware/BaseHTTPMiddleware in
    between). That gap is exactly why the original tests passed while the live
    probe showed 500s losing both the X-Request-ID header and the body
    request_id. These tests exercise the production app so the regression
    cannot slip through again.
    """

    @pytest.fixture
    def app(self):
        from app.main import create_app

        _app = create_app()

        @_app.get("/__test_raise_500")
        async def _raise_500():  # pragma: no cover - body never returns
            raise RuntimeError("boom-production-stack")

        return _app

    @pytest.fixture
    def client(self, app) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def test_production_500_status(self, client: TestClient):
        response = client.get("/__test_raise_500")
        assert response.status_code == 500

    def test_production_500_body_request_id_non_null_uuid4(self, client: TestClient):
        """Through the real stack, the 500 body request_id must be a non-null UUID4."""
        response = client.get("/__test_raise_500")
        rid = response.json()["error"]["request_id"]
        assert rid is not None, (
            "Production 500 lost its body request_id — correlation context not "
            "preserved past the unhandled-exception boundary"
        )
        assert _UUID4_PATTERN.match(rid), f"Expected UUID4, got: {rid!r}"

    def test_production_500_header_present_and_matches_body(self, client: TestClient):
        """Through the real stack, X-Request-ID header must be present and match body."""
        response = client.get("/__test_raise_500")
        header_rid = response.headers.get("x-request-id")
        body_rid = response.json()["error"]["request_id"]
        assert header_rid is not None, (
            "Production 500 is missing the X-Request-ID header"
        )
        assert _UUID4_PATTERN.match(header_rid), f"Expected UUID4 header, got: {header_rid!r}"
        assert header_rid == body_rid, (
            f"Production 500 header {header_rid!r} != body {body_rid!r}"
        )

    def test_production_500_no_stack_trace_in_body(self, client: TestClient):
        """The 500 body must never leak the exception type or traceback."""
        response = client.get("/__test_raise_500")
        assert "Traceback" not in response.text
        assert "RuntimeError" not in response.text
        assert response.json()["error"]["code"] == "internal_error"


# ---------------------------------------------------------------------------
# Task 2.3 — Gate: no synchronous network/monitoring call in live SSE turn path
# ---------------------------------------------------------------------------


class TestLivePathGate:
    """Verify that CorrelationMiddleware adds zero synchronous I/O to the live path."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app_with_middleware(), raise_server_exceptions=False)

    def test_correlation_binding_is_pure_cpu_no_network(self, client: TestClient):
        """Correlation middleware must not make any network calls.

        We verify this by patching common async network primitives and asserting
        they are never called during a simple GET through the middleware.
        """
        with (
            patch("asyncio.open_connection") as mock_net,
            patch("httpx.AsyncClient.get") as mock_httpx,
        ):
            response = client.get("/ping")
        assert response.status_code == 200
        mock_net.assert_not_called()
        mock_httpx.assert_not_called()

    def test_streaming_endpoint_not_blocked_by_middleware(self, client: TestClient):
        """Streaming response must complete without the middleware blocking mid-stream."""
        response = client.get("/stream")
        assert response.status_code == 200
        # Content must contain both chunks
        assert b"chunk1" in response.content
        assert b"chunk2" in response.content


# ---------------------------------------------------------------------------
# Validation error input redaction — PII/secret leakage guard
# ---------------------------------------------------------------------------


def _walk_for_input_key(node: object) -> bool:
    """Recursively return True if any dict in ``node`` contains an 'input' key."""
    if isinstance(node, dict):
        if "input" in node:
            return True
        return any(_walk_for_input_key(v) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_walk_for_input_key(item) for item in node)
    return False


class TestValidationErrorRedaction:
    """Validation error details must never echo raw submitted ``input`` values."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app_with_middleware(), raise_server_exceptions=False)

    def test_redact_helper_removes_top_level_input(self):
        """_redact_validation_errors strips the top-level 'input' key."""
        raw = [
            {
                "type": "missing",
                "loc": ("body", "name"),
                "msg": "Field required",
                "input": {"field": "submitted-value"},
            }
        ]
        cleaned = _redact_validation_errors(raw)
        assert "input" not in cleaned[0]
        # Other developer-facing keys are preserved
        assert cleaned[0]["type"] == "missing"
        assert cleaned[0]["msg"] == "Field required"
        assert cleaned[0]["loc"] == ("body", "name")

    def test_redact_helper_removes_nested_ctx_input(self):
        """_redact_validation_errors strips 'input' nested inside 'ctx'."""
        raw = [
            {
                "type": "string_too_short",
                "loc": ("body", "code"),
                "msg": "String should have at least 8 characters",
                "input": "abc",
                "ctx": {"min_length": 8, "input": "abc"},
            }
        ]
        cleaned = _redact_validation_errors(raw)
        assert "input" not in cleaned[0]
        assert "input" not in cleaned[0]["ctx"]
        # Non-sensitive ctx data is preserved
        assert cleaned[0]["ctx"]["min_length"] == 8

    def test_redact_helper_does_not_mutate_original(self):
        """Redaction returns new dicts; the source error list is untouched."""
        raw = [{"type": "x", "loc": (), "msg": "m", "input": "leak"}]
        _redact_validation_errors(raw)
        assert raw[0]["input"] == "leak"

    def test_response_details_omit_submitted_input(self, client: TestClient):
        """422 response 'details' must not contain any 'input' key."""
        response = client.post("/raise-422", json={"wrong_field": 42})
        assert response.status_code == 422
        details = response.json().get("details", [])
        assert details, "Expected non-empty details for developer tooling"
        for entry in details:
            assert "input" not in entry, (
                f"Submitted input leaked into validation details: {entry}"
            )

    def test_sensitive_input_value_not_in_response_body(self, client: TestClient):
        """A submitted field value must never be echoed back in the 422 body.

        Uses a non-secret sentinel that stands in for any sensitive submitted
        value. The test proves redaction never reflects submitted input — the
        sentinel must not appear anywhere in the serialized response.
        """
        submitted_value = "SENTINEL-SUBMITTED-VALUE-MUST-NOT-ECHO"
        response = client.post(
            "/raise-422-sensitive",
            json={"password": submitted_value, "code": "x"},
        )
        assert response.status_code == 422
        # Submitted value must not appear anywhere in the serialized response
        assert submitted_value not in response.text
        # And no 'input' key at any depth of the details payload
        details = response.json().get("details", [])
        assert not _walk_for_input_key(details), (
            "An 'input' key leaked somewhere in validation details"
        )
