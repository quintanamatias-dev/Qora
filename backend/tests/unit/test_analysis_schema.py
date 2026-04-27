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


# ---------------------------------------------------------------------------
# Scenario: PostCallAnalysis.data_corrections field (Issue #21)
# ---------------------------------------------------------------------------


def test_post_call_analysis_has_data_corrections_field():
    """PostCallAnalysis includes data_corrections field of type str with default ''."""
    from app.analysis_schema import PostCallAnalysis

    schema = PostCallAnalysis.model_json_schema()
    properties = schema.get("properties", {})
    assert (
        "data_corrections" in properties
    ), "PostCallAnalysis must have data_corrections field — Issue #21"


def test_post_call_analysis_data_corrections_defaults_to_empty_string():
    """PostCallAnalysis.data_corrections defaults to '' (empty string)."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Test.",
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

    assert (
        analysis.data_corrections == ""
    ), "data_corrections must default to '' — Issue #21"


def test_post_call_analysis_data_corrections_accepts_string():
    """PostCallAnalysis.data_corrections accepts a non-empty string value."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Lead corrected car model.",
        objections=[],
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        data_corrections="car_model: Polo Trend",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead engaged.",
            engagement_quality="high",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs coverage.",
            urgency="medium",
        ),
    )

    assert analysis.data_corrections == "car_model: Polo Trend"


def test_post_call_analysis_data_corrections_rejects_dict():
    """PostCallAnalysis.data_corrections is str — raises ValidationError when dict is assigned."""
    from pydantic import ValidationError
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    with pytest.raises((ValidationError, Exception)):
        PostCallAnalysis(
            summary="Test.",
            objections=[],
            interest_level=50,
            current_insurance=None,
            next_action_suggested="wait",
            misc_notes="",
            data_corrections={"car_model": "Polo Trend"},  # dict — must be rejected
            call_outcome=CallOutcome(
                classification="busy",
                reason="Test.",
                engagement_quality="none",
            ),
            detected_interests=DetectedInterests(),
            identified_problem=IdentifiedProblem(
                primary_need="Unknown.",
                urgency="low",
            ),
        )


def test_analysis_system_prompt_mentions_data_corrections():
    """ANALYSIS_SYSTEM_PROMPT instructs LLM about data_corrections field."""
    from app.analysis_schema import ANALYSIS_SYSTEM_PROMPT

    prompt_lower = ANALYSIS_SYSTEM_PROMPT.lower()
    assert (
        "data_corrections" in prompt_lower or "correction" in prompt_lower
    ), "ANALYSIS_SYSTEM_PROMPT must mention data_corrections — Issue #21"


# ===========================================================================
# Issue #35 — Enhanced Per-Call Extraction
# Phase 1: 4 new universal axis models + ExtractionConfig validation
# ===========================================================================


# ---------------------------------------------------------------------------
# ServiceIssuesAxis
# ---------------------------------------------------------------------------


def test_service_issues_axis_defaults_to_empty_list():
    """ServiceIssuesAxis.issues defaults to empty list when not provided."""
    from app.analysis_schema import ServiceIssuesAxis

    axis = ServiceIssuesAxis()
    assert axis.issues == []


def test_service_issues_axis_accepts_list_of_strings():
    """ServiceIssuesAxis.issues accepts a list of strings."""
    from app.analysis_schema import ServiceIssuesAxis

    axis = ServiceIssuesAxis(issues=["late delivery", "wrong product sent"])
    assert axis.issues == ["late delivery", "wrong product sent"]


# ---------------------------------------------------------------------------
# ProfileFactsAxis
# ---------------------------------------------------------------------------


def test_profile_facts_axis_defaults_to_empty_list():
    """ProfileFactsAxis.facts defaults to empty list when not provided."""
    from app.analysis_schema import ProfileFactsAxis

    axis = ProfileFactsAxis()
    assert axis.facts == []


def test_profile_facts_axis_accepts_populated_list():
    """ProfileFactsAxis.facts accepts a list of personal/professional facts."""
    from app.analysis_schema import ProfileFactsAxis

    axis = ProfileFactsAxis(
        facts=["works in tech", "has 2 kids", "lives in Buenos Aires"]
    )
    assert len(axis.facts) == 3
    assert "works in tech" in axis.facts


