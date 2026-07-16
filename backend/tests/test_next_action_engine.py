"""Tests for the next_action decision engine — Issue #47 (qora-next-action).

Strict TDD: tests written BEFORE production code exists.

Covers:
- NextActionResult schema validation (Pydantic)
- NextActionContext + dataclasses (LeadSnapshot, ClientRules)
- NextActionClientRules defaults
- Rules engine priority order (P1-P5)
- GPT fallback (P6)
- _due_to_utc timing helper
- run_next_action_pipeline orchestration
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone


# ===========================================================================
# Phase 1 — Schemas + Client Config
# ===========================================================================


class TestNextActionResult:
    """NextActionResult schema: valid construction, field constraints."""

    def test_valid_result_rules_path(self):
        """NextActionResult constructs with all required fields (rules path)."""
        from app.analysis.universal.next_action import NextActionResult

        result = NextActionResult(
            action="follow_up",
            reason="Lead showed strong interest",
            confidence="high",
            decided_by="rules",
        )
        assert result.action == "follow_up"
        assert result.decided_by == "rules"
        assert result.confidence == "high"
        assert result.next_action_at is None  # default
        assert result.priority == "normal"  # default

    def test_valid_result_gpt_path(self):
        """NextActionResult constructs for gpt decided_by path."""
        from app.analysis.universal.next_action import NextActionResult

        result = NextActionResult(
            action="human_review",
            reason="Ambiguous context",
            confidence="low",
            decided_by="gpt",
        )
        assert result.action == "human_review"
        assert result.decided_by == "gpt"

    def test_action_vocabulary_all_five(self):
        """NextActionResult accepts exactly the 5 valid action values."""
        from app.analysis.universal.next_action import NextActionResult

        valid_actions = [
            "follow_up",
            "retry_call",
            "schedule_call",
            "close_lead",
            "human_review",
        ]
        for action in valid_actions:
            r = NextActionResult(
                action=action,
                reason="test",
                confidence="medium",
                decided_by="rules",
            )
            assert r.action == action

    def test_action_rejects_old_vocabulary(self):
        """NextActionResult rejects old vocabulary (call_again, do_not_call, etc.)."""
        from app.analysis.universal.next_action import NextActionResult
        from pydantic import ValidationError

        invalid_actions = ["call_again", "send_quote", "wait", "do_not_call"]
        for bad_action in invalid_actions:
            with pytest.raises(ValidationError):
                NextActionResult(
                    action=bad_action,
                    reason="test",
                    confidence="high",
                    decided_by="rules",
                )

    def test_decided_by_only_rules_or_gpt(self):
        """decided_by only accepts 'rules' or 'gpt'."""
        from app.analysis.universal.next_action import NextActionResult
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            NextActionResult(
                action="follow_up",
                reason="test",
                confidence="high",
                decided_by="manual",  # invalid
            )

    def test_confidence_three_values(self):
        """Confidence accepts low, medium, high only."""
        from app.analysis.universal.next_action import NextActionResult
        from pydantic import ValidationError

        # Valid
        for c in ["low", "medium", "high"]:
            r = NextActionResult(
                action="close_lead", reason="t", confidence=c, decided_by="rules"
            )
            assert r.confidence == c

        # Invalid
        with pytest.raises(ValidationError):
            NextActionResult(
                action="close_lead",
                reason="t",
                confidence="very_high",
                decided_by="rules",
            )

    def test_next_action_at_optional_datetime(self):
        """next_action_at accepts None (default) or a datetime."""
        from app.analysis.universal.next_action import NextActionResult

        dt = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
        result = NextActionResult(
            action="schedule_call",
            reason="callback commitment",
            confidence="high",
            decided_by="rules",
            next_action_at=dt,
        )
        assert result.next_action_at == dt

    def test_priority_defaults_normal(self):
        """priority defaults to 'normal'."""
        from app.analysis.universal.next_action import NextActionResult

        r = NextActionResult(
            action="retry_call", reason="busy", confidence="high", decided_by="rules"
        )
        assert r.priority == "normal"

    def test_model_dump_serializable(self):
        """NextActionResult.model_dump() produces a serializable dict."""
        from app.analysis.universal.next_action import NextActionResult

        r = NextActionResult(
            action="close_lead", reason="hostile", confidence="high", decided_by="rules"
        )
        d = r.model_dump()
        assert d["action"] == "close_lead"
        assert d["decided_by"] == "rules"
        assert "next_action_at" in d


class TestLeadSnapshot:
    """LeadSnapshot dataclass: stores lead state."""

    def test_lead_snapshot_fields(self):
        """LeadSnapshot holds call_count, do_not_call, last_called_at."""
        from app.analysis.universal.next_action import LeadSnapshot

        snap = LeadSnapshot(call_count=3, do_not_call=False, last_called_at=None)
        assert snap.call_count == 3
        assert snap.do_not_call is False
        assert snap.last_called_at is None

    def test_lead_snapshot_with_do_not_call(self):
        """LeadSnapshot with do_not_call=True reflects flag correctly."""
        from app.analysis.universal.next_action import LeadSnapshot

        snap = LeadSnapshot(call_count=1, do_not_call=True, last_called_at=None)
        assert snap.do_not_call is True


class TestClientRules:
    """ClientRules dataclass: client-configurable thresholds."""

    def test_client_rules_fields(self):
        """ClientRules holds all expected threshold fields."""
        from app.analysis.universal.next_action import ClientRules

        rules = ClientRules(
            max_attempts=5,
            min_interest_for_followup=40,
            close_on_hard_rejection=True,
            scheduler_cooldown_minutes=60,
            scheduler_allowed_hours_start=9,
            scheduler_allowed_hours_end=20,
            scheduler_timezone="America/Argentina/Buenos_Aires",
        )
        assert rules.max_attempts == 5
        assert rules.min_interest_for_followup == 40
        assert rules.close_on_hard_rejection is True
        assert rules.scheduler_timezone == "America/Argentina/Buenos_Aires"

    def test_client_rules_with_custom_threshold(self):
        """ClientRules accepts overridden thresholds."""
        from app.analysis.universal.next_action import ClientRules

        rules = ClientRules(
            max_attempts=10,
            min_interest_for_followup=60,
            close_on_hard_rejection=False,
            scheduler_cooldown_minutes=120,
            scheduler_allowed_hours_start=8,
            scheduler_allowed_hours_end=18,
            scheduler_timezone="America/New_York",
        )
        assert rules.max_attempts == 10
        assert rules.min_interest_for_followup == 60
        assert rules.close_on_hard_rejection is False


class TestNextActionContext:
    """NextActionContext dataclass: assembles dimension outputs + lead state + client rules."""

    def _make_context(self, **overrides):
        """Helper to build a minimal NextActionContext."""
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        defaults = dict(
            outcome=CallOutcome(
                classification="completed_positive",
                reason="test",
                confidence="high",
            ),
            interest_level=50,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        defaults.update(overrides)
        return NextActionContext(**defaults)

    def test_context_has_all_required_fields(self):
        """NextActionContext holds all dimension outputs + lead + client fields."""

        ctx = self._make_context()
        assert hasattr(ctx, "outcome")
        assert hasattr(ctx, "interest_level")
        assert hasattr(ctx, "commitments")
        assert hasattr(ctx, "objections")
        assert hasattr(ctx, "problem")
        assert hasattr(ctx, "lead")
        assert hasattr(ctx, "client")

    def test_context_carries_interest_level(self):
        """NextActionContext correctly stores interest_level."""
        ctx = self._make_context(interest_level=75)
        assert ctx.interest_level == 75


# ===========================================================================
# Phase 1 — Client model columns
# ===========================================================================


class TestClientNextActionColumns:
    """Client model has 3 new next_action columns with correct defaults."""

    def test_client_model_has_next_action_max_attempts(self):
        """Client model has next_action_max_attempts column."""
        from app.tenants.models import Client
        import sqlalchemy as sa

        col = Client.__table__.c.get("next_action_max_attempts")
        assert col is not None
        assert isinstance(col.type, sa.Integer)

    def test_client_model_has_next_action_min_interest_for_followup(self):
        """Client model has next_action_min_interest_for_followup column."""
        from app.tenants.models import Client
        import sqlalchemy as sa

        col = Client.__table__.c.get("next_action_min_interest_for_followup")
        assert col is not None
        assert isinstance(col.type, sa.Integer)

    def test_client_model_has_next_action_close_on_hard_rejection(self):
        """Client model has next_action_close_on_hard_rejection column."""
        from app.tenants.models import Client
        import sqlalchemy as sa

        col = Client.__table__.c.get("next_action_close_on_hard_rejection")
        assert col is not None
        assert isinstance(col.type, sa.Boolean)

    def test_scheduler_retry_on_outcomes_default_updated(self):
        """scheduler_retry_on_outcomes default uses new 5-action vocabulary."""
        from app.tenants.models import Client

        col = Client.__table__.c.get("scheduler_retry_on_outcomes")
        assert col is not None
        # The default should contain the new vocabulary, not old "call_again"
        default_val = col.default.arg
        assert "follow_up" in default_val
        assert "retry_call" in default_val
        assert "schedule_call" in default_val
        assert "call_again" not in default_val


# ===========================================================================
# Phase 2 — Rules Engine
# ===========================================================================


class TestRuleHardStops:
    """P1: hard stop rules — outcome classification, do_not_call, hard rejection."""

    def _make_ctx(self, **overrides):
        """Build minimal NextActionContext for rules testing."""
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        defaults = dict(
            outcome=CallOutcome(
                classification="completed_positive",
                reason="test",
                confidence="high",
            ),
            interest_level=50,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        defaults.update(overrides)
        return NextActionContext(**defaults)

    def test_do_not_contact_outcome_returns_close_lead(self):
        """P1: outcome=do_not_contact → close_lead, rules, high confidence."""
        from app.analysis.universal.next_action import _rule_hard_stops
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="do_not_contact",
                reason="asked not to call",
                confidence="high",
            )
        )
        result = _rule_hard_stops(ctx)
        assert result is not None
        assert result.action == "close_lead"
        assert result.decided_by == "rules"
        assert result.confidence == "high"

    def test_wrong_number_outcome_returns_close_lead(self):
        """P1: outcome=wrong_number → close_lead."""
        from app.analysis.universal.next_action import _rule_hard_stops
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="wrong_number", reason="wrong person", confidence="high"
            )
        )
        result = _rule_hard_stops(ctx)
        assert result is not None
        assert result.action == "close_lead"

    def test_hostile_outcome_returns_close_lead(self):
        """P1: outcome=hostile → close_lead."""
        from app.analysis.universal.next_action import _rule_hard_stops
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="hostile", reason="rude", confidence="high"
            )
        )
        result = _rule_hard_stops(ctx)
        assert result is not None
        assert result.action == "close_lead"

    def test_do_not_call_flag_returns_close_lead(self):
        """P1: lead.do_not_call=True → close_lead even with neutral outcome."""
        from app.analysis.universal.next_action import _rule_hard_stops, LeadSnapshot
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="completed_positive",
                reason="positive",
                confidence="high",
            ),
            lead=LeadSnapshot(call_count=1, do_not_call=True, last_called_at=None),
        )
        result = _rule_hard_stops(ctx)
        assert result is not None
        assert result.action == "close_lead"
        assert result.decided_by == "rules"

    def test_hard_rejection_with_client_flag_returns_close_lead(self):
        """P1: hard_rejection objection + close_on_hard_rejection=True → close_lead."""
        from app.analysis.universal.next_action import _rule_hard_stops, ClientRules
        from app.analysis.universal.objections import ObjectionsAxis, Objection

        ctx = self._make_ctx(
            objections=ObjectionsAxis(
                objections=[
                    Objection(
                        category="hard_rejection",
                        strength="high",
                        resolution_status="unresolved",
                        evidence="I never want to hear from you again",
                        description="Hard rejection",
                        confidence="high",
                    )
                ]
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
        )
        result = _rule_hard_stops(ctx)
        assert result is not None
        assert result.action == "close_lead"

    def test_hard_rejection_client_flag_off_returns_none(self):
        """P1: hard_rejection + close_on_hard_rejection=False → rule does NOT fire."""
        from app.analysis.universal.next_action import _rule_hard_stops, ClientRules
        from app.analysis.universal.objections import ObjectionsAxis, Objection

        ctx = self._make_ctx(
            objections=ObjectionsAxis(
                objections=[
                    Objection(
                        category="hard_rejection",
                        strength="high",
                        resolution_status="unresolved",
                        evidence="Do not call me",
                        description="Hard rejection",
                        confidence="high",
                    )
                ]
            ),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=False,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        result = _rule_hard_stops(ctx)
        assert result is None

    def test_completed_positive_no_flag_returns_none(self):
        """P1: normal completed_positive with no flags → rule returns None."""
        from app.analysis.universal.next_action import _rule_hard_stops

        ctx = self._make_ctx()
        result = _rule_hard_stops(ctx)
        assert result is None


class TestRuleMaxAttempts:
    """P2: max attempts rule."""

    def _make_ctx(self, call_count: int, max_attempts: int):
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
                classification="completed_positive", reason="test", confidence="high"
            ),
            interest_level=50,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(
                call_count=call_count, do_not_call=False, last_called_at=None
            ),
            client=ClientRules(
                max_attempts=max_attempts,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    def test_call_count_equals_max_returns_close_lead(self):
        """P2: call_count == max_attempts → close_lead."""
        from app.analysis.universal.next_action import _rule_max_attempts

        ctx = self._make_ctx(call_count=5, max_attempts=5)
        result = _rule_max_attempts(ctx)
        assert result is not None
        assert result.action == "close_lead"
        assert result.decided_by == "rules"
        assert result.confidence == "high"

    def test_call_count_exceeds_max_returns_close_lead(self):
        """P2: call_count > max_attempts → close_lead."""
        from app.analysis.universal.next_action import _rule_max_attempts

        ctx = self._make_ctx(call_count=7, max_attempts=5)
        result = _rule_max_attempts(ctx)
        assert result is not None
        assert result.action == "close_lead"

    def test_call_count_below_max_returns_none(self):
        """P2: call_count < max_attempts → rule does NOT fire."""
        from app.analysis.universal.next_action import _rule_max_attempts

        ctx = self._make_ctx(call_count=2, max_attempts=5)
        result = _rule_max_attempts(ctx)
        assert result is None


class TestRuleCommitmentBased:
    """P3: commitment-based rules (schedule_call, follow_up)."""

    def _make_ctx(self, commitments, **overrides):
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        return NextActionContext(
            outcome=CallOutcome(
                classification="completed_positive", reason="test", confidence="high"
            ),
            interest_level=50,
            commitments=commitments,
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    def test_strong_callback_returns_schedule_call(self):
        """P3: callback commitment, strength=strong, owner=lead → schedule_call."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis, Commitment

        ctx = self._make_ctx(
            commitments=CommitmentsAxis(
                commitments=[
                    Commitment(
                        type="callback",
                        owner="lead",
                        description="Will call back tomorrow",
                        due="tomorrow",
                        strength="strong",
                        evidence="I'll call you back tomorrow morning",
                        confidence="high",
                    )
                ]
            )
        )
        result = _rule_commitment_based(ctx)
        assert result is not None
        assert result.action == "schedule_call"
        assert result.decided_by == "rules"

    def test_medium_callback_from_both_returns_schedule_call(self):
        """P3: callback, strength=medium, owner=both → schedule_call."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis, Commitment

        ctx = self._make_ctx(
            commitments=CommitmentsAxis(
                commitments=[
                    Commitment(
                        type="callback",
                        owner="both",
                        description="We'll arrange a call",
                        due="this_week",
                        strength="medium",
                        evidence="Let's set up a time",
                        confidence="medium",
                    )
                ]
            )
        )
        result = _rule_commitment_based(ctx)
        assert result is not None
        assert result.action == "schedule_call"

    def test_weak_callback_returns_none(self):
        """P3: callback, strength=weak → rule does NOT fire."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis, Commitment

        ctx = self._make_ctx(
            commitments=CommitmentsAxis(
                commitments=[
                    Commitment(
                        type="callback",
                        owner="lead",
                        description="Maybe sometime",
                        due="unknown",
                        strength="weak",
                        evidence="maybe",
                        confidence="low",
                    )
                ]
            )
        )
        result = _rule_commitment_based(ctx)
        assert result is None

    def test_receive_quote_strong_returns_follow_up(self):
        """P3: receive_quote, strength=strong → follow_up."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis, Commitment

        ctx = self._make_ctx(
            commitments=CommitmentsAxis(
                commitments=[
                    Commitment(
                        type="receive_quote",
                        owner="agent",
                        description="Agent will send quote",
                        due="today",
                        strength="strong",
                        evidence="Please send me the quote",
                        confidence="high",
                    )
                ]
            )
        )
        result = _rule_commitment_based(ctx)
        assert result is not None
        assert result.action == "follow_up"

    def test_consult_third_party_returns_follow_up(self):
        """P3: consult_third_party commitment → follow_up."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis, Commitment

        ctx = self._make_ctx(
            commitments=CommitmentsAxis(
                commitments=[
                    Commitment(
                        type="consult_third_party",
                        owner="lead",
                        description="Will consult spouse",
                        due="this_week",
                        strength="medium",
                        evidence="I need to talk to my wife first",
                        confidence="high",
                    )
                ]
            )
        )
        result = _rule_commitment_based(ctx)
        assert result is not None
        assert result.action == "follow_up"

    def test_no_commitments_returns_none(self):
        """P3: no commitments → rule returns None."""
        from app.analysis.universal.next_action import _rule_commitment_based
        from app.analysis.universal.commitments import CommitmentsAxis

        ctx = self._make_ctx(commitments=CommitmentsAxis())
        result = _rule_commitment_based(ctx)
        assert result is None


