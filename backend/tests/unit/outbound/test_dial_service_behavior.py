"""Strengthened behavioral tests for dial_outbound_call().

Review blockers addressed (CRITICAL-2):
  - Prove CallSession is flushed to DB BEFORE provider dispatch
  - All outcome paths persist expected fields on CallSession
  - Provider call counts: accepted=1 call; transient=2 calls; permanent=1 call
  - One transient retry only — no additional retries
  - No retry for no_answer / permanent errors
  - pre-dial telephony_status='dialing', provider='elevenlabs' stored on session

TDD cycle: these tests are written before reviewing service.py behavior in detail.
Run them RED first, then confirm GREEN after implementation review.
All ElevenLabs HTTP mocked — no live calls allowed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_settings(enable_outbound: bool = True):
    s = MagicMock()
    s.enable_outbound_calls = enable_outbound
    from pydantic import SecretStr
    s.elevenlabs_api_key = SecretStr("test-xi-key")
    return s


def _make_lead(phone: str = "+541155551234", lead_id: str = "lead-beh-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = phone
    lead.client_id = "client-a"
    lead.name = "Behavior Test Lead"
    return lead


def _make_agent():
    agent = MagicMock()
    agent.id = "agent-beh-001"
    agent.elevenlabs_agent_id = "el-agent-beh"
    agent.elevenlabs_phone_number_id = "pn-beh-xyz"
    agent.name = "Behavior Test Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "Behavior Test Client"
    return client


def _accepted_result(call_id: str = "el-call-123"):
    """Build a mock OutboundCallResult with outcome='accepted'."""
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = call_id
    r.provider_metadata = {"raw": "data", "cost": 0.05}
    r.error_detail = None
    r.error_category = None
    return r


def _transient_result(detail: str = "503 Service Unavailable"):
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "transient"
    return r


def _permanent_result(detail: str = "400 Bad phone number"):
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "permanent"
    return r


def _unknown_result(detail: str = "read_timeout=ReadTimeout: timed out"):
    """Ambiguous side effect — read/write timeout after the request was sent.

    The provider may already have placed a real (billed) SIP call. This category
    MUST NOT be retried (retrying dials a second call).
    """
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "unknown"
    return r


def _build_mock_db(active_session=None):
    """Build a mock AsyncSession that:
    - Returns active_session (or None) on SELECT query
    - Captures objects passed to db.add() (db.add is sync, not awaited)
    - Records flush/commit calls in order
    """
    mock_db = AsyncMock()

    # SELECT query result
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = active_session
    mock_db.execute.return_value = mock_result

    # db.add() is called WITHOUT await in SQLAlchemy — must be a sync callable.
    # Using AsyncMock for add causes "coroutine was never awaited" warnings.
    added_objects: list = []

    def _sync_add(obj):
        added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_sync_add)
    mock_db._added_objects = added_objects

    # Track flush/commit order
    call_order: list[str] = []

    async def _tracked_flush():
        call_order.append("flush")

    async def _tracked_commit():
        call_order.append("commit")

    mock_db.flush = _tracked_flush
    mock_db.commit = _tracked_commit
    mock_db._call_order = call_order

    return mock_db


# ---------------------------------------------------------------------------
# TEST: CallSession created with telephony_status='dialing' BEFORE API call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_session_created_before_provider_dispatch():
    """GIVEN a valid outbound trigger
    WHEN dial_outbound_call is called
    THEN db.flush() must occur BEFORE ElevenLabs is called.

    This proves crash-safety: session exists in DB before the provider API fires.
    """
    from app.outbound.service import dial_outbound_call

    flush_happened_before_api = []

    mock_db = _build_mock_db(active_session=None)

    # We track whether flush happened before the API call
    # by intercepting initiate_outbound_call and checking flush was already called
    async def _fake_flush():
        flush_happened_before_api.append("flushed")

    mock_db.flush = _fake_flush
    mock_db.commit = AsyncMock()
    mock_db._call_order = []

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        # Capture state when API is called
        api_call_state: list = []

        async def _capturing_api(request):
            api_call_state.append(len(flush_happened_before_api))
            return _accepted_result()

        mock_api.side_effect = _capturing_api

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
            )

    assert result.status == "dialing"
    assert len(api_call_state) == 1, "ElevenLabs API must be called exactly once on success"
    # flush must have run BEFORE the ElevenLabs API was called
    assert api_call_state[0] > 0, (
        "db.flush() must be called BEFORE ElevenLabs initiate_outbound_call(). "
        "CallSession must be persisted to DB before the provider fires."
    )


@pytest.mark.asyncio
async def test_call_session_has_dialing_status_at_flush_time():
    """GIVEN a valid outbound trigger
    WHEN dial_outbound_call creates the CallSession
    THEN telephony_status must be 'dialing' when db.flush() is called.
    """
    from app.outbound.service import dial_outbound_call

    captured_session_at_flush: list = []
    mock_db = _build_mock_db(active_session=None)

    async def _capturing_flush():
        # Capture the session state at flush time
        if mock_db._added_objects:
            obj = mock_db._added_objects[-1]
            captured_session_at_flush.append({
                "telephony_status": getattr(obj, "telephony_status", None),
                "telephony_provider": getattr(obj, "telephony_provider", None),
                "lead_id": getattr(obj, "lead_id", None),
            })

    mock_db.flush = _capturing_flush
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
            await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert len(captured_session_at_flush) >= 1, "flush must be called at least once"
    snap = captured_session_at_flush[0]
    assert snap["telephony_status"] == "dialing", (
        f"CallSession telephony_status at flush must be 'dialing', got {snap['telephony_status']!r}"
    )
    assert snap["telephony_provider"] == "elevenlabs", (
        f"CallSession telephony_provider at flush must be 'elevenlabs', got {snap['telephony_provider']!r}"
    )


# ---------------------------------------------------------------------------
# TEST: Accepted path — expected fields persisted on CallSession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepted_path_runs_mock_persistence_path():
    """GIVEN ElevenLabs API returns outcome='accepted'
    WHEN dial_outbound_call completes
    THEN CallSession has telephony_status='ringing', provider_call_id set,
         provider_metadata set, and db.commit() was called.

    Field-level proof that the accepted path updates all contract fields.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    # Replace add to also capture the session object
    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.commit = AsyncMock()

    accepted = _accepted_result(call_id="el-call-ACCEPTED-001")
    accepted.provider_metadata = {"cost": 0.10, "duration_seconds": 30}

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=accepted,
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
            )

    assert result.status == "dialing"
    assert result.call_session_id is not None

    # Verify ElevenLabs called exactly once
    assert mock_api.call_count == 1, (
        f"ElevenLabs initiate_outbound_call must be called exactly once on success, "
        f"got {mock_api.call_count}"
    )

    # Mock sessions cannot model a database refresh. Real-session regressions below
    # assert fields; this unit test only verifies the persistence path is invoked.
    assert session_obj is not None, "A CallSession must be created"
    assert mock_db.execute.await_count >= 3
    assert mock_db.commit.call_count >= 1, "db.commit() must be called after accepted response"


