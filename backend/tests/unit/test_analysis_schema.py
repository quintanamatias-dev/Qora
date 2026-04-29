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


def test_analysis_schema_no_app_imports():
    """app.analysis package only imports pydantic and enum — no foreign app dependencies.

    The schema lives in ``app/analysis/`` (split into enums, schema, universal/).
    Internal cross-imports between these submodules are allowed; what must stay
    forbidden is FastAPI, SQLAlchemy, structlog, or any non-analysis ``app.*``
    module so the package remains copy-pastable into other runtimes.
    """
    import ast
    import pathlib

    package_root = (
        pathlib.Path(__file__).parent.parent.parent / "app" / "analysis"
    )
    forbidden_prefixes = ("fastapi", "sqlalchemy", "structlog")
    allowed_app_prefix = "app.analysis"

    for py_file in package_root.rglob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
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
                        f"{py_file} must not import '{module_name}' — "
                        f"found forbidden prefix '{prefix}'"
                    )
                if module_name.startswith("app.") and not module_name.startswith(
                    allowed_app_prefix
                ):
                    raise AssertionError(
                        f"{py_file} must not import '{module_name}' — only "
                        f"'app.analysis.*' internal imports are permitted"
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
# Scenario: Edge cases — defaults, extra fields, model_config
# ---------------------------------------------------------------------------


def test_post_call_analysis_constructs_with_no_args():
    """PostCallAnalysis() with no args is valid — every field has a default.

    This is a deliberate architectural choice for the per-dimension pipeline:
    asyncio.gather(return_exceptions=True) leaves a failed dimension's field
    unset, and PostCallAnalysis(**fields) must still validate so the caller
    can persist a partial analysis.
    """
    from app.analysis_schema import PostCallAnalysis

    analysis = PostCallAnalysis()
    assert analysis.summary == ""
    assert analysis.objections == []
    assert analysis.interest_level == 0
    assert analysis.next_action_suggested == "wait"


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


# ===========================================================================
# Issue #35 — Enhanced Per-Call Extraction
# Phase 1: 4 new universal axis models
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


# ===========================================================================
# Per-dimension analyze() coroutine — every module must have one
# ===========================================================================


@pytest.mark.parametrize(
    "mod",
    [
        __import__("app.analysis.universal.summary", fromlist=["x"]),
        __import__("app.analysis.universal.objections", fromlist=["x"]),
        __import__("app.analysis.universal.interest_level", fromlist=["x"]),
        __import__("app.analysis.universal.next_action", fromlist=["x"]),
        __import__("app.analysis.universal.misc_notes", fromlist=["x"]),
        __import__("app.analysis.universal.data_corrections", fromlist=["x"]),
        __import__("app.analysis.universal.outcome", fromlist=["x"]),
        __import__("app.analysis.universal.interests", fromlist=["x"]),
        __import__("app.analysis.universal.problem", fromlist=["x"]),
        __import__("app.analysis.universal.service_issues", fromlist=["x"]),
        __import__("app.analysis.universal.profile_facts", fromlist=["x"]),
        __import__("app.analysis.universal.commitments", fromlist=["x"]),
        __import__("app.analysis.universal.abandonment", fromlist=["x"]),
    ],
    ids=lambda m: m.DIMENSION["name"],
)
def test_dimension_module_contract(mod):
    """Every dimension module exposes DIMENSION dict, target_field, and async analyze()."""
    import inspect
    from app.analysis import PostCallAnalysis

    assert hasattr(mod, "DIMENSION"), f"{mod.__name__} must define DIMENSION"
    assert hasattr(mod, "analyze"), f"{mod.__name__} must define analyze()"
    assert inspect.iscoroutinefunction(mod.analyze), "analyze must be async"

    dim = mod.DIMENSION
    for key in ("name", "schema", "target_field", "prompt", "model"):
        assert key in dim, f"{mod.__name__}.DIMENSION missing key: {key}"

    target = dim["target_field"]
    assert (
        target in PostCallAnalysis.model_fields
    ), f"{mod.__name__} target_field {target!r} is not a PostCallAnalysis field"


def test_dimension_modules_cover_all_post_call_analysis_fields():
    """Every PostCallAnalysis field is owned by exactly one dimension module."""
    from app.analysis import PostCallAnalysis
    from app.analysis.universal import DIMENSION_MODULES

    target_fields = [mod.DIMENSION["target_field"] for mod in DIMENSION_MODULES]
    assert len(target_fields) == len(set(target_fields)), (
        f"Duplicate target_field across dimensions: {target_fields}"
    )
    expected = set(PostCallAnalysis.model_fields.keys())
    assert set(target_fields) == expected, (
        f"Mismatch — extra: {set(target_fields) - expected}, "
        f"missing: {expected - set(target_fields)}"
    )


@pytest.mark.asyncio
async def test_dimension_analyze_returns_unwrapped_value_for_simple_axes():
    """Simple-wrapper analyze() returns the inner primitive, not the axis model."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal import (
        SummaryAxis,
        ObjectionsAxis,
        InterestLevelAxis,
        NextActionAxis,
        MiscNotesAxis,
        DataCorrectionsAxis,
        summary as summary_mod,
        objections as objections_mod,
        interest_level as interest_level_mod,
        next_action as next_action_mod,
        misc_notes as misc_notes_mod,
        data_corrections as data_corrections_mod,
    )

    cases = [
        (summary_mod, SummaryAxis(text="hi"), str, "hi"),
        (objections_mod, ObjectionsAxis(items=["p"]), list, ["p"]),
        (interest_level_mod, InterestLevelAxis(score=42), int, 42),
        (next_action_mod, NextActionAxis(action="wait"), str, "wait"),
        (misc_notes_mod, MiscNotesAxis(notes="ok"), str, "ok"),
        (data_corrections_mod, DataCorrectionsAxis(corrections=""), str, ""),
    ]
    for mod, parsed, expected_type, expected_value in cases:
        client = AsyncMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.parsed = parsed
        client.beta.chat.completions.parse = AsyncMock(return_value=response)
        result = await mod.analyze("transcript", client)
        assert isinstance(result, expected_type), (
            f"{mod.__name__}.analyze returned {type(result)}, expected {expected_type}"
        )
        assert result == expected_value


@pytest.mark.asyncio
async def test_dimension_analyze_returns_axis_for_complex_axes():
    """Complex-axis analyze() returns the parsed axis model unchanged."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal import (
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        CommitmentSignalsAxis,
        AbandonmentReasonAxis,
        outcome as outcome_mod,
        interests as interests_mod,
        problem as problem_mod,
        service_issues as service_issues_mod,
        profile_facts as profile_facts_mod,
        commitments as commitments_mod,
        abandonment as abandonment_mod,
    )

    cases = [
        (
            outcome_mod,
            CallOutcome(classification="busy", reason="r", engagement_quality="none"),
        ),
        (interests_mod, DetectedInterests()),
        (problem_mod, IdentifiedProblem(primary_need="n", urgency="low")),
        (service_issues_mod, ServiceIssuesAxis()),
        (profile_facts_mod, ProfileFactsAxis()),
        (commitments_mod, CommitmentSignalsAxis()),
        (abandonment_mod, AbandonmentReasonAxis()),
    ]
    for mod, parsed in cases:
        client = AsyncMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.parsed = parsed
        client.beta.chat.completions.parse = AsyncMock(return_value=response)
        result = await mod.analyze("transcript", client)
        assert result is parsed


def test_dimension_modules_iteration_order_is_stable():
    """DIMENSION_MODULES order is stable so the summarizer fan-out is deterministic."""
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert names == [
        "summary",
        "objections",
        "interest_level",
        "next_action",
        "misc_notes",
        "data_corrections",
        "outcome",
        "interests",
        "problem",
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    ]