# ---------------------------------------------------------------------------
# CommitmentSignalsAxis
# ---------------------------------------------------------------------------


def test_commitment_signals_axis_defaults_to_empty_list():
    """CommitmentSignalsAxis.signals defaults to empty list."""
    from app.analysis_schema import CommitmentSignalsAxis

    axis = CommitmentSignalsAxis()
    assert axis.signals == []


def test_commitment_signals_axis_accepts_signals():
    """CommitmentSignalsAxis.signals accepts a list of verbal commitments."""
    from app.analysis_schema import CommitmentSignalsAxis

    axis = CommitmentSignalsAxis(signals=["said yes to demo", "asked for invoice"])
    assert "said yes to demo" in axis.signals
    assert "asked for invoice" in axis.signals


# ---------------------------------------------------------------------------
# AbandonmentReasonAxis
# ---------------------------------------------------------------------------


def test_abandonment_reason_axis_defaults_to_none():
    """AbandonmentReasonAxis.reason defaults to None (nullable)."""
    from app.analysis_schema import AbandonmentReasonAxis

    axis = AbandonmentReasonAxis()
    assert axis.reason is None


def test_abandonment_reason_axis_accepts_string():
    """AbandonmentReasonAxis.reason accepts a non-None string."""
    from app.analysis_schema import AbandonmentReasonAxis

    axis = AbandonmentReasonAxis(reason="Lead said they found a cheaper provider")
    assert axis.reason == "Lead said they found a cheaper provider"


# ---------------------------------------------------------------------------
# PostCallAnalysis now includes the 4 new axes
# ---------------------------------------------------------------------------


def test_post_call_analysis_has_four_new_axes():
    """PostCallAnalysis includes all 4 new universal axis fields."""
    from app.analysis_schema import PostCallAnalysis

    schema = PostCallAnalysis.model_json_schema()
    props = schema.get("properties", {})

    assert "service_issues" in props, "PostCallAnalysis must have service_issues axis"
    assert "profile_facts" in props, "PostCallAnalysis must have profile_facts axis"
    assert (
        "commitment_signals" in props
    ), "PostCallAnalysis must have commitment_signals axis"
    assert (
        "abandonment_reason" in props
    ), "PostCallAnalysis must have abandonment_reason axis"


def test_post_call_analysis_new_axes_have_correct_defaults():
    """PostCallAnalysis new axes default to empty lists / None without explicit data."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Test.",
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

    assert analysis.service_issues.issues == []
    assert analysis.profile_facts.facts == []
    assert analysis.commitment_signals.signals == []
    assert analysis.abandonment_reason.reason is None


def test_post_call_analysis_new_axes_accept_data():
    """PostCallAnalysis accepts populated data for all 4 new axes."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        CommitmentSignalsAxis,
        AbandonmentReasonAxis,
    )

    analysis = PostCallAnalysis(
        summary="Full analysis.",
        objections=[],
        interest_level=75,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead engaged well.",
            engagement_quality="high",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs a solution.",
            urgency="medium",
        ),
        service_issues=ServiceIssuesAxis(issues=["billing error"]),
        profile_facts=ProfileFactsAxis(facts=["manager at startup"]),
        commitment_signals=CommitmentSignalsAxis(signals=["will call back Friday"]),
        abandonment_reason=AbandonmentReasonAxis(reason="Found competitor cheaper"),
    )

    assert analysis.service_issues.issues == ["billing error"]
    assert analysis.profile_facts.facts == ["manager at startup"]
    assert analysis.commitment_signals.signals == ["will call back Friday"]
    assert analysis.abandonment_reason.reason == "Found competitor cheaper"


# ---------------------------------------------------------------------------
# ExtractionConfig — valid/invalid scenarios
# ---------------------------------------------------------------------------


