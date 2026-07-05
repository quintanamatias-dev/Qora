"""Unit tests for dial_outbound_call() — the central dialing entry point.

Spec: outbound-call-trigger — Requirements:
  - Feature Flag Guard: flag off → no call, no CallSession
  - Concurrent Call Guard: active session → 409
  - Call Attempt Persistence: CallSession created BEFORE ElevenLabs API call
  - Failure Classification: transient → retry once; permanent → no retry; recurrent_error on 2nd failure
  - Scheduler Reuse: dial_outbound_call accepts scheduled_call=None

Design: backend/app/outbound/service.py — dial_outbound_call()
  Returns DialResult(status, call_session_id, error)
  Never raises — catches all exceptions.

These are RED tests; the outbound module does not exist yet.
All ElevenLabs HTTP is mocked — no live calls allowed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_settings(enable_outbound: bool = True):
    settings = MagicMock()
    settings.enable_outbound_calls = enable_outbound
    settings.elevenlabs_api_key = SecretStr("test-xi-key")
    return settings


def _make_lead(
    phone: str = "+14155552671",
    client_id: str = "client-a",
    lead_id: str = "lead-001",
):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = phone
    lead.client_id = client_id
    lead.name = "Test Lead"
    return lead


def _make_agent(
    elevenlabs_agent_id: str = "el-agent-abc",
    elevenlabs_phone_number_id: str = "pn-xyz",
    client_id: str = "client-a",
):
    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = elevenlabs_agent_id
    agent.elevenlabs_phone_number_id = elevenlabs_phone_number_id
    agent.client_id = client_id
    agent.name = "Test Agent"
    return agent


def _make_client(client_id: str = "client-a", name: str = "Test Client"):
    client = MagicMock()
    client.id = client_id
    client.name = name
    return client


# ---------------------------------------------------------------------------
# RED — feature flag guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_returns_failed_when_flag_off():
    """GIVEN enable_outbound_calls=False
    WHEN dial_outbound_call is called
    THEN DialResult.status='failed', no CallSession created, no ElevenLabs call.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = AsyncMock()
    settings = _make_settings(enable_outbound=False)

    result = await dial_outbound_call(
        db=mock_db,
        lead=_make_lead(),
        agent=_make_agent(),
        client=_make_client(),
        settings=settings,
    )

    assert result.status == "failed"
    assert "flag" in result.error.lower() or "disabled" in result.error.lower()
    # DB session was NOT used to create a CallSession
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_dial_returns_failed_when_flag_off_and_call_session_id_is_none():
    """GIVEN enable_outbound_calls=False
    WHEN dial_outbound_call is called
    THEN call_session_id is None in the DialResult (no CallSession was created).
    """
    from app.outbound.service import dial_outbound_call

    settings = _make_settings(enable_outbound=False)
    result = await dial_outbound_call(
        db=AsyncMock(),
        lead=_make_lead(),
        agent=_make_agent(),
        client=_make_client(),
        settings=settings,
    )
    assert result.call_session_id is None


# ---------------------------------------------------------------------------
# RED — E.164 validation guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_returns_failed_for_invalid_phone():
    """GIVEN a lead with an invalid phone number (not E.164)
    WHEN dial_outbound_call is called with flag on
    THEN DialResult.status='failed' with validation error, no CallSession created.
    """
    from app.outbound.service import dial_outbound_call

    settings = _make_settings(enable_outbound=True)
    bad_lead = _make_lead(phone="not-a-phone")

    result = await dial_outbound_call(
        db=AsyncMock(),
        lead=bad_lead,
        agent=_make_agent(),
        client=_make_client(),
        settings=settings,
    )

    assert result.status == "failed"
    assert result.call_session_id is None
    assert result.error is not None


# ---------------------------------------------------------------------------
# RED — concurrent call guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_returns_failed_when_active_session_exists():
    """GIVEN a lead already has an active CallSession (telephony_status='dialing')
    WHEN dial_outbound_call is called
    THEN DialResult.status='failed' with concurrency error, no new CallSession.

    The service must query DB for active sessions before creating a new one.
    """
    from app.outbound.service import dial_outbound_call
    from app.calls.models import CallSession

    # Build a mock DB session that returns an active session on query
    mock_active_session = MagicMock(spec=CallSession)
    mock_active_session.telephony_status = "dialing"
    mock_active_session.id = "existing-session-123"

    mock_db = AsyncMock()
    # Simulate the DB query finding an active session
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_active_session
    mock_db.execute.return_value = mock_result

    settings = _make_settings(enable_outbound=True)

    result = await dial_outbound_call(
        db=mock_db,
        lead=_make_lead(),
        agent=_make_agent(),
        client=_make_client(),
        settings=settings,
    )

    assert result.status == "failed"
    assert result.call_session_id is None
    assert result.error is not None


# ---------------------------------------------------------------------------
# RED — DialResult dataclass structure
# ---------------------------------------------------------------------------


def test_dial_result_structure():
    """GIVEN a DialResult is constructed
    WHEN accessed
    THEN it has status, call_session_id, and error fields.
    """
    from app.outbound.service import DialResult

    r = DialResult(status="dialing", call_session_id="sess-abc", error=None)
    assert r.status == "dialing"
    assert r.call_session_id == "sess-abc"
    assert r.error is None


def test_dial_result_failed_status():
    """GIVEN a DialResult with status='failed'
    WHEN accessed
    THEN error field can carry a message.
    """
    from app.outbound.service import DialResult

    r = DialResult(status="failed", call_session_id=None, error="API error: 503")
    assert r.status == "failed"
    assert "503" in r.error


def test_dial_result_recurrent_error_status():
    """GIVEN a DialResult with status='recurrent_error'
    WHEN accessed
    THEN it is a distinct status from 'failed'.
    """
    from app.outbound.service import DialResult

    r = DialResult(status="recurrent_error", call_session_id="sess-xyz", error="retry failed")
    assert r.status == "recurrent_error"
    assert r.status != "failed"


# ---------------------------------------------------------------------------
# RED — scheduler-compatible signature
# ---------------------------------------------------------------------------


def test_dial_outbound_call_accepts_scheduled_call_param():
    """GIVEN dial_outbound_call function
    WHEN inspected
    THEN it accepts a scheduled_call parameter (scheduler reuse contract).
    """
    import inspect
    from app.outbound.service import dial_outbound_call

    sig = inspect.signature(dial_outbound_call)
    assert "scheduled_call" in sig.parameters
    # Default must be None (manual trigger uses None)
    assert sig.parameters["scheduled_call"].default is None
