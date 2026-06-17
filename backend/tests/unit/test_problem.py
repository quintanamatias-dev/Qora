"""Unit tests for problem dimension — TDD RED phase.

Phase 1: Schema foundation (tasks 1.1 → 1.3)
Phase 2: Prompt + analyze() contract (tasks 2.1 → 2.2)

Categories (Issue #52 — generic taxonomy):
    cost, coverage, renewal, bad_experience, lack_of_clarity,
    new_need, risk_exposure, comparison, deadline, dissatisfaction, other
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers / fixture data builders
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = [
    "cost",
    "coverage",
    "renewal",
    "bad_experience",
    "lack_of_clarity",
    "new_need",
    "risk_exposure",
    # "comparison" REMOVED — post-call-analysis-bi-friendly PR 1.
    # Comparison behavior routes to interests as COMPARANDO_OPCIONES, not pain_points.
    "deadline",
    "dissatisfaction",
    "other",
]

_VALID_URGENCIES = ["low", "medium", "high", "unknown"]
_VALID_CONFIDENCES = ["low", "medium", "high"]


def _make_pain_point(**overrides):
    """Return a valid PainPoint kwargs dict; callers can override any field."""
    base = {
        "category": "cost",
        "description": "El lead quiere pagar menos por su seguro",
        "evidence": "Quiero pagar menos, el seguro actual es muy caro",
        "urgency": "medium",
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Phase 1: Schema foundation
# ===========================================================================

# ---------------------------------------------------------------------------
# 1.1 — All 11 PainPointCategory values are accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", _VALID_CATEGORIES)
def test_pain_point_accepts_all_10_categories(category):
    """PainPoint model accepts each of the 10 valid category values (comparison removed)."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point(category=category))
    assert pp.category == category


def test_pain_point_rejects_invalid_category():
    """PainPoint raises ValidationError for a category not in the 10 valid values."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(category="unknown_cat"))


def test_pain_point_rejects_comparison_after_pr1():
    """'comparison' MUST NOT be a valid PainPointCategory (removed in PR 1)."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(category="comparison"))


# ---------------------------------------------------------------------------
# 1.1 — PainUrgency: low/medium/high/unknown (4 values)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("urgency", _VALID_URGENCIES)
def test_pain_point_accepts_all_4_urgency_values(urgency):
    """PainPoint accepts low/medium/high/unknown for urgency."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point(urgency=urgency))
    assert pp.urgency == urgency


def test_pain_point_rejects_invalid_urgency():
    """PainPoint raises ValidationError for unknown urgency value."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(urgency="critical"))


# ---------------------------------------------------------------------------
# 1.1 — PainConfidence: low/medium/high (3 values)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", _VALID_CONFIDENCES)
def test_pain_point_accepts_all_3_confidence_values(confidence):
    """PainPoint accepts low/medium/high for confidence."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point(confidence=confidence))
    assert pp.confidence == confidence


def test_pain_point_rejects_invalid_confidence():
    """PainPoint raises ValidationError for unknown confidence value."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(confidence="certain"))


# ---------------------------------------------------------------------------
# 1.1 — Required fields: min_length=1 for description and evidence
# ---------------------------------------------------------------------------


def test_pain_point_empty_description_raises():
    """Empty description string raises ValidationError (min_length=1)."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(description=""))


def test_pain_point_empty_evidence_raises():
    """Empty evidence string raises ValidationError (min_length=1)."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError):
        PainPoint(**_make_pain_point(evidence=""))


# ---------------------------------------------------------------------------
# 1.1 — is_primary: defaults False, can be True
# ---------------------------------------------------------------------------


def test_pain_point_is_primary_defaults_false():
    """PainPoint.is_primary defaults to False when not provided."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point())
    assert pp.is_primary is False


def test_pain_point_is_primary_can_be_set_true():
    """is_primary can be explicitly set to True."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point(is_primary=True))
    assert pp.is_primary is True


# ---------------------------------------------------------------------------
# 1.1 — No id field on PainPoint (AD-7)
# ---------------------------------------------------------------------------


