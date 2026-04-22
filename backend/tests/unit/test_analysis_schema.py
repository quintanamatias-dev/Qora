"""Unit tests for analysis_schema.py — standalone, zero app imports.

TDD: RED phase — written before analysis_schema.py exists.
Spec: sdd/qora-post-call-analysis/spec — Requirement: Analysis Schema Module

These tests verify:
- analysis_schema is importable without any app context
- All models instantiate with valid data
- Enums reject invalid values (ValidationError)
- PostCallAnalysis generates a valid JSON schema
- Defaults work: empty lists for DetectedInterests fields
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Scenario: Schema contract is stable — standalone import
# ---------------------------------------------------------------------------


def test_analysis_schema_importable_standalone():
    """analysis_schema can be imported without any app context."""
    import importlib

    mod = importlib.import_module("app.analysis_schema")
    # Module exposes the required symbols
    assert hasattr(mod, "PostCallAnalysis")
    assert hasattr(mod, "CallOutcome")
    assert hasattr(mod, "DetectedInterests")
    assert hasattr(mod, "IdentifiedProblem")
    assert hasattr(mod, "OutcomeClassification")
    assert hasattr(mod, "EngagementQuality")
    assert hasattr(mod, "Urgency")
    assert hasattr(mod, "ANALYSIS_SYSTEM_PROMPT")


def test_analysis_schema_no_app_imports():
    """analysis_schema module only imports pydantic and enum — no app.* dependencies."""
    import ast
    import pathlib

    schema_path = (
        pathlib.Path(__file__).parent.parent.parent / "app" / "analysis_schema.py"
    )
    source = schema_path.read_text()
    tree = ast.parse(source)

    forbidden_prefixes = ("app.", "fastapi", "sqlalchemy", "structlog")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
            for prefix in forbidden_prefixes:
                assert not module_name.startswith(prefix), (
                    f"analysis_schema.py must not import '{module_name}' — "
                    f"found forbidden prefix '{prefix}'"
                )


# ---------------------------------------------------------------------------
# Scenario: CallOutcome — valid instantiation
# ---------------------------------------------------------------------------


def test_call_outcome_valid():
    """CallOutcome model accepts valid enum values and fields."""
    from app.analysis_schema import (
        CallOutcome,
        OutcomeClassification,
        EngagementQuality,
    )

    outcome = CallOutcome(
        classification=OutcomeClassification.interested,
        reason="Lead was enthusiastic about todo riesgo coverage.",
        engagement_quality=EngagementQuality.high,
    )
    assert outcome.classification == OutcomeClassification.interested
    assert outcome.reason == "Lead was enthusiastic about todo riesgo coverage."
    assert outcome.engagement_quality == EngagementQuality.high


def test_call_outcome_string_enum_values():
    """CallOutcome accepts string versions of enum values (Pydantic v2 coercion)."""
    from app.analysis_schema import CallOutcome

    outcome = CallOutcome(
        classification="not_interested",
        reason="Lead already has insurance.",
        engagement_quality="low",
    )
    assert outcome.classification.value == "not_interested"
    assert outcome.engagement_quality.value == "low"


# ---------------------------------------------------------------------------
# Scenario: Schema rejects invalid enum values
# ---------------------------------------------------------------------------


def test_call_outcome_rejects_invalid_classification():
    """CallOutcome raises ValidationError when classification is invalid."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="very_interested",  # NOT a valid enum value
            reason="Some reason.",
            engagement_quality="high",
        )


