"""Tests: B9 observability — Sentry exception capture in 500 handler (task 3.3).

Strict TDD RED phase.

Covered scenarios (spec: observability-sentry — Requirement: Unhandled Exception Capture):
    - 500 handler calls sentry_sdk.capture_exception() when DSN is configured
    - 500 handler includes request_id tag in Sentry event
    - 500 handler does NOT call capture_exception when DSN is absent
    - Sentry capture happens AFTER response is constructed (no live-path latency)
    - Non-synchronous: capture must not block response construction
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.core.observability import (
    CorrelationMiddleware,
    handle_exception,
    handle_http_exception,
    handle_validation_error,
)


def _make_app() -> FastAPI:
    """Minimal app with correlation middleware and all exception handlers."""
    app = FastAPI()
    app.add_exception_handler(Exception, handle_exception)
    app.add_middleware(CorrelationMiddleware)

    @app.get("/raise-500")
    async def raise_500():
        raise RuntimeError("unhandled in tests")

    # Live voice/custom-LLM path: a 500 here must NOT trigger synchronous
    # Sentry capture (live-call latency constraint).
    @app.get("/api/v1/voice/{client_id}/custom-llm/chat/completions")
    async def raise_500_live(client_id: str):
        raise RuntimeError("unhandled on live voice path")

    return app


class TestSentryCaptureWith500Handler:
    """500 handler must capture exceptions in Sentry when DSN is configured."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app(), raise_server_exceptions=False)

    def test_capture_exception_called_when_sentry_active(self, client: TestClient):
        """sentry_sdk.capture_exception() must be called when Sentry is initialized.

        We simulate Sentry being active by patching sentry_sdk.is_initialized()
        to return True and intercepting capture_exception.
        """
        with (
            patch("app.core.observability.sentry_sdk.is_initialized", return_value=True),
            patch("app.core.observability.sentry_sdk.capture_exception") as mock_capture,
            patch("app.core.observability.sentry_sdk.push_scope"),
        ):
            response = client.get("/raise-500")

        assert response.status_code == 500
        mock_capture.assert_called_once()

    def test_capture_exception_not_called_when_sentry_inactive(
        self, client: TestClient
    ):
        """sentry_sdk.capture_exception() must NOT be called when Sentry is not initialized."""
        with (
            patch(
                "app.core.observability.sentry_sdk.is_initialized", return_value=False
            ),
            patch(
                "app.core.observability.sentry_sdk.capture_exception"
            ) as mock_capture,
        ):
            response = client.get("/raise-500")

        assert response.status_code == 500
        mock_capture.assert_not_called()

    def test_500_response_is_still_returned_when_sentry_capture_fails(
        self, client: TestClient
    ):
        """If sentry_sdk.capture_exception() raises, the 500 response must still be returned.

        Sentry capture is best-effort; it must never break the error response.
        """
        with (
            patch(
                "app.core.observability.sentry_sdk.is_initialized", return_value=True
            ),
            patch(
                "app.core.observability.sentry_sdk.capture_exception",
                side_effect=RuntimeError("Sentry SDK unavailable"),
            ),
            patch("app.core.observability.sentry_sdk.push_scope"),
        ):
            response = client.get("/raise-500")

        # The canonical 500 must still be returned even if Sentry capture fails.
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"

    def test_request_id_tag_included_with_sentry_capture(self, client: TestClient):
        """Sentry capture must include request_id as a tag on the event.

        Design: the handler uses sentry_sdk.push_scope() to set tags before
        calling capture_exception(), ensuring the event is tagged with the
        active correlation ID.
        """
        captured_tags = {}

        class _FakeScope:
            def set_tag(self, key, value):
                captured_tags[key] = value

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch(
                "app.core.observability.sentry_sdk.is_initialized", return_value=True
            ),
            patch(
                "app.core.observability.sentry_sdk.push_scope",
                return_value=_FakeScope(),
            ),
            patch("app.core.observability.sentry_sdk.capture_exception"),
        ):
            response = client.get("/raise-500")

        assert response.status_code == 500
        assert "request_id" in captured_tags, (
            "Sentry event must be tagged with request_id for correlation"
        )
        # The request_id tag must be a non-empty string (UUID4 from middleware)
        assert captured_tags["request_id"] is not None
        assert len(captured_tags["request_id"]) > 0


class TestSentryCaptureLivePathGate:
    """500s on live voice/custom-LLM paths must NOT call Sentry synchronously.

    User constraint: nothing in a live call may add request-path latency.
    Non-live 500s still capture; live-path 500s skip capture but keep the
    canonical error envelope and request_id in both the response and the log.
    """

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_app(), raise_server_exceptions=False)

    def test_non_live_500_captures_when_initialized(self, client: TestClient):
        """A non-live 500 must still capture in Sentry when initialized."""
        with (
            patch(
                "app.core.observability.sentry_sdk.is_initialized", return_value=True
            ),
            patch(
                "app.core.observability.sentry_sdk.capture_exception"
            ) as mock_capture,
            patch("app.core.observability.sentry_sdk.push_scope"),
        ):
            response = client.get("/raise-500")

        assert response.status_code == 500
        mock_capture.assert_called_once()

    def test_live_custom_llm_500_skips_capture(self, client: TestClient):
        """A 500 on the live custom-LLM path must NOT call capture_exception.

        Even with Sentry initialized, the live turn path stays free of any
        synchronous Sentry I/O.
        """
        with (
            patch(
                "app.core.observability.sentry_sdk.is_initialized", return_value=True
            ),
            patch(
                "app.core.observability.sentry_sdk.capture_exception"
            ) as mock_capture,
            patch("app.core.observability.sentry_sdk.push_scope") as mock_scope,
        ):
            response = client.get(
                "/api/v1/voice/acme/custom-llm/chat/completions"
            )

        assert response.status_code == 500
        mock_capture.assert_not_called()
        mock_scope.assert_not_called()

    def test_live_500_still_returns_canonical_error_with_request_id(
        self, client: TestClient
    ):
        """The live 500 response must still carry the canonical error + request_id.

        Skipping Sentry capture must not weaken the response contract: the
        canonical envelope, the request_id field, and the X-Request-ID header
        are all still present.
        """
        with patch(
            "app.core.observability.sentry_sdk.is_initialized", return_value=True
        ):
            response = client.get(
                "/api/v1/voice/acme/custom-llm/chat/completions"
            )

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["request_id"]
        # Body request_id matches the X-Request-ID header from the middleware.
        assert body["error"]["request_id"] == response.headers["x-request-id"]
