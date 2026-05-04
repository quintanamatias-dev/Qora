"""Unit tests for objections dimension — TDD RED phase.

Phase 1: Schema foundation (tasks 1.1 → 1.3)
Phase 2: Prompt + analyze() contract (tasks 2.1 → 2.3)

Categories (Issue #45):
    price, current_provider, timing, authority, trust, need,
    information_gap, coverage_or_product_fit, payment_or_budget,
    documentation_or_data, channel_preference, bad_experience,
    hard_rejection, other

Resolution statuses (Issue #45):
    resolved, partially_resolved, unresolved, bypassed, unknown
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers / fixture data builders
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = [
    "price",
    "current_provider",
    "timing",
    "authority",
    "trust",
    "need",
    "information_gap",
    "coverage_or_product_fit",
    "payment_or_budget",
    "documentation_or_data",
    "channel_preference",
    "bad_experience",
    "hard_rejection",
    "other",
]

_VALID_STATUSES = [
    "resolved",
    "partially_resolved",
    "unresolved",
    "bypassed",
    "unknown",
]


def _make_objection(**overrides):
    """Return a valid Objection kwargs dict; callers can override any field."""
    base = {
        "category": "price",
        "strength": "medium",
        "resolution_status": "unresolved",
        "evidence": "El precio me parece muy alto",
        "description": "Lead thinks the price is too high.",
        "confidence": "high",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Phase 1: Schema foundation
# ===========================================================================

# ---------------------------------------------------------------------------
# 1.1 — All 14 ObjectionCategory values are accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", _VALID_CATEGORIES)
def test_objection_accepts_all_14_categories(category):
    """Objection model accepts each of the 14 valid category values."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection(category=category))
    assert obj.category == category


def test_objection_rejects_invalid_category():
    """Objection raises ValidationError for a category not in the 14 valid values."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(category="too_expensive"))


# ---------------------------------------------------------------------------
# 1.2 — All 5 ResolutionStatus values are accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _VALID_STATUSES)
def test_objection_accepts_all_5_resolution_statuses(status):
    """Objection model accepts each of the 5 valid resolution_status values."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection(resolution_status=status))
    assert obj.resolution_status == status


def test_objection_rejects_invalid_resolution_status():
    """Objection raises ValidationError for a status not in the 5 valid values."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(resolution_status="dismissed"))


# ---------------------------------------------------------------------------
# 1.3 — Required fields: all 6 must be present
# ---------------------------------------------------------------------------


def test_objection_all_required_fields_present():
    """Objection accepts an instance with all 6 required fields."""
    from app.analysis.universal.objections import Objection

    obj = Objection(
        category="trust",
        strength="high",
        resolution_status="partially_resolved",
        evidence="No confío en las aseguradoras",
        description="Lead expressed distrust in insurance companies.",
        confidence="medium",
    )
    assert obj.category == "trust"
    assert obj.strength == "high"
    assert obj.resolution_status == "partially_resolved"
    assert obj.evidence == "No confío en las aseguradoras"
    assert obj.description == "Lead expressed distrust in insurance companies."
    assert obj.confidence == "medium"


def test_objection_missing_required_field_raises():
    """Objection raises ValidationError when a required field is missing (evidence)."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(
            category="price",
            strength="low",
            resolution_status="unresolved",
            # evidence is missing — required
            description="Lead mentioned price.",
            confidence="low",
        )


# ---------------------------------------------------------------------------
# 1.4 — Optional fields default correctly
# ---------------------------------------------------------------------------


def test_objection_optional_fields_default():
    """Optional fields agent_response_summary and is_primary have correct defaults."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection())
    assert obj.agent_response_summary == ""
    assert obj.is_primary is False


def test_objection_is_primary_can_be_set_true():
    """is_primary can be explicitly set to True."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection(is_primary=True))
    assert obj.is_primary is True


def test_objection_agent_response_summary_can_be_set():
    """agent_response_summary accepts a non-empty string."""
    from app.analysis.universal.objections import Objection

    obj = Objection(
        **_make_objection(agent_response_summary="Agent explained value proposition.")
    )
    assert obj.agent_response_summary == "Agent explained value proposition."


# ---------------------------------------------------------------------------
# 1.5 — Empty evidence/description validation (min_length=1)
# ---------------------------------------------------------------------------


def test_objection_empty_evidence_raises():
    """Empty evidence string raises ValidationError (min_length=1)."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(evidence=""))


def test_objection_empty_description_raises():
    """Empty description string raises ValidationError (min_length=1)."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(description=""))


# ---------------------------------------------------------------------------
# 1.6 — ObjectionsAxis wrapper: max_length=5, defaults to empty list
# ---------------------------------------------------------------------------


def test_objections_axis_defaults_to_empty_list():
    """ObjectionsAxis() with no arguments yields an empty objections list."""
    from app.analysis.universal.objections import ObjectionsAxis

    axis = ObjectionsAxis()
    assert axis.objections == []


def test_objections_axis_accepts_exactly_5():
    """ObjectionsAxis accepts exactly 5 Objection objects (boundary — valid)."""
    from app.analysis.universal.objections import Objection, ObjectionsAxis

    items = [
        Objection(**_make_objection(category=cat)) for cat in _VALID_CATEGORIES[:5]
    ]
    axis = ObjectionsAxis(objections=items)
    assert len(axis.objections) == 5