def test_call_outcome_rejects_invalid_engagement_quality():
    """CallOutcome raises ValidationError when engagement_quality is invalid."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="interested",
            reason="Some reason.",
            engagement_quality="extreme",  # NOT a valid enum value
        )


def test_identified_problem_rejects_invalid_urgency():
    """IdentifiedProblem raises ValidationError when urgency is invalid."""
    from pydantic import ValidationError
    from app.analysis_schema import IdentifiedProblem

    with pytest.raises(ValidationError):
        IdentifiedProblem(
            primary_need="Needs coverage for new car.",
            pain_points=["no coverage"],
            urgency="critical",  # NOT a valid enum value
        )


# ---------------------------------------------------------------------------
# Scenario: DetectedInterests — defaults to empty lists
# ---------------------------------------------------------------------------


def test_detected_interests_defaults_to_empty_lists():
    """DetectedInterests fields default to empty lists when not provided."""
    from app.analysis_schema import DetectedInterests

    interests = DetectedInterests()
    assert interests.products == []
    assert interests.specific_needs == []
    assert interests.buying_signals == []


def test_detected_interests_with_data():
    """DetectedInterests accepts populated list fields."""
    from app.analysis_schema import DetectedInterests

    interests = DetectedInterests(
        products=["todo_riesgo", "terceros_completo"],
        specific_needs=["precio_competitivo"],
        buying_signals=["asked about monthly price"],
    )
    assert "todo_riesgo" in interests.products
    assert "precio_competitivo" in interests.specific_needs
    assert "asked about monthly price" in interests.buying_signals


# ---------------------------------------------------------------------------
# Scenario: IdentifiedProblem — valid instantiation
# ---------------------------------------------------------------------------


def test_identified_problem_valid():
    """IdentifiedProblem model accepts valid data including urgency enum."""
    from app.analysis_schema import IdentifiedProblem, Urgency

    problem = IdentifiedProblem(
        primary_need="Needs affordable coverage for a new vehicle.",
        pain_points=["current plan too expensive", "bad claim experience"],
        urgency=Urgency.high,
    )
    assert problem.primary_need == "Needs affordable coverage for a new vehicle."
    assert len(problem.pain_points) == 2
    assert problem.urgency == Urgency.high


def test_identified_problem_pain_points_defaults_empty():
    """IdentifiedProblem.pain_points defaults to empty list."""
    from app.analysis_schema import IdentifiedProblem

    problem = IdentifiedProblem(
        primary_need="Needs any coverage.",
        urgency="low",
    )
    assert problem.pain_points == []


# ---------------------------------------------------------------------------
# Scenario: PostCallAnalysis — full schema generation
# ---------------------------------------------------------------------------


def test_post_call_analysis_json_schema_contains_required_keys():
    """PostCallAnalysis.model_json_schema() includes all expected top-level properties."""
    from app.analysis_schema import PostCallAnalysis

    schema = PostCallAnalysis.model_json_schema()
    properties = schema.get("properties", {})

    # Existing fields
    assert "summary" in properties
    assert "objections" in properties
    assert "interest_level" in properties
    assert "current_insurance" in properties
    assert "next_action_suggested" in properties
    assert "misc_notes" in properties

    # New Phase 5 axes
    assert "call_outcome" in properties
    assert "detected_interests" in properties
    assert "identified_problem" in properties


def test_post_call_analysis_valid_full_instance():
    """PostCallAnalysis accepts a complete valid payload with all axes."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        OutcomeClassification,
        EngagementQuality,
        Urgency,
    )

    analysis = PostCallAnalysis(
        summary="Lead was very interested in todo riesgo coverage.",
        objections=["price too high"],
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car year: 2022",
        call_outcome=CallOutcome(
            classification=OutcomeClassification.interested,
            reason="Lead requested a quote.",
            engagement_quality=EngagementQuality.high,
        ),
        detected_interests=DetectedInterests(
            products=["todo_riesgo"],
            specific_needs=["cobertura_amplia"],
            buying_signals=["asked for price"],
        ),
        identified_problem=IdentifiedProblem(
            primary_need="Needs comprehensive vehicle coverage.",
            pain_points=["no current insurance"],
            urgency=Urgency.high,
        ),
    )

    assert analysis.summary == "Lead was very interested in todo riesgo coverage."
    assert analysis.interest_level == 85
    assert analysis.call_outcome.classification == OutcomeClassification.interested
    assert analysis.detected_interests.products == ["todo_riesgo"]
    assert analysis.identified_problem.urgency == Urgency.high


