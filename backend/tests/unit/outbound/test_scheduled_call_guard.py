"""Tests for ScheduledCall in_progress overlap guard in dial_outbound_call().

Review blocker WARNING-4:
  When dial_outbound_call() is triggered by the scheduler (scheduled_call is not None),
  it must check whether an 'in_progress' ScheduledCall already exists for the same lead.
  If one exists (different from the current scheduled_call), it must block — two scheduler
  ticks could fire for the same lead and create two provider calls.

  For manual triggers (scheduled_call=None), the existing telephony_status guard suffices.

Spec: outbound-call-trigger
  - Only one active call per lead at a time (concurrent guard covers telephony side)
  - Scheduler must not create two in_progress ScheduledCalls for the same lead
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    s = MagicMock()
    s.enable_outbound_calls = True
    s.elevenlabs_api_key = SecretStr("test-key")
    return s


def _make_lead(lead_id: str = "lead-sched-guard-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Scheduled Guard Test Lead"
    return lead


def _make_agent():
    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = "pn-xyz"
    agent.name = "Test Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "Test Client"
    return client


def _make_scheduled_call(call_id: str, status: str = "in_progress"):
    sc = MagicMock()
    sc.id = call_id
    sc.status = status
    sc.lead_id = "lead-sched-guard-001"
    return sc


def _build_mock_db(active_telephony_session=None, active_scheduled_call=None):
    """Build mock DB.

    SELECT queries return:
    - First query (CallSession): active_telephony_session or None
    - Second query (ScheduledCall): active_scheduled_call or None

    Using side_effect list for sequential execute() calls.
    """
    mock_db = AsyncMock()

    call_session_result = MagicMock()
    call_session_result.scalars.return_value.first.return_value = active_telephony_session

    scheduled_call_result = MagicMock()
    scheduled_call_result.scalars.return_value.first.return_value = active_scheduled_call

    # Both results (guard check: CallSession, then ScheduledCall if scheduled_call provided)
    mock_db.execute.side_effect = [
        call_session_result,
        scheduled_call_result,
    ]

    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    return mock_db


def _accepted_result():
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = "el-call-sched-ok"
    r.provider_metadata = {"cost": 0.05}
    r.error_detail = None
    r.error_category = None
    return r


# ---------------------------------------------------------------------------
# Test: existing in_progress ScheduledCall blocks the second scheduled dial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_progress_scheduled_call_blocks_duplicate_scheduled_dial():
    """GIVEN a scheduled_call is passed AND another in_progress ScheduledCall exists for same lead
    WHEN dial_outbound_call is called
    THEN DialResult.status='failed', no provider call made, no new CallSession.

    This guards against duplicate scheduler ticks dialing the same lead twice.
    """
    from app.outbound.service import dial_outbound_call

    # An existing in_progress ScheduledCall for the same lead
    existing_sc = _make_scheduled_call("existing-sc-001", status="in_progress")

    # No active telephony session, but there IS an in_progress ScheduledCall
    mock_db = _build_mock_db(
        active_telephony_session=None,
        active_scheduled_call=existing_sc,
    )

    # Current scheduled_call is a DIFFERENT one (not the existing one)
    current_sc = _make_scheduled_call("current-sc-002", status="in_progress")

    from unittest.mock import patch

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
                scheduled_call=current_sc,
            )

    assert result.status == "failed", (
        f"In-progress ScheduledCall overlap must return status='failed', got {result.status!r}"
    )
    assert result.call_session_id is None, (
        "No CallSession must be created when ScheduledCall overlap guard triggers"
    )
    assert mock_api.call_count == 0, (
        f"Provider must NOT be called when ScheduledCall overlap guard triggers. "
        f"Got {mock_api.call_count} call(s)."
    )
    assert "scheduled" in (result.error or "").lower() or "overlap" in (result.error or "").lower() or "progress" in (result.error or "").lower(), (
        f"Error message should mention scheduled/overlap/in_progress, got: {result.error!r}"
    )


@pytest.mark.asyncio
async def test_manual_trigger_blocked_when_in_progress_scheduled_call_exists():
    """GIVEN scheduled_call=None (manual trigger) and an in_progress ScheduledCall for the lead
    WHEN dial_outbound_call is called
    THEN the call is REJECTED (guard applies to ALL triggers, not just scheduled ones).

    Spec update (re-review round 2):
      Spec: outbound-call-trigger — Requirement: Concurrent Call Guard
        "The system MUST reject a trigger attempt if the lead already has an active
         CallSession or an in_progress ScheduledCall."
      This applies to manual triggers too — two simultaneous calls would incur double charges.
    """
    from app.outbound.service import dial_outbound_call

    # An existing in_progress ScheduledCall for the same lead
    existing_sc = _make_scheduled_call("existing-sc-manual-overlap", status="in_progress")

    # No active telephony session but there IS an in_progress ScheduledCall
    mock_db = _build_mock_db(
        active_telephony_session=None,
        active_scheduled_call=existing_sc,
    )

    from unittest.mock import patch

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
                scheduled_call=None,  # Manual trigger — overlap guard MUST still apply
            )

    assert result.status == "failed", (
        f"Manual trigger must be REJECTED when lead has in_progress ScheduledCall. "
        f"Got {result.status!r}. "
        "Spec: 'reject if lead has active CallSession OR in_progress ScheduledCall.'"
    )
    assert result.call_session_id is None, (
        "No CallSession must be created when in_progress ScheduledCall guard triggers."
    )
    assert mock_api.call_count == 0, (
        f"Provider must NOT be called. Got {mock_api.call_count} call(s)."
    )


@pytest.mark.asyncio
async def test_scheduled_call_no_overlap_guard_when_no_other_in_progress():
    """GIVEN scheduled_call is provided but NO other in_progress ScheduledCall exists
    WHEN dial_outbound_call is called
    THEN the call PROCEEDS normally.
    """
    from app.outbound.service import dial_outbound_call

    # No active telephony, no other in_progress ScheduledCall
    mock_db = _build_mock_db(
        active_telephony_session=None,
        active_scheduled_call=None,  # No overlap
    )

    current_sc = _make_scheduled_call("current-sc-only", status="in_progress")

    from unittest.mock import patch

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=_accepted_result(),
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
                scheduled_call=current_sc,
            )

    assert result.status == "dialing", (
        f"Scheduled call with no overlap must succeed. Got {result.status!r}"
    )
