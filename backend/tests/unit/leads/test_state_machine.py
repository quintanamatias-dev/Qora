"""Unit tests for Lead state machine — valid and invalid transitions.

RED: References app.leads.models VALID_TRANSITIONS and LeadStatus.
Tests pure logic only — no DB needed.
"""

from __future__ import annotations


from app.leads.models import LeadStatus, VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------


def test_new_can_transition_to_called():
    """new → called is a valid transition."""
    assert LeadStatus.CALLED in VALID_TRANSITIONS[LeadStatus.NEW]


def test_called_can_transition_to_interested():
    """called → interested is a valid transition."""
    assert LeadStatus.INTERESTED in VALID_TRANSITIONS[LeadStatus.CALLED]


def test_called_can_transition_to_not_interested():
    """called → not_interested is a valid transition."""
    assert LeadStatus.NOT_INTERESTED in VALID_TRANSITIONS[LeadStatus.CALLED]


def test_called_can_transition_to_follow_up():
    """called → follow_up is a valid transition."""
    assert LeadStatus.FOLLOW_UP in VALID_TRANSITIONS[LeadStatus.CALLED]


def test_follow_up_can_transition_to_called():
    """follow_up → called is a valid transition (re-call)."""
    assert LeadStatus.CALLED in VALID_TRANSITIONS[LeadStatus.FOLLOW_UP]


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_new_cannot_skip_to_interested():
    """new → interested is NOT a valid transition (must go through called)."""
    assert LeadStatus.INTERESTED not in VALID_TRANSITIONS[LeadStatus.NEW]


def test_new_cannot_skip_to_not_interested():
    """new → not_interested is NOT a valid transition."""
    assert LeadStatus.NOT_INTERESTED not in VALID_TRANSITIONS[LeadStatus.NEW]


def test_new_cannot_skip_to_follow_up():
    """new → follow_up is NOT a valid transition."""
    assert LeadStatus.FOLLOW_UP not in VALID_TRANSITIONS[LeadStatus.NEW]


def test_interested_has_no_further_transitions():
    """interested is a terminal state — no transitions allowed."""
    assert VALID_TRANSITIONS[LeadStatus.INTERESTED] == set()


def test_not_interested_has_no_further_transitions():
    """not_interested is a terminal state — no transitions allowed."""
    assert VALID_TRANSITIONS[LeadStatus.NOT_INTERESTED] == set()


# ---------------------------------------------------------------------------
# is_valid_transition helper
# ---------------------------------------------------------------------------


def test_is_valid_transition_function_returns_true_for_valid():
    """is_valid_transition() returns True for new → called."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition(LeadStatus.NEW, LeadStatus.CALLED) is True


def test_is_valid_transition_function_returns_false_for_invalid():
    """is_valid_transition() returns False for new → not_interested."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition(LeadStatus.NEW, LeadStatus.NOT_INTERESTED) is False


def test_is_valid_transition_handles_string_inputs():
    """is_valid_transition() accepts string status values as well."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition("new", "called") is True
    assert is_valid_transition("new", "interested") is False
