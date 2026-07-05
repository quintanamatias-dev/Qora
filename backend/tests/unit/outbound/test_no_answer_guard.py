"""Regression tests: no_answer and recurrent_error must not be overwritten by session-end.

Spec: outbound-call-trigger — FAS-Safe Semantics
  - telephony_status='no_answer' and 'recurrent_error' represent calls where no real
    conversation occurred. A session-end webhook arriving for these statuses is
    out-of-order, duplicate, or stale and MUST NOT silently flip the status to
    'completed', which would corrupt billing/CRM outcomes.

  - telephony_status='failed' and 'stale_in_call' ARE intentionally overwritten:
    the session-end webhook is ground truth evidence that a conversation happened.

Guards implemented in update_telephony_status_on_session_end()
in backend/app/outbound/linkage.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.outbound.linkage import update_telephony_status_on_session_end


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbound_session(telephony_status: str) -> MagicMock:
    """Return a minimal mock outbound CallSession with the given telephony_status."""
    cs = MagicMock()
    cs.id = "session-test-001"
    cs.telephony_status = telephony_status
    cs.session_end_received = False
    return cs


# ---------------------------------------------------------------------------
# no_answer guard
# ---------------------------------------------------------------------------


class TestNoAnswerGuard:
    """no_answer must never be overwritten to 'completed' by a session-end webhook."""

    def test_no_answer_not_overwritten_by_session_end(self):
        """REGRESSION: session-end webhook must NOT flip no_answer → completed.

        GIVEN an outbound CallSession with telephony_status='no_answer'
        WHEN update_telephony_status_on_session_end() is called (session-end fires)
        THEN telephony_status remains 'no_answer' (no overwrite)
        AND session_end_received is set to True (webhook evidence still recorded)
        """
        cs = _make_outbound_session(telephony_status="no_answer")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "no_answer", (
            "no_answer must NOT be overwritten to 'completed' by a session-end webhook. "
            f"Got: {result.telephony_status!r}"
        )
        assert result.session_end_received is True, (
            "session_end_received must be set to True even when telephony_status is preserved."
        )

    def test_no_answer_session_end_received_set(self):
        """session_end_received=True is recorded even when no_answer is preserved.

        The sweep must know the webhook fired — we only skip the status overwrite.
        """
        cs = _make_outbound_session(telephony_status="no_answer")

        update_telephony_status_on_session_end(cs)

        assert cs.session_end_received is True


# ---------------------------------------------------------------------------
# recurrent_error guard
# ---------------------------------------------------------------------------


class TestRecurrentErrorGuard:
    """recurrent_error must never be overwritten to 'completed' by a session-end webhook."""

    def test_recurrent_error_not_overwritten_by_session_end(self):
        """REGRESSION: session-end webhook must NOT flip recurrent_error → completed.

        GIVEN an outbound CallSession with telephony_status='recurrent_error'
        WHEN update_telephony_status_on_session_end() is called (session-end fires)
        THEN telephony_status remains 'recurrent_error' (no overwrite)
        AND session_end_received is set to True
        """
        cs = _make_outbound_session(telephony_status="recurrent_error")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "recurrent_error", (
            "recurrent_error must NOT be overwritten to 'completed' by a session-end webhook. "
            f"Got: {result.telephony_status!r}"
        )
        assert result.session_end_received is True, (
            "session_end_received must be set to True even when telephony_status is preserved."
        )

    def test_recurrent_error_session_end_received_set(self):
        """session_end_received=True is recorded even when recurrent_error is preserved."""
        cs = _make_outbound_session(telephony_status="recurrent_error")

        update_telephony_status_on_session_end(cs)

        assert cs.session_end_received is True


# ---------------------------------------------------------------------------
# Intentional overwrites still work (non-regression)
# ---------------------------------------------------------------------------


class TestIntentionalOverwritesPreserved:
    """failed and stale_in_call must still be overwritten — webhook is ground truth."""

    def test_failed_is_overwritten_to_completed(self):
        """failed → completed is intentional: webhook proves a conversation happened."""
        cs = _make_outbound_session(telephony_status="failed")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed", (
            "failed must be overwritten to 'completed' when the session-end webhook arrives. "
            f"Got: {result.telephony_status!r}"
        )

    def test_stale_in_call_is_overwritten_to_completed(self):
        """stale_in_call → completed: a late webhook resolves the stuck session."""
        cs = _make_outbound_session(telephony_status="stale_in_call")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed", (
            "stale_in_call must be overwritten to 'completed' when the session-end webhook arrives. "
            f"Got: {result.telephony_status!r}"
        )

    def test_ringing_is_overwritten_to_completed(self):
        """ringing → completed: normal in-progress call that ended."""
        cs = _make_outbound_session(telephony_status="ringing")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed"

    def test_already_completed_stays_completed(self):
        """Idempotent: completed → completed, no mutation."""
        cs = _make_outbound_session(telephony_status="completed")

        result = update_telephony_status_on_session_end(cs)

        assert result.telephony_status == "completed"
