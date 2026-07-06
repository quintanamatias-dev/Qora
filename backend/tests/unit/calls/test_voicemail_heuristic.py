"""Unit tests for _apply_voicemail_heuristic() in app.calls.service.

Spec: call-state-machine — Requirement: Voicemail Heuristic
  Heuristic: duration_seconds < 30 AND total_user_turns == 0 → telephony_status = 'voicemail'

Scenarios:
  1. Short call (duration=25s) + 0 user turns → voicemail detected
  2. Short call (duration=25s) + 1+ user turns → NOT voicemail
  3. Long call (duration=35s) + 0 user turns → NOT voicemail (over threshold)
  4. Session already in 'voicemail' state → stays voicemail (no double-apply)

All tests are pure unit tests — no DB, no HTTP.
The function is synchronous and mutates the session object in place.

TDD: Tests written BEFORE verifying coverage. They must target the exact
heuristic branching in _apply_voicemail_heuristic().
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbound_session(
    *,
    telephony_status: str = "completed",
    duration_seconds: float | None = None,
    total_user_turns: int = 0,
    total_agent_turns: int = 0,
    session_id: str = "session-vm-test-001",
) -> MagicMock:
    """Return a mock CallSession with the given state."""
    cs = MagicMock()
    cs.id = session_id
    cs.telephony_status = telephony_status
    cs.duration_seconds = duration_seconds
    cs.total_user_turns = total_user_turns
    cs.total_agent_turns = total_agent_turns
    return cs


def _call_heuristic(cs: MagicMock) -> None:
    """Invoke _apply_voicemail_heuristic with structlog muted."""
    from app.calls.service import _apply_voicemail_heuristic

    fake_logger = MagicMock()
    with patch("structlog.get_logger", return_value=fake_logger):
        _apply_voicemail_heuristic(cs)


# ---------------------------------------------------------------------------
# Scenario 1: Short duration + 0 user turns → voicemail
# ---------------------------------------------------------------------------


class TestVoicemailHeuristicDetected:
    """duration < 30 AND user_turns == 0 → telephony_status set to 'voicemail'."""

    def test_duration_25_zero_user_turns_is_voicemail(self) -> None:
        """GIVEN completed outbound session, duration=25s, 0 user turns
        WHEN _apply_voicemail_heuristic is called
        THEN telephony_status is set to 'voicemail'.
        """
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=25.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "voicemail", (
            "duration=25s and 0 user turns must trigger voicemail classification. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )

    def test_duration_exactly_at_threshold_minus_one_is_voicemail(self) -> None:
        """duration=29.9s (just below 30) AND 0 turns → voicemail."""
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=29.9,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "voicemail", (
            "duration=29.9s (just below 30s threshold) with 0 user turns must be voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )

    def test_duration_zero_zero_user_turns_is_voicemail(self) -> None:
        """Edge case: duration=0s and 0 user turns → voicemail (instant hang-up / machine pickup)."""
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=0.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "voicemail", (
            "duration=0s and 0 user turns must be classified as voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: Short duration + 1+ user turns → NOT voicemail
# ---------------------------------------------------------------------------


class TestVoicemailHeuristicNotDetectedUserTurns:
    """Short duration but with user turns present → NOT voicemail."""

    def test_duration_25_one_user_turn_not_voicemail(self) -> None:
        """GIVEN duration=25s, 1 user turn
        WHEN _apply_voicemail_heuristic is called
        THEN telephony_status stays 'completed' (not voicemail).
        """
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=25.0,
            total_user_turns=1,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "completed", (
            "duration=25s with 1 user turn must NOT be classified as voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )

    def test_duration_25_multiple_user_turns_not_voicemail(self) -> None:
        """duration=25s, 5 user turns → NOT voicemail (real conversation happened)."""
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=25.0,
            total_user_turns=5,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "completed", (
            "duration=25s with 5 user turns must NOT be classified as voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 3: Duration >= 30s AND 0 user turns → NOT voicemail
# ---------------------------------------------------------------------------


class TestVoicemailHeuristicNotDetectedLongCall:
    """Duration at or above threshold → NOT voicemail regardless of turns."""

    def test_duration_35_zero_user_turns_not_voicemail(self) -> None:
        """GIVEN duration=35s, 0 user turns
        WHEN _apply_voicemail_heuristic is called
        THEN telephony_status stays 'completed' (call was long enough to not be voicemail).
        """
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=35.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "completed", (
            "duration=35s (above 30s threshold) with 0 user turns must NOT be voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )

    def test_duration_exactly_30_zero_user_turns_not_voicemail(self) -> None:
        """duration=30.0 (at threshold) and 0 user turns → NOT voicemail.

        The heuristic uses strict less-than (< 30), so exactly 30 must NOT trigger.
        """
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=30.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "completed", (
            "duration=30.0 (exactly at threshold) with 0 user turns must NOT be voicemail. "
            "The heuristic is strictly less-than (< 30s), not less-than-or-equal. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )

    def test_duration_60_zero_user_turns_not_voicemail(self) -> None:
        """Long call (60s) with 0 turns → definitely not voicemail."""
        cs = _make_outbound_session(
            telephony_status="completed",
            duration_seconds=60.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "completed", (
            "duration=60s with 0 user turns must NOT be classified as voicemail. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Session already in 'voicemail' state → stays voicemail
# ---------------------------------------------------------------------------


class TestVoicemailHeuristicIdempotent:
    """Session already voicemail → stays voicemail, no double-apply."""

    def test_already_voicemail_stays_voicemail(self) -> None:
        """GIVEN a session already in telephony_status='voicemail'
        WHEN _apply_voicemail_heuristic is called again
        THEN telephony_status remains 'voicemail' (idempotent).

        Note: The function guards on telephony_status == 'completed' before
        calling the heuristic (in service.py close_session). So if called
        directly with telephony_status='voicemail', it should not change the
        status back (because is_voicemail would need to be True, but even so
        it only sets to 'voicemail' which is already the value).
        This verifies there's no destructive mutation on already-voicemail sessions.
        """
        cs = _make_outbound_session(
            telephony_status="voicemail",
            duration_seconds=20.0,
            total_user_turns=0,
        )

        _call_heuristic(cs)

        assert cs.telephony_status == "voicemail", (
            "A session already in 'voicemail' state must remain 'voicemail' after heuristic. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )


# ---------------------------------------------------------------------------
# Guard: Inbound sessions (telephony_status=None) → heuristic is a no-op
# ---------------------------------------------------------------------------


class TestVoicemailHeuristicInboundGuard:
    """Inbound sessions (telephony_status=None) must not be affected by the heuristic."""

    def test_inbound_session_not_affected(self) -> None:
        """GIVEN inbound session (telephony_status=None), duration=10s, 0 user turns
        WHEN _apply_voicemail_heuristic is called
        THEN telephony_status stays None (inbound — heuristic is a no-op).
        """
        cs = _make_outbound_session(
            telephony_status=None,  # type: ignore[arg-type]
            duration_seconds=10.0,
            total_user_turns=0,
        )
        # Manually set to None since MagicMock may behave oddly with None
        cs.telephony_status = None

        _call_heuristic(cs)

        assert cs.telephony_status is None, (
            "Inbound sessions (telephony_status=None) must not be affected by voicemail heuristic. "
            f"Got: telephony_status={cs.telephony_status!r}"
        )