class TestRuleNoUsefulConversation:
    """P4: no useful conversation rules (retry_call)."""

    def _make_ctx(self, outcome):
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        return NextActionContext(
            outcome=outcome,
            interest_level=30,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    def test_no_answer_returns_retry_call(self):
        """P4: outcome=no_answer → retry_call."""
        from app.analysis.universal.next_action import _rule_no_useful_conversation
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="no_answer", reason="no answer", confidence="high"
            )
        )
        result = _rule_no_useful_conversation(ctx)
        assert result is not None
        assert result.action == "retry_call"
        assert result.decided_by == "rules"

    def test_busy_returns_retry_call(self):
        """P4: outcome=busy → retry_call."""
        from app.analysis.universal.next_action import _rule_no_useful_conversation
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(classification="busy", reason="busy", confidence="high")
        )
        result = _rule_no_useful_conversation(ctx)
        assert result is not None
        assert result.action == "retry_call"

    def test_technical_issue_returns_retry_call(self):
        """P4: outcome=technical_issue → retry_call."""
        from app.analysis.universal.next_action import _rule_no_useful_conversation
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="technical_issue", reason="dropped", confidence="high"
            )
        )
        result = _rule_no_useful_conversation(ctx)
        assert result is not None
        assert result.action == "retry_call"

    def test_abrupt_external_interruption_returns_retry_call(self):
        """P4: was_abrupt=True + abandonment_trigger=external_interruption → retry_call."""
        from app.analysis.universal.next_action import _rule_no_useful_conversation
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="no_answer",
                reason="interrupted",
                confidence="medium",
                was_abrupt=True,
                abandonment_trigger="external_interruption",
            )
        )
        result = _rule_no_useful_conversation(ctx)
        assert result is not None
        assert result.action == "retry_call"

    def test_completed_positive_returns_none(self):
        """P4: completed_positive → rule does NOT fire."""
        from app.analysis.universal.next_action import _rule_no_useful_conversation
        from app.analysis.universal.outcome import CallOutcome

        ctx = self._make_ctx(
            outcome=CallOutcome(
                classification="completed_positive", reason="good", confidence="high"
            )
        )
        result = _rule_no_useful_conversation(ctx)
        assert result is None


