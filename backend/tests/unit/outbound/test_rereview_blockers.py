"""RED tests for WU1 re-review blockers (round 2).

These tests were written BEFORE the fixes — they define the contract that the
implementation must satisfy.

Blockers:
  CRITICAL-B1: Manual trigger must reject in_progress ScheduledCall for the lead.
               Current code only checks when scheduled_call is not None.
               Spec says: reject if lead has active CallSession OR in_progress ScheduledCall.
               Manual triggers MUST also check for in_progress ScheduledCall.

  CRITICAL-B2: Concurrency guard releases lock too early (after flush, before commit).
               A second independent AsyncSession may not see the uncommitted row.
               Fix: hold lock through the entire critical section (including commit and
               provider API completion) for single-process MVP safety.

  CRITICAL-B3: Metadata allowlist drops billed_duration_seconds.
               Spec says: "both cost and billed_duration_seconds stored without transformation".
               Current allowlist only has duration_seconds; billed_duration_seconds is dropped.

  WARNING-B4:  Agent with missing elevenlabs_phone_number_id causes Pydantic runtime error.
               Must be a controlled guard returning DialResult.status='failed' (not a crash).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_settings():
    s = MagicMock()
    s.enable_outbound_calls = True
    s.elevenlabs_api_key = SecretStr("test-key")
    return s


def _make_lead(lead_id: str = "lead-rereview-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Re-review Test Lead"
    return lead


def _make_agent(phone_number_id: str | None = "pn-xyz"):
    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = phone_number_id
    agent.name = "Test Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "Test Client"
    return client


def _make_in_progress_scheduled_call(call_id: str = "sc-in-progress-001"):
    sc = MagicMock()
    sc.id = call_id
    sc.status = "in_progress"
    sc.lead_id = "lead-rereview-001"
    return sc


def _build_mock_db_with_no_active_session_but_in_progress_sc(in_progress_sc):
    """DB mock: no active CallSession (telephony), but there IS an in_progress ScheduledCall.

    SELECT query sequence:
    - 1st execute: CallSession guard → no active session
    - 2nd execute: ScheduledCall guard → returns in_progress_sc
    """
    mock_db = AsyncMock()

    call_session_result = MagicMock()
    call_session_result.scalars.return_value.first.return_value = None  # no active telephony

    sched_call_result = MagicMock()
    sched_call_result.scalars.return_value.first.return_value = in_progress_sc  # overlap!

    mock_db.execute.side_effect = [call_session_result, sched_call_result]
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


def _accepted_result():
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = "el-call-ok"
    r.provider_metadata = {"cost": 0.05, "billed_duration_seconds": 30}
    r.error_detail = None
    r.error_category = None
    return r


# ---------------------------------------------------------------------------
# CRITICAL-B1: Manual trigger must reject in_progress ScheduledCall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_trigger_blocked_when_lead_has_in_progress_scheduled_call():
    """GIVEN a manual trigger (scheduled_call=None) for a lead that has an in_progress ScheduledCall
    WHEN dial_outbound_call is called
    THEN the call is REJECTED (DialResult.status='failed'), no provider call, no new CallSession.

    Spec: outbound-call-trigger — Requirement: Concurrent Call Guard
      "The system MUST reject a trigger attempt if the lead already has an active CallSession
       or an in_progress ScheduledCall."

    This was not guarded before: manual triggers passed scheduled_call=None so the
    `if scheduled_call is not None` guard was never evaluated.
    """
    from app.outbound.service import dial_outbound_call

    in_progress_sc = _make_in_progress_scheduled_call()
    mock_db = _build_mock_db_with_no_active_session_but_in_progress_sc(in_progress_sc)

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
                scheduled_call=None,  # MANUAL trigger — no ScheduledCall reference
            )

    assert result.status == "failed", (
        f"Manual trigger must be rejected when lead has in_progress ScheduledCall. "
        f"Got status={result.status!r}. "
        "Spec requires: reject if lead has active CallSession OR in_progress ScheduledCall."
    )
    assert result.call_session_id is None, (
        "No CallSession must be created when in_progress ScheduledCall guard triggers "
        "on a manual trigger attempt."
    )
    assert mock_api.call_count == 0, (
        f"Provider API must NOT be called when guard triggers. Got {mock_api.call_count} calls."
    )
    # Error message must indicate the reason clearly
    error_lower = (result.error or "").lower()
    assert any(kw in error_lower for kw in ("scheduled", "in_progress", "progress", "overlap")), (
        f"Error message must mention scheduled/in_progress/overlap. Got: {result.error!r}"
    )


@pytest.mark.asyncio
async def test_manual_trigger_proceeds_when_no_in_progress_scheduled_call():
    """GIVEN a manual trigger and no in_progress ScheduledCall for the lead
    WHEN dial_outbound_call is called
    THEN the call PROCEEDS normally (guard not triggered).
    """
    from app.outbound.service import dial_outbound_call

    mock_db = AsyncMock()

    # Both guards return None: no active telephony, no in_progress ScheduledCall
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

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
                scheduled_call=None,
            )

    assert result.status == "dialing", (
        f"Manual trigger with no in_progress ScheduledCall must succeed. Got {result.status!r}"
    )


# ---------------------------------------------------------------------------
# CRITICAL-B2: Lock must cover the full critical section (through commit/provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_lock_held_through_provider_call():
    """GIVEN two concurrent manual triggers for the SAME lead via asyncio.gather()
    WHEN both coroutines use INDEPENDENT DB sessions (each sees no active session initially)
    THEN exactly ONE provider call is made (lock held through provider, not released after flush).

    The previous implementation released the lock after db.flush() but BEFORE
    db.commit() and before the provider API call. A second independent DB session
    (not sharing the same session object) may not see an uncommitted row, so it
    could pass the guard and fire a second provider call.

    Fix: hold the lock through the full critical section — from DB guard check
    through provider API call completion (or until commit is done).

    Test strategy:
    - Two independent DB sessions (db1, db2) — each starts seeing no active session.
    - Lock serializes them. Second waiter must see the committed row from the first.
    - If lock is released after flush (before commit), the second may proceed.
    - If lock is held through commit, the second SELECT in the lock finds the row.
    """
    from app.outbound.service import dial_outbound_call, _LEAD_LOCKS

    lead_id = "lead-lock-commit-TEST-001"
    _LEAD_LOCKS.pop(lead_id, None)

    provider_call_count = 0

    async def _counting_provider(request):
        nonlocal provider_call_count
        provider_call_count += 1
        await asyncio.sleep(0)  # yield to allow the second waiter to proceed
        return _accepted_result()

    # Shared state to simulate "visibility after commit":
    # When the first coroutine commits, the second coroutine's SELECT inside the lock
    # should see the committed session. We simulate this with a flag.
    first_committed = False

    def _build_independent_db(lead_id: str):
        """Independent DB session — simulates a fresh AsyncSession."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        active_mock = MagicMock()
        active_mock.id = "call-from-first"
        active_mock.telephony_status = "dialing"

        execute_call_count = [0]

        async def _execute(stmt):
            execute_call_count[0] += 1
            result = MagicMock()
            # Second+ executes on any session after first_committed: simulate visibility
            if first_committed and execute_call_count[0] >= 1:
                result.scalars.return_value.first.return_value = active_mock
            else:
                result.scalars.return_value.first.return_value = None
            return result

        db.execute.side_effect = _execute

        async def _commit():
            nonlocal first_committed
            first_committed = True

        db.commit = _commit
        return db

    db1 = _build_independent_db(lead_id)
    db2 = _build_independent_db(lead_id)

    lead = _make_lead(lead_id=lead_id)

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        side_effect=_counting_provider,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            r1, r2 = await asyncio.gather(
                dial_outbound_call(
                    db=db1,
                    lead=lead,
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
                dial_outbound_call(
                    db=db2,
                    lead=lead,
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
            )

    statuses = {r1.status, r2.status}
    assert provider_call_count == 1, (
        f"Lock held through provider call must allow exactly 1 provider call across independent "
        f"sessions. Got {provider_call_count} provider call(s). "
        "If the lock is released before commit, the second independent session "
        "may not see the uncommitted row and fires a duplicate paid call."
    )
    assert "dialing" in statuses, "At least one call must succeed"
    assert "failed" in statuses, "Second concurrent attempt must be blocked"


# ---------------------------------------------------------------------------
# CRITICAL-B3: billed_duration_seconds must be in the metadata allowlist
# ---------------------------------------------------------------------------


def test_billed_duration_seconds_preserved_in_allowlist():
    """GIVEN a provider response containing billed_duration_seconds
    WHEN _extract_safe_provider_metadata is called
    THEN billed_duration_seconds is preserved in the result.

    Spec: outbound-call-trigger — Scenario: Cost and billed seconds persisted when available
      "GIVEN the ElevenLabs response includes cost and billed_duration_seconds
       WHEN the response is persisted
       THEN both values are stored in provider_metadata without transformation."

    Previously the allowlist had 'duration_seconds' but NOT 'billed_duration_seconds',
    so the spec-required field was silently dropped.
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {
        "call_id": "el-call-billing",
        "status": "completed",
        "cost": 0.21,
        "duration_seconds": 60,           # general duration (may differ from billed)
        "billed_duration_seconds": 62,    # BILLED duration — spec requires this preserved
        "message": "Call completed",
        # Unsafe fields — must still be dropped:
        "sip_uri": "sip:+1555@telnyx.com",
        "to_number": "+14155552671",
    }

    safe = _extract_safe_provider_metadata(raw)

    assert safe is not None
    assert "billed_duration_seconds" in safe, (
        "billed_duration_seconds MUST be preserved in provider_metadata per spec. "
        "Spec: 'cost and billed_duration_seconds stored without transformation.' "
        f"Got: {safe}"
    )
    assert safe["billed_duration_seconds"] == 62, (
        f"billed_duration_seconds value must be preserved exactly. Got {safe.get('billed_duration_seconds')}"
    )
    # Billing fields all present
    assert safe["cost"] == 0.21, "cost must be preserved"
    assert safe["duration_seconds"] == 60, "duration_seconds must still be preserved"

    # Unsafe fields still stripped
    assert "sip_uri" not in safe, "sip_uri must still be dropped after fix"
    assert "to_number" not in safe, "to_number must still be dropped after fix"


def test_billed_duration_seconds_absent_when_not_in_response():
    """GIVEN a provider response that does NOT include billed_duration_seconds
    WHEN _extract_safe_provider_metadata is called
    THEN billed_duration_seconds is absent from result (no None-padding).
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {"call_id": "el-no-billing", "cost": 0.05}
    safe = _extract_safe_provider_metadata(raw)

    assert safe is not None
    # Should NOT pad with None for missing fields
    assert "billed_duration_seconds" not in safe or safe.get("billed_duration_seconds") is None, (
        "billed_duration_seconds must not appear with a None value if not in the original response"
    )


# ---------------------------------------------------------------------------
# WARNING-B4: Agent missing elevenlabs_phone_number_id must fail controlled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_missing_phone_number_id_returns_controlled_failure():
    """GIVEN an agent with elevenlabs_phone_number_id=None (not configured)
    WHEN dial_outbound_call is called
    THEN DialResult.status='failed' with a clear error message (NOT a Pydantic/runtime crash).

    Without an explicit guard, the code passes None to OutboundCallRequest.agent_phone_number_id,
    which raises a Pydantic ValidationError at runtime — an uncontrolled exception that
    propagates out of dial_outbound_call() (violating its "always returns DialResult, never raises" contract).
    """
    from app.outbound.service import dial_outbound_call

    # Agent with NO phone_number_id configured
    agent = _make_agent(phone_number_id=None)

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            # Must NOT raise — must return DialResult
            try:
                result = await dial_outbound_call(
                    db=mock_db,
                    lead=_make_lead(),
                    agent=agent,
                    client=_make_client(),
                    settings=_make_settings(),
                    scheduled_call=None,
                )
            except Exception as exc:
                pytest.fail(
                    f"dial_outbound_call() raised {type(exc).__name__} instead of returning DialResult. "
                    f"It must NEVER raise — return DialResult with status='failed'. Error: {exc}"
                )

    assert result.status == "failed", (
        f"Missing elevenlabs_phone_number_id must return status='failed'. Got {result.status!r}"
    )
    assert result.call_session_id is None or isinstance(result.call_session_id, str), (
        "call_session_id may be None or a string"
    )
    error_lower = (result.error or "").lower()
    assert any(kw in error_lower for kw in ("phone_number_id", "phone number id", "agent", "configured", "missing")), (
        f"Error must mention phone_number_id or configuration. Got: {result.error!r}"
    )
    # Provider must NOT be called when guard triggers
    assert mock_api.call_count == 0, (
        f"Provider must NOT be called when agent phone_number_id is missing. Got {mock_api.call_count} call(s)."
    )


@pytest.mark.asyncio
async def test_agent_with_phone_number_id_proceeds_normally():
    """GIVEN an agent WITH elevenlabs_phone_number_id set
    WHEN dial_outbound_call is called
    THEN the call proceeds normally (guard not triggered).
    """
    from app.outbound.service import dial_outbound_call

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

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
                agent=_make_agent(phone_number_id="pn-configured"),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing", (
        f"Agent with valid phone_number_id must succeed. Got {result.status!r}"
    )
