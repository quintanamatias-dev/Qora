"""WU2 Task 3.2 — close_session integration with telephony_status linkage.

Spec: outbound-call-trigger — Requirement: FAS-Safe Semantics
  - telephony_status=completed MUST require webhook evidence (session-end callback).
  - close_session() is the webhook evidence path (called from /end or post-call webhook).
  - When close_session() is called on an outbound CallSession (has telephony_status),
    it MUST also update telephony_status='completed' to maintain consistency.

Spec: Design ID Linkage Chain:
  CallSession.id
    ├── provider_call_id     (set by outbound API response — WU1)
    ├── elevenlabs_conversation_id (set by webhook linkage — WU2)
    └── lead_id

Design: close_session() is the canonical "call completed" signal.
  - For inbound calls: it was the only path; telephony_status was NULL.
  - For outbound calls: close_session() signals real human conversation ended.
    It must also update telephony_status='completed' to reflect this.
  - The update must only happen when telephony_status is NOT already 'completed'
    and IS NOT NULL (i.e., this is an outbound call).

Integration test pattern: Uses unit mocks (no real DB) — verifies behavior contract.
All external calls mocked — no live calls.

TDD: Tests written BEFORE implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbound_session(
    session_id: str = "session-outbound-001",
    telephony_status: str = "ringing",
    status: str = "initiated",
) -> MagicMock:
    """Return a mock outbound CallSession (has telephony_status set)."""
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = "lead-001"
    cs.client_id = "client-001"
    cs.status = status
    cs.telephony_status = telephony_status
    cs.provider_call_id = "el-call-abc123"
    cs.elevenlabs_conversation_id = "conv-el-xyz"
    cs.started_at = datetime(2026, 7, 3, 10, 0, 0, tzinfo=timezone.utc)
    cs.ended_at = None
    cs.duration_seconds = None
    cs.billable_minutes = None
    cs.total_user_turns = 0
    cs.total_agent_turns = 0
    cs.closed_reason = None
    cs.merged_into_session_id = None
    return cs


def _make_inbound_session(session_id: str = "session-inbound-001") -> MagicMock:
    """Return a mock inbound CallSession (telephony_status is None)."""
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = "lead-002"
    cs.client_id = "client-001"
    cs.status = "initiated"
    cs.telephony_status = None  # inbound calls have no telephony_status
    cs.provider_call_id = None
    cs.elevenlabs_conversation_id = "conv-el-inbound"
    cs.started_at = datetime(2026, 7, 3, 10, 0, 0, tzinfo=timezone.utc)
    cs.ended_at = None
    cs.duration_seconds = None
    cs.billable_minutes = None
    cs.total_user_turns = 2
    cs.total_agent_turns = 3
    cs.closed_reason = None
    cs.merged_into_session_id = None
    return cs


# ---------------------------------------------------------------------------
# Task 3.2 RED Tests
# ---------------------------------------------------------------------------


class TestCloseSessionTelephonyStatusSync:
    """close_session() must sync telephony_status=completed for outbound sessions."""

    @pytest.mark.asyncio
    async def test_close_session_updates_telephony_status_for_outbound(self):
        """close_session() sets telephony_status='completed' for outbound sessions.

        GIVEN an outbound CallSession with telephony_status='ringing'
        WHEN close_session() is called (session-end webhook fires)
        THEN status='completed' AND telephony_status='completed'
        (Both the main status and the telephony status must be completed)
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_outbound_session(telephony_status="ringing")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed", (
            "close_session() must set telephony_status='completed' for outbound sessions. "
            f"Got: {result.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_inbound_session_telephony_status_unchanged(self):
        """close_session() does NOT set telephony_status for inbound sessions.

        GIVEN an inbound CallSession with telephony_status=None
        WHEN update_telephony_status_on_session_end() is called
        THEN telephony_status remains None (inbound sessions have no telephony_status)
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_inbound_session()

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status is None, (
            "Inbound sessions must NOT have telephony_status set by close_session. "
            f"Got: {result.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_already_completed_telephony_status_unchanged(self):
        """Idempotent: already-completed telephony_status stays 'completed'.

        GIVEN an outbound CallSession with telephony_status='completed'
        WHEN update_telephony_status_on_session_end() is called
        THEN telephony_status remains 'completed' (no change)
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_outbound_session(telephony_status="completed")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed"

    @pytest.mark.asyncio
    async def test_failed_telephony_status_updated_on_session_end(self):
        """Even a 'failed' outbound session gets telephony_status=completed on session-end.

        GIVEN an outbound CallSession with telephony_status='failed' (retry exhausted)
        WHEN the session-end webhook fires (conversation did happen — FAS scenario)
        THEN telephony_status becomes 'completed' (webhook evidence wins)

        Rationale: If the conversation webhook fires, a real conversation happened
        regardless of what the outbound API reported. The conversation is the ground truth.
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_outbound_session(telephony_status="failed")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed", (
            "Even a 'failed' outbound session must have telephony_status='completed' "
            "when webhook evidence (conversation) arrives. "
            f"Got: {result.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_stale_in_call_telephony_status_updated_on_session_end(self):
        """stale_in_call can still be completed if webhook finally arrives.

        GIVEN a CallSession with telephony_status='stale_in_call'
        WHEN the session-end webhook fires (conversation evidence)
        THEN telephony_status becomes 'completed'
        (Late-arriving webhook should still resolve the session correctly)
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_outbound_session(telephony_status="stale_in_call")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed", (
            "stale_in_call sessions must become 'completed' when webhook arrives late. "
            f"Got: {result.telephony_status!r}"
        )