class TestRuleInterestOutcome:
    """P5: interest + outcome signal rules."""

    def _make_ctx(self, interest_level: int, classification: str):
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
                classification=classification, reason="test", confidence="high"
            ),
            interest_level=interest_level,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    def test_high_interest_completed_positive_returns_follow_up(self):
        """P5: interest=65 + completed_positive → follow_up."""
        from app.analysis.universal.next_action import _rule_interest_outcome

        ctx = self._make_ctx(interest_level=65, classification="completed_positive")
        result = _rule_interest_outcome(ctx)
        assert result is not None
        assert result.action == "follow_up"
        assert result.decided_by == "rules"

    def test_high_interest_completed_neutral_returns_follow_up(self):
        """P5: interest=40 (threshold) + completed_neutral → follow_up."""
        from app.analysis.universal.next_action import _rule_interest_outcome

        ctx = self._make_ctx(interest_level=40, classification="completed_neutral")
        result = _rule_interest_outcome(ctx)
        assert result is not None
        assert result.action == "follow_up"

    def test_low_interest_completed_negative_returns_close_lead(self):
        """P5: interest=10 (<20) + completed_negative → close_lead."""
        from app.analysis.universal.next_action import _rule_interest_outcome

        ctx = self._make_ctx(interest_level=10, classification="completed_negative")
        result = _rule_interest_outcome(ctx)
        assert result is not None
        assert result.action == "close_lead"

    def test_interest_below_threshold_returns_none(self):
        """P5: interest=35 (below 40) + completed_positive → rule does NOT fire."""
        from app.analysis.universal.next_action import _rule_interest_outcome

        ctx = self._make_ctx(interest_level=35, classification="completed_positive")
        result = _rule_interest_outcome(ctx)
        assert result is None

    def test_interest_high_but_negative_outcome_returns_none(self):
        """P5: interest=80 but completed_negative → neither branch fires."""
        from app.analysis.universal.next_action import _rule_interest_outcome

        # interest >= threshold but classification is completed_negative (not completed_positive/neutral)
        # AND interest is NOT < 20 (so close_lead branch won't fire either)
        ctx = self._make_ctx(interest_level=80, classification="completed_negative")
        result = _rule_interest_outcome(ctx)
        assert result is None