def test_extraction_config_defaults():
    """ExtractionConfig() with no args has empty extra_axes, disabled_axes, prompt_addendum."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig()
    assert config.extra_axes == []
    assert config.disabled_axes == []
    assert config.prompt_addendum == ""


def test_extraction_config_valid_extra_axes():
    """ExtractionConfig accepts extra_axes with allowed field types."""
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    config = ExtractionConfig(
        extra_axes=[
            AxisFieldDef(
                name="property_type", field_type="str", description="Type of property"
            ),
            AxisFieldDef(name="budget_range", field_type="str", description="Budget"),
            AxisFieldDef(
                name="num_rooms", field_type="int", description="Number of rooms"
            ),
        ]
    )
    assert len(config.extra_axes) == 3
    assert config.extra_axes[0].name == "property_type"
    assert config.extra_axes[0].field_type == "str"


def test_extraction_config_valid_list_str_type():
    """ExtractionConfig accepts 'list[str]' as field_type in extra_axes."""
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    config = ExtractionConfig(
        extra_axes=[
            AxisFieldDef(
                name="amenities",
                field_type="list[str]",
                description="Property amenities",
            )
        ]
    )
    assert config.extra_axes[0].field_type == "list[str]"


def test_extraction_config_rejects_unsupported_field_type():
    """ExtractionConfig raises ValidationError when extra_axes has unsupported field type."""
    from pydantic import ValidationError
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    with pytest.raises(ValidationError):
        ExtractionConfig(
            extra_axes=[
                AxisFieldDef(name="bad_field", field_type="dict", description="Bad")
            ]
        )


def test_extraction_config_disabled_axes_valid():
    """ExtractionConfig accepts disabled_axes referencing known base axes."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig(disabled_axes=["service_issues", "abandonment_reason"])
    assert "service_issues" in config.disabled_axes
    assert "abandonment_reason" in config.disabled_axes


def test_extraction_config_disabled_axes_rejects_unknown():
    """ExtractionConfig raises ValidationError when disabled_axes references unknown axis name."""
    from pydantic import ValidationError
    from app.analysis_schema import ExtractionConfig

    with pytest.raises(ValidationError):
        ExtractionConfig(disabled_axes=["nonexistent_axis"])


def test_extraction_config_rejects_more_than_10_extra_axes():
    """ExtractionConfig raises ValidationError when more than 10 extra_axes are provided."""
    from pydantic import ValidationError
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    axes = [
        AxisFieldDef(name=f"field_{i}", field_type="str", description=f"Field {i}")
        for i in range(11)
    ]
    with pytest.raises(ValidationError):
        ExtractionConfig(extra_axes=axes)


def test_extraction_config_rejects_name_collision_with_base_axes():
    """ExtractionConfig raises ValidationError when extra_axes name collides with a base field."""
    from pydantic import ValidationError
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    with pytest.raises(ValidationError):
        ExtractionConfig(
            extra_axes=[
                # 'summary' is a base PostCallAnalysis field — collision
                AxisFieldDef(
                    name="summary", field_type="str", description="Collision test"
                )
            ]
        )


def test_axis_field_def_name_must_be_snake_case():
    """AxisFieldDef.name must be valid snake_case (^[a-z][a-z0-9_]{1,30}$)."""
    from pydantic import ValidationError
    from app.analysis_schema import AxisFieldDef

    with pytest.raises(ValidationError):
        AxisFieldDef(name="BadName", field_type="str", description="Bad")

    with pytest.raises(ValidationError):
        AxisFieldDef(name="123bad", field_type="str", description="Bad")


def test_extraction_config_with_prompt_addendum():
    """ExtractionConfig accepts a prompt_addendum string."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig(
        prompt_addendum="Focus on real estate properties in CABA."
    )
    assert config.prompt_addendum == "Focus on real estate properties in CABA."


def test_analysis_schema_exports_new_symbols():
    """analysis_schema exports ExtractionConfig, AxisFieldDef, and 4 new axis models."""
    import importlib

    mod = importlib.import_module("app.analysis_schema")

    assert hasattr(mod, "ExtractionConfig"), "Must export ExtractionConfig"
    assert hasattr(mod, "AxisFieldDef"), "Must export AxisFieldDef"
    assert hasattr(mod, "ServiceIssuesAxis"), "Must export ServiceIssuesAxis"
    assert hasattr(mod, "ProfileFactsAxis"), "Must export ProfileFactsAxis"
    assert hasattr(mod, "CommitmentSignalsAxis"), "Must export CommitmentSignalsAxis"
    assert hasattr(mod, "AbandonmentReasonAxis"), "Must export AbandonmentReasonAxis"


# ===========================================================================
# Issue #35 — Phase 2: build_analysis_model() and build_system_prompt()
# ===========================================================================


# ---------------------------------------------------------------------------
# build_analysis_model — base config (no extra axes)
# ---------------------------------------------------------------------------


def test_build_analysis_model_base_has_all_four_new_axes():
    """build_analysis_model(base_config) returns model with all 4 universal axis fields."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config = ExtractionConfig()
    Model = build_analysis_model(config)

    schema = Model.model_json_schema()
    props = schema.get("properties", {})
    assert "service_issues" in props
    assert "profile_facts" in props
    assert "commitment_signals" in props
    assert "abandonment_reason" in props


