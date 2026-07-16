"""Phase C6 — Retry & Recontact Policy: voicemail recontact rule tests.

Spec: Domain recontact-policy — voicemail triggers recontact via next-action voicemail path.
- Context with telephony_status='voicemail' → retry_call
- Context with telephony_status='completed' + 1 user turn → no voicemail rule trigger
- Context with telephony_status=None → no voicemail rule trigger
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(telephony_status=None, outcome_classification="completed_positive"):
    """Build a minimal NextActionContext for voicemail rule tests."""
    from app.analysis.universal.next_action import (
        NextActionContext,
        LeadSnapshot,
        ClientRules,
    )
    from app.analysis.universal.outcome import CallOutcome
    from app.analysis.universal.commitments import CommitmentsAxis
    from app.analysis.universal.objections import ObjectionsAxis
    from app.analysis.universal.problem import ProblemAxis

    return NextActionContext(
        outcome=CallOutcome(
            classification=outcome_classification,
            reason="test",
            confidence="high",
        ),
        interest_level=50,
        commitments=CommitmentsAxis(),
        objections=ObjectionsAxis(),
        problem=ProblemAxis(pain_points=[]),
        lead=LeadSnapshot(
            call_count=1,
            do_not_call=False,
            last_called_at=datetime.now(timezone.utc),
        ),
        client=ClientRules(
            max_attempts=5,
            min_interest_for_followup=40,
            close_on_hard_rejection=True,
            scheduler_cooldown_minutes=60,
            scheduler_allowed_hours_start=9,
            scheduler_allowed_hours_end=20,
            scheduler_timezone="America/Argentina/Buenos_Aires",
        ),
        telephony_status=telephony_status,
    )


# ===========================================================================
# Task 2.1: _rule_voicemail_recontact
# ===========================================================================


class TestRuleVoicemailRecontact:
    """P3.5 voicemail recontact rule must fire for telephony_status='voicemail'."""

    def test_voicemail_status_triggers_retry_call(self):
        """telephony_status='voicemail' → retry_call result."""
        from app.analysis.universal.next_action import _rule_voicemail_recontact

        ctx = _make_context(telephony_status="voicemail")
        result = _rule_voicemail_recontact(ctx)

        assert result is not None, "Rule must return a result for voicemail status"
        assert result.action == "retry_call", (
            f"Expected retry_call, got {result.action}"
        )
        assert result.decided_by == "rules"
        assert result.confidence == "high"

    def test_voicemail_result_has_next_action_at(self):
        """Voicemail rule result has next_action_at set (scheduler cooldown)."""
        from app.analysis.universal.next_action import _rule_voicemail_recontact

        ctx = _make_context(telephony_status="voicemail")
        result = _rule_voicemail_recontact(ctx)

        assert result is not None
        assert result.next_action_at is not None, (
            "Voicemail retry result must include next_action_at from scheduler cooldown"
        )

    def test_completed_status_does_not_trigger_voicemail_rule(self):
        """telephony_status='completed' → rule returns None (no voicemail match)."""
        from app.analysis.universal.next_action import _rule_voicemail_recontact

        ctx = _make_context(telephony_status="completed")
        result = _rule_voicemail_recontact(ctx)

        assert result is None, (
            f"Rule must not fire for telephony_status='completed', got {result}"
        )

    def test_none_telephony_status_does_not_trigger_voicemail_rule(self):
        """telephony_status=None → rule returns None."""
        from app.analysis.universal.next_action import _rule_voicemail_recontact

        ctx = _make_context(telephony_status=None)
        result = _rule_voicemail_recontact(ctx)

        assert result is None, (
            f"Rule must not fire for telephony_status=None, got {result}"
        )

    def test_no_answer_outcome_does_not_double_trigger_voicemail_rule(self):
        """telephony_status='no_answer' → rule returns None (only voicemail fires)."""
        from app.analysis.universal.next_action import _rule_voicemail_recontact

        ctx = _make_context(telephony_status="no_answer")
        result = _rule_voicemail_recontact(ctx)

        assert result is None, (
            "Voicemail rule must only fire for 'voicemail' status, not 'no_answer'"
        )

    def test_voicemail_rule_position_is_p3_5_between_p3_and_p4(self):
        """Voicemail rule is in _RULES list between P3 (_rule_commitment_based) and P4."""
        from app.analysis.universal.next_action import (
            _RULES,
            _rule_commitment_based,
            _rule_no_useful_conversation,
            _rule_voicemail_recontact,
        )

        p3_idx = _RULES.index(_rule_commitment_based)
        p4_idx = _RULES.index(_rule_no_useful_conversation)
        vm_idx = _RULES.index(_rule_voicemail_recontact)

        assert p3_idx < vm_idx < p4_idx, (
            f"Voicemail rule must be between P3 ({p3_idx}) and P4 ({p4_idx}), "
            f"but is at position {vm_idx}"
        )