class TestDueToUtc:
    """_due_to_utc timing helper: maps commitment due values to UTC datetime."""

    def test_today_returns_todays_start_hour(self):
        """due=today → start_hour today in client TZ → UTC."""
        from app.analysis.universal.next_action import _due_to_utc
        from zoneinfo import ZoneInfo

        tz_str = "America/Argentina/Buenos_Aires"
        now_utc = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)  # 09:00 local
        result = _due_to_utc("today", tz_str, start_hour=9, now_utc=now_utc)
        assert result is not None
        local = result.astimezone(ZoneInfo(tz_str))
        assert local.hour == 9
        assert local.date() == datetime(2026, 5, 7, tzinfo=ZoneInfo(tz_str)).date()

    def test_tomorrow_returns_next_day_start_hour(self):
        """due=tomorrow → start_hour tomorrow in client TZ → UTC."""
        from app.analysis.universal.next_action import _due_to_utc
        from zoneinfo import ZoneInfo

        tz_str = "America/Argentina/Buenos_Aires"
        now_utc = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = _due_to_utc("tomorrow", tz_str, start_hour=9, now_utc=now_utc)
        assert result is not None
        local = result.astimezone(ZoneInfo(tz_str))
        assert local.hour == 9
        assert local.day == 8  # next day

    def test_unknown_returns_none(self):
        """due=unknown → returns None (caller falls back to calculate_scheduled_at)."""
        from app.analysis.universal.next_action import _due_to_utc

        now_utc = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = _due_to_utc(
            "unknown", "America/Argentina/Buenos_Aires", start_hour=9, now_utc=now_utc
        )
        assert result is None

    def test_specific_date_returns_none(self):
        """due=specific_date → returns None (caller falls back)."""
        from app.analysis.universal.next_action import _due_to_utc

        now_utc = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = _due_to_utc(
            "specific_date",
            "America/Argentina/Buenos_Aires",
            start_hour=9,
            now_utc=now_utc,
        )
        assert result is None

    def test_this_week_returns_two_days_ahead(self):
        """due=this_week → 2 days from now at start_hour."""
        from app.analysis.universal.next_action import _due_to_utc
        from zoneinfo import ZoneInfo

        tz_str = "America/Argentina/Buenos_Aires"
        now_utc = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = _due_to_utc("this_week", tz_str, start_hour=9, now_utc=now_utc)
        assert result is not None
        local = result.astimezone(ZoneInfo(tz_str))
        assert local.hour == 9
        assert local.day == 9  # 2 days ahead from May 7