def test_objections_axis_rejects_6():
    """ObjectionsAxis raises ValidationError when given 6 Objection objects (max_length=5)."""
    from app.analysis.universal.objections import Objection, ObjectionsAxis

    items = [
        Objection(**_make_objection(category=cat)) for cat in _VALID_CATEGORIES[:6]
    ]
    with pytest.raises(ValidationError):
        ObjectionsAxis(objections=items)


def test_objections_axis_is_primary_accessible():
    """ObjectionsAxis preserves is_primary flag on contained Objections."""
    from app.analysis.universal.objections import Objection, ObjectionsAxis

    obj = Objection(**_make_objection(is_primary=True))
    axis = ObjectionsAxis(objections=[obj])
    assert axis.objections[0].is_primary is True


# ---------------------------------------------------------------------------
# 1.7 — Strength and confidence Literal validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strength", ["low", "medium", "high"])
def test_objection_accepts_all_strength_values(strength):
    """Objection accepts low/medium/high for strength."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection(strength=strength))
    assert obj.strength == strength


def test_objection_rejects_invalid_strength():
    """Objection raises ValidationError for unknown strength value."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(strength="extreme"))


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_objection_accepts_all_confidence_values(confidence):
    """Objection accepts low/medium/high for confidence."""
    from app.analysis.universal.objections import Objection

    obj = Objection(**_make_objection(confidence=confidence))
    assert obj.confidence == confidence


def test_objection_rejects_invalid_confidence():
    """Objection raises ValidationError for unknown confidence value."""
    from app.analysis.universal.objections import Objection

    with pytest.raises(ValidationError):
        Objection(**_make_objection(confidence="certain"))


# ===========================================================================
# Phase 2: Prompt + analyze() contract
# ===========================================================================

# ---------------------------------------------------------------------------
# 2.1 — DIMENSION dict contract
# ---------------------------------------------------------------------------


def test_dimension_dict_contract():
    """DIMENSION dict has correct name, target_field, schema, and model."""
    from app.analysis.universal.objections import DIMENSION, ObjectionsAxis

    assert DIMENSION["name"] == "objections"
    assert DIMENSION["target_field"] == "objections"
    assert DIMENSION["schema"] is ObjectionsAxis
    assert DIMENSION["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 2.2 — Prompt contains all 14 categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", _VALID_CATEGORIES)
def test_prompt_contains_all_14_categories(category):
    """DIMENSION['prompt'] contains each of the 14 category strings verbatim."""
    from app.analysis.universal.objections import DIMENSION

    assert category in DIMENSION["prompt"], f"Prompt is missing category: {category}"


# ---------------------------------------------------------------------------
# 2.3 — Prompt contains all 5 resolution statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _VALID_STATUSES)
def test_prompt_contains_all_5_resolution_statuses(status):
    """DIMENSION['prompt'] contains each of the 5 resolution_status strings verbatim."""
    from app.analysis.universal.objections import DIMENSION

    assert (
        status in DIMENSION["prompt"]
    ), f"Prompt is missing resolution status: {status}"


# ---------------------------------------------------------------------------
# 2.4 — Prompt contains field-level guidance
# ---------------------------------------------------------------------------


def test_prompt_mentions_evidence_confidence_strength():
    """Prompt references evidence, confidence, and strength field names."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "evidence" in prompt, "Prompt must reference 'evidence'"
    assert "confidence" in prompt, "Prompt must reference 'confidence'"
    assert "strength" in prompt, "Prompt must reference 'strength'"


def test_prompt_contains_max_5_and_empty_guidance():
    """Prompt mentions the max 5 cap and empty array fallback."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "5" in prompt, "Prompt must mention max 5 constraint"
    # Accept either 'empty' or '[]' as the empty fallback indicator
    assert (
        "empty" in prompt or "[]" in prompt
    ), "Prompt must mention empty array fallback"


# ---------------------------------------------------------------------------
# 2.5 — Prompt contains exclusion guidance (DO NOT block)
# ---------------------------------------------------------------------------


def test_prompt_contains_exclusion_language():
    """Prompt includes at least one negation/exclusion phrase."""
    from app.analysis.universal.objections import DIMENSION

    prompt = DIMENSION["prompt"]
    exclusion_words = ["not", "don't", "DO NOT", "never", "NEVER"]
    has_exclusion = any(w in prompt for w in exclusion_words)
    assert (
        has_exclusion
    ), f"Prompt must contain exclusion guidance (one of: {exclusion_words})"


# ---------------------------------------------------------------------------
# 2.6 — analyze() returns ObjectionsAxis (mocked client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_returns_objections_axis():
    """analyze() returns the full ObjectionsAxis, not an unwrapped list."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.objections import analyze, ObjectionsAxis

    expected = ObjectionsAxis(
        objections=[
            {
                "category": "price",
                "strength": "high",
                "resolution_status": "unresolved",
                "evidence": "El precio es muy alto",
                "description": "Lead considers the price too high.",
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
        result, ObjectionsAxis
    ), f"analyze() must return ObjectionsAxis, got {type(result)}"
    assert result is expected


@pytest.mark.asyncio
async def test_analyze_returns_empty_objections_axis():
    """analyze() with empty result returns ObjectionsAxis with empty list."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.objections import analyze, ObjectionsAxis

    expected = ObjectionsAxis()  # empty

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("greeting only", client)

    assert isinstance(result, ObjectionsAxis)
    assert result.objections == []
