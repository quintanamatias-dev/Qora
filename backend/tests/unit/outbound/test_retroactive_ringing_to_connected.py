"""Unit tests for retroactive ringing→connected transition in linkage.py.

Spec: call-state-machine — Requirement: Retroactive State Repair
  When a post-call webhook fires for a session still in 'ringing' state,
  the session MUST be retroactively moved through 'connected' before completing.

Design (linkage.py):
  If cs.telephony_status == 'ringing' when link_outbound_session_by_webhook fires,
  set telephony_status = 'connected' (retroactive — state machine fidelity),
  then set telephony_status = 'completed' (the normal webhook completion path).

Scenarios:
  1. Session in 'ringing' + post-call webhook arrives
     → intermediate 'connected' logged, final status is 'completed'
  2. Session already in 'connected' + post-call webhook arrives
     → goes directly to 'completed' (no double log)
  3. Session in 'dialing' + post-call webhook arrives
     → goes directly to 'completed' (no retroactive ringing→connected — already past ringing)
  4. Session already 'completed' + duplicate webhook
     → stays 'completed' (idempotent path)

All tests use mocked DB — no live calls, no live DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    *,
    telephony_status: str,
    elevenlabs_conversation_id: str | None = None,
    session_id: str = "session-ringing-001",
    session_end_received: bool = False,
) -> MagicMock:
    """Return a mock outbound CallSession with the given telephony state."""
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = "lead-001"
    cs.client_id = "client-001"
    cs.telephony_status = telephony_status
    cs.provider_call_id = "el-call-abc123"
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.session_end_received = session_end_received
    return cs


def _make_db(session: MagicMock) -> AsyncMock:
    """Return an async DB mock that returns `session` on first execute()."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = session
    db.execute = AsyncMock(return_value=result_mock)

    return db


def _make_db_no_match() -> AsyncMock:
    """Return an async DB mock that finds no session (returns None)."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    return db


# ---------------------------------------------------------------------------
# Scenario 1: ringing + post-call webhook → retroactive connected, final completed
# ---------------------------------------------------------------------------


class TestRetroactiveRingingToConnected:
    """Session in 'ringing' when post-call webhook fires → connected then completed."""

    @pytest.mark.asyncio
    async def test_ringing_session_gets_retroactive_connected_then_completed(self) -> None:
        """GIVEN an outbound CallSession with telephony_status='ringing'
        WHEN link_outbound_session_by_webhook() is called (post-call webhook)
        THEN telephony_status is retroactively updated to 'connected' (logged)
        AND then set to 'completed' (the final state after webhook evidence).
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_session(telephony_status="ringing", elevenlabs_conversation_id=None)
        db = _make_db(cs)

        logged_events: list[str] = []

        class FakeLogger:
            def info(self, event: str, **kwargs) -> None:
                logged_events.append(event)

            def warning(self, event: str, **kwargs) -> None:
                logged_events.append(event)

        with patch("app.outbound.linkage.logger", FakeLogger()):
            linked = await link_outbound_session_by_webhook(
                db,
                conversation_id="conv-webhook-ringing-001",
            )

        assert linked is not None, "Session must be found and returned."

        # Final state must be 'completed' — webhook evidence always closes the session
        assert linked.telephony_status == "completed", (
            "After post-call webhook, telephony_status must be 'completed'. "
            f"Got: {linked.telephony_status!r}"
        )

        # The retroactive ringing→connected transition must be logged
        assert any(
            "retroactive_ringing_to_connected" in event or "retroactive" in event
            for event in logged_events
        ), (
            "The retroactive ringing→connected transition must be logged. "
            f"Logged events: {logged_events}"
        )

        # session_end_received must be set to True (webhook evidence recorded)
        assert linked.session_end_received is True, (
            "session_end_received must be True after successful webhook linkage. "
            f"Got: {linked.session_end_received!r}"
        )

    @pytest.mark.asyncio
    async def test_ringing_session_elevenlabs_id_stored(self) -> None:
        """GIVEN ringing session with no elevenlabs_conversation_id
        WHEN post-call webhook fires with a conversation_id
        THEN elevenlabs_conversation_id is stored on the session.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_session(telephony_status="ringing", elevenlabs_conversation_id=None)
        db = _make_db(cs)

        with patch("app.outbound.linkage.logger"):
            linked = await link_outbound_session_by_webhook(
                db,
                conversation_id="conv-ringing-store-id",
            )

        assert linked is not None
        assert linked.elevenlabs_conversation_id == "conv-ringing-store-id", (
            "elevenlabs_conversation_id must be stored when the session was missing it. "
            f"Got: {linked.elevenlabs_conversation_id!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: connected + post-call webhook → completed (no retroactive log)
# ---------------------------------------------------------------------------


class TestConnectedSessionWebhook:
    """Session already in 'connected' when webhook fires — no retroactive ringing→connected."""

    @pytest.mark.asyncio
    async def test_connected_session_goes_directly_to_completed(self) -> None:
        """GIVEN telephony_status='connected'
        WHEN post-call webhook fires
        THEN telephony_status = 'completed' and NO retroactive log is emitted.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_session(
            telephony_status="connected",
            elevenlabs_conversation_id="conv-connected-001",
        )
        db = _make_db(cs)

        logged_events: list[str] = []

        class FakeLogger:
            def info(self, event: str, **kwargs) -> None:
                logged_events.append(event)

            def warning(self, event: str, **kwargs) -> None:
                logged_events.append(event)

        with patch("app.outbound.linkage.logger", FakeLogger()):
            linked = await link_outbound_session_by_webhook(
                db,
                conversation_id="conv-connected-001",
            )

        assert linked is not None
        assert linked.telephony_status == "completed", (
            "connected session must become 'completed' after webhook. "
            f"Got: {linked.telephony_status!r}"
        )

        # Must NOT emit the retroactive ringing→connected log
        assert not any("retroactive_ringing_to_connected" in e for e in logged_events), (
            "retroactive ringing→connected log must NOT fire for a 'connected' session. "
            f"Logged events: {logged_events}"
        )