# ===========================================================================
# Phase 3 — GPT Fallback + Pipeline Orchestration
# ===========================================================================


class TestRulesPriorityOrder:
    """Rules engine: first match wins — priority ordering verified."""

    def _make_ctx(self, outcome_classification, interest_level=80):
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
            interest_level=interest_level,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    def test_do_not_contact_wins_over_high_interest(self):
        """P1 fires before P5: do_not_contact + interest=80 → close_lead (not follow_up)."""
        from app.analysis.universal.next_action import _RULES

        ctx = self._make_ctx("do_not_contact", interest_level=80)
        for rule in _RULES:
            result = rule(ctx)
            if result is not None:
                assert result.action == "close_lead"
                break
        else:
            pytest.fail("No rule fired for do_not_contact context")

    def test_rules_list_has_six_entries(self):
        """_RULES contains exactly 6 rule functions (P1-P3.5-P5).

        C6 added _rule_voicemail_recontact as P3.5 between P3 and P4.
        """
        from app.analysis.universal.next_action import _RULES

        assert len(_RULES) == 6

    def test_evaluate_rules_returns_first_match(self):
        """_evaluate_rules() returns first non-None result."""
        from app.analysis.universal.next_action import _evaluate_rules
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        ctx = NextActionContext(
            outcome=CallOutcome(
                classification="do_not_contact", reason="test", confidence="high"
            ),
            interest_level=80,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        result = _evaluate_rules(ctx)
        assert result is not None
        assert result.action == "close_lead"


class TestGptFallback:
    """GPT fallback: invoked only when no rule matches, returns valid action."""

    def _make_ambiguous_ctx(self):
        """Context where no deterministic rule fires (ambiguous case)."""
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
                classification="completed_neutral",
                reason="neutral",
                confidence="medium",
            ),
            interest_level=35,  # below 40 threshold
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=2, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

    @pytest.mark.asyncio
    async def test_gpt_fallback_returns_valid_action(self):
        """_gpt_fallback returns NextActionResult with valid action."""
        from unittest.mock import AsyncMock, MagicMock
        from app.analysis.universal.next_action import _gpt_fallback

        mock_client = MagicMock()

        # Mock the GPT response
        mock_response = MagicMock()
        mock_response.choices[
            0
        ].message.content = '{"action": "human_review", "reason": "ambiguous context", "confidence": "low"}'
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        ctx = self._make_ambiguous_ctx()
        result = await _gpt_fallback(ctx, mock_client)

        assert result.decided_by == "gpt"
        assert result.action in [
            "follow_up",
            "retry_call",
            "schedule_call",
            "close_lead",
            "human_review",
        ]

    @pytest.mark.asyncio
    async def test_pipeline_calls_gpt_when_no_rule_matches(self):
        """run_next_action_pipeline invokes GPT when all rules return None."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.analysis.universal.next_action import run_next_action_pipeline

        ctx = self._make_ambiguous_ctx()
        mock_client = MagicMock()

        mock_result_from_gpt = MagicMock()
        mock_result_from_gpt.action = "human_review"
        mock_result_from_gpt.reason = "ambiguous"
        mock_result_from_gpt.confidence = "low"
        mock_result_from_gpt.decided_by = "gpt"
        mock_result_from_gpt.next_action_at = None
        mock_result_from_gpt.priority = "normal"

        with patch(
            "app.analysis.universal.next_action._gpt_fallback",
            AsyncMock(return_value=mock_result_from_gpt),
        ) as mock_gpt:
            result = await run_next_action_pipeline(ctx, mock_client)
            mock_gpt.assert_called_once_with(ctx, mock_client)
            assert result.decided_by == "gpt"

    @pytest.mark.asyncio
    async def test_pipeline_validates_rules_with_gpt(self):
        """run_next_action_pipeline calls GPT validation when a rule fires."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.analysis.universal.next_action import run_next_action_pipeline
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
            NextActionResult,
        )
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        # Hard stop context — P1 fires immediately
        ctx = NextActionContext(
            outcome=CallOutcome(
                classification="do_not_contact", reason="test", confidence="high"
            ),
            interest_level=80,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        mock_client = MagicMock()

        # GPT validation agrees with rules decision
        validated_result = NextActionResult(
            action="close_lead",
            reason="Hard stop: outcome classification is 'do_not_contact' [GPT validated: agreed]",
            confidence="high",
            decided_by="rules",
        )

        with patch(
            "app.analysis.universal.next_action._gpt_validate_rules_decision",
            AsyncMock(return_value=validated_result),
        ) as mock_validate:
            result = await run_next_action_pipeline(ctx, mock_client)
            mock_validate.assert_called_once()
            assert result.action == "close_lead"
            assert result.decided_by == "rules"

    @pytest.mark.asyncio
    async def test_pipeline_falls_back_gracefully_when_validation_fails(self):
        """If GPT validation fails, rules decision is trusted as-is."""
        from unittest.mock import AsyncMock, MagicMock
        from app.analysis.universal.next_action import (
            run_next_action_pipeline,
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis

        ctx = NextActionContext(
            outcome=CallOutcome(
                classification="do_not_contact", reason="test", confidence="high"
            ),
            interest_level=0,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(call_count=1, do_not_call=False, last_called_at=None),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )

        # Simulate GPT validation raising an exception — should fall back gracefully
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("OpenAI timeout")
        )

        result = await run_next_action_pipeline(ctx, mock_client)
        # Should still return the rules decision despite GPT failure
        assert result.action == "close_lead"
        assert result.decided_by == "rules"


class TestDimensionModulesExports:
    """next_action removed from DIMENSION_MODULES; new symbols exported."""

    def test_next_action_not_in_dimension_modules(self):
        """DIMENSION_MODULES does not contain next_action module."""
        from app.analysis.universal import DIMENSION_MODULES

        module_names = [mod.__name__ for mod in DIMENSION_MODULES]
        assert "app.analysis.universal.next_action" not in module_names

    def test_dimension_modules_has_six_entries(self):
        """DIMENSION_MODULES has exactly 6 entries after removing next_action."""
        from app.analysis.universal import DIMENSION_MODULES

        assert len(DIMENSION_MODULES) == 6

    def test_next_action_result_exported_from_universal(self):
        """NextActionResult is accessible from app.analysis.universal."""
        from app.analysis.universal import NextActionResult

        assert NextActionResult is not None

    def test_run_next_action_pipeline_exported_from_universal(self):
        """run_next_action_pipeline is accessible from app.analysis.universal."""
        from app.analysis.universal import run_next_action_pipeline

        assert run_next_action_pipeline is not None


class TestSchemaNextActionResult:
    """PostCallAnalysis schema has next_action_result field."""

    def test_post_call_analysis_has_next_action_result_field(self):
        """PostCallAnalysis has next_action_result: dict | None = None."""
        from app.analysis.schema import PostCallAnalysis

        analysis = PostCallAnalysis()
        assert hasattr(analysis, "next_action_result")
        assert analysis.next_action_result is None