def test_pain_point_has_no_id_field():
    """PainPoint must NOT have an 'id' field (AD-7)."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(**_make_pain_point())
    assert not hasattr(pp, "id"), "PainPoint must NOT have an id field (AD-7)"
    assert "id" not in PainPoint.model_fields


# ---------------------------------------------------------------------------
# 1.2 — ProblemAxis: defaults to empty, accepts 5, rejects 6
# ---------------------------------------------------------------------------


def test_problem_axis_defaults_to_empty_list():
    """ProblemAxis() with no arguments yields an empty pain_points list."""
    from app.analysis.universal.problem import ProblemAxis

    axis = ProblemAxis()
    assert axis.pain_points == []


def test_problem_axis_accepts_exactly_5():
    """ProblemAxis accepts exactly 5 PainPoint objects (boundary — valid)."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    items = [
        PainPoint(**_make_pain_point(category=cat)) for cat in _VALID_CATEGORIES[:5]
    ]
    axis = ProblemAxis(pain_points=items)
    assert len(axis.pain_points) == 5


def test_problem_axis_rejects_6():
    """ProblemAxis raises ValidationError when given 6 PainPoint objects (max_length=5)."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    items = [
        PainPoint(**_make_pain_point(category=cat)) for cat in _VALID_CATEGORIES[:6]
    ]
    with pytest.raises(ValidationError):
        ProblemAxis(pain_points=items)


def test_problem_axis_is_primary_accessible():
    """ProblemAxis preserves is_primary flag on contained PainPoints."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    pp = PainPoint(**_make_pain_point(is_primary=True))
    axis = ProblemAxis(pain_points=[pp])
    assert axis.pain_points[0].is_primary is True


# ---------------------------------------------------------------------------
# 1.2 — Mixed categories + empty axis
# ---------------------------------------------------------------------------


def test_problem_axis_mixed_categories():
    """ProblemAxis accepts multiple PainPoints with different categories."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    items = [
        PainPoint(**_make_pain_point(category="cost")),
        PainPoint(**_make_pain_point(category="bad_experience")),
        PainPoint(**_make_pain_point(category="coverage")),
    ]
    axis = ProblemAxis(pain_points=items)
    assert len(axis.pain_points) == 3
    assert axis.pain_points[0].category == "cost"
    assert axis.pain_points[1].category == "bad_experience"
    assert axis.pain_points[2].category == "coverage"


def test_problem_axis_single_primary_pain():
    """ProblemAxis with one is_primary=True item is valid."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    items = [
        PainPoint(**_make_pain_point(category="cost", is_primary=True)),
        PainPoint(**_make_pain_point(category="dissatisfaction", is_primary=False)),
    ]
    axis = ProblemAxis(pain_points=items)
    primaries = [p for p in axis.pain_points if p.is_primary]
    assert len(primaries) == 1


# ===========================================================================
# Phase 2: Prompt + analyze() contract
# ===========================================================================

# ---------------------------------------------------------------------------
# 2.1 — DIMENSION dict contract
# ---------------------------------------------------------------------------


def test_dimension_dict_contract():
    """DIMENSION dict has correct name, target_field, schema, and model."""
    from app.analysis.universal.problem import DIMENSION, ProblemAxis

    assert DIMENSION["name"] == "problem"
    assert DIMENSION["target_field"] == "identified_problem"
    assert DIMENSION["schema"] is ProblemAxis
    assert DIMENSION["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 2.1 — Prompt contains all 12 categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", _VALID_CATEGORIES)
def test_prompt_contains_all_10_categories(category):
    """DIMENSION['prompt'] contains each of the 10 category strings verbatim (comparison removed)."""
    from app.analysis.universal.problem import DIMENSION

    assert category in DIMENSION["prompt"], f"Prompt is missing category: {category}"


# ---------------------------------------------------------------------------
# 2.1 — Prompt contains field-level guidance
# ---------------------------------------------------------------------------


def test_prompt_mentions_evidence_confidence_urgency():
    """Prompt references evidence, confidence, and urgency field names."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "evidence" in prompt, "Prompt must reference 'evidence'"
    assert "confidence" in prompt, "Prompt must reference 'confidence'"
    assert "urgency" in prompt, "Prompt must reference 'urgency'"


def test_prompt_contains_max_5_constraint():
    """Prompt mentions the max 5 cap."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "5" in prompt, "Prompt must mention max 5 constraint"


