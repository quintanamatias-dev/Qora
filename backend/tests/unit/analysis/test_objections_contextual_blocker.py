"""Unit tests for current_provider objection boundary — TDD RED phase.

Acceptance criteria from spec: call-analysis-dimensions — Objection as
Contextual Sales Blocker.

Tasks 1.3 → 1.4 (PR 1)

Scenarios covered:
- Prompt contains explicit contextual sales blocker / traba language
- Prompt requires resistance/friction framing, not bare mention
- Prompt boundary: neutral mention NOT an objection
- Prompt boundary: contextual blocker IS an objection
- Schema: current_provider remains a valid ObjectionCategory
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Task 1.3 — Prompt contains contextual sales blocker guidance
# ---------------------------------------------------------------------------


def test_objections_prompt_mentions_sales_blocker_or_traba():
    """Prompt MUST contain explicit contextual blocker / traba language for current_provider."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    # The prompt must contain language about contextual friction / sales blocker
    blocker_terms = ["blocker", "traba", "sales blocker", "contextual", "resist"]
    has_blocker_language = any(term in prompt.lower() for term in blocker_terms)
    assert has_blocker_language, (
        f"Prompt must contain contextual sales blocker / traba language. "
        f"Checked terms: {blocker_terms}. Prompt excerpt: {prompt[:500]}"
    )


def test_objections_prompt_rejects_neutral_mention_for_current_provider():
    """Prompt MUST explicitly state that neutral mentions of current provider are NOT objections."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    # Should say something like "mere mention" or "mention ≠ objection" or "neutral mention"
    neutral_terms = [
        "neutral mention",
        "mere mention",
        "mention alone",
        "just mention",
        "only mention",
        "not a mere mention",
        "not just mention",
        "mention is not",
        "mention doesn't",
    ]
    has_neutral_exclusion = any(term in prompt.lower() for term in neutral_terms)
    assert has_neutral_exclusion, (
        f"Prompt must state that neutral mentions of current provider are NOT objections. "
        f"Checked terms: {neutral_terms}"
    )


def test_objections_prompt_requires_resistance_for_current_provider():
    """Prompt MUST require active resistance / friction for current_provider to fire."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    # Should contain language about resistance, friction, or using provider as reason to reject/slow
    resistance_terms = [
        "resistance",
        "resist",
        "slow down",
        "reason to",
        "as a reason",
        "reluctance",
        "pushback",
        "friction",
    ]
    has_resistance = any(term in prompt.lower() for term in resistance_terms)
    assert has_resistance, (
        f"Prompt must require resistance/friction for current_provider to be classified "
        f"as an objection. Checked terms: {resistance_terms}"
    )


def test_objections_prompt_contextual_blocker_example_present():
    """Prompt MUST contain an example of contextual sales blocker framing."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    # The spec says the boundary is: using current provider as a reason to RESIST/SLOW the sale.
    # The prompt should have a concrete example or reference such framing.
    example_terms = [
        "no vale la pena",
        "recién cambié",
        "estoy bien con",
        "no me apuro",
        "no necesito moverme",
        "no me interesa cambiar",
    ]
    has_example = any(term in prompt for term in example_terms)
    assert has_example, (
        f"Prompt must contain at least one contextual blocker example. "
        f"Checked phrases: {example_terms}"
    )


# ---------------------------------------------------------------------------
# Task 1.3 — current_provider remains a valid ObjectionCategory
# ---------------------------------------------------------------------------


def test_current_provider_remains_valid_category():
    """ObjectionCategory must still include 'current_provider' after the boundary tightening."""
    from app.analysis.universal.objections import Objection

    from pydantic import ValidationError

    # Should NOT raise — current_provider is still valid
    obj = Objection(
        category="current_provider",
        strength="medium",
        resolution_status="unresolved",
        evidence="recién cambié hace 6 meses, no vale la pena moverme",
        description="Lead uses current provider as reason to resist the sale.",
        confidence="high",
    )
    assert obj.category == "current_provider"


def test_current_provider_contextual_blocker_is_medium_strength():
    """An objection with contextual blocker framing is valid with strength=medium."""
    from app.analysis.universal.objections import Objection

    obj = Objection(
        category="current_provider",
        strength="medium",
        resolution_status="unresolved",
        evidence="recién cambié hace 6 meses, no me apuro",
        description="Lead uses recent switch as reason to delay.",
        confidence="high",
        is_primary=True,
    )
    assert obj.strength == "medium"
    assert obj.is_primary is True


def test_current_provider_explicit_rejection_is_high_strength():
    """An objection with strong explicit rejection framing is valid with strength=high."""
    from app.analysis.universal.objections import Objection

    obj = Objection(
        category="current_provider",
        strength="high",
        resolution_status="unresolved",
        evidence="X me cubre bien, no necesito moverme",
        description="Lead explicitly rejects offer, citing current provider satisfaction.",
        confidence="high",
    )
    assert obj.strength == "high"


# ---------------------------------------------------------------------------
# Task 1.3 — Prompt distinction: satisfaction as motivator vs. objection
# ---------------------------------------------------------------------------


def test_objections_prompt_clarifies_satisfaction_vs_resistance():
    """Prompt MUST distinguish 'dissatisfied with current provider' (pain) from
    'satisfied with current provider as reason to reject' (current_provider objection)."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    # The existing DO NOT block covers this partially; the new guidance should
    # explicitly address when current_provider fires vs. when it doesn't.
    # Checking for the key conceptual distinction in the prompt.
    assert "current_provider" in prompt, "Prompt must reference current_provider category"

    # The prompt should contain guidance that mere provider mention is insufficient
    # (the updated prompt should have this distinction)
    assert "REJECT" in prompt or "reject" in prompt or "resistance" in prompt.lower(), (
        "Prompt must reference rejection/resistance as condition for current_provider"
    )
