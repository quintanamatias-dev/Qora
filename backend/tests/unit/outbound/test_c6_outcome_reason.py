"""Phase C6 — Retry & Recontact Policy: outcome_reason assignment tests.

Spec:
- error_category='permanent' → outcome_reason='provider_permanent'
- error_category='transient' (recurrent) → outcome_reason='provider_transient'
  + schedule_tech_retry() called
- error_category='unknown' → outcome_reason='timeout_ambiguous', no retry
- Guard failures (Guard 2b: agent not configured) → return BEFORE CallSession creation.
  The config_error taxonomy is expressed via DialResult.failure_code='agent_not_configured',
  NOT via CallSession.outcome_reason (no session exists to write to).
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Outcome reason constants test
# ---------------------------------------------------------------------------


def test_outcome_reason_constants_defined():
    """OUTCOME_REASONS set with all 5 C6 values."""
    from app.outbound.service import OUTCOME_REASONS

    expected = {
        "sip_routing_error",
        "provider_transient",
        "provider_permanent",
        "config_error",
        "timeout_ambiguous",
    }
    assert expected.issubset(OUTCOME_REASONS), (
        f"OUTCOME_REASONS missing: {expected - OUTCOME_REASONS}"
    )


# ---------------------------------------------------------------------------
# Guard failure → config_error
# ---------------------------------------------------------------------------


async def test_guard_missing_agent_id_sets_config_error():
    """Agent without elevenlabs_agent_id → DialResult with config_error semantics.

    Architectural contract (C6 spec — Domain: technical-error-classification):
    - Guard failures (Guard 2b: agent not configured) return BEFORE a CallSession
      is created. This is by design: no dangling 'dialing' sessions for config errors.
    - The config_error taxonomy is carried by DialResult.failure_code='agent_not_configured'.
    - outcome_reason='config_error' on a CallSession is NOT applicable here because
      no session exists to write it to — writing one would violate the "no dangling session
      on config error" invariant.

    This test proves the full contract:
    1. DialResult.status == 'failed'
    2. DialResult.failure_code == 'agent_not_configured'  ← config_error semantic
    3. DialResult.call_session_id is None  ← no session created (architectural invariant)
    """
    from app.outbound.service import dial_outbound_call

    mock_lead = MagicMock()
    mock_lead.id = "lead-001"
    mock_lead.phone = "+5491100000001"

    mock_agent = MagicMock()
    mock_agent.id = "agent-001"
    mock_agent.elevenlabs_agent_id = None  # missing → config guard
    mock_agent.elevenlabs_phone_number_id = "pnum_test"

    mock_client = MagicMock()
    mock_client.id = "test-client"

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True

    mock_db = AsyncMock()

    result = await dial_outbound_call(
        mock_db,
        lead=mock_lead,
        agent=mock_agent,
        client=mock_client,
        settings=mock_settings,
    )

    assert result.status == "failed"
    assert result.failure_code == "agent_not_configured", (
        f"Expected failure_code='agent_not_configured', got {result.failure_code!r}"
    )
    # Architectural invariant: no CallSession is created for config guard failures.
    # The config_error taxonomy is expressed via DialResult.failure_code, not via
    # a CallSession.outcome_reason (which requires a session to exist).
    assert result.call_session_id is None, (
        f"Guard failure must not create a CallSession, got call_session_id={result.call_session_id!r}"
    )


async def test_guard_missing_phone_number_id_sets_config_error():
    """Agent without elevenlabs_phone_number_id → DialResult with config_error semantics.

    Triangulation: proves Guard 2b-ii (phone_number_id) follows the same contract as
    Guard 2b-i (agent_id). Both produce failure_code='agent_not_configured' with no
    CallSession created.
    """
    from app.outbound.service import dial_outbound_call

    mock_lead = MagicMock()
    mock_lead.id = "lead-002"
    mock_lead.phone = "+5491100000002"

    mock_agent = MagicMock()
    mock_agent.id = "agent-002"
    mock_agent.elevenlabs_agent_id = "el-agent-configured"  # agent_id IS set
    mock_agent.elevenlabs_phone_number_id = None  # phone_number_id missing → config guard

    mock_client = MagicMock()
    mock_client.id = "test-client"

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True

    mock_db = AsyncMock()

    result = await dial_outbound_call(
        mock_db,
        lead=mock_lead,
        agent=mock_agent,
        client=mock_client,
        settings=mock_settings,
    )

    assert result.status == "failed"
    assert result.failure_code == "agent_not_configured", (
        f"Expected failure_code='agent_not_configured', got {result.failure_code!r}"
    )
    assert result.call_session_id is None, (
        f"Guard failure must not create a CallSession, got call_session_id={result.call_session_id!r}"
    )


# ---------------------------------------------------------------------------
# Permanent error → outcome_reason = 'provider_permanent'
# ---------------------------------------------------------------------------


async def test_permanent_error_sets_provider_permanent_outcome_reason():
    """error_category='permanent' → call_session.outcome_reason='provider_permanent'."""
    from app.outbound.service import dial_outbound_call
    from app.elevenlabs.models import OutboundCallResult

    # We test via the CallSession mutation: capture what gets set
    captured_outcome_reason = {}

    class FakeCallSession:
        id = "cs-permanent-001"
        telephony_status = "dialing"
        telephony_error = None
        outcome_reason = None
        elevenlabs_conversation_id = None
        provider_call_id = None
        provider_metadata = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name == "outcome_reason":
                captured_outcome_reason["value"] = value

    mock_lead = MagicMock()
    mock_lead.id = "lead-perm"
    mock_lead.phone = "+5491100000001"

    mock_agent = MagicMock()
    mock_agent.id = "agent-001"
    mock_agent.elevenlabs_agent_id = "el-agent-001"
    mock_agent.elevenlabs_phone_number_id = "pnum_test"

    mock_client = MagicMock()
    mock_client.id = "test-client"

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True

    perm_result = OutboundCallResult(
        outcome="error",
        error_category="permanent",
        error_detail="4xx provider error",
        provider_call_id=None,
        provider_metadata=None,
    )

    fake_cs = FakeCallSession()
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    with (
        patch("app.outbound.service.validate_e164"),
        patch("app.outbound.service._find_active_call_session", return_value=None),
        patch("app.outbound.service._find_in_progress_scheduled_call", return_value=None),
        patch("app.outbound.service.CallSession", return_value=fake_cs),
        patch("app.outbound.service.ElevenLabsService") as MockEL,
        patch("app.outbound.dynamic_vars.build_dynamic_variables", return_value={}),
    ):
        MockEL.return_value.initiate_outbound_call = AsyncMock(return_value=perm_result)

        with patch.object(mock_db, "add"):
            with patch.object(mock_db, "refresh"):
                result = await dial_outbound_call(
                    mock_db,
                    lead=mock_lead,
                    agent=mock_agent,
                    client=mock_client,
                    settings=mock_settings,
                )

    assert result.status == "failed"
    assert captured_outcome_reason.get("value") == "provider_permanent", (
        f"Expected outcome_reason='provider_permanent', "
        f"got {captured_outcome_reason.get('value')!r}"
    )


# ---------------------------------------------------------------------------
# Unknown error → outcome_reason = 'timeout_ambiguous', no tech retry
# ---------------------------------------------------------------------------


async def test_unknown_error_sets_timeout_ambiguous_outcome_reason():
    """error_category='unknown' → outcome_reason='timeout_ambiguous'."""
    from app.outbound.service import dial_outbound_call
    from app.elevenlabs.models import OutboundCallResult

    captured = {}

    class FakeCallSession:
        id = "cs-unknown-001"
        telephony_status = "dialing"
        telephony_error = None
        outcome_reason = None
        elevenlabs_conversation_id = None
        provider_call_id = None
        provider_metadata = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name == "outcome_reason":
                captured["value"] = value

    mock_lead = MagicMock()
    mock_lead.id = "lead-unknown"
    mock_lead.phone = "+5491100000001"

    mock_agent = MagicMock()
    mock_agent.id = "agent-001"
    mock_agent.elevenlabs_agent_id = "el-agent-001"
    mock_agent.elevenlabs_phone_number_id = "pnum_test"

    mock_client = MagicMock()
    mock_client.id = "test-client"

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True

    unknown_result = OutboundCallResult(
        outcome="error",
        error_category="unknown",
        error_detail="ReadTimeout",
        provider_call_id=None,
        provider_metadata=None,
    )

    fake_cs = FakeCallSession()
    mock_db = AsyncMock()

    with (
        patch("app.outbound.service.validate_e164"),
        patch("app.outbound.service._find_active_call_session", return_value=None),
        patch("app.outbound.service._find_in_progress_scheduled_call", return_value=None),
        patch("app.outbound.service.CallSession", return_value=fake_cs),
        patch("app.outbound.service.ElevenLabsService") as MockEL,
        patch("app.outbound.dynamic_vars.build_dynamic_variables", return_value={}),
        patch("app.outbound.service._fire_probe"),
    ):
        MockEL.return_value.initiate_outbound_call = AsyncMock(return_value=unknown_result)

        with patch.object(mock_db, "add"), patch.object(mock_db, "refresh"):
            result = await dial_outbound_call(
                mock_db,
                lead=mock_lead,
                agent=mock_agent,
                client=mock_client,
                settings=mock_settings,
            )

    assert result.status == "failed"
    assert captured.get("value") == "timeout_ambiguous", (
        f"Expected outcome_reason='timeout_ambiguous', got {captured.get('value')!r}"
    )


# ---------------------------------------------------------------------------
# Recurrent error (transient × 2) → outcome_reason = 'provider_transient'
# ---------------------------------------------------------------------------


async def test_recurrent_error_sets_provider_transient_outcome_reason():
    """Two transient failures → recurrent_error + outcome_reason='provider_transient'."""
    from app.outbound.service import dial_outbound_call
    from app.elevenlabs.models import OutboundCallResult

    captured = {}

    class FakeCallSession:
        id = "cs-recurrent-001"
        telephony_status = "dialing"
        telephony_error = None
        outcome_reason = None
        elevenlabs_conversation_id = None
        provider_call_id = None
        provider_metadata = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if name == "outcome_reason":
                captured["value"] = value

    mock_lead = MagicMock()
    mock_lead.id = "lead-recurrent"
    mock_lead.phone = "+5491100000001"

    mock_agent = MagicMock()
    mock_agent.id = "agent-001"
    mock_agent.elevenlabs_agent_id = "el-agent-001"
    mock_agent.elevenlabs_phone_number_id = "pnum_test"

    mock_client = MagicMock()
    mock_client.id = "test-client"

    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True

    transient_result = OutboundCallResult(
        outcome="error",
        error_category="transient",
        error_detail="503 service unavailable",
        provider_call_id=None,
        provider_metadata=None,
    )

    fake_cs = FakeCallSession()
    mock_db = AsyncMock()

    with (
        patch("app.outbound.service.validate_e164"),
        patch("app.outbound.service._find_active_call_session", return_value=None),
        patch("app.outbound.service._find_in_progress_scheduled_call", return_value=None),
        patch("app.outbound.service.CallSession", return_value=fake_cs),
        patch("app.outbound.service.ElevenLabsService") as MockEL,
        patch("app.outbound.dynamic_vars.build_dynamic_variables", return_value={}),
        patch("app.scheduler.service.schedule_tech_retry", new_callable=AsyncMock) as mock_tr,
    ):
        MockEL.return_value.initiate_outbound_call = AsyncMock(
            return_value=transient_result
        )
        mock_tr.return_value = None  # schedule_tech_retry returns something

        with patch.object(mock_db, "add"), patch.object(mock_db, "refresh"):
            result = await dial_outbound_call(
                mock_db,
                lead=mock_lead,
                agent=mock_agent,
                client=mock_client,
                settings=mock_settings,
            )

    assert result.status == "recurrent_error"
    assert captured.get("value") == "provider_transient", (
        f"Expected outcome_reason='provider_transient', got {captured.get('value')!r}"
    )
    mock_tr.assert_called_once()