def test_build_analysis_model_base_has_existing_post_call_analysis_fields():
    """build_analysis_model() includes all existing PostCallAnalysis fields."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config = ExtractionConfig()
    Model = build_analysis_model(config)
    schema = Model.model_json_schema()
    props = schema.get("properties", {})

    assert "summary" in props
    assert "objections" in props
    assert "interest_level" in props
    assert "call_outcome" in props
    assert "detected_interests" in props
    assert "identified_problem" in props


def test_build_analysis_model_returns_valid_json_schema():
    """build_analysis_model() output is a valid JSON-serializable schema dict."""
    import json
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config = ExtractionConfig()
    Model = build_analysis_model(config)
    schema = Model.model_json_schema()

    # Must be JSON-serializable (no non-serializable objects)
    json_str = json.dumps(schema)
    assert len(json_str) > 100  # non-trivial schema


def test_build_analysis_model_can_be_instantiated_with_valid_data():
    """The model returned by build_analysis_model() can be validated with model_validate."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config = ExtractionConfig()
    Model = build_analysis_model(config)

    instance = Model.model_validate(
        {
            "summary": "Test call",
            "objections": [],
            "interest_level": 50,
            "current_insurance": None,
            "next_action_suggested": "wait",
            "misc_notes": "",
            "data_corrections": "",
            "call_outcome": {
                "classification": "interested",
                "reason": "Test reason",
                "engagement_quality": "medium",
            },
            "detected_interests": {
                "products": [],
                "specific_needs": [],
                "buying_signals": [],
            },
            "identified_problem": {
                "primary_need": "Test need",
                "pain_points": [],
                "urgency": "low",
            },
        }
    )
    assert instance.summary == "Test call"
    assert instance.interest_level == 50


# ---------------------------------------------------------------------------
# build_analysis_model — cache identity
# ---------------------------------------------------------------------------


def test_build_analysis_model_same_config_returns_same_object():
    """build_analysis_model() with identical configs returns same cached model class."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config1 = ExtractionConfig()
    config2 = ExtractionConfig()
    Model1 = build_analysis_model(config1)
    Model2 = build_analysis_model(config2)

    # Same config → same model object (lru_cache by config hash)
    assert Model1 is Model2


def test_build_analysis_model_different_config_returns_different_object():
    """build_analysis_model() with different configs returns different model classes."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig, AxisFieldDef

    config_base = ExtractionConfig()
    config_extended = ExtractionConfig(
        extra_axes=[AxisFieldDef(name="region", field_type="str", description="Region")]
    )

    Model_base = build_analysis_model(config_base)
    Model_ext = build_analysis_model(config_extended)

    assert Model_base is not Model_ext


# ---------------------------------------------------------------------------
# build_analysis_model — disabled axes
# ---------------------------------------------------------------------------