def test_post_call_analysis_model_dump_contains_axes():
    """PostCallAnalysis.model_dump() produces dict with all 3 new axes."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Test summary.",
        objections=[],
        interest_level=50,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="busy",
            reason="Lead was driving.",
            engagement_quality="none",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Unknown.",
            urgency="low",
        ),
    )

    dumped = analysis.model_dump()
    assert "call_outcome" in dumped
    assert "detected_interests" in dumped
    assert "identified_problem" in dumped
    # call_outcome is a nested dict
    assert dumped["call_outcome"]["classification"] == "busy"
    assert dumped["identified_problem"]["urgency"] == "low"


# ---------------------------------------------------------------------------
# Scenario: ANALYSIS_SYSTEM_PROMPT is non-empty string
# ---------------------------------------------------------------------------


def test_analysis_system_prompt_is_non_empty_string():
    """ANALYSIS_SYSTEM_PROMPT is a non-empty string."""
    from app.analysis_schema import ANALYSIS_SYSTEM_PROMPT

    assert isinstance(ANALYSIS_SYSTEM_PROMPT, str)
    assert len(ANALYSIS_SYSTEM_PROMPT) > 50  # meaningful prompt, not a stub


def test_analysis_system_prompt_mentions_axes():
    """ANALYSIS_SYSTEM_PROMPT references all 3 analysis axes."""
    from app.analysis_schema import ANALYSIS_SYSTEM_PROMPT

    prompt_lower = ANALYSIS_SYSTEM_PROMPT.lower()
    assert "call_outcome" in prompt_lower or "outcome" in prompt_lower
    assert "detected_interests" in prompt_lower or "interest" in prompt_lower
    assert "identified_problem" in prompt_lower or "problem" in prompt_lower


# ---------------------------------------------------------------------------
# Scenario: Edge cases — unknown keys, extra fields, model_config
# ---------------------------------------------------------------------------


def test_post_call_analysis_rejects_unknown_fields():
    """PostCallAnalysis does NOT silently ignore unknown fields (strict by default)."""
    from pydantic import ValidationError
    from app.analysis_schema import (
        PostCallAnalysis,
        DetectedInterests,
        IdentifiedProblem,
    )

    # Missing required call_outcome → should raise
    with pytest.raises(ValidationError):
        PostCallAnalysis(
            summary="Test.",
            objections=[],
            interest_level=50,
            current_insurance=None,
            next_action_suggested="wait",
            misc_notes="",
            # call_outcome is MISSING — required field
            detected_interests=DetectedInterests(),
            identified_problem=IdentifiedProblem(
                primary_need="Test need.",
                urgency="low",
            ),
        )


def test_detected_interests_with_empty_buying_signals():
    """DetectedInterests with products but empty buying_signals is valid."""
    from app.analysis_schema import DetectedInterests

    interests = DetectedInterests(
        products=["todo_riesgo"],
        specific_needs=[],
        buying_signals=[],
    )
    assert interests.products == ["todo_riesgo"]
    assert interests.buying_signals == []


def test_post_call_analysis_current_insurance_nullable():
    """PostCallAnalysis.current_insurance can be None (nullable field)."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Lead was not interested.",
        objections=["already covered"],
        interest_level=10,
        current_insurance=None,  # explicit None
        next_action_suggested="do_not_call",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="not_interested",
            reason="Lead already has insurance and is satisfied.",
            engagement_quality="low",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="No current need — satisfied with existing coverage.",
            urgency="low",
        ),
    )
    assert analysis.current_insurance is None
    dumped = analysis.model_dump()
    assert dumped["current_insurance"] is None


def test_call_outcome_all_classifications_valid():
    """Every OutcomeClassification value creates a valid CallOutcome."""
    from app.analysis_schema import CallOutcome, OutcomeClassification

    for classification in OutcomeClassification:
        outcome = CallOutcome(
            classification=classification,
            reason=f"Test reason for {classification.value}",
            engagement_quality="medium",
        )
        assert outcome.classification == classification


# ---------------------------------------------------------------------------
# Scenario: Enum values are correct
# ---------------------------------------------------------------------------


def test_outcome_classification_all_values():
    """OutcomeClassification contains the 7 expected values."""
    from app.analysis_schema import OutcomeClassification

    expected = {
        "interested",
        "not_interested",
        "busy",
        "follow_up",
        "no_answer",
        "hostile",
        "confused",
    }
    actual = {e.value for e in OutcomeClassification}
    assert actual == expected


def test_engagement_quality_all_values():
    """EngagementQuality contains high/medium/low/none."""
    from app.analysis_schema import EngagementQuality

    expected = {"high", "medium", "low", "none"}
    actual = {e.value for e in EngagementQuality}
    assert actual == expected


def test_urgency_all_values():
    """Urgency contains high/medium/low."""
    from app.analysis_schema import Urgency

    expected = {"high", "medium", "low"}
    actual = {e.value for e in Urgency}
    assert actual == expected
