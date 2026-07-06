"""Unit tests for GET /api/v1/calls/{session_id}/status — call status polling endpoint.

Spec: call-status-polling — Requirements:
  - Status Polling Endpoint: returns {session_id, telephony_status, outcome_reason,
    started_at, duration_seconds, is_terminal}
  - Rate Limiting: max 1 req/s per session_id; exceeded → 429 + Retry-After
  - Short-Circuit on Terminal State: is_terminal=true for terminal statuses
  - Response Latency: within 500ms, no external HTTP calls

Design: backend/app/calls/router.py — GET /{session_id}/status
         backend/app/calls/schemas.py — CallStatusResponse schema + _TERMINAL_STATUSES
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_call_session(
    session_id: str = "sess-abc-001",
    telephony_status: str = "ringing",
    outcome_reason: str | None = None,
    duration_seconds: float | None = None,
    started_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal CallSession mock for the polling endpoint."""
    cs = MagicMock()
    cs.id = session_id
    cs.telephony_status = telephony_status
    cs.outcome_reason = outcome_reason
    cs.duration_seconds = duration_seconds
    cs.started_at = started_at or datetime.now(timezone.utc)
    return cs


def _make_async_cm(call_session: MagicMock | None):
    """Return an asynccontextmanager factory that yields a mock DB session."""
    @asynccontextmanager
    async def _fake_db():
        mock_db = AsyncMock()
        yield mock_db

    return _fake_db


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with the calls router and auth disabled."""
    from app.calls.router import router as calls_router
    from app.core.auth import require_api_key

    app = FastAPI()
    app.include_router(calls_router, prefix="/api/v1")
    app.dependency_overrides[require_api_key] = lambda: None
    return app


# ---------------------------------------------------------------------------
# Task 3.1 RED: Endpoint exists — schema and route importable
# ---------------------------------------------------------------------------


def test_status_endpoint_importable() -> None:
    """The calls router exposes a GET /{session_id}/status route."""
    from app.calls.router import router as calls_router

    routes = {r.path for r in calls_router.routes}
    matching = [r for r in routes if r.endswith("/status")]
    assert matching, (
        f"Expected a /status route in calls_router. Found routes: {routes}"
    )


def test_call_status_response_schema_importable() -> None:
    """CallStatusResponse and _TERMINAL_STATUSES exist in app.calls.schemas."""
    from app.calls.schemas import CallStatusResponse, _TERMINAL_STATUSES  # noqa: F401


# ---------------------------------------------------------------------------
# Task 3.1 RED: Endpoint returns 200 for active session
# ---------------------------------------------------------------------------


def test_status_endpoint_returns_200_for_active_session() -> None:
    """GET /calls/{session_id}/status returns 200 with telephony_status for active session."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    cs = _make_call_session(session_id="sess-ringing-001", telephony_status="ringing")

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", new_callable=AsyncMock, return_value=cs), \
         patch("app.calls.router.db_session", _make_async_cm(cs)):
        response = client.get(
            "/api/v1/calls/sess-ringing-001/status",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess-ringing-001"
    assert data["telephony_status"] == "ringing"
    assert data["is_terminal"] is False


def test_status_endpoint_returns_200_for_terminal_session() -> None:
    """GET /calls/{session_id}/status returns 200 with is_terminal=True for terminal status."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    cs = _make_call_session(
        session_id="sess-failed-001",
        telephony_status="failed",
        outcome_reason="sip_routing_error",
    )

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", new_callable=AsyncMock, return_value=cs), \
         patch("app.calls.router.db_session", _make_async_cm(cs)):
        response = client.get(
            "/api/v1/calls/sess-failed-001/status",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_terminal"] is True
    assert data["outcome_reason"] == "sip_routing_error"


def test_status_endpoint_returns_404_for_unknown_session() -> None:
    """GET /calls/{session_id}/status returns 404 when session not found."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", new_callable=AsyncMock, return_value=None), \
         patch("app.calls.router.db_session", _make_async_cm(None)):
        response = client.get(
            "/api/v1/calls/nonexistent-session/status",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Task 3.1 RED: is_terminal flag
# ---------------------------------------------------------------------------


TERMINAL_STATUSES = ["completed", "no_answer", "failed", "recurrent_error", "stale_in_call", "voicemail"]
NON_TERMINAL_STATUSES = ["queued", "dialing", "ringing", "connected"]


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_is_terminal_true_for_terminal_statuses(status: str) -> None:
    """is_terminal=True for all terminal statuses."""
    from app.calls.schemas import _TERMINAL_STATUSES

    assert status in _TERMINAL_STATUSES, (
        f"Expected {status!r} in _TERMINAL_STATUSES"
    )


@pytest.mark.parametrize("status", NON_TERMINAL_STATUSES)
def test_is_terminal_false_for_non_terminal_statuses(status: str) -> None:
    """is_terminal=False for all non-terminal (active/intermediate) statuses."""
    from app.calls.schemas import _TERMINAL_STATUSES

    assert status not in _TERMINAL_STATUSES, (
        f"Expected {status!r} NOT in _TERMINAL_STATUSES"
    )


# ---------------------------------------------------------------------------
# Task 3.1 RED: Rate limiting — 1 req/s per session_id
# ---------------------------------------------------------------------------


def test_rate_limiting_within_limit_returns_200() -> None:
    """First request within rate limit window returns 200."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    cs = _make_call_session(session_id="sess-rate-001", telephony_status="dialing")

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", new_callable=AsyncMock, return_value=cs), \
         patch("app.calls.router.db_session", _make_async_cm(cs)):
        response = client.get(
            "/api/v1/calls/sess-rate-001/status",
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200


def test_rate_limiting_second_request_within_window_returns_429() -> None:
    """Second request within 1s window for same session_id returns 429."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    cs = _make_call_session(session_id="sess-rate-002", telephony_status="ringing")

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", new_callable=AsyncMock, return_value=cs), \
         patch("app.calls.router.db_session", _make_async_cm(cs)):
        # First request — should succeed
        r1 = client.get(
            "/api/v1/calls/sess-rate-002/status",
            headers={"X-API-Key": "test-key"},
        )
        assert r1.status_code == 200

        # Second request immediately — should be rate-limited (no DB call)
        r2 = client.get(
            "/api/v1/calls/sess-rate-002/status",
            headers={"X-API-Key": "test-key"},
        )

    assert r2.status_code == 429
    assert "Retry-After" in r2.headers


def test_rate_limiting_different_sessions_not_shared() -> None:
    """Rate limit is per session_id — different sessions each get their own budget."""
    from app.calls.router import _clear_rate_limit_state

    _clear_rate_limit_state()

    cs_a = _make_call_session(session_id="sess-rate-003-a", telephony_status="ringing")
    cs_b = _make_call_session(session_id="sess-rate-003-b", telephony_status="ringing")

    async def _get_session_side_effect(db, session_id: str):
        if session_id == "sess-rate-003-a":
            return cs_a
        return cs_b

    app = _build_app()
    client = TestClient(app)

    with patch("app.calls.router.get_session", side_effect=_get_session_side_effect), \
         patch("app.calls.router.db_session", _make_async_cm(cs_a)):
        r_a = client.get(
            "/api/v1/calls/sess-rate-003-a/status",
            headers={"X-API-Key": "test-key"},
        )
        r_b = client.get(
            "/api/v1/calls/sess-rate-003-b/status",
            headers={"X-API-Key": "test-key"},
        )

    assert r_a.status_code == 200
    assert r_b.status_code == 200


# ---------------------------------------------------------------------------
# Task 3.1 RED: CallStatusResponse schema shape
# ---------------------------------------------------------------------------


def test_call_status_response_schema_has_required_fields() -> None:
    """CallStatusResponse has all required fields from the spec."""
    from app.calls.schemas import CallStatusResponse

    schema_fields = set(CallStatusResponse.model_fields.keys())
    required_fields = {
        "session_id",
        "telephony_status",
        "outcome_reason",
        "started_at",
        "duration_seconds",
        "is_terminal",
    }
    missing = required_fields - schema_fields
    assert not missing, f"CallStatusResponse is missing fields: {missing}"


def test_call_status_response_outcome_reason_nullable() -> None:
    """outcome_reason can be None in CallStatusResponse."""
    from app.calls.schemas import CallStatusResponse

    resp = CallStatusResponse(
        session_id="sess-001",
        telephony_status="ringing",
        outcome_reason=None,
        started_at=datetime.now(timezone.utc),
        duration_seconds=None,
        is_terminal=False,
    )
    assert resp.outcome_reason is None
