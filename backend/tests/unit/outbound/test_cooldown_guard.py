"""Tests for the cooldown/idempotency guard in the outbound router.

Review blocker WARNING-6:
  Rapid repeated trigger attempts from the UI/operator (e.g., double-click on
  "Call Now" button, or operator refreshing and clicking again) should be rejected
  with 429 if the same lead was just attempted within a cooldown window.

  The cooldown guard is at the HTTP router layer (not the dialing service) because:
  1. It's a UI/operator protection, not a telephony guarantee.
  2. The cooldown tracks recent failed attempts, not just active sessions.
  3. A 10-second cooldown prevents accidental double-charges from UI bugs.

  Implementation: in-process dict tracking last attempt timestamp per lead_id.
  For MVP (single-process), this is sufficient. Future: move to Redis.

  Cooldown window: OUTBOUND_CALL_COOLDOWN_SECONDS (default: 10 seconds).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test: cooldown returns 429 on rapid repeated calls
# ---------------------------------------------------------------------------


def test_cooldown_guard_rejects_rapid_repeat_within_window():
    """GIVEN a lead was just called within the cooldown window
    WHEN the endpoint is called again for the same lead
    THEN HTTP 429 is returned.
    """
    from app.outbound.router import _should_cooldown_reject, _record_call_attempt

    lead_id = "lead-cooldown-test-001"
    cooldown_seconds = 10

    # Record a recent attempt
    _record_call_attempt(lead_id)

    # Immediately check — must be rejected
    assert _should_cooldown_reject(lead_id, cooldown_seconds=cooldown_seconds), (
        "Immediate repeat call must be rejected by cooldown guard"
    )


def test_cooldown_guard_allows_call_after_window():
    """GIVEN a lead was called more than cooldown_seconds ago
    WHEN the endpoint is called again
    THEN the cooldown guard passes (not rejected).
    """
    from app.outbound.router import _should_cooldown_reject, _record_call_attempt

    lead_id = "lead-cooldown-test-expired-001"

    # Record an old attempt (simulate time passing by using a tiny cooldown)
    _record_call_attempt(lead_id)

    # With a 0-second cooldown, the attempt is immediately expired
    assert not _should_cooldown_reject(lead_id, cooldown_seconds=0), (
        "Call must be allowed after cooldown window expires"
    )


def test_cooldown_guard_allows_first_call():
    """GIVEN a lead has never been called
    WHEN the endpoint is called
    THEN the cooldown guard passes (no prior attempt recorded).
    """
    from app.outbound.router import _should_cooldown_reject

    lead_id = "lead-cooldown-first-call-xyz-987"  # unique, never called

    assert not _should_cooldown_reject(lead_id, cooldown_seconds=10), (
        "First call for a lead must not be blocked by cooldown guard"
    )


def test_cooldown_guard_different_leads_are_independent():
    """GIVEN lead A was just called
    WHEN the endpoint is called for lead B
    THEN lead B is NOT affected by lead A's cooldown.
    """
    from app.outbound.router import _should_cooldown_reject, _record_call_attempt

    lead_a = "lead-cooldown-A-zzz"
    lead_b = "lead-cooldown-B-zzz"

    _record_call_attempt(lead_a)

    # Lead B must NOT be blocked
    assert not _should_cooldown_reject(lead_b, cooldown_seconds=10), (
        "Cooldown for lead A must not affect lead B"
    )


def test_cooldown_endpoint_returns_429():
    """GIVEN a lead was just called (cooldown active)
    WHEN POST /clients/{client_id}/leads/{lead_id}/call is called again
    THEN HTTP 429 is returned with a meaningful error.
    """
    from app.outbound.router import router as outbound_router, get_db_session, get_settings
    from app.outbound.router import _record_call_attempt
    from app.core.auth import require_api_key
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    lead_id = "lead-cooldown-429-test-ep"
    # Pre-seed the cooldown (as if a previous call just happened)
    _record_call_attempt(lead_id)

    app = FastAPI()
    app.include_router(outbound_router)

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True
    mock_settings.outbound_call_cooldown_seconds = 10

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    async def _fake_settings():
        return mock_settings

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_settings] = _fake_settings
    app.dependency_overrides[get_db_session] = _fake_db
    app.dependency_overrides[require_api_key] = lambda: None

    client = TestClient(app, raise_server_exceptions=False)

    # Need to mock client/lead lookup so we get past guard 2/3 to reach cooldown guard
    with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client_svc, \
         patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead_svc:
        mock_client_svc.return_value = MagicMock(id="client-a")
        lead_obj = MagicMock()
        lead_obj.id = lead_id
        lead_obj.client_id = "client-a"
        lead_obj.phone = "+14155552671"
        mock_lead_svc.return_value = lead_obj

        response = client.post(f"/clients/client-a/leads/{lead_id}/call")

    assert response.status_code == 429, (
        f"Rapid repeat call must return 429 (cooldown active). "
        f"Got {response.status_code}: {response.json()}"
    )
    body = response.json()
    assert "cooldown" in body.get("detail", "").lower(), (
        f"429 response must mention cooldown. Got: {body}"
    )
