"""WU2 Task 3.3 — Timeout reconciliation sweep for stale in_call/ringing/dialing sessions.

Spec: outbound-call-trigger — Design: Reconciliation Sweep (in_call timeout)
  Background task: query CallSessions with telephony_status=in_call older than 30 minutes.
  - If matching webhook evidence exists (elevenlabs_conversation_id set): mark 'completed'.
  - If not: mark 'stale_in_call' and log for operator review.
  - Prevents calls stuck in 'in_call' forever if webhook never arrives.

Spec: FAS-Safe Semantics
  - stale_in_call remains distinct from 'no_answer' for operator triage.
  - Operator decides what to do with stale_in_call sessions.
  - NEVER auto-transition stale_in_call → completed without webhook evidence.

Design decisions:
  - 30-minute ceiling (matches design.md: "30-min ceiling via background reconciliation sweep")
  - Sweep looks at: dialing, ringing, in_call — all stale outbound statuses
  - Webhook evidence = elevenlabs_conversation_id is NOT NULL (conversation started)
  - sweep_stale_outbound_sessions() returns count of transitioned sessions

TDD: Tests written BEFORE implementation.
All tests must fail (RED) until sweep_stale_outbound_sessions is implemented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_outbound_session(
    session_id: str = "session-stale-001",
    telephony_status: str = "connected",  # 'in_call' renamed to 'connected' (call-state-machine)
    started_at: datetime | None = None,
    elevenlabs_conversation_id: str | None = None,
    session_end_received: bool = False,
) -> MagicMock:
    """Return a mock stale outbound CallSession.

    session_end_received defaults to False (no session-end webhook).
    Tests that expect 'stale_in_call' outcome must not set this to True.
    Tests that expect 'completed' outcome must set session_end_received=True.
    """
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = "lead-001"
    cs.client_id = "client-001"
    cs.telephony_status = telephony_status
    cs.provider_call_id = "el-call-stale"
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.started_at = started_at or (_utcnow() - timedelta(minutes=45))
    # Explicitly set session_end_received so bool() is predictable.
    # MagicMock attributes are truthy by default — must be explicit.
    cs.session_end_received = session_end_received
    return cs


def _make_db_with_sessions(sessions: list) -> AsyncMock:
    """Return a mock DB that yields the given sessions on execute."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = sessions
    db.execute.return_value = result_mock
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Task 3.3 RED Tests
# ---------------------------------------------------------------------------


class TestStaleSweepNoWebhook:
    """Sessions older than 30 min with no webhook evidence → stale_in_call."""

    @pytest.mark.asyncio
    async def test_stale_in_call_no_webhook_becomes_stale_in_call(self):
        """in_call session older than 30 min with no webhook → stale_in_call.

        GIVEN a CallSession with telephony_status='in_call'
              and started_at more than 30 minutes ago
              and elevenlabs_conversation_id is None (no webhook evidence)
        WHEN sweep_stale_outbound_sessions() runs
        THEN telephony_status becomes 'stale_in_call'
        AND NOT 'completed' (no webhook evidence = no completed)
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id=None,
        )
        db = _make_db_with_sessions([stale])

        count = await sweep_stale_outbound_sessions(db)

        assert count == 1, f"Expected 1 session swept, got {count}"
        assert stale.telephony_status == "stale_in_call", (
            "in_call session with no webhook evidence must become stale_in_call. "
            f"Got: {stale.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_stale_in_call_never_becomes_completed_without_webhook(self):
        """Stale in_call without webhook evidence must NOT transition to completed.

        FAS constraint: completed requires webhook evidence only.
        The sweep MUST NOT set telephony_status='completed' without
        elevenlabs_conversation_id being set.
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=60),
            elevenlabs_conversation_id=None,
        )
        db = _make_db_with_sessions([stale])

        await sweep_stale_outbound_sessions(db)

        assert stale.telephony_status != "completed", (
            "FAS violation: sweep must NEVER set telephony_status='completed' "
            "without webhook evidence (elevenlabs_conversation_id). "
            f"Got: {stale.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_stale_ringing_also_swept(self):
        """ringing session older than 30 min → stale_in_call (no answer from provider).

        Design: Sweep covers all active telephony statuses stuck >30 min:
        dialing, ringing, in_call.
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="ringing",
            started_at=_utcnow() - timedelta(minutes=35),
            elevenlabs_conversation_id=None,
        )
        db = _make_db_with_sessions([stale])

        count = await sweep_stale_outbound_sessions(db)

        assert count == 1
        assert stale.telephony_status == "stale_in_call", (
            "ringing session with no webhook evidence must also become stale_in_call. "
            f"Got: {stale.telephony_status!r}"
        )


class TestStaleSweepWithWebhookEvidence:
    """Sessions with session_end_received=True → completed."""

    @pytest.mark.asyncio
    async def test_stale_in_call_with_session_end_becomes_completed(self):
        """in_call session with session_end_received=True → completed.

        GIVEN a CallSession with telephony_status='in_call'
              and session_end_received=True (session-end webhook confirmed)
              and started_at more than 30 minutes ago
        WHEN sweep_stale_outbound_sessions() runs
        THEN telephony_status becomes 'completed'
        (session_end_received=True is the canonical completion evidence — WU2 Fix B4)
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id="conv-el-evidence-exists",
            session_end_received=True,  # session-end webhook confirmed
        )
        db = _make_db_with_sessions([stale])

        count = await sweep_stale_outbound_sessions(db)

        assert count == 1
        assert stale.telephony_status == "completed", (
            "in_call session WITH session_end_received=True must become 'completed'. "
            f"Got: {stale.telephony_status!r}"
        )