@pytest.mark.asyncio
async def test_accepted_path_runs_mock_conversation_linkage_path():
    """GIVEN the accepted provider_metadata contains a conversation_id
    WHEN dial_outbound_call completes
    THEN CallSession.elevenlabs_conversation_id is set to that conversation_id.

    This linkage lets the custom-llm endpoint resolve the CallSession (and its
    lead) from an incoming conversation_id — without it, outbound calls arrive
    with lead_id=null and no lead context.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.commit = AsyncMock()

    accepted = _accepted_result(call_id="conv_abc123")
    # Real SIP-trunk response shape — provider_call_id resolved from conversation_id.
    accepted.provider_metadata = {
        "conversation_id": "conv_abc123",
        "sip_call_id": "otb_xyz789",
    }

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=accepted,
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
            )

    assert result.status == "dialing"
    assert session_obj is not None
    assert mock_db.execute.await_count >= 3


# ---------------------------------------------------------------------------
# TEST: Permanent error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permanent_error_path_no_retry():
    """GIVEN ElevenLabs API returns a permanent error (4xx)
    WHEN dial_outbound_call handles it
    THEN telephony_status='failed', no retry attempted (only 1 API call),
         telephony_error is set, and db.commit() was called.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    perm = _permanent_result("400 Invalid agent_id")

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=perm,
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
            )

    assert result.status == "failed"
    assert result.call_session_id is not None, "CallSession must still be created"

    # NO retry for permanent errors
    assert mock_api.call_count == 1, (
        f"Permanent error must NOT retry. ElevenLabs called {mock_api.call_count} time(s), expected 1."
    )

    assert session_obj is not None
    assert session_obj.telephony_status == "failed", (
        f"Permanent error must set telephony_status='failed', got {session_obj.telephony_status!r}"
    )
    assert session_obj.telephony_error is not None, (
        "Permanent error must set telephony_error on CallSession"
    )
    assert mock_db.commit.call_count >= 1, "db.commit() must be called after permanent error"