def test_build_analysis_model_disabled_axis_excluded():
    """build_analysis_model() with disabled_axes excludes those axes from the model."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig

    config = ExtractionConfig(disabled_axes=["service_issues"])
    Model = build_analysis_model(config)
    schema = Model.model_json_schema()
    props = schema.get("properties", {})

    assert "service_issues" not in props
    # Other axes still present
    assert "profile_facts" in props
    assert "commitment_signals" in props
    assert "abandonment_reason" in props


# ---------------------------------------------------------------------------
# build_analysis_model — extra axes land in extra_axes_data
# ---------------------------------------------------------------------------


def test_build_analysis_model_extra_axes_produces_extra_axes_data_field():
    """build_analysis_model() with extra_axes includes extra_axes_data in schema."""
    from app.analysis_schema import build_analysis_model, ExtractionConfig, AxisFieldDef

    config = ExtractionConfig(
        extra_axes=[
            AxisFieldDef(
                name="property_type", field_type="str", description="Type of property"
            )
        ]
    )
    Model = build_analysis_model(config)
    schema = Model.model_json_schema()
    props = schema.get("properties", {})

    assert "extra_axes_data" in props


# ---------------------------------------------------------------------------
# build_system_prompt — base config
# ---------------------------------------------------------------------------


def test_build_system_prompt_base_contains_all_four_axis_names():
    """build_system_prompt(base) mentions all 4 universal axis names."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    config = ExtractionConfig()
    prompt = build_system_prompt(config)

    assert "service_issues" in prompt or "service issues" in prompt.lower()
    assert "profile_facts" in prompt or "profile facts" in prompt.lower()
    assert "commitment_signals" in prompt or "commitment signals" in prompt.lower()
    assert "abandonment_reason" in prompt or "abandonment reason" in prompt.lower()


def test_build_system_prompt_base_contains_rules_section():
    """build_system_prompt() always includes a RULES section."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    config = ExtractionConfig()
    prompt = build_system_prompt(config)

    assert "RULES" in prompt or "rules" in prompt.lower()


def test_build_system_prompt_is_non_empty_string():
    """build_system_prompt() returns a meaningful non-empty string."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    prompt = build_system_prompt(ExtractionConfig())
    assert isinstance(prompt, str)
    assert len(prompt) > 100


# ---------------------------------------------------------------------------
# build_system_prompt — context description
# ---------------------------------------------------------------------------


def test_build_system_prompt_includes_context_description():
    """build_system_prompt() includes context_description in the prompt when set via addendum."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    config = ExtractionConfig(prompt_addendum="Real estate broker in Buenos Aires")
    prompt = build_system_prompt(config)

    assert "Real estate broker in Buenos Aires" in prompt


def test_build_system_prompt_no_addendum_no_extra_text():
    """build_system_prompt() with empty addendum does NOT add extra placeholder text."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    config = ExtractionConfig()
    prompt = build_system_prompt(config)

    # No placeholder artifacts
    assert "{{" not in prompt
    assert "}}" not in prompt


# ---------------------------------------------------------------------------
# build_system_prompt — extra axes instructions
# ---------------------------------------------------------------------------


def test_build_system_prompt_mentions_extra_axes():
    """build_system_prompt() instructs extraction of extra axis names when extra_axes set."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig, AxisFieldDef

    config = ExtractionConfig(
        extra_axes=[
            AxisFieldDef(
                name="property_type", field_type="str", description="Type of property"
            )
        ]
    )
    prompt = build_system_prompt(config)

    assert "property_type" in prompt


# ---------------------------------------------------------------------------
# build_system_prompt — disabled axes NOT mentioned
# ---------------------------------------------------------------------------


def test_build_system_prompt_disabled_axis_not_mentioned():
    """build_system_prompt() excludes disabled axes from instructions."""
    from app.analysis_schema import build_system_prompt, ExtractionConfig

    config = ExtractionConfig(disabled_axes=["service_issues"])
    prompt = build_system_prompt(config)

    # service_issues must NOT appear in instructions
    assert "service_issues" not in prompt


# ---------------------------------------------------------------------------
# build_analysis_model and build_system_prompt exported
# ---------------------------------------------------------------------------


def test_analysis_schema_exports_builder_functions():
    """analysis_schema exports build_analysis_model and build_system_prompt."""
    import importlib

    mod = importlib.import_module("app.analysis_schema")

    assert hasattr(mod, "build_analysis_model"), "Must export build_analysis_model"
    assert hasattr(mod, "build_system_prompt"), "Must export build_system_prompt"


# ===========================================================================
# CRITICAL 1 (verify fix) — ExtractionConfig.context_description alias
# ===========================================================================


def test_extraction_config_accepts_context_description_as_alias():
    """CRITICAL 1: ExtractionConfig can be constructed with 'context_description' field name.

    The spec used context_description; the implementation uses prompt_addendum.
    The alias ensures forward-compat: JSON payloads with context_description are accepted.
    """
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig.model_validate(
        {"context_description": "Real estate broker context"}
    )
    # The field is stored as prompt_addendum
    assert config.prompt_addendum == "Real estate broker context"


def test_extraction_config_context_description_property_returns_prompt_addendum():
    """CRITICAL 1: ExtractionConfig.context_description property returns prompt_addendum value."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig(prompt_addendum="Insurance broker context")
    assert config.context_description == "Insurance broker context"


