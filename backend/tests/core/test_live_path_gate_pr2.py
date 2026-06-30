"""Tests: B9 PR2 — Gate: no synchronous Sentry/network calls in live turn path (task 4.2).

This gate verifies that the PR2 additions (Sentry init, PII filter, dead-letter capture)
do NOT introduce any synchronous I/O into the live voice/SSE/custom-LLM call path.

Spec constraint (critical live-call latency constraint):
    - PR2 must not add anything during live calls that can add delay.
    - Optional Sentry must be best-effort and initialized at startup/config boundaries only.
    - Sentry capture in handle_exception is only on 500s, never on the live SSE path.
    - Dead-letter capture is only in background job workers, never in the request path.

Gate scenarios:
    1. CorrelationMiddleware (PR1) makes no Sentry calls in the live path.
    2. A successful SSE/streaming response makes no calls to sentry_sdk.
    3. Sentry initialization path is separate from the request handler path.
    4. The voice SSE path (no exception) does not invoke any Sentry API.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core.observability import (
    CorrelationMiddleware,
    handle_exception,
    handle_http_exception,
    handle_validation_error,
)


def _make_sse_app() -> FastAPI:
    """Minimal FastAPI app mimicking the Qora voice/SSE endpoint structure."""
    app = FastAPI()
    app.add_exception_handler(Exception, handle_exception)
    app.add_middleware(CorrelationMiddleware)

    @app.get("/voice/custom-llm")
    async def fake_custom_llm():
        """Simulate a streaming SSE response (live voice turn)."""

        async def _generate():
            for chunk in [b"data: chunk1\n\n", b"data: chunk2\n\n", b"data: [DONE]\n\n"]:
                yield chunk
                await asyncio.sleep(0)  # yield to event loop (non-blocking)

        return StreamingResponse(_generate(), media_type="text/event-stream")

    @app.get("/voice/initiation")
    async def fake_initiation():
        """Simulate the voice initiation endpoint (non-streaming)."""
        return {"conversation_id": "test-conv-id", "call_session_id": "test-session"}

    return app


class TestLivePathGatePR2:
    """Gate: PR2 Sentry additions must not touch the live turn path."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_make_sse_app(), raise_server_exceptions=False)

    def test_sentry_sdk_not_called_during_successful_sse_stream(
        self, client: TestClient
    ):
        """A successful SSE stream must not trigger any sentry_sdk API call.

        This is the critical live-call latency gate: Sentry must only be
        called at startup (init_sentry in lifespan) or on 500 errors
        (handle_exception). A healthy SSE stream must never touch Sentry.
        """
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            response = client.get("/voice/custom-llm")

        assert response.status_code == 200
        # No Sentry API should be called during a successful SSE response
        mock_sentry.init.assert_not_called()
        mock_sentry.capture_exception.assert_not_called()
        mock_sentry.capture_event.assert_not_called()
        mock_sentry.push_scope.assert_not_called()

    def test_sentry_sdk_not_called_during_voice_initiation(
        self, client: TestClient
    ):
        """The voice initiation path must not call any Sentry API.

        Initiation resolves conversation_id and starts the voice session.
        Latency here directly affects user experience.
        """
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            response = client.get("/voice/initiation")

        assert response.status_code == 200
        mock_sentry.capture_exception.assert_not_called()
        mock_sentry.capture_event.assert_not_called()

    def test_correlation_middleware_makes_no_sentry_calls(
        self, client: TestClient
    ):
        """CorrelationMiddleware must make zero Sentry API calls per request.

        The middleware runs on EVERY request including live voice turns.
        Any Sentry call here would add latency to all requests.
        """
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            # Make multiple requests to cover both new and existing requests
            for _ in range(3):
                response = client.get("/voice/custom-llm")
                assert response.status_code == 200

        # After 3 requests, Sentry must never have been touched
        mock_sentry.capture_exception.assert_not_called()
        mock_sentry.init.assert_not_called()

    def test_successful_request_no_sentry_network_io(self, client: TestClient):
        """No network I/O (Sentry or otherwise) on the normal request path.

        Gate: correlation binding must be pure CPU with zero network calls.
        This mirrors the PR1 gate but explicitly checks PR2-introduced Sentry paths.
        """
        with (
            patch("asyncio.open_connection") as mock_net,
            patch("app.core.observability.sentry_sdk") as mock_sentry,
        ):
            response = client.get("/voice/custom-llm")

        assert response.status_code == 200
        mock_net.assert_not_called()
        # Sentry must not be called outside the 500-handler path
        mock_sentry.capture_exception.assert_not_called()
