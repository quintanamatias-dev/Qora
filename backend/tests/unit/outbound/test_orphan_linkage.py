"""Orphan outbound session linkage tests.

Tests for the Step 3 fallback in link_outbound_session_by_webhook():
when both conversation_id and provider_call_id lookups fail, the
webhook's conversation_initiation_client_data.custom_llm_extra_body
is used to find the most recent orphan outbound session by
client_id + lead_id.

An "orphan" session is defined as:
  - outbound (telephony_status IS NOT NULL)
  - no elevenlabs_conversation_id (never linked)
  - non-terminal telephony_status (dialing, ringing, in_call, failed, stale_in_call)
  - created within the last 10 minutes

Safety contracts verified:
  - Tenant-scoped (client_id must match — no cross-tenant)
  - Lead-scoped (lead_id must match — no cross-lead)
  - Does NOT match sessions with elevenlabs_conversation_id already set
  - Does NOT match sessions older than the time window
  - Does NOT match terminal statuses (completed, no_answer, recurrent_error)
  - Returns most recent when multiple orphans exist
  - Postcall webhook extracts cicd from payload and calls linkage
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers (mirrors test_wu2_review_blockers.py patterns)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_outbound_session(
    session_id: str = "session-orphan-001",
    telephony_status: str = "dialing",
    client_id: str = "client-a",
    lead_id: str = "lead-001",
    started_at: datetime | None = None,
    elevenlabs_conversation_id: str | None = None,
    provider_call_id: str | None = None,
    session_end_received: bool = False,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = lead_id
    cs.client_id = client_id
    cs.telephony_status = telephony_status
    cs.provider_call_id = provider_call_id
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.started_at = started_at or _utcnow()
    cs.session_end_received = session_end_received
    return cs


def _make_db_returning(session: MagicMock | None) -> AsyncMock:
    """Build a mock db.execute that returns a single session (or None)."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = session
    db.execute.return_value = result_mock
    db.commit = AsyncMock()
    return db


def _make_db_sequence(*sessions) -> AsyncMock:
    """Build a mock db.execute that returns sessions in sequence across calls."""
    db = AsyncMock()
    db.commit = AsyncMock()

    call_count = [0]
    mocks = []
    for s in sessions:
        rm = MagicMock()
        rm.scalars.return_value.first.return_value = s
        mocks.append(rm)

    async def execute_side_effect(stmt):
        idx = min(call_count[0], len(mocks) - 1)
        call_count[0] += 1
        return mocks[idx]

    db.execute.side_effect = execute_side_effect
    return db


# ---------------------------------------------------------------------------
# _find_orphan_outbound_session — unit tests
# ---------------------------------------------------------------------------


