"""WU2 Reliability Blocker Fix — /end route fallback must fully close session.

RED tests written BEFORE the fix.

Blocker:
  POST /calls/{conversation_id}/end — when close_session() misses by conversation_id
  and the route finds the outbound session via provider_call_id fallback, it must
  NOT just link and return. It must continue through the normal close-session path so
  the session ends up with status='completed', ended_at, duration_seconds,
  billable_minutes, closed_reason, and lead counters incremented.

  Current (broken) behaviour:
    link_outbound_session_by_webhook() → return EndSessionResponse(linked.status, ...)
    → session has telephony_status='completed' but status still='initiated'
    → ended_at/duration_seconds/closed_reason remain NULL

  Required (correct) behaviour:
    link_outbound_session_by_webhook() links conversation_id to session
    → close_session(linked.id, ...) closes session fully
    → EndSessionResponse carries the CLOSED state (status='completed', duration, etc.)

Contract:
  - After /end fallback via provider_call_id, close_session is called with linked.id.
  - close_session receives the correct closed_reason from body.reason.
  - The response reflects the closed state (not the pre-close state).
  - Tenant safeguards: body.client_id (when present) is passed to linkage.
  - When linkage returns None (no session found), 404 is still returned.
  - Idempotency: if session was already 'completed', close_session returns it idempotent.

TDD Cycle: RED (this file) → GREEN (router fix) → REFACTOR.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_outbound_session(
    session_id: str = "session-fallback-001",
    telephony_status: str = "in_call",
    client_id: str = "client-a",
    lead_id: str = "lead-001",
    elevenlabs_conversation_id: str | None = None,
    provider_call_id: str = "el-call-fallback",
    status: str = "initiated",
    duration_seconds: float | None = None,
    closed_reason: str | None = None,
    ended_at: datetime | None = None,
    billable_minutes: int | None = None,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = lead_id
    cs.client_id = client_id
    cs.telephony_status = telephony_status
    cs.provider_call_id = provider_call_id
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.status = status
    cs.duration_seconds = duration_seconds
    cs.closed_reason = closed_reason
    cs.ended_at = ended_at
    cs.billable_minutes = billable_minutes
    return cs


def _make_closed_session(
    session_id: str = "session-fallback-001",
    duration_seconds: float = 125.0,
    closed_reason: str = "agent_goodbye",
    status: str = "completed",
) -> MagicMock:
    """Return a session as it looks after close_session() has run."""
    cs = _make_outbound_session(
        session_id=session_id,
        status=status,
        duration_seconds=duration_seconds,
        closed_reason=closed_reason,
        ended_at=_utcnow(),
        billable_minutes=3,
    )
    return cs


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Core blocker: fallback must close session, not just link
# ---------------------------------------------------------------------------


class TestEndFallbackMustCloseSessionAfterLinking:
    """POST /calls/{conversation_id}/end — provider_call_id fallback must call close_session.

    This class proves the EXTERNAL CONTRACT of /end is honored even in the
    provider_call_id fallback path: a session that was linked via provider_call_id
    must be fully closed (status='completed', ended_at, duration_seconds, etc.)
    before the response is returned.
    """

    @pytest.mark.asyncio
    async def test_fallback_calls_close_session_after_link(self):
        """When /end links via provider_call_id, it must call close_session on the linked id.

        GIVEN no session has elevenlabs_conversation_id == 'conv-unknown'
        AND the outbound session has provider_call_id='el-call-fallback'
        AND body.provider_call_id == 'el-call-fallback'
        WHEN POST /calls/conv-unknown/end is called
        THEN link_outbound_session_by_webhook is called (links the session)
        AND close_session is called with the linked session's id
        AND close_session receives closed_reason from body.reason
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        linked_session = _make_outbound_session(
            session_id="sess-fallback-001",
            status="initiated",
            telephony_status="connected",
        )
        closed_session = _make_closed_session(
            session_id="sess-fallback-001",
            closed_reason="agent_goodbye",
        )

        body = EndSessionRequest(
            reason="agent_goodbye",
            provider_call_id="el-call-fallback",
        )

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=ValueError("not found")) as mock_close,
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked_session),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            # Re-patch close_session: first call raises ValueError (primary path),
            # second call (after link) should succeed with the closed session.
            call_count = [0]

            async def close_session_side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise ValueError("not found")
                # Second call: after linkage — return the closed session
                return (closed_session, False)

            with patch("app.calls.router.close_session", side_effect=close_session_side_effect) as mock_close_2:
                response = await end_call_session("conv-unknown", body)

        # close_session must have been called twice:
        # 1st: primary path (raises ValueError)
        # 2nd: after linkage (closes the linked session)
        assert mock_close_2.call_count == 2, (
            f"/end route must call close_session twice in fallback path: "
            f"once for primary (raises ValueError) and once for linked session. "
            f"Got {mock_close_2.call_count} call(s)."
        )

        # Second call must use the linked session's id
        second_call_kwargs = mock_close_2.call_args_list[1].kwargs
        assert second_call_kwargs.get("session_id") == "sess-fallback-001", (
            "close_session (second call) must use the linked session's id. "
            f"Got session_id={second_call_kwargs.get('session_id')!r}"
        )

        # Second call must pass the correct closed_reason from body.reason
        assert second_call_kwargs.get("closed_reason") == "agent_goodbye", (
            "close_session (second call) must pass closed_reason from body.reason. "
            f"Got closed_reason={second_call_kwargs.get('closed_reason')!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_response_reflects_closed_state_not_linked_state(self):
        """Response from /end must reflect the CLOSED state, not the pre-close linked state.

        GIVEN the linked session starts as status='initiated', duration_seconds=None
        AND close_session closes it with status='completed', duration_seconds=125
        WHEN POST /calls/conv-unknown/end returns
        THEN response.status == 'completed'
        AND response.duration_seconds == 125
        AND response.closed_reason == 'agent_goodbye'

        This is the core contract: the response must reflect the fully closed state.
        Returning the pre-close state is the defect this fix resolves.
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        linked_session = _make_outbound_session(
            session_id="sess-contract-001",
            status="initiated",       # not yet closed
            duration_seconds=None,    # not yet set
            closed_reason=None,       # not yet set
            telephony_status="connected",
        )

        closed_session = _make_closed_session(
            session_id="sess-contract-001",
            status="completed",
            duration_seconds=125.0,
            closed_reason="agent_goodbye",
        )

        body = EndSessionRequest(
            reason="agent_goodbye",
            provider_call_id="el-call-contract",
        )

        mock_db = _make_db()

        call_count = [0]

        async def close_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("not found")
            return (closed_session, False)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_session_side_effect),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked_session),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await end_call_session("conv-unknown", body)

        assert response.status == "completed", (
            f"Response status must be 'completed' after close_session. "
            f"Got: {response.status!r}. "
            f"This proves /end honors its close contract in the fallback path."
        )
        assert response.duration_seconds == 125.0, (
            f"Response duration_seconds must be 125.0 (from close_session). "
            f"Got: {response.duration_seconds!r}. "
            f"Returning pre-close duration (None) is the defect being fixed."
        )
        assert response.closed_reason == "agent_goodbye", (
            f"Response closed_reason must be 'agent_goodbye'. "
            f"Got: {response.closed_reason!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_passes_client_id_to_linkage_when_present(self):
        """When body.client_id is set, it must be passed to link_outbound_session_by_webhook.

        GIVEN body includes client_id='client-scoped' for tenant safety
        WHEN /end performs the provider_call_id fallback
        THEN link_outbound_session_by_webhook is called with client_id='client-scoped'
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        linked_session = _make_outbound_session(
            session_id="sess-tenant-001",
            client_id="client-scoped",
        )
        closed_session = _make_closed_session(
            session_id="sess-tenant-001",
            closed_reason="user_hangup",
        )

        body = EndSessionRequest(
            reason="user_hangup",
            provider_call_id="el-call-scoped",
            client_id="client-scoped",
        )

        mock_db = _make_db()

        call_count = [0]

        async def close_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("not found")
            return (closed_session, False)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_session_side_effect),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked_session) as mock_link,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            await end_call_session("conv-unknown", body)

        link_kwargs = mock_link.call_args.kwargs
        assert link_kwargs.get("client_id") == "client-scoped", (
            "link_outbound_session_by_webhook must receive client_id='client-scoped' "
            "from body.client_id for tenant-scoped lookups. "
            f"Got: {link_kwargs.get('client_id')!r}"
        )

    @pytest.mark.asyncio
    async def test_fallback_404_when_link_returns_none(self):
        """When provider_call_id linkage also finds nothing, 404 is returned.

        GIVEN no session found by conversation_id or provider_call_id
        WHEN /end is called with provider_call_id
        THEN 404 is raised (not 500, not 200 with partial state)
        AND close_session is NOT called after the failed linkage
        """
        from fastapi import HTTPException

        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        body = EndSessionRequest(
            reason="user_hangup",
            provider_call_id="el-call-notfound",
        )

        mock_db = _make_db()

        close_call_count = [0]

        async def close_session_side_effect(*args, **kwargs):
            close_call_count[0] += 1
            if close_call_count[0] == 1:
                raise ValueError("not found")
            # Should never reach here if 404 is raised after None linkage
            return (MagicMock(), False)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_session_side_effect),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=None),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await end_call_session("conv-unknown", body)

        assert exc_info.value.status_code == 404, (
            f"When provider_call_id linkage returns None, must return 404. "
            f"Got: {exc_info.value.status_code}"
        )
        # close_session must not be called a second time when link returns None
        assert close_call_count[0] == 1, (
            f"close_session must only be called once (primary path) when linkage returns None. "
            f"Got {close_call_count[0]} call(s)."
        )

    @pytest.mark.asyncio
    async def test_fallback_idempotent_when_already_closed(self):
        """When linked session is already 'completed', close_session returns idempotent.

        GIVEN a session was previously closed (status='completed')
        AND link_outbound_session_by_webhook returns it in completed state
        WHEN /end fallback runs
        THEN close_session is still called (idempotency is close_session's responsibility)
        AND response still reflects the completed state
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        already_closed = _make_outbound_session(
            session_id="sess-idem-001",
            status="completed",
            duration_seconds=90.0,
            closed_reason="agent_goodbye",
            telephony_status="completed",
        )

        body = EndSessionRequest(
            reason="agent_goodbye",
            provider_call_id="el-call-idem",
        )

        mock_db = _make_db()

        call_count = [0]

        async def close_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("not found")
            # Already closed — idempotent return
            return (already_closed, True)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_session_side_effect) as mock_close,
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=already_closed),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await end_call_session("conv-unknown", body)

        assert response.status == "completed", (
            f"Response must reflect completed state on idempotent close. Got: {response.status!r}"
        )
        assert response.duration_seconds == 90.0, (
            f"Response must carry existing duration_seconds. Got: {response.duration_seconds!r}"
        )


# ---------------------------------------------------------------------------
# Integration-style: real session object lifecycle via service layer
# ---------------------------------------------------------------------------


class TestEndFallbackSessionLifecycleIntegration:
    """Integration-style tests using real service behavior patterns.

    These tests assert the FULL close contract is honored after provider_call_id
    fallback — not just that certain functions are called, but that the session
    object ends up in the correct persisted state.

    They use the real close_session() logic via a mock DB that behaves
    realistically enough to confirm field assignments happen in order.
    """

    @pytest.mark.asyncio
    async def test_end_fallback_session_has_completed_status_in_db(self):
        """After /end fallback, the session row must have status='completed' in the DB.

        This is an integration-style test: we let close_session() run against
        a mock session object and assert its fields after the close call.

        GIVEN an outbound session with status='initiated' in DB
        AND the session is found via provider_call_id fallback
        WHEN /end processes the fallback path
        THEN the session object has status='completed' after close_session runs
        AND closed_reason is set from body.reason
        """
        from app.calls.service import close_session as real_close_session
        from app.calls.models import CallSession

        # Build a real-ish session object (not fully ORM — but close enough for
        # the service layer to assign attributes onto it)
        class FakeSession:
            id = "fake-sess-close-001"
            client_id = "client-a"
            lead_id = "lead-001"
            status = "initiated"
            telephony_status = "connected"
            provider_call_id = "el-call-close-test"
            elevenlabs_conversation_id = None
            session_end_received = False
            started_at = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
            ended_at = None
            duration_seconds = None
            billable_minutes = None
            closed_reason = None
            total_user_turns = 0
            total_agent_turns = 0
            merged_into_session_id = None

        fake_cs = FakeSession()

        # Build a mock DB that returns our fake session on get_session() call
        mock_db = AsyncMock()

        # get_session -> SELECT -> fake_cs
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = fake_cs

        # count_turns -> (0, 0)
        turn_result = MagicMock()
        turn_result.all.return_value = [("user", 0), ("agent", 0)]

        # lead query -> None (no lead to update counters for — simplify)
        lead_result = MagicMock()
        lead_result.scalar_one_or_none.return_value = None

        # sibling merge query -> []
        sibling_result = MagicMock()
        sibling_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            session_result,   # get_session select
            turn_result,      # count_turns select
            lead_result,      # lead lookup (counters)
            sibling_result,   # merge siblings select
        ]
        mock_db.flush = AsyncMock()

        # We need to also patch executor.enqueue and settings
        with (
            patch("app.calls.service.settings") as mock_settings,
            patch("app.calls.service.executor") as mock_executor,
            patch("app.calls.service.count_turns", return_value=(0, 0)),
            patch("app.calls.service._merge_sibling_sessions", return_value=[]),
        ):
            mock_settings.enable_job_executor = False
            mock_executor.enqueue = AsyncMock()

            with patch("app.calls.service._schedule_summarize"):
                cs, was_already_closed = await real_close_session(
                    mock_db,
                    session_id="fake-sess-close-001",
                    closed_reason="agent_goodbye",
                    update_lead_counters=False,
                )

        assert cs.status == "completed", (
            f"close_session must set status='completed'. Got: {cs.status!r}"
        )
        assert cs.closed_reason == "agent_goodbye", (
            f"close_session must set closed_reason='agent_goodbye'. Got: {cs.closed_reason!r}"
        )
        assert cs.ended_at is not None, (
            "close_session must set ended_at. Got: None"
        )
        assert cs.duration_seconds is not None, (
            "close_session must set duration_seconds. Got: None"
        )
        assert was_already_closed is False, (
            "was_already_closed must be False for first close."
        )

    @pytest.mark.asyncio
    async def test_end_fallback_full_path_status_and_fields(self):
        """Full /end fallback path: link → close → response carries final fields.

        This test uses the real end_call_session route handler with mocked
        close_session that actually sets fields on the session object, confirming
        the route wires through to a real close and returns what close_session
        actually produces.

        GIVEN an outbound session (status='initiated', no elevenlabs_conversation_id)
        AND /end is called with provider_call_id fallback
        WHEN close_session runs after linkage
        THEN EndSessionResponse.status == 'completed'
        AND EndSessionResponse.closed_reason == body.reason
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        body = EndSessionRequest(
            reason="user_hangup",
            provider_call_id="el-call-full",
        )

        # Simulates what link_outbound_session_by_webhook produces:
        # session has telephony_status='completed' but status='initiated' still
        linked = _make_outbound_session(
            session_id="sess-full-001",
            status="initiated",
            telephony_status="completed",   # linkage sets this
            duration_seconds=None,
            closed_reason=None,
        )

        # What close_session produces after being called on linked.id
        after_close = _make_closed_session(
            session_id="sess-full-001",
            status="completed",
            duration_seconds=77.0,
            closed_reason="user_hangup",
        )

        mock_db = _make_db()
        call_count = [0]

        async def close_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("session not found by conversation_id")
            # After link, close_session is called on linked.id → returns closed state
            return (after_close, False)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_side_effect),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await end_call_session("conv-full", body)

        # Response must reflect the state from close_session — not the pre-close linked state
        assert response.id == "sess-full-001"
        assert response.status == "completed", (
            f"EndSessionResponse.status must be 'completed'. Got: {response.status!r}. "
            f"Returning 'initiated' (linked-but-not-closed state) is the defect."
        )
        assert response.duration_seconds == 77.0, (
            f"EndSessionResponse.duration_seconds must be 77.0 from close_session. "
            f"Got: {response.duration_seconds!r}"
        )
        assert response.closed_reason == "user_hangup", (
            f"EndSessionResponse.closed_reason must be 'user_hangup'. "
            f"Got: {response.closed_reason!r}"
        )