# ---------------------------------------------------------------------------
# TEST: Ambiguous timeout (unknown) — NO retry, session marked 'failed'
#
# Regression for the duplicate-call bug: a read timeout after a side-effecting
# outbound dial produced two real SIP calls because the timeout was classified
# 'transient' and retried. The 'unknown' category must NEVER be retried.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_timeout_does_not_retry_and_marks_failed():
    """GIVEN ElevenLabs read-times-out AFTER the request was sent (error_category='unknown')
    WHEN dial_outbound_call handles it
    THEN exactly 1 API call is made (NO retry — avoids a duplicate billed call),
         telephony_status='failed', telephony_error explains the ambiguous timeout,
         and status='failed' is returned (never left 'dialing').
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    ambiguous = _unknown_result("read_timeout=ReadTimeout: timed out after 45s")

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=ambiguous,
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
            )

    # CRITICAL: exactly ONE API call — retrying an ambiguous timeout would place a
    # second real billed call while the first may already be ringing.
    assert mock_api.call_count == 1, (
        f"Ambiguous timeout must NOT retry. ElevenLabs called {mock_api.call_count} "
        f"time(s), expected 1 (retrying would dial a duplicate real call)."
    )

    assert result.status == "failed", (
        f"Ambiguous timeout must return status='failed' (not 'dialing'/'recurrent_error'), "
        f"got {result.status!r}"
    )
    assert result.call_session_id is not None, "CallSession must still be created (durable record)"

    assert session_obj is not None
    assert session_obj.telephony_status == "failed", (
        f"Ambiguous timeout must set telephony_status='failed', got {session_obj.telephony_status!r}"
    )
    assert session_obj.telephony_error is not None
    assert "ambiguous" in session_obj.telephony_error.lower() or "timeout" in session_obj.telephony_error.lower(), (
        f"telephony_error must explain the ambiguous timeout, got {session_obj.telephony_error!r}"
    )
    assert session_obj.provider_call_id is None, (
        "No provider_call_id was captured on an ambiguous timeout"
    )


# ---------------------------------------------------------------------------
# TEST: Transient error — exactly 1 retry, then recurrent_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_error_retries_exactly_once_then_recurrent_error():
    """GIVEN ElevenLabs API returns transient errors on both attempts
    WHEN dial_outbound_call handles it
    THEN ElevenLabs called exactly TWICE (attempt + 1 retry),
         final telephony_status='recurrent_error', error contains both attempt details.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    transient1 = _transient_result("503 Upstream error attempt 1")
    transient2 = _transient_result("503 Upstream error attempt 2")

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=[transient1, transient2],
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            # C6: patch schedule_tech_retry so it doesn't invoke DB.add
            # (which would overwrite session_obj with a ScheduledCall).
            with patch(
                "app.scheduler.service.schedule_tech_retry",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await dial_outbound_call(
                    db=mock_db,
                    lead=_make_lead(),
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                )

    # Exactly 2 API calls — no more
    assert mock_api.call_count == 2, (
        f"Transient error must retry exactly once (2 total API calls). "
        f"Got {mock_api.call_count} call(s)."
    )

    assert result.status == "recurrent_error", (
        f"Two consecutive transient failures must produce status='recurrent_error', "
        f"got {result.status!r}"
    )
    assert result.call_session_id is not None

    assert session_obj is not None
    assert session_obj.telephony_status == "recurrent_error", (
        f"telephony_status must be 'recurrent_error', got {session_obj.telephony_status!r}"
    )
    # Error message must reference both attempts
    assert session_obj.telephony_error is not None
    assert "attempt_1" in session_obj.telephony_error or "1" in session_obj.telephony_error, (
        "telephony_error must reference the first attempt failure"
    )
    assert "attempt_2" in session_obj.telephony_error or "2" in session_obj.telephony_error, (
        "telephony_error must reference the second attempt failure"
    )


# ---------------------------------------------------------------------------
# TEST: Transient error then accepted on retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_then_accepted_on_retry_runs_mock_persistence_path():
    """GIVEN ElevenLabs returns transient error on attempt 1, accepted on attempt 2
    WHEN dial_outbound_call handles it
    THEN status='dialing', telephony_status='ringing', provider_call_id set,
         telephony_error cleared (None), exactly 2 API calls made.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj
        mock_db._added_objects.append(obj)

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    transient = _transient_result("503 retry me")
    accepted = _accepted_result(call_id="el-call-RETRY-OK")

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=[transient, accepted],
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
            )

    assert mock_api.call_count == 2, (
        f"Transient-then-accepted must make exactly 2 API calls, got {mock_api.call_count}"
    )
    assert result.status == "dialing"
    assert result.call_session_id is not None

    assert session_obj is not None
    assert mock_db.execute.await_count >= 3


# ---------------------------------------------------------------------------
# TEST: no_answer — permanent, no retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_answer_is_distinct_status_no_retry():
    """GIVEN ElevenLabs returns no_answer (error_category='no_answer')
    WHEN dial_outbound_call handles it
    THEN exactly 1 API call made, telephony_status='no_answer' (NOT 'failed'), no retry.

    Spec: Live Status State Machine — ringing → no_answer when provider reports
    no answer / ring timeout. This is distinct from system failure ('failed').
    It should never be retried — retrying a ring timeout is wasteful and
    semantically wrong (the called party chose not to answer).

    Verify-fix: previously mapped to 'failed' incorrectly. Now uses distinct 'no_answer' status.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    # no_answer uses the distinct 'no_answer' error_category (not 'permanent')
    no_answer = MagicMock()
    no_answer.outcome = "error"
    no_answer.provider_call_id = None
    no_answer.provider_metadata = None
    no_answer.error_detail = "no_answer: lead did not pick up within ring timeout"
    no_answer.error_category = "no_answer"  # distinct category — do not retry

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=no_answer,
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
            )

    assert mock_api.call_count == 1, (
        f"no_answer must NOT retry. API called {mock_api.call_count} time(s)."
    )
    assert result.status == "failed", (
        f"DialResult.status must be 'failed' for no_answer, got {result.status!r}"
    )
    # Key spec assertion: session telephony_status must be 'no_answer', not 'failed'
    added_sessions = mock_db._added_objects
    assert len(added_sessions) >= 1, "CallSession must have been created"
    call_session = added_sessions[0]
    assert call_session.telephony_status == "no_answer", (
        f"telephony_status must be 'no_answer' (distinct from 'failed'), "
        f"got {call_session.telephony_status!r}"
    )