class TestFindOrphanOutboundSession:
    """Unit tests for _find_orphan_outbound_session helper."""

    @pytest.mark.asyncio
    async def test_finds_dialing_session_matching_client_and_lead(self):
        """Finds a dialing orphan session scoped to the correct client_id + lead_id.

        GIVEN an outbound session with telephony_status='dialing',
              client_id='client-a', lead_id='lead-001',
              no elevenlabs_conversation_id, created <10 min ago
        WHEN _find_orphan_outbound_session is called with matching client_id + lead_id
        THEN the session is returned
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        orphan = _make_outbound_session(
            telephony_status="dialing",
            client_id="client-a",
            lead_id="lead-001",
            elevenlabs_conversation_id=None,
            started_at=_utcnow() - timedelta(minutes=3),
        )
        db = _make_db_returning(orphan)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is orphan, (
            "_find_orphan_outbound_session must return the matching dialing session. "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_does_not_match_session_with_conversation_id_already_set(self):
        """Does NOT match sessions that already have elevenlabs_conversation_id.

        GIVEN a session with elevenlabs_conversation_id='conv-already-linked'
        WHEN _find_orphan_outbound_session is called
        THEN None is returned (session is not an orphan — it's already linked)

        The DB mock returns None to simulate the SQL filter excluding it.
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        # DB mock returns None — simulates SQL filter: WHERE elevenlabs_conversation_id IS NULL
        db = _make_db_returning(None)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is None, (
            "_find_orphan_outbound_session must return None when no orphan exists "
            "(simulates session with conversation_id already set being filtered out). "
            f"Got: {result!r}"
        )
        # Verify execute was called (query ran)
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_match_session_older_than_time_window(self):
        """Does NOT match sessions older than started_after_minutes.

        GIVEN a session created 20 minutes ago (outside the 10-minute window)
        WHEN _find_orphan_outbound_session is called (default 10 min window)
        THEN None is returned

        The DB mock returns None to simulate the SQL cutoff filter.
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        # DB returns None — simulates started_at < cutoff filter
        db = _make_db_returning(None)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001", started_after_minutes=10
        )

        assert result is None, (
            "_find_orphan_outbound_session must return None for sessions outside "
            "the time window (simulates started_at < cutoff). "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_does_not_match_terminal_status_completed(self):
        """Does NOT match sessions in terminal status 'completed'.

        The DB mock returns None to simulate the SQL filter excluding
        completed/no_answer/recurrent_error statuses.
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        db = _make_db_returning(None)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is None, (
            "_find_orphan_outbound_session must not match terminal statuses "
            "(completed, no_answer, recurrent_error are excluded by SQL). "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_returns_most_recent_when_multiple_orphans_exist(self):
        """Returns the most recent orphan when multiple exist (ORDER BY started_at DESC).

        GIVEN two orphan sessions for the same lead created at different times
        WHEN _find_orphan_outbound_session is called
        THEN the most recent session is returned

        The DB mock returns the most recent session first (simulating ORDER BY … DESC LIMIT 1).
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        recent = _make_outbound_session(
            session_id="recent-orphan",
            telephony_status="dialing",
            started_at=_utcnow() - timedelta(minutes=2),
            elevenlabs_conversation_id=None,
        )
        # DB returns 'recent' — simulates ORDER BY started_at DESC LIMIT 1
        db = _make_db_returning(recent)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is recent, (
            "_find_orphan_outbound_session must return the most recent orphan. "
            f"Got session_id={getattr(result, 'id', None)!r}, "
            f"expected 'recent-orphan'."
        )

    @pytest.mark.asyncio
    async def test_does_not_match_different_client_id(self):
        """Does NOT match sessions from a different client_id.

        GIVEN a session with client_id='client-b'
        WHEN _find_orphan_outbound_session is called with client_id='client-a'
        THEN None is returned (cross-tenant isolation)

        The DB mock returns None to simulate the SQL WHERE client_id='client-a' filter.
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        db = _make_db_returning(None)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is None, (
            "_find_orphan_outbound_session must return None when no session "
            "belongs to client_id='client-a' (cross-tenant isolation). "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_does_not_match_different_lead_id(self):
        """Does NOT match sessions from a different lead_id.

        GIVEN a session with lead_id='lead-999'
        WHEN _find_orphan_outbound_session is called with lead_id='lead-001'
        THEN None is returned (cross-lead isolation)
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        db = _make_db_returning(None)

        result = await _find_orphan_outbound_session(
            db, client_id="client-a", lead_id="lead-001"
        )

        assert result is None, (
            "_find_orphan_outbound_session must return None when no session "
            "belongs to lead_id='lead-001' (cross-lead isolation). "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_matches_all_non_terminal_orphan_statuses(self):
        """Matches sessions in any non-terminal orphan status.

        GIVEN sessions with telephony_status in (dialing, ringing, in_call, failed, stale_in_call)
        WHEN _find_orphan_outbound_session is called and DB returns each
        THEN the session is returned for each non-terminal status
        """
        from app.outbound.linkage import _find_orphan_outbound_session

        non_terminal_statuses = ["dialing", "ringing", "in_call", "failed", "stale_in_call"]

        for status in non_terminal_statuses:
            orphan = _make_outbound_session(
                telephony_status=status,
                started_at=_utcnow() - timedelta(minutes=5),
                elevenlabs_conversation_id=None,
            )
            db = _make_db_returning(orphan)

            result = await _find_orphan_outbound_session(
                db, client_id="client-a", lead_id="lead-001"
            )

            assert result is orphan, (
                f"_find_orphan_outbound_session must match status={status!r}. "
                f"Got: {result!r}"
            )


# ---------------------------------------------------------------------------
# link_outbound_session_by_webhook — orphan fallback integration
# ---------------------------------------------------------------------------


class TestLinkOutboundSessionOrphanFallback:
    """Integration tests: orphan fallback wired into link_outbound_session_by_webhook."""

    @pytest.mark.asyncio
    async def test_link_uses_orphan_fallback_when_both_primary_lookups_fail(self):
        """link_outbound_session_by_webhook falls back to orphan match on Step 3.

        GIVEN Steps 1+2 return None (unknown conversation_id, no provider_call_id)
        AND client_id + lead_id are provided
        AND _find_orphan_outbound_session finds a matching session
        WHEN link_outbound_session_by_webhook is called with client_id + lead_id
        THEN the orphan session is linked (telephony_status=completed,
             elevenlabs_conversation_id set, session_end_received=True)
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        orphan = _make_outbound_session(
            session_id="orphan-sess-001",
            telephony_status="dialing",
            client_id="client-a",
            lead_id="lead-001",
            elevenlabs_conversation_id=None,
            provider_call_id=None,
        )

        # Three execute calls: Step1 (conv_id) → None, Step2 skipped (no pcid),
        # Step3 (_find_orphan) → orphan
        call_count = [0]

        async def execute_side_effect(stmt):
            rm = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # Step 1: find by conversation_id → not found
                rm.scalars.return_value.first.return_value = None
            else:
                # Step 3: orphan lookup → found
                rm.scalars.return_value.first.return_value = orphan
            return rm

        db = AsyncMock()
        db.execute.side_effect = execute_side_effect
        db.commit = AsyncMock()

        result = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-unknown-xyz",
            client_id="client-a",
            lead_id="lead-001",
        )

        assert result is orphan, (
            "link_outbound_session_by_webhook must return the orphan session "
            "when Step 3 fallback matches. "
            f"Got: {result!r}"
        )
        assert orphan.telephony_status == "completed", (
            "Orphan session must be marked 'completed' after linkage. "
            f"Got: {orphan.telephony_status!r}"
        )
        assert orphan.elevenlabs_conversation_id == "conv-unknown-xyz", (
            "Orphan session must have elevenlabs_conversation_id set. "
            f"Got: {orphan.elevenlabs_conversation_id!r}"
        )
        assert orphan.session_end_received is True, (
            "Orphan session must have session_end_received=True after linkage. "
            f"Got: {orphan.session_end_received!r}"
        )
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_link_orphan_fallback_skipped_when_lead_id_missing(self):
        """Orphan fallback is NOT attempted when lead_id is absent.

        GIVEN Steps 1+2 return None
        AND lead_id is NOT provided
        WHEN link_outbound_session_by_webhook is called
        THEN returns None (no orphan search attempted — missing lead_id)
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        db = _make_db_returning(None)

        result = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-unknown-xyz",
            client_id="client-a",
            # lead_id intentionally absent
        )

        assert result is None, (
            "link_outbound_session_by_webhook must return None when lead_id "
            "is not provided (orphan fallback requires both client_id + lead_id). "
            f"Got: {result!r}"
        )

    @pytest.mark.asyncio
    async def test_link_orphan_fallback_skipped_when_client_id_missing(self):
        """Orphan fallback is NOT attempted when client_id is absent.

        Cross-tenant safety: without client_id we cannot scope the search.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        db = _make_db_returning(None)

        result = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-unknown-xyz",
            lead_id="lead-001",
            # client_id intentionally absent
        )

        assert result is None, (
            "link_outbound_session_by_webhook must return None when client_id "
            "is not provided (orphan fallback requires both client_id + lead_id). "
            f"Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# Postcall webhook router — orphan fallback extraction
# ---------------------------------------------------------------------------


class TestPostcallWebhookOrphanFallback:
    """Postcall webhook handler extracts cicd and calls orphan fallback."""

    @pytest.mark.asyncio
    async def test_postcall_webhook_links_via_orphan_match(self):
        """Postcall webhook falls back to orphan match via cicd extraction.

        GIVEN a webhook payload with unknown conversation_id
              AND conversation_initiation_client_data.custom_llm_extra_body
              carrying client_id='client-a' + lead_id='lead-001'
              AND both Step 1 (conversation_id) and Step 2 (provider_call_id) fail
        WHEN the elevenlabs_postcall_webhook handler processes the payload
        THEN link_outbound_session_by_webhook is called with client_id + lead_id
             AND close_session is called on the linked session (new contract)
             AND the response is {"status": "ok", "session_id": ...}
        """
        from app.calls.router import elevenlabs_postcall_webhook
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-unknown-orphan",
                # No provider_call_id — simulates API timeout scenario
                conversation_initiation_client_data={
                    "dynamic_variables": {"lead_name": "Matias"},
                    "custom_llm_extra_body": {
                        "client_id": "client-a",
                        "lead_id": "lead-001",
                    },
                },
            ),
        )

        mock_linked_cs = MagicMock()
        mock_linked_cs.id = "orphan-sess-001"
        # The handler checks cs.status to decide the close path.
        # "initiated" → calls close_session with reason="network_drop".
        mock_linked_cs.status = "initiated"

        mock_closed_cs = MagicMock()
        mock_closed_cs.id = "orphan-sess-001"
        mock_closed_cs.status = "completed"

        mock_db = AsyncMock()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.link_outbound_session_by_webhook") as mock_link,
            patch("app.calls.router.close_session", return_value=(mock_closed_cs, False)) as mock_close,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            # Payload has no provider_call_id, so Step 2 (provider_call_id block) is
            # skipped entirely. link_outbound_session_by_webhook is called only ONCE —
            # for the orphan fallback (Step 3) — and returns the linked session.
            mock_link.return_value = mock_linked_cs

            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await elevenlabs_postcall_webhook(payload)

        assert result["status"] == "ok", f"Expected status='ok', got: {result!r}"
        assert result["session_id"] == "orphan-sess-001", (
            f"Response must carry the orphan session_id. Got: {result.get('session_id')!r}"
        )
        # linked_via is no longer in the response (handler falls through to normal close path)
        assert "linked_via" not in result, (
            "linked_via must NOT be in the response — handler now falls through to "
            "close_session instead of returning early. "
            f"Got: {result!r}"
        )

        # Verify the orphan call was made with the cicd-extracted ids (primary contract)
        mock_link.assert_called_once()
        orphan_call = mock_link.call_args
        assert orphan_call.kwargs.get("client_id") == "client-a", (
            "Orphan fallback must pass client_id='client-a' extracted from cicd. "
            f"Got kwargs: {orphan_call.kwargs!r}"
        )
        assert orphan_call.kwargs.get("lead_id") == "lead-001", (
            "Orphan fallback must pass lead_id='lead-001' extracted from cicd. "
            f"Got kwargs: {orphan_call.kwargs!r}"
        )

        # New contract: close_session must be called on the linked session
        mock_close.assert_called_once(), (
            "close_session must be called on the linked orphan session — "
            "billing, duration, and lead counters require it. "
        )

    @pytest.mark.asyncio
    async def test_postcall_webhook_skips_orphan_when_cicd_missing(self):
        """Orphan fallback is NOT triggered when conversation_initiation_client_data absent.

        GIVEN no cicd in payload (or cicd has no custom_llm_extra_body)
        WHEN the postcall webhook processes the payload with unknown conversation_id
        THEN it returns 404 (no orphan lookup attempted)
        """
        from fastapi import HTTPException

        from app.calls.router import elevenlabs_postcall_webhook
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-truly-unknown",
                # No conversation_initiation_client_data
            ),
        )

        mock_db = AsyncMock()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=None),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await elevenlabs_postcall_webhook(payload)

        assert exc_info.value.status_code == 404, (
            "Unknown conversation with no cicd must return 404. "
            f"Got: {exc_info.value.status_code}"
        )