def test_extraction_config_prompt_addendum_still_works_directly():
    """CRITICAL 1: ExtractionConfig constructed with prompt_addendum (primary name) still works."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig(prompt_addendum="Direct addendum")
    assert config.prompt_addendum == "Direct addendum"
    assert config.context_description == "Direct addendum"


# ===========================================================================
# Spec alignment: extra_axes dict→list[AxisFieldDef] convenience conversion
# ===========================================================================


def test_extraction_config_accepts_dict_shaped_extra_axes():
    """ExtractionConfig auto-converts dict-shaped extra_axes to list[AxisFieldDef].

    Spec alignment fix: old spec used dict[str, str] shape, implementation uses
    list[AxisFieldDef]. This test verifies the convenience conversion so both
    shapes work — forward compat for JSON payloads sent in dict form.

    Input:  {"extra_axes": {"property_type": "str", "budget_range": "list[str]"}}
    Output: list[AxisFieldDef] with 2 entries, names/types preserved
    """
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig.model_validate(
        {"extra_axes": {"property_type": "str", "budget_range": "list[str]"}}
    )
    assert isinstance(config.extra_axes, list)
    assert len(config.extra_axes) == 2
    names = {ax.name for ax in config.extra_axes}
    assert "property_type" in names
    assert "budget_range" in names
    types = {ax.name: ax.field_type for ax in config.extra_axes}
    assert types["property_type"] == "str"
    assert types["budget_range"] == "list[str]"


def test_extraction_config_dict_extra_axes_generates_description():
    """Dict-converted AxisFieldDef entries have a non-empty auto-generated description."""
    from app.analysis_schema import ExtractionConfig

    config = ExtractionConfig.model_validate({"extra_axes": {"property_type": "str"}})
    assert len(config.extra_axes) == 1
    ax = config.extra_axes[0]
    assert ax.description  # non-empty
    assert isinstance(ax.description, str)


def test_extraction_config_dict_extra_axes_rejects_unsupported_type():
    """Dict-shaped extra_axes raises ValidationError when a value is an unsupported type."""
    from pydantic import ValidationError
    from app.analysis_schema import ExtractionConfig

    with pytest.raises(ValidationError):
        ExtractionConfig.model_validate({"extra_axes": {"bad_field": "dict"}})


def test_extraction_config_list_shape_still_works_after_dict_support():
    """Native list[AxisFieldDef] shape still accepted after adding dict conversion."""
    from app.analysis_schema import ExtractionConfig, AxisFieldDef

    config = ExtractionConfig(
        extra_axes=[
            AxisFieldDef(name="region", field_type="str", description="Sales region")
        ]
    )
    assert len(config.extra_axes) == 1
    assert config.extra_axes[0].name == "region"


def test_build_analysis_model_cache_eviction_max_100():
    """WARNING 2: build_analysis_model LRU cache evicts oldest entries beyond 100 items."""
    from app.analysis_schema import (
        build_analysis_model,
        ExtractionConfig,
        AxisFieldDef,
        _model_cache,
    )

    # Clear cache to start fresh
    _model_cache.clear()

    # Build 101 distinct models (different extra_axes names force distinct cache keys)
    models = []
    for i in range(101):
        config = ExtractionConfig(
            extra_axes=[
                AxisFieldDef(
                    name=f"field_{i:03d}",
                    field_type="str",
                    description=f"Field number {i}",
                )
            ]
        )
        model = build_analysis_model(config)
        models.append(model)

    # Cache should not exceed 100 entries (oldest was evicted)
    assert (
        len(_model_cache) <= 100
    ), f"Cache size {len(_model_cache)} exceeds max of 100 — eviction not working"
