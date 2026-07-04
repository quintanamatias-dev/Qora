"""Tests for the per-lead asyncio concurrency guard in dial_outbound_call().

Review blocker CRITICAL-3:
  The original concurrent guard did a DB SELECT → CallSession INSERT without an
  asyncio-level lock. Two coroutines could both pass the SELECT (seeing no active
  session), then both proceed to create CallSessions and make provider calls.

  Fix: per-lead asyncio.Lock keyed by lead_id is acquired BEFORE the DB SELECT.
  Both the guard check and the CallSession creation happen inside the lock.

These tests use asyncio.gather() with real coroutines to exercise true concurrency
within a single asyncio event loop — the scenario where the bug bites.
"""

from __future__ import annotations

import asyncio
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


def _make_lead(lead_id: str = "lead-concurrent-lock-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Concurrent Lock Test Lead"
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


def _build_db_no_active_session():
    """DB mock that always returns no active session (guard check passes)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


def _accepted_result():
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = "el-call-concurrent"
    r.provider_metadata = {"cost": 0.05}
    r.error_detail = None
    r.error_category = None
    return r


# ---------------------------------------------------------------------------
# Test: asyncio-level lock prevents two provider calls for same lead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_lead_lock_prevents_double_provider_call():
    """GIVEN two concurrent dial_outbound_call() invocations for the SAME lead_id
    WHEN both are launched simultaneously with asyncio.gather()
    THEN exactly ONE ElevenLabs provider call is made — the second is blocked by the lock.

    How the lock + test work together:
      - The per-lead asyncio.Lock serializes the two coroutines.
      - Coroutine 1 acquires the lock, runs the DB guard, creates a CallSession, flushes.
      - Coroutine 2 waits at the lock. When lock is released, it re-runs the DB guard
        via _find_active_call_session inside the lock.
      - Because both coroutines share the same mock_db (shared state), the second
        query sees the 'dialing' session created by the first → returns "failed".

    NOTE: in production they share a real SQLite DB, so the second flush is visible
    to the second SELECT. In this test we share one mock_db to replicate that semantics.
    """
    from app.outbound.service import dial_outbound_call, _LEAD_LOCKS

    # Clear any residual lock state from previous tests for this lead_id
    lead_id = "lead-lock-race-TEST-001"
    _LEAD_LOCKS.pop(lead_id, None)

    provider_call_count = 0

    async def _counting_provider(request):
        nonlocal provider_call_count
        provider_call_count += 1
        await asyncio.sleep(0)  # yield — gives the event loop a chance to run second waiter
        return _accepted_result()

    # Use SHARED mock_db so the second SELECT sees the state from the first flush.
    # This mirrors production (shared SQLite connection) better than two independent mocks.
    first_call_done = False

    shared_db = AsyncMock()
    shared_db.add = MagicMock()
    shared_db.flush = AsyncMock()
    shared_db.commit = AsyncMock()

    # SELECT mock: accounts for the new query order per coroutine:
    #   1. CallSession guard (telephony_status IN {dialing, ringing, in_call})
    #   2. ScheduledCall guard (status = 'in_progress') — now runs for ALL triggers
    #
    # Coroutine 1 holds the lock:
    #   - execute #1: CallSession guard → None (no active session, C1 proceeds)
    #   - execute #2: ScheduledCall guard → None (no in_progress scheduled call, C1 proceeds)
    #   - C1 creates CallSession, flushes, calls provider, commits, releases lock
    #
    # Coroutine 2 acquires the lock:
    #   - execute #3: CallSession guard → active_mock (C1's committed session, C2 blocked)
    #   (ScheduledCall guard is not reached since C2 is already blocked)
    active_mock = MagicMock()
    active_mock.id = "call-from-first-dial"
    active_mock.telephony_status = "dialing"

    select_call_count = 0

    async def _execute_side_effect(stmt):
        nonlocal select_call_count
        select_call_count += 1
        result = MagicMock()
        if select_call_count == 1:
            # C1 — CallSession guard: no active session
            result.scalars.return_value.first.return_value = None
        elif select_call_count == 2:
            # C1 — ScheduledCall guard: no in_progress scheduled call
            result.scalars.return_value.first.return_value = None
        else:
            # C2 — CallSession guard: sees C1's committed 'dialing' session
            result.scalars.return_value.first.return_value = active_mock
        return result

    shared_db.execute.side_effect = _execute_side_effect

    from unittest.mock import patch

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        side_effect=_counting_provider,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            lead = _make_lead(lead_id=lead_id)

            r1, r2 = await asyncio.gather(
                dial_outbound_call(
                    db=shared_db,
                    lead=lead,
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
                dial_outbound_call(
                    db=shared_db,
                    lead=lead,  # same lead object, same shared_db
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
            )

    statuses = {r1.status, r2.status}
    assert "dialing" in statuses, "At least one call must succeed"
    assert "failed" in statuses, (
        "The second concurrent call must be blocked (failed) by the per-lead lock. "
        f"Got statuses: {statuses}"
    )
    assert provider_call_count == 1, (
        f"Per-lead asyncio lock must allow exactly 1 provider call. "
        f"Got {provider_call_count} provider call(s). "
        "Without the lock, both coroutines pass the DB guard and fire two provider calls."
    )


@pytest.mark.asyncio
async def test_different_leads_can_dial_concurrently():
    """GIVEN two concurrent dial_outbound_call() invocations for DIFFERENT lead_ids
    WHEN both are launched simultaneously with asyncio.gather()
    THEN BOTH succeed and BOTH make a provider call (2 total).

    Locks are per-lead — different leads must not block each other.
    """
    from app.outbound.service import dial_outbound_call

    provider_call_count = 0

    async def _counting_provider(request):
        nonlocal provider_call_count
        provider_call_count += 1
        await asyncio.sleep(0)
        return _accepted_result()

    db1 = _build_db_no_active_session()
    db2 = _build_db_no_active_session()

    from unittest.mock import patch

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        side_effect=_counting_provider,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            # Different lead_ids — should not block each other
            r1, r2 = await asyncio.gather(
                dial_outbound_call(
                    db=db1,
                    lead=_make_lead(lead_id="lead-different-A"),
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
                dial_outbound_call(
                    db=db2,
                    lead=_make_lead(lead_id="lead-different-B"),
                    agent=_make_agent(),
                    client=_make_client(),
                    settings=_make_settings(),
                ),
            )

    assert r1.status == "dialing", f"Lead A must succeed, got {r1.status}"
    assert r2.status == "dialing", f"Lead B must succeed, got {r2.status}"
    assert provider_call_count == 2, (
        f"Two different leads must each make a provider call (2 total). "
        f"Got {provider_call_count}. Per-lead locks must not cross-block different leads."
    )


@pytest.mark.asyncio
async def test_lock_is_released_after_completion():
    """GIVEN a lead was dialed and the lock was released
    WHEN a new dial attempt is made for the same lead (no active session in DB)
    THEN the new attempt succeeds (lock is not stuck/leaked).

    Proves locks are properly released even after failures.
    """
    from app.outbound.service import dial_outbound_call

    from unittest.mock import patch

    lead = _make_lead(lead_id="lead-lock-release-test")

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
            db1 = _build_db_no_active_session()
            r1 = await dial_outbound_call(
                db=db1,
                lead=lead,
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )
            # Lock should be released — second sequential call must also work
            db2 = _build_db_no_active_session()
            r2 = await dial_outbound_call(
                db=db2,
                lead=lead,
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert r1.status == "dialing", f"First call must succeed, got {r1.status}"
    assert r2.status == "dialing", (
        f"Second sequential call must succeed (lock released), got {r2.status}. "
        "Lock must not leak/remain locked after the first call completes."
    )