def test_prompt_contains_do_not_block_vs_objections():
    """Prompt includes DO NOT block differentiating pain from objections/interests."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    exclusion_words = ["DO NOT", "not", "don't", "NEVER"]
    has_exclusion = any(w in prompt for w in exclusion_words)
    assert has_exclusion, "Prompt must contain exclusion/DO NOT block"


# ---------------------------------------------------------------------------
# 2.1 — Prompt contains boundary examples for overlapping categories
# ---------------------------------------------------------------------------


def test_prompt_contains_bad_experience_boundary():
    """Prompt specifically mentions bad_experience boundary rule vs objections."""
    from app.analysis.universal.problem import DIMENSION

    prompt = DIMENSION["prompt"]
    assert (
        "bad_experience" in prompt
    ), "Prompt must mention bad_experience boundary (vs objections)"


# ---------------------------------------------------------------------------
# 2.2 — analyze() returns typed ProblemAxis (mocked client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_returns_problem_axis():
    """analyze() returns the full ProblemAxis, not an unwrapped list."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.problem import analyze, ProblemAxis

    expected = ProblemAxis(
        pain_points=[
            {
                "category": "cost",
                "description": "Lead quiere pagar menos",
                "evidence": "Me parece muy caro el seguro",
                "urgency": "high",
                "confidence": "high",
            }
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("some transcript", client)

    assert isinstance(
        result, ProblemAxis
    ), f"analyze() must return ProblemAxis, got {type(result)}"
    assert result is expected


@pytest.mark.asyncio
async def test_analyze_returns_empty_problem_axis():
    """analyze() with empty result returns ProblemAxis with empty list."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.problem import analyze, ProblemAxis

    expected = ProblemAxis()  # empty

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("greeting only", client)

    assert isinstance(result, ProblemAxis)
    assert result.pain_points == []


# ===========================================================================
# Phase 5: Integration + isolation tests
# ===========================================================================


def test_pain_point_all_fields_preserved_in_model_dump():
    """PainPoint.model_dump() includes all 6 fields."""
    from app.analysis.universal.problem import PainPoint

    pp = PainPoint(
        category="risk_exposure",
        description="No tiene cobertura adecuada para su situación",
        evidence="Mi situación actual tiene riesgos que no están cubiertos",
        urgency="high",
        confidence="medium",
        is_primary=True,
    )
    dumped = pp.model_dump()
    assert dumped["category"] == "risk_exposure"
    assert dumped["description"] == "No tiene cobertura adecuada para su situación"
    assert (
        dumped["evidence"] == "Mi situación actual tiene riesgos que no están cubiertos"
    )
    assert dumped["urgency"] == "high"
    assert dumped["confidence"] == "medium"
    assert dumped["is_primary"] is True
    assert "id" not in dumped  # AD-7


def test_problem_axis_model_dump_structure():
    """ProblemAxis.model_dump() produces correct structure with pain_points list."""
    from app.analysis.universal.problem import PainPoint, ProblemAxis

    pp = PainPoint(**_make_pain_point(category="cost", is_primary=True))
    axis = ProblemAxis(pain_points=[pp])
    dumped = axis.model_dump()

    assert "pain_points" in dumped
    assert isinstance(dumped["pain_points"], list)
    assert len(dumped["pain_points"]) == 1
    assert dumped["pain_points"][0]["category"] == "cost"
    assert dumped["pain_points"][0]["is_primary"] is True


def test_malformed_category_does_not_corrupt_other_fields():
    """A PainPoint with invalid category fails cleanly with ValidationError."""
    from app.analysis.universal.problem import PainPoint

    with pytest.raises(ValidationError) as exc_info:
        PainPoint(
            category="INVALID",
            description="something",
            evidence="some quote",
            urgency="medium",
            confidence="high",
        )
    # Confirm it's a category error
    errors = exc_info.value.errors()
    assert any(e["loc"] == ("category",) for e in errors)