# ---------------------------------------------------------------------------
# Scenario 3: dialing + post-call webhook → completed (no retroactive log)
# ---------------------------------------------------------------------------


class TestDialingSessionWebhook:
    """Session in 'dialing' state when webhook fires — no retroactive ringing→connected."""

    @pytest.mark.asyncio
    async def test_dialing_session_goes_to_completed(self) -> None:
        """GIVEN telephony_status='dialing'
        WHEN post-call webhook fires
        THEN telephony_status = 'completed' and no retroactive log is emitted.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_session(
            telephony_status="dialing",
            elevenlabs_conversation_id=None,
        )
        db = _make_db(cs)

        logged_events: list[str] = []

        class FakeLogger:
            def info(self, event: str, **kwargs) -> None:
                logged_events.append(event)

            def warning(self, event: str, **kwargs) -> None:
                logged_events.append(event)

        with patch("app.outbound.linkage.logger", FakeLogger()):
            linked = await link_outbound_session_by_webhook(
                db,
                conversation_id="conv-dialing-001",
            )

        assert linked is not None
        assert linked.telephony_status == "completed", (
            "dialing session must become 'completed' after webhook. "
            f"Got: {linked.telephony_status!r}"
        )

        assert not any("retroactive_ringing_to_connected" in e for e in logged_events), (
            "retroactive ringing→connected log must NOT fire for a 'dialing' session. "
            f"Logged events: {logged_events}"
        )


# ---------------------------------------------------------------------------
# Scenario 4: already completed + duplicate webhook → idempotent
# ---------------------------------------------------------------------------


class TestAlreadyCompletedIdempotent:
    """Session already in 'completed' — duplicate webhook must be idempotent."""

    @pytest.mark.asyncio
    async def test_already_completed_stays_completed(self) -> None:
        """GIVEN telephony_status='completed'
        WHEN a duplicate post-call webhook fires
        THEN telephony_status stays 'completed' — no re-mutation.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_session(
            telephony_status="completed",
            elevenlabs_conversation_id="conv-already-done",
        )
        db = _make_db(cs)

        logged_events: list[str] = []

        class FakeLogger:
            def info(self, event: str, **kwargs) -> None:
                logged_events.append(event)

            def warning(self, event: str, **kwargs) -> None:
                logged_events.append(event)

        with patch("app.outbound.linkage.logger", FakeLogger()):
            linked = await link_outbound_session_by_webhook(
                db,
                conversation_id="conv-already-done",
            )

        assert linked is not None
        assert linked.telephony_status == "completed", (
            "Already-completed session must stay 'completed' on duplicate webhook. "
            f"Got: {linked.telephony_status!r}"
        )

        # Idempotent path must be logged
        assert any("idempotent" in e for e in logged_events), (
            "Duplicate webhook on already-completed session must log idempotency. "
            f"Logged events: {logged_events}"
        )

        # commit must NOT be called (idempotent — no re-mutation)
        db.commit.assert_not_called()
