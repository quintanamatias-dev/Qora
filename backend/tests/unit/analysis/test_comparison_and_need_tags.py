"""Unit tests for comparison reclassification and NEED_TAGS enforcement — TDD RED phase.

Acceptance criteria from spec: call-analysis-dimensions
- Comparison behavior classified as interests (COMPARANDO_OPCIONES), not pain_points
- NEED_TAGS allowlist includes COMPARANDO_OPCIONES and 'other' fallback
- Interests prompt enforces NEED_TAGS; no free-form near-duplicate tags
- PainPointCategory does NOT include 'comparison' (removed from taxonomy)
- problem.py prompt does not reference 'comparison' as a valid pain category

Tasks 1.5 → 1.6 (PR 1)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Task 1.5 — comparison NOT in PainPointCategory after this change
# ---------------------------------------------------------------------------


def test_comparison_not_valid_pain_category():
    """PainPoint MUST NOT accept 'comparison' as a valid category after PR 1."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(
            category="comparison",  # Must be invalid after this change
            description="Lead is comparing options",
            evidence="estoy comparando precios con varias aseguradoras",
            urgency="medium",
            confidence="high",
        )


def test_problem_prompt_does_not_list_comparison():
    """problem.py DIMENSION prompt MUST NOT list 'comparison' as a valid pain category."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    # Prompt should not offer comparison as a valid pain category option
    # We check the specific instruction line that lists categories
    # The old line: "- category: one of cost, coverage, renewal, ..., comparison, ..."
    # After removal, 'comparison' must not appear in that list as a valid option
    lines = prompt.split("\n")
    category_lines = [
        line for line in lines if "- category: one of" in line or "comparison" in line.lower()
    ]
    # If comparison appears in the prompt, it must only be in the DO NOT or BOUNDARY context
    # (i.e., "DO NOT classify comparison as pain_points")
    comparison_lines = [
        line for line in lines if "comparison" in line.lower()
    ]
    for line in comparison_lines:
        # Must not appear as a valid category enumeration
        assert "one of" not in line, (
            f"'comparison' must not appear in the valid category list. Line: {line!r}"
        )


def test_pain_categories_count_after_comparison_removal():
    """PainPointCategory Literal MUST have 10 values (was 11; comparison removed)."""
    from app.analysis.universal.problem import PainPointCategory
    import typing

    # Get the args of the Literal type
    args = typing.get_args(PainPointCategory)
    assert len(args) == 10, (
        f"PainPointCategory must have 10 values after removing 'comparison'. "
        f"Got {len(args)}: {args}"
    )
    assert "comparison" not in args, (
        "'comparison' must not be a valid PainPointCategory after PR 1"
    )


# ---------------------------------------------------------------------------
# Task 1.5 — COMPARANDO_OPCIONES in NEED_TAGS
# ---------------------------------------------------------------------------


def test_need_tags_contains_comparando_opciones():
    """NEED_TAGS MUST contain 'COMPARANDO_OPCIONES' after this change."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert "COMPARANDO_OPCIONES" in NEED_TAGS, (
        "'COMPARANDO_OPCIONES' must be in NEED_TAGS allowlist"
    )


def test_need_tags_contains_other_fallback():
    """NEED_TAGS MUST contain 'other' as a fallback tag for unmatched interests."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert "other" in NEED_TAGS, (
        "'other' fallback tag must be in NEED_TAGS"
    )


def test_need_tags_count_after_additions():
    """NEED_TAGS MUST have 10 values after adding COMPARANDO_OPCIONES and 'other' (was 8)."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert len(NEED_TAGS) == 10, (
        f"NEED_TAGS must have 10 values after adding COMPARANDO_OPCIONES and 'other'. "
        f"Got {len(NEED_TAGS)}: {NEED_TAGS}"
    )


# ---------------------------------------------------------------------------
# Task 1.5 — Interests prompt mentions COMPARANDO_OPCIONES
# ---------------------------------------------------------------------------


def test_interests_prompt_contains_comparando_opciones():
    """Interests DIMENSION prompt MUST contain 'COMPARANDO_OPCIONES' as a valid NEED_TAG."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert "COMPARANDO_OPCIONES" in DIMENSION["prompt"], (
        "Interests prompt must list 'COMPARANDO_OPCIONES' as a valid NEED_TAG"
    )


def test_interests_prompt_contains_other_tag():
    """Interests DIMENSION prompt MUST contain 'other' as a fallback NEED_TAG."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert "other" in DIMENSION["prompt"], (
        "Interests prompt must list 'other' as a fallback NEED_TAG"
    )


# ---------------------------------------------------------------------------
# Task 1.5 — problem.py prompt contains DO NOT / BOUNDARY for comparison
# ---------------------------------------------------------------------------


def test_problem_prompt_routes_comparison_to_interests():
    """problem.py prompt MUST route comparison behavior to interests, not pain_points."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    # The prompt should instruct the model to route comparison behavior to interests
    routing_terms = [
        "interests",
        "interest",
        "COMPARANDO_OPCIONES",
        "interest dimension",
        "comparison",
    ]
    # At minimum, comparison and routing to interests should be mentioned
    has_comparison_routing = "comparison" in prompt.lower() and (
        "interest" in prompt.lower() or "COMPARANDO_OPCIONES" in prompt
    )
    assert has_comparison_routing, (
        "problem.py prompt must route comparison behavior to interests. "
        "It should mention 'comparison' and 'interests' or 'COMPARANDO_OPCIONES'"
    )


# ---------------------------------------------------------------------------
# Task 1.5 — Triangulation: known pain categories still valid after removal
# ---------------------------------------------------------------------------


def test_cost_pain_category_still_valid():
    """'cost' must still be a valid PainPointCategory after comparison removal."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(
        category="cost",
        description="Lead quiere pagar menos",
        evidence="El seguro es muy caro",
        urgency="medium",
        confidence="high",
    )
    assert pp.category == "cost"


def test_dissatisfaction_pain_category_still_valid():
    """'dissatisfaction' must still be a valid PainPointCategory after comparison removal."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(
        category="dissatisfaction",
        description="Lead está insatisfecho con su proveedor actual",
        evidence="No estoy conforme con el servicio",
        urgency="low",
        confidence="medium",
    )
    assert pp.category == "dissatisfaction"
