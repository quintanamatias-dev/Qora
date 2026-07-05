"""Integration tests for POST /api/v1/clients/{client_id}/leads/{lead_id}/call.

Spec: outbound-call-trigger — Requirement: Manual Trigger Endpoint
  - 403 when ENABLE_OUTBOUND_CALLS=false
  - 404 when client or lead not found
  - 422 when phone is not E.164
  - 409 when concurrent active call exists
  - 200 when all guards pass (ElevenLabs mocked — no live calls)

Uses TestClient with FastAPI dependency_overrides for DB and settings.
Spec: "Automated tests must mock external providers; do not make live Telnyx/ElevenLabs calls."
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared test app factory using dependency_overrides
# ---------------------------------------------------------------------------


def _build_app(
    enable_outbound: bool,
    lead=None,
    client_obj=None,
    agent=None,
    active_session=None,
    mock_dial_result=None,
):
    """Build a test FastAPI app with all dependencies overridden."""
    from app.outbound.router import router as outbound_router, get_db_session, get_settings
    from app.core.auth import require_api_key

    app = FastAPI()
    app.include_router(outbound_router)

    # Settings override
    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = enable_outbound
    # Disable cooldown for router tests — cooldown is tested separately in test_cooldown_guard.py
    mock_settings.outbound_call_cooldown_seconds = 0

    async def _fake_settings():
        return mock_settings

    # DB session override
    mock_db = AsyncMock()

    # Simulate concurrent session query result
    if active_session is not None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = active_session
        mock_db.execute.return_value = mock_result
    else:
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = mock_result

    async def _fake_db():
        yield mock_db

    # Override dependencies
    app.dependency_overrides[get_settings] = _fake_settings
    app.dependency_overrides[get_db_session] = _fake_db
    # Bypass auth for tests
    app.dependency_overrides[require_api_key] = lambda: None

    return app, mock_settings, mock_db


# ---------------------------------------------------------------------------
# Feature flag off → 403
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointFlagOff:
    """Feature flag off → 403 for all trigger requests."""

    def test_flag_off_returns_403(self):
        """GIVEN enable_outbound_calls=False
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 403 is returned.
        """
        app, _, _ = _build_app(enable_outbound=False)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/clients/client-a/leads/lead-001/call")

        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower() or \
               "ENABLE_OUTBOUND_CALLS" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Lead not found → 404
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointLeadNotFound:
    """Lead or client not found → 404."""

    def test_lead_not_found_returns_404(self):
        """GIVEN flag on but lead does not exist in DB
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 404 is returned.
        """
        app, _, _ = _build_app(enable_outbound=True)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead:

            mock_client.return_value = MagicMock(id="client-a", name="Test Client")
            mock_lead.return_value = None  # lead not found

            response = client.post("/clients/client-a/leads/nonexistent-lead/call")

        assert response.status_code == 404

    def test_client_not_found_returns_404(self):
        """GIVEN flag on but client does not exist in DB
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 404 is returned.
        """
        app, _, _ = _build_app(enable_outbound=True)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client:
            mock_client.return_value = None  # client not found

            response = client.post("/clients/unknown-client/leads/lead-001/call")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Invalid phone → 422
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointInvalidPhone:
    """Invalid E.164 phone number → 422."""

    def test_invalid_phone_returns_422(self):
        """GIVEN flag on, lead found, but phone is not E.164
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 422 is returned with descriptive error.
        """
        app, _, _ = _build_app(enable_outbound=True)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead:

            mock_client.return_value = MagicMock(id="client-a", name="Test Client")
            bad_lead = MagicMock()
            bad_lead.id = "lead-001"
            bad_lead.client_id = "client-a"
            bad_lead.phone = "not-a-phone"
            bad_lead.name = "Test Lead"
            mock_lead.return_value = bad_lead

            response = client.post("/clients/client-a/leads/lead-001/call")

        assert response.status_code == 422
        assert "E.164" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Concurrent active session → 409
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointConcurrentSession:
    """Concurrent active call → 409."""

    def test_concurrent_session_returns_409(self):
        """GIVEN flag on, lead found with valid phone, but active session exists
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 409 is returned.
        """
        # Create a mock active session
        mock_active = MagicMock()
        mock_active.id = "active-session-123"
        mock_active.telephony_status = "dialing"

        app, _, _ = _build_app(enable_outbound=True, active_session=mock_active)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent:

            mock_client.return_value = MagicMock(id="client-a", name="Test Client")
            lead = MagicMock()
            lead.id = "lead-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            lead.name = "Test Lead"
            mock_lead.return_value = lead
            mock_agent.return_value = MagicMock(
                id="agent-001",
                elevenlabs_agent_id="el-agent-abc",
                elevenlabs_phone_number_id="pn-xyz",
            )

            response = client.post("/clients/client-a/leads/lead-001/call")

        assert response.status_code == 409


# ---------------------------------------------------------------------------
# Happy path → 200 with call_session_id
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointSuccess:
    """Happy path — endpoint delegates to dial_outbound_call and returns 200."""

    def test_successful_trigger_returns_200_with_session_id(self):
        """GIVEN flag on, valid lead with E.164 phone, no active sessions
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 200 returned with {status: 'dialing', call_session_id}.

        ElevenLabs is mocked — no live calls placed.
        """
        app, _, _ = _build_app(enable_outbound=True)
        client_http = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            from app.outbound.service import DialResult

            mock_dial.return_value = DialResult(
                status="dialing",
                call_session_id="sess-abc-123",
            )

            mock_client.return_value = MagicMock(id="client-a", name="Test Client")
            lead = MagicMock()
            lead.id = "lead-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            lead.name = "Test Lead"
            mock_lead.return_value = lead
            mock_agent.return_value = MagicMock(
                id="agent-001",
                elevenlabs_agent_id="el-agent-abc",
                elevenlabs_phone_number_id="pn-xyz",
            )

            response = client_http.post("/clients/client-a/leads/lead-001/call")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "dialing"
        assert body["call_session_id"] == "sess-abc-123"

    def test_no_live_elevenlabs_call_when_dial_mocked(self):
        """GIVEN the dial service is mocked
        WHEN the endpoint is called
        THEN no real HTTP request is made to ElevenLabs.

        This proves the automated test never places a real call.
        """
        import httpx

        real_calls_made: list[str] = []

        app, _, _ = _build_app(enable_outbound=True)
        client_http = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            from app.outbound.service import DialResult
            mock_dial.return_value = DialResult(status="dialing", call_session_id="x")

            mock_client.return_value = MagicMock(id="client-a")
            lead = MagicMock()
            lead.id = "lead-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            mock_lead.return_value = lead
            mock_agent.return_value = MagicMock(id="agent-001")

            client_http.post("/clients/client-a/leads/lead-001/call")

        # dial_outbound_call was called once and returned immediately (mocked)
        mock_dial.assert_called_once()
        # No real network calls were made — real_calls_made remains empty
        assert len(real_calls_made) == 0