class TestStaleSweepBoundaryConditions:
    """Sessions within the 30-min window must NOT be swept."""

    @pytest.mark.asyncio
    async def test_recent_in_call_not_swept(self):
        """in_call session started less than 30 min ago is NOT swept.

        GIVEN a CallSession with telephony_status='in_call'
              and started_at LESS THAN 30 minutes ago
        WHEN sweep_stale_outbound_sessions() runs
        THEN the session is NOT modified
        AND count returned is 0
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        # The sweep query should exclude recent sessions — simulate by
        # having the DB return an empty list (as the real query would)
        db = _make_db_with_sessions([])  # DB would filter by cutoff time

        count = await sweep_stale_outbound_sessions(db)

        assert count == 0, (
            "Recent in_call sessions must not be swept. "
            f"Expected 0, got {count}"
        )

    @pytest.mark.asyncio
    async def test_no_stale_sessions_returns_zero(self):
        """When no stale sessions exist, sweep returns 0.

        GIVEN no CallSessions with stale active telephony statuses
        WHEN sweep_stale_outbound_sessions() runs
        THEN it returns 0
        AND makes no mutations
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        db = _make_db_with_sessions([])

        count = await sweep_stale_outbound_sessions(db)

        assert count == 0
        db.commit.assert_not_called()  # no work = no commit

    @pytest.mark.asyncio
    async def test_multiple_stale_sessions_all_swept(self):
        """Multiple stale sessions are all swept in one run.

        GIVEN 3 stale outbound CallSessions (all in_call, no webhook evidence)
        WHEN sweep_stale_outbound_sessions() runs
        THEN all 3 become stale_in_call
        AND count is 3
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        sessions = [
            _make_outbound_session(
                session_id=f"session-stale-{i:03d}",
                telephony_status="connected",
                started_at=_utcnow() - timedelta(minutes=40 + i),
                elevenlabs_conversation_id=None,
            )
            for i in range(3)
        ]
        db = _make_db_with_sessions(sessions)

        count = await sweep_stale_outbound_sessions(db)

        assert count == 3, f"Expected 3, got {count}"
        for cs in sessions:
            assert cs.telephony_status == "stale_in_call", (
                f"Session {cs.id} must become stale_in_call. "
                f"Got: {cs.telephony_status!r}"
            )


class TestStaleSweepCommit:
    """Sweep must commit mutations for durability."""

    @pytest.mark.asyncio
    async def test_sweep_commits_when_sessions_swept(self):
        """sweep_stale_outbound_sessions() commits when mutations are made.

        GIVEN a stale outbound session
        WHEN sweep_stale_outbound_sessions() runs
        THEN db.commit() is called
        (Mutations must be durable — not just flushed)
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id=None,
        )
        db = _make_db_with_sessions([stale])

        await sweep_stale_outbound_sessions(db)

        assert db.commit.call_count >= 1, (
            "db.commit() must be called after sweeping stale sessions. "
            "Status updates must be durable."
        )

    @pytest.mark.asyncio
    async def test_sweep_does_not_commit_when_nothing_swept(self):
        """sweep_stale_outbound_sessions() does NOT commit when no mutations made.

        GIVEN no stale sessions
        WHEN sweep_stale_outbound_sessions() runs
        THEN db.commit() is NOT called (no unnecessary writes)
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        db = _make_db_with_sessions([])

        await sweep_stale_outbound_sessions(db)

        db.commit.assert_not_called()