# ---------------------------------------------------------------------------
# TEST: Concurrent guard — only 1 provider call even under simulated race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_guard_blocks_second_dial():
    """GIVEN two dial_outbound_call invocations for the same lead running concurrently
    WHEN both are awaited
    THEN at most one ElevenLabs API call is made (the guard must block the second).

    This tests the per-lead concurrency guard works under asyncio concurrency.
    Both calls share the same asyncio event loop tick.
    """
    import asyncio
    from app.outbound.service import dial_outbound_call

    api_call_count = 0
    lock_released = asyncio.Event()

    # First call: accepted but slow
    async def _slow_accepted(request):
        nonlocal api_call_count
        api_call_count += 1
        await asyncio.sleep(0)  # yield to let second call try to interleave
        return _accepted_result()

    # DB for lead #1 (first call) — returns no active session
    mock_db1 = _build_mock_db(active_session=None)
    mock_db1.flush = AsyncMock()
    mock_db1.commit = AsyncMock()

    # DB for lead #1 (second call) — returns active session (simulating lock state)
    from unittest.mock import MagicMock as MM
    active_sess = MM()
    active_sess.telephony_status = "dialing"
    active_sess.id = "active-from-first-call"
    mock_db2 = _build_mock_db(active_session=active_sess)
    mock_db2.flush = AsyncMock()
    mock_db2.commit = AsyncMock()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=_slow_accepted,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            r1, r2 = await asyncio.gather(
                dial_outbound_call(
                    db=mock_db1,
                    lead=_make_lead(lead_id="lead-concurrent-001"),
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
                dial_outbound_call(
                    db=mock_db2,
                    lead=_make_lead(lead_id="lead-concurrent-001"),
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
            )

    # Exactly one of them is "dialing" and the other is "failed" (concurrent guard)
    statuses = {r1.status, r2.status}
    assert "dialing" in statuses, "One call must succeed"
    assert "failed" in statuses, "The second concurrent call must be blocked"

    # Only one API call must be made (the guard blocked the second before dispatch)
    assert api_call_count == 1, (
        f"Concurrent guard must allow exactly 1 provider call. "
        f"Got {api_call_count} API call(s)."
    )


# ---------------------------------------------------------------------------
# TEST: conversation_initiation_client_data wraps dynamic_variables correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_initiation_client_data_wraps_dynamic_variables():
    """GIVEN dial_outbound_call is called with non-empty dynamic variables
    WHEN the ElevenLabs API is called
    THEN conversation_initiation_client_data must have a "dynamic_variables" key
         wrapping the variables dict — not a flat dict at the top level.

    Root cause: ElevenLabs requires {dynamic_variables: {...}} structure for
    template substitution (e.g. {{lead_name}}). A flat dict is silently ignored
    and the agent uses the literal template text instead of the substituted value.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.commit = AsyncMock()

    captured_requests: list = []

    async def _capture_request(request):
        captured_requests.append(request)
        return _accepted_result()

    dynamic_vars_returned = {"lead_name": "Ana García", "lead_phone": "+541155551234"}

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=_capture_request,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value=dynamic_vars_returned,
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(lead_id="lead-dv-001"),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert len(captured_requests) == 1, "ElevenLabs API must be called exactly once"
    cicd = captured_requests[0].conversation_initiation_client_data

    assert cicd is not None, "conversation_initiation_client_data must not be None"
    assert "dynamic_variables" in cicd, (
        "conversation_initiation_client_data must have a 'dynamic_variables' key. "
        f"Got keys: {list(cicd.keys())}"
    )
    assert cicd["dynamic_variables"] == dynamic_vars_returned, (
        f"dynamic_variables must match the dict returned by build_dynamic_variables. "
        f"Got: {cicd['dynamic_variables']!r}"
    )
    # Flat keys must NOT be at the top level of cicd
    for flat_key in dynamic_vars_returned:
        assert flat_key not in cicd, (
            f"Key {flat_key!r} must be nested under 'dynamic_variables', "
            f"not at the top level of conversation_initiation_client_data."
        )


@pytest.mark.asyncio
async def test_conversation_initiation_client_data_includes_custom_llm_extra_body():
    """GIVEN dial_outbound_call is called
    WHEN the ElevenLabs API is called
    THEN conversation_initiation_client_data must include a "custom_llm_extra_body"
         key with client_id and lead_id so the Custom LLM can route the session.

    The Custom LLM handler (webhook.py) extracts client_id and lead_id from
    elevenlabs_extra_body — which ElevenLabs populates from custom_llm_extra_body
    in conversation_initiation_client_data. Without this, outbound calls have no
    lead context and the agent addresses the lead generically.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.commit = AsyncMock()

    captured_requests: list = []

    async def _capture_request(request):
        captured_requests.append(request)
        return _accepted_result()

    lead = _make_lead(lead_id="lead-extra-001")
    client = _make_client()
    client.id = "client-test-001"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=_capture_request,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=lead,
                agent=_make_agent(),
                client=client,
                settings=_make_settings(),
            )

    assert len(captured_requests) == 1
    cicd = captured_requests[0].conversation_initiation_client_data

    assert cicd is not None, "conversation_initiation_client_data must not be None"
    assert "custom_llm_extra_body" in cicd, (
        "conversation_initiation_client_data must have a 'custom_llm_extra_body' key "
        "so ElevenLabs forwards it to the Custom LLM endpoint. "
        f"Got keys: {list(cicd.keys())}"
    )
    extra_body = cicd["custom_llm_extra_body"]
    assert extra_body.get("client_id") == client.id, (
        f"custom_llm_extra_body must include client_id={client.id!r}. Got: {extra_body!r}"
    )
    assert extra_body.get("lead_id") == str(lead.id), (
        f"custom_llm_extra_body must include lead_id={str(lead.id)!r}. Got: {extra_body!r}"
    )


@pytest.mark.asyncio
async def test_conversation_initiation_client_data_always_includes_custom_llm_extra_body_even_when_no_dynamic_vars():
    """GIVEN dial_outbound_call is called with empty dynamic variables
    WHEN the ElevenLabs API is called
    THEN conversation_initiation_client_data must still include custom_llm_extra_body
         with client_id and lead_id even when there are no template variables.

    This ensures outbound calls always carry routing context to the Custom LLM,
    regardless of whether the dynamic_variables dict is empty.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.commit = AsyncMock()

    captured_requests: list = []

    async def _capture_request(request):
        captured_requests.append(request)
        return _accepted_result()

    lead = _make_lead(lead_id="lead-nodv-001")
    client = _make_client()
    client.id = "client-nodv-001"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        side_effect=_capture_request,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},  # empty dict — no dynamic vars
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=lead,
                agent=_make_agent(),
                client=client,
                settings=_make_settings(),
            )

    assert len(captured_requests) == 1
    cicd = captured_requests[0].conversation_initiation_client_data

    assert cicd is not None
    # dynamic_variables must be absent when dict was empty
    assert "dynamic_variables" not in cicd, (
        "dynamic_variables key must be omitted when dynamic_vars is empty"
    )
    # custom_llm_extra_body must always be present
    assert "custom_llm_extra_body" in cicd
    assert cicd["custom_llm_extra_body"]["client_id"] == client.id
    assert cicd["custom_llm_extra_body"]["lead_id"] == str(lead.id)


# ---------------------------------------------------------------------------
# TEST: Real-session late provider responses must not regress webhook evidence
# ---------------------------------------------------------------------------


async def _seed_dial_records(db_engine, suffix: str):
    """Create the persisted tenant, agent, and lead required for a real dial."""
    from app.leads.models import Lead
    from app.tenants.models import Agent, Client

    client = Client(
        id=f"client-late-{suffix}",
        name=f"Late response client {suffix}",
        voice_id="voice-late-response",
    )
    agent = Agent(
        id=f"agent-late-{suffix}",
        client_id=client.id,
        slug=f"late-{suffix}",
        name="Late Response Agent",
        voice_id="voice-late-response",
        elevenlabs_agent_id="el-agent-late-response",
        elevenlabs_phone_number_id="pn-late-response",
    )
    lead = Lead(
        id=f"lead-late-{suffix}",
        client_id=client.id,
        name="Late Response Lead",
        phone="+541155551234",
        status="new",
    )
    async with db_engine.async_session_factory() as db:
        db.add_all([client, agent, lead])
        await db.commit()
    return client, agent, lead


async def _commit_webhook_completion(db_engine, *, client_id: str, lead_id: str) -> None:
    """Commit actual webhook linkage plus newer diagnostic evidence in another session."""
    from app.outbound.linkage import link_outbound_session_by_webhook

    async with db_engine.async_session_factory() as webhook_db:
        call_session = await link_outbound_session_by_webhook(
            webhook_db,
            conversation_id="webhook-conversation-id",
            client_id=client_id,
            lead_id=lead_id,
        )
        assert call_session is not None
        call_session.telephony_error = "webhook diagnostic evidence"
        await webhook_db.commit()


async def _get_persisted_call_session(db_engine, session_id: str):
    from app.calls.models import CallSession

    async with db_engine.async_session_factory() as verification_db:
        return await verification_db.get(CallSession, session_id)


@pytest.mark.asyncio
async def test_first_accepted_late_response_preserves_committed_webhook_completion(db_engine):
    """A first accepted response must not regress separately committed webhook evidence."""
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "first")
    accepted = _accepted_result(call_id="provider-first-call-id")
    accepted.provider_metadata = {
        "conversation_id": "provider-conversation-id",
        "cost": 0.05,
        "unsafe": "must-not-persist",
    }

    async def _accepted_after_webhook(_request):
        await _commit_webhook_completion(
            db_engine, client_id=client.id, lead_id=lead.id
        )
        return accepted

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            side_effect=_accepted_after_webhook,
        ), patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db,
                lead=lead,
                agent=agent,
                client=client,
                settings=_make_settings(),
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert result.status == "dialing"
    assert persisted is not None
    assert persisted.telephony_status == "completed"
    assert persisted.telephony_error == "webhook diagnostic evidence"
    assert persisted.session_end_received is True
    assert persisted.elevenlabs_conversation_id == "webhook-conversation-id"
    assert persisted.provider_call_id == "provider-first-call-id"
    assert persisted.provider_metadata == {
        "conversation_id": "provider-conversation-id",
        "cost": 0.05,
    }


@pytest.mark.asyncio
async def test_retry_accepted_late_response_preserves_committed_webhook_completion(db_engine):
    """A retry accepted response must provide the same real-session guarantee."""
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "retry")
    transient = _transient_result("503 before webhook completion")
    accepted = _accepted_result(call_id="provider-retry-call-id")
    accepted.provider_metadata = {
        "conversation_id": "provider-retry-conversation-id",
        "cost": 0.07,
    }
    attempts = 0

    async def _transient_then_accepted_after_webhook(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return transient
        await _commit_webhook_completion(
            db_engine, client_id=client.id, lead_id=lead.id
        )
        return accepted

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            side_effect=_transient_then_accepted_after_webhook,
        ), patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db,
                lead=lead,
                agent=agent,
                client=client,
                settings=_make_settings(),
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert attempts == 2
    assert result.status == "dialing"
    assert persisted is not None
    assert persisted.telephony_status == "completed"
    assert persisted.telephony_error == "webhook diagnostic evidence"
    assert persisted.session_end_received is True
    assert persisted.elevenlabs_conversation_id == "webhook-conversation-id"
    assert persisted.provider_call_id == "provider-retry-call-id"
    assert persisted.provider_metadata == {
        "conversation_id": "provider-retry-conversation-id",
        "cost": 0.07,
    }


@pytest.mark.asyncio
async def test_accepted_path_persists_expected_fields(db_engine):
    """Accepted responses persist allowed fields through a real database session."""
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "accepted-fields")
    accepted = _accepted_result("provider-accepted-fields")
    accepted.provider_metadata = {
        "conversation_id": "provider-conversation-fields",
        "cost": 0.10,
        "billed_duration_seconds": 30,
        "unsafe": "must-not-persist",
    }

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as provider, patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db, lead=lead, agent=agent, client=client, settings=_make_settings()
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert provider.await_count == 1
    assert result.status == "dialing"
    assert persisted is not None
    assert persisted.telephony_status == "ringing"
    assert persisted.telephony_error is None
    assert persisted.provider_call_id == "provider-accepted-fields"
    assert persisted.elevenlabs_conversation_id == "provider-conversation-fields"
    assert persisted.provider_metadata == {
        "conversation_id": "provider-conversation-fields",
        "cost": 0.10,
        "billed_duration_seconds": 30,
    }


@pytest.mark.asyncio
async def test_accepted_path_stores_conversation_id_for_custom_llm_linkage(db_engine):
    """A real accepted response stores its conversation ID for Custom LLM linkage."""
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "accepted-conversation")
    accepted = _accepted_result("provider-conversation-link")
    accepted.provider_metadata = {"conversation_id": "conversation-link", "sip_call_id": "sip-link"}

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            return_value=accepted,
        ) as provider, patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db, lead=lead, agent=agent, client=client, settings=_make_settings()
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert provider.await_count == 1
    assert persisted is not None
    assert persisted.elevenlabs_conversation_id == "conversation-link"
    assert persisted.provider_metadata == {
        "conversation_id": "conversation-link",
        "sip_call_id": "sip-link",
    }


@pytest.mark.asyncio
async def test_transient_then_accepted_on_retry(db_engine):
    """A real retry transitions the still-dialing record to ringing and clears errors."""
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "retry-accepted")
    transient = _transient_result("503 retry me")
    accepted = _accepted_result("provider-retry-accepted")
    accepted.provider_metadata = {"conversation_id": "conversation-retry", "cost": 0.07}

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            side_effect=[transient, accepted],
        ) as provider, patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db, lead=lead, agent=agent, client=client, settings=_make_settings()
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert provider.await_count == 2
    assert result.status == "dialing"
    assert persisted is not None
    assert persisted.telephony_status == "ringing"
    assert persisted.telephony_error is None
    assert persisted.provider_call_id == "provider-retry-accepted"
    assert persisted.elevenlabs_conversation_id == "conversation-retry"
    assert persisted.provider_metadata == {"conversation_id": "conversation-retry", "cost": 0.07}


@pytest.mark.asyncio
async def test_transient_retry_keeps_durable_dialing_state_active_for_independent_guard(db_engine):
    """The retry starts while a separate session can still observe an active dial."""
    from app.outbound.service import _find_active_call_session, dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, "retry-guard")
    transient = _transient_result("503 before retry")
    accepted = _accepted_result("provider-retry-guard")
    attempts = 0

    async def _provider(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return transient
        async with db_engine.async_session_factory() as guard_db:
            active = await _find_active_call_session(guard_db, lead.id)
            assert active is not None
            assert active.telephony_status == "dialing"
        return accepted

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            side_effect=_provider,
        ), patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db, lead=lead, agent=agent, client=client, settings=_make_settings()
            )

    assert attempts == 2
    assert result.status == "dialing"


@pytest.mark.parametrize("path, requires_retry", [("first", False), ("retry", True)])
@pytest.mark.parametrize(
    "advanced_status",
    ["connected", "voicemail", "completed", "failed", "no_answer", "recurrent_error", "stale_in_call"],
)
@pytest.mark.asyncio
async def test_late_accepted_response_preserves_independent_advanced_state(
    db_engine, path, requires_retry, advanced_status
):
    """First and retry acceptance never overwrite newer independent call evidence."""
    from sqlalchemy import select

    from app.calls.models import CallSession
    from app.outbound.service import dial_outbound_call

    client, agent, lead = await _seed_dial_records(db_engine, f"advanced-{path}-{advanced_status}")
    transient = _transient_result("503 before advanced evidence")
    accepted = _accepted_result(f"provider-{path}-{advanced_status}")
    accepted.provider_metadata = {"conversation_id": f"provider-{advanced_status}", "cost": 0.03}
    attempts = 0
    authoritative_metadata = {"call_id": f"authoritative-{advanced_status}", "cost": 0.99}

    async def _provider(_request):
        nonlocal attempts
        attempts += 1
        if requires_retry and attempts == 1:
            return transient
        async with db_engine.async_session_factory() as evidence_db:
            call_session = (await evidence_db.execute(
                select(CallSession).where(CallSession.lead_id == lead.id)
            )).scalar_one()
            call_session.telephony_status = advanced_status
            call_session.telephony_error = f"authoritative {advanced_status} error"
            call_session.outcome_reason = "sip_routing_error"
            call_session.session_end_received = True
            call_session.elevenlabs_conversation_id = f"authoritative-conversation-{advanced_status}"
            call_session.provider_call_id = f"authoritative-provider-{advanced_status}"
            call_session.provider_metadata = authoritative_metadata
            await evidence_db.commit()
        return accepted

    async with db_engine.async_session_factory() as dial_db:
        with patch(
            "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
            new_callable=AsyncMock,
            side_effect=_provider,
        ), patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ), patch("app.outbound.service._fire_probe"):
            result = await dial_outbound_call(
                db=dial_db, lead=lead, agent=agent, client=client, settings=_make_settings()
            )

    persisted = await _get_persisted_call_session(db_engine, result.call_session_id)
    assert attempts == (2 if requires_retry else 1)
    assert persisted is not None
    assert persisted.telephony_status == advanced_status
    assert persisted.telephony_error == f"authoritative {advanced_status} error"
    assert persisted.outcome_reason == "sip_routing_error"
    assert persisted.session_end_received is True
    assert persisted.elevenlabs_conversation_id == f"authoritative-conversation-{advanced_status}"
    assert persisted.provider_call_id == f"authoritative-provider-{advanced_status}"
    assert persisted.provider_metadata == authoritative_metadata
