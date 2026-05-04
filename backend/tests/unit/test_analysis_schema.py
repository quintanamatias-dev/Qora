"""Unit tests for analysis_schema.py — standalone, zero app imports.

TDD: RED phase updated for qora-outcome (Issue #50).
Spec: sdd/qora-outcome/spec — Requirement: Call Outcome Classification Schema

These tests verify:
- analysis_schema is importable without any app context
- All models instantiate with valid data
- CallOutcome uses 11 Literal classifications + confidence: Literal["low","medium","high"]
- engagement_quality field MUST NOT exist
- OutcomeClassification/EngagementQuality enums MUST NOT be importable
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
    assert hasattr(mod, "IdentifiedProblem")
    # qora-interest-pipeline: DetectedInterests replaced by InterestsAxis
    assert not hasattr(mod, "DetectedInterests"), (
        "DetectedInterests (old model) must be removed from analysis_schema exports "
        "(qora-interest-pipeline spec — use InterestsAxis instead)"
    )
    # OutcomeClassification and EngagementQuality MUST NOT be exported post-outcome
    assert not hasattr(
        mod, "OutcomeClassification"
    ), "OutcomeClassification must be removed from analysis_schema exports (qora-outcome spec)"
    assert not hasattr(
        mod, "EngagementQuality"
    ), "EngagementQuality must be removed from analysis_schema exports (qora-outcome spec)"
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

    package_root = pathlib.Path(__file__).parent.parent.parent / "app" / "analysis"
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
# Scenario: CallOutcome — 11-classification system (qora-outcome spec)
# ---------------------------------------------------------------------------

_VALID_11_CLASSIFICATIONS = [
    "no_answer",
    "busy",
    "callback_requested",
    "completed_positive",
    "completed_neutral",
    "completed_negative",
    "do_not_contact",
    "wrong_number",
    "hostile",
    "confused",
    "technical_issue",
]


@pytest.mark.parametrize("classification", _VALID_11_CLASSIFICATIONS)
def test_call_outcome_accepts_all_11_classifications(classification):
    """CallOutcome accepts each of the 11 valid Literal classification values."""
    from app.analysis_schema import CallOutcome

    outcome = CallOutcome(
        classification=classification,
        reason=f"Test reason for {classification}",
        confidence="medium",
    )
    assert outcome.classification == classification
    assert outcome.confidence == "medium"
    # engagement_quality must NOT exist
    assert not hasattr(
        outcome, "engagement_quality"
    ), "engagement_quality must be removed from CallOutcome (qora-outcome spec)"


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_call_outcome_accepts_all_confidence_levels(confidence):
    """CallOutcome accepts confidence: 'low', 'medium', 'high'."""
    from app.analysis_schema import CallOutcome

    outcome = CallOutcome(
        classification="completed_positive",
        reason="Lead agreed to purchase.",
        confidence=confidence,
    )
    assert outcome.confidence == confidence


def test_call_outcome_rejects_old_classification_interested():
    """CallOutcome raises ValidationError for legacy 'interested' classification."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="interested",  # OLD value — must be rejected
            reason="Some reason.",
            confidence="medium",
        )


def test_call_outcome_rejects_old_classification_follow_up():
    """CallOutcome raises ValidationError for legacy 'follow_up' classification."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="follow_up",  # OLD value — must be rejected
            reason="Some reason.",
            confidence="low",
        )


def test_call_outcome_rejects_invalid_classification():
    """CallOutcome raises ValidationError when classification is not in 11 valid values."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="very_interested",  # NOT a valid value
            reason="Some reason.",
            confidence="high",
        )


def test_call_outcome_rejects_invalid_confidence():
    """CallOutcome raises ValidationError when confidence is not low/medium/high."""
    from pydantic import ValidationError
    from app.analysis_schema import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="busy",
            reason="Lead was busy.",
            confidence="extreme",  # NOT valid
        )


def test_call_outcome_no_engagement_quality_field():
    """CallOutcome must NOT have an engagement_quality field."""
    from app.analysis_schema import CallOutcome

    outcome = CallOutcome(
        classification="no_answer",
        reason="No answer.",
        confidence="low",
    )
    assert not hasattr(
        outcome, "engagement_quality"
    ), "engagement_quality must NOT exist on CallOutcome (qora-outcome spec)"
    # Also verify model fields don't include engagement_quality
    assert "engagement_quality" not in CallOutcome.model_fields


def test_call_outcome_rejects_engagement_quality_as_extra_field():
    """CallOutcome raises ValidationError or ignores engagement_quality (not stored)."""
    from app.analysis_schema import CallOutcome

    # Pydantic v2 by default ignores extra fields — confirm it doesn't store it
    outcome = CallOutcome(
        classification="busy",
        reason="Lead was driving.",
        confidence="low",
        engagement_quality="high",  # should be ignored or rejected
    )
    assert not hasattr(outcome, "engagement_quality")


# ---------------------------------------------------------------------------
# Scenario: OutcomeClassification and EngagementQuality enums must NOT exist
# ---------------------------------------------------------------------------


def test_outcome_classification_enum_removed_from_enums():
    """OutcomeClassification class must NOT exist in enums.py (qora-outcome spec)."""
    import app.analysis.enums as enums_mod

    assert not hasattr(
        enums_mod, "OutcomeClassification"
    ), "OutcomeClassification must be deleted from enums.py (qora-outcome spec)"


def test_engagement_quality_enum_removed_from_enums():
    """EngagementQuality class must NOT exist in enums.py (qora-outcome spec)."""
    import app.analysis.enums as enums_mod

    assert not hasattr(
        enums_mod, "EngagementQuality"
    ), "EngagementQuality must be deleted from enums.py (qora-outcome spec)"


def test_outcome_classification_not_importable_from_analysis():
    """OutcomeClassification must NOT be importable from app.analysis (qora-outcome spec)."""
    import app.analysis as analysis_pkg

    assert not hasattr(
        analysis_pkg, "OutcomeClassification"
    ), "OutcomeClassification must be removed from app.analysis exports"


def test_engagement_quality_not_importable_from_analysis():
    """EngagementQuality must NOT be importable from app.analysis (qora-outcome spec)."""
    import app.analysis as analysis_pkg

    assert not hasattr(
        analysis_pkg, "EngagementQuality"
    ), "EngagementQuality must be removed from app.analysis exports"


# ---------------------------------------------------------------------------
# Scenario: outcome.py imports — no enums.py references
# ---------------------------------------------------------------------------


def test_outcome_py_does_not_import_from_enums():
    """outcome.py must NOT import OutcomeClassification or EngagementQuality from enums."""
    import ast
    import pathlib

    outcome_path = (
        pathlib.Path(__file__).parent.parent.parent
        / "app"
        / "analysis"
        / "universal"
        / "outcome.py"
    )
    source = outcome_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "enums" in node.module:
                imported_names = [alias.name for alias in node.names]
                assert (
                    "OutcomeClassification" not in imported_names
                ), "outcome.py must NOT import OutcomeClassification from enums"
                assert (
                    "EngagementQuality" not in imported_names
                ), "outcome.py must NOT import EngagementQuality from enums"


# ---------------------------------------------------------------------------
# Scenario: Default factory — _default_call_outcome()
# ---------------------------------------------------------------------------


def test_default_call_outcome_returns_no_answer_with_low_confidence():
    """_default_call_outcome() returns classification='no_answer' and confidence='low'."""
    from app.analysis.schema import _default_call_outcome

    outcome = _default_call_outcome()
    assert outcome.classification == "no_answer"
    assert outcome.confidence == "low"
    assert outcome.reason  # non-empty
    assert not hasattr(outcome, "engagement_quality")


def test_default_call_outcome_no_engagement_quality():
    """_default_call_outcome() must NOT set engagement_quality."""
    from app.analysis.schema import _default_call_outcome, CallOutcome

    _default_call_outcome()  # ensure it doesn't raise
    assert "engagement_quality" not in CallOutcome.model_fields


# ---------------------------------------------------------------------------
# Scenario: outcome.py DIMENSION prompt — 11 classifications + no engagement_quality
# ---------------------------------------------------------------------------


def test_outcome_dimension_prompt_includes_all_11_classifications():
    """DIMENSION['prompt'] in outcome.py must mention all 11 classification strings."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    for classification in _VALID_11_CLASSIFICATIONS:
        assert (
            classification in prompt
        ), f"outcome.py DIMENSION prompt missing classification: {classification}"


def test_outcome_dimension_prompt_no_engagement_quality():
    """DIMENSION['prompt'] must NOT mention engagement_quality."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    assert (
        "engagement_quality" not in prompt
    ), "outcome.py DIMENSION prompt must not reference engagement_quality (qora-outcome spec)"


# ---------------------------------------------------------------------------
# Scenario: InterestsAxis (new) — replaces old DetectedInterests
# qora-interest-pipeline spec: detected_interests field now uses InterestsAxis
# ---------------------------------------------------------------------------


def test_detected_interests_defaults_to_empty_lists():
    """InterestsAxis defaults to empty items list when not provided.

    qora-interest-pipeline: detected_interests now uses InterestsAxis (items: list[InterestItem])
    instead of the old DetectedInterests (products/specific_needs/buying_signals).
    """
    from app.analysis.universal.interest.interests import InterestsAxis

    axis = InterestsAxis()
    assert axis.items == []


def test_detected_interests_with_data():
    """InterestsAxis accepts populated InterestItem list."""
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["precio_competitivo"],
        evidence="Me interesa el todo riesgo.",
        confidence="high",
    )
    axis = InterestsAxis(items=[item])
    assert len(axis.items) == 1
    assert axis.items[0].product == "auto_todo_riesgo"
    assert "precio_competitivo" in axis.items[0].needs


# ---------------------------------------------------------------------------
# Scenario: IdentifiedProblem — valid instantiation
# ---------------------------------------------------------------------------


def test_identified_problem_valid():
    """ProblemAxis (IdentifiedProblem alias) accepts valid PainPoint objects."""
    from app.analysis.universal.problem import ProblemAxis, PainPoint

    pp1 = PainPoint(
        category="cost",
        description="Current plan too expensive",
        evidence="El seguro actual es muy caro",
        urgency="high",
        confidence="high",
        is_primary=True,
    )
    pp2 = PainPoint(
        category="bad_experience",
        description="Bad claim experience",
        evidence="Tardaron mucho en procesar mi siniestro",
        urgency="medium",
        confidence="medium",
    )
    problem = ProblemAxis(pain_points=[pp1, pp2])
    assert len(problem.pain_points) == 2
    assert problem.pain_points[0].category == "cost"
    assert problem.pain_points[0].is_primary is True
    assert problem.pain_points[1].category == "bad_experience"


def test_identified_problem_pain_points_defaults_empty():
    """ProblemAxis.pain_points defaults to empty list."""
    from app.analysis.universal.problem import ProblemAxis

    problem = ProblemAxis()
    assert problem.pain_points == []


def test_identified_problem_rejects_invalid_category():
    """ProblemAxis raises ValidationError when PainPoint has invalid category."""
    from pydantic import ValidationError
    from app.analysis.universal.problem import ProblemAxis

    with pytest.raises(ValidationError):
        ProblemAxis(
            pain_points=[
                {
                    "category": "INVALID_CATEGORY",
                    "description": "something",
                    "evidence": "some quote",
                    "urgency": "medium",
                    "confidence": "high",
                }
            ]
        )


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
    )
    from app.analysis.universal.problem import ProblemAxis, PainPoint
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["precio_competitivo"],
        evidence="Me interesa el todo riesgo.",
        confidence="high",
    )
    pp = PainPoint(
        category="cost",
        description="Needs comprehensive vehicle coverage.",
        evidence="No tengo seguro actualmente",
        urgency="high",
        confidence="high",
        is_primary=True,
    )
    analysis = PostCallAnalysis(
        summary="Lead was very interested in todo riesgo coverage.",
        objections=_OA(),
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car year: 2022",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead requested a quote.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(items=[item]),
        identified_problem=ProblemAxis(pain_points=[pp]),
    )

    assert analysis.summary == "Lead was very interested in todo riesgo coverage."
    assert analysis.interest_level == 85
    assert analysis.call_outcome.classification == "completed_positive"
    assert len(analysis.detected_interests.items) == 1
    assert analysis.detected_interests.items[0].product == "auto_todo_riesgo"
    assert len(analysis.identified_problem.pain_points) == 1
    assert analysis.identified_problem.pain_points[0].urgency == "high"


def test_post_call_analysis_model_dump_contains_axes():
    """PostCallAnalysis.model_dump() produces dict with all 3 new axes."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
    )
    from app.analysis.universal.problem import ProblemAxis
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    analysis = PostCallAnalysis(
        summary="Test summary.",
        objections=_OA(),
        interest_level=50,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="busy",
            reason="Lead was driving.",
            confidence="low",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=ProblemAxis(),
    )

    dumped = analysis.model_dump()
    assert "call_outcome" in dumped
    assert "detected_interests" in dumped
    assert "identified_problem" in dumped
    # call_outcome is a nested dict
    assert dumped["call_outcome"]["classification"] == "busy"
    # identified_problem has pain_points key (new ProblemAxis format)
    assert "pain_points" in dumped["identified_problem"]
    assert isinstance(dumped["identified_problem"]["pain_points"], list)
    # detected_interests has items key (new InterestsAxis format)
    assert "items" in dumped["detected_interests"]
    # engagement_quality must NOT be in dumped call_outcome
    assert "engagement_quality" not in dumped["call_outcome"]


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
    from app.analysis.universal.objections import ObjectionsAxis

    analysis = PostCallAnalysis()
    assert analysis.summary == ""
    # objections is now ObjectionsAxis (qora-objections spec)
    assert isinstance(analysis.objections, ObjectionsAxis)
    assert analysis.objections.objections == []
    assert analysis.interest_level == 0
    assert analysis.next_action_suggested == "wait"


# ---------------------------------------------------------------------------
# Scenario: PostCallAnalysis.objections is now ObjectionsAxis (qora-objections)
# ---------------------------------------------------------------------------


def test_post_call_analysis_objections_field_is_ObjectionsAxis():
    """PostCallAnalysis.objections field must be ObjectionsAxis, not list[str]."""
    from app.analysis_schema import PostCallAnalysis
    from app.analysis.universal.objections import ObjectionsAxis

    analysis = PostCallAnalysis()
    assert isinstance(
        analysis.objections, ObjectionsAxis
    ), "PostCallAnalysis.objections must be ObjectionsAxis (qora-objections spec)"


def test_post_call_analysis_objections_default_is_empty_axis():
    """PostCallAnalysis() default objections is ObjectionsAxis with empty list."""
    from app.analysis_schema import PostCallAnalysis
    from app.analysis.universal.objections import ObjectionsAxis

    analysis = PostCallAnalysis()
    assert isinstance(analysis.objections, ObjectionsAxis)
    assert analysis.objections.objections == []


def test_post_call_analysis_accepts_ObjectionsAxis():
    """PostCallAnalysis accepts a populated ObjectionsAxis for objections field."""
    from app.analysis_schema import PostCallAnalysis
    from app.analysis.universal.objections import ObjectionsAxis, Objection

    obj = Objection(
        category="price",
        strength="high",
        resolution_status="unresolved",
        evidence="El precio es muy alto para mi presupuesto.",
        description="Lead objects to the price being too high.",
        confidence="high",
    )
    analysis = PostCallAnalysis(objections=ObjectionsAxis(objections=[obj]))
    assert isinstance(analysis.objections, ObjectionsAxis)
    assert len(analysis.objections.objections) == 1
    assert analysis.objections.objections[0].category == "price"


def test_post_call_analysis_objections_model_dump_is_dict():
    """PostCallAnalysis.model_dump() produces objections as a nested dict (not list[str])."""
    from app.analysis_schema import PostCallAnalysis
    from app.analysis.universal.objections import ObjectionsAxis, Objection

    obj = Objection(
        category="trust",
        strength="medium",
        resolution_status="partially_resolved",
        evidence="No confío en seguros.",
        description="Lead does not trust the insurance company.",
        confidence="medium",
    )
    analysis = PostCallAnalysis(objections=ObjectionsAxis(objections=[obj]))
    dumped = analysis.model_dump()
    assert isinstance(
        dumped["objections"], dict
    ), "model_dump()['objections'] must be a dict (ObjectionsAxis)"
    assert "objections" in dumped["objections"]
    assert isinstance(dumped["objections"]["objections"], list)
    assert dumped["objections"]["objections"][0]["category"] == "trust"


def test_Objection_importable_from_universal():
    """Objection must be importable from app.analysis.universal (qora-objections spec)."""
    from app.analysis.universal import Objection  # noqa: F401 — import test

    assert Objection is not None


def test_detected_interests_with_empty_buying_signals():
    """InterestsAxis with items but empty needs is valid.

    qora-interest-pipeline: buying_signals field removed; needs is per-item.
    """
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=[],
        evidence="Me interesa el todo riesgo.",
        confidence="low",
    )
    axis = InterestsAxis(items=[item])
    assert len(axis.items) == 1
    assert axis.items[0].product == "auto_todo_riesgo"
    assert axis.items[0].needs == []


def test_call_outcome_all_11_classifications_valid():
    """Every one of the 11 valid classifications creates a valid CallOutcome."""
    from app.analysis_schema import CallOutcome

    for classification in _VALID_11_CLASSIFICATIONS:
        outcome = CallOutcome(
            classification=classification,
            reason=f"Test reason for {classification}",
            confidence="medium",
        )
        assert outcome.classification == classification


# ---------------------------------------------------------------------------
# Scenario: Urgency enum values are correct
# ---------------------------------------------------------------------------


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
    )
    from app.analysis.universal.problem import ProblemAxis
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    analysis = PostCallAnalysis(
        summary="Test.",
        objections=_OA(),
        interest_level=50,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="busy",
            reason="Lead was driving.",
            confidence="low",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=ProblemAxis(),
    )

    assert (
        analysis.data_corrections == ""
    ), "data_corrections must default to '' — Issue #21"


def test_post_call_analysis_data_corrections_accepts_string():
    """PostCallAnalysis.data_corrections accepts a non-empty string value."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
    )
    from app.analysis.universal.problem import ProblemAxis
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    analysis = PostCallAnalysis(
        summary="Lead corrected car model.",
        objections=_OA(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        data_corrections="car_model: Polo Trend",
        call_outcome=CallOutcome(
            classification="callback_requested",
            reason="Lead engaged.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=ProblemAxis(),
    )

    assert analysis.data_corrections == "car_model: Polo Trend"


def test_post_call_analysis_data_corrections_rejects_dict():
    """PostCallAnalysis.data_corrections is str — raises ValidationError when dict is assigned."""
    from pydantic import ValidationError
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
    )
    from app.analysis.universal.problem import ProblemAxis
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    with pytest.raises((ValidationError, Exception)):
        PostCallAnalysis(
            summary="Test.",
            objections=_OA(),
            interest_level=50,
            current_insurance=None,
            next_action_suggested="wait",
            misc_notes="",
            data_corrections={"car_model": "Polo Trend"},  # dict — must be rejected
            call_outcome=CallOutcome(
                classification="busy",
                reason="Test.",
                confidence="low",
            ),
            detected_interests=InterestsAxis(),
            identified_problem=ProblemAxis(),
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


def test_service_issues_axis_accepts_list_of_service_issues():
    """ServiceIssuesAxis.issues accepts a list of ServiceIssue objects."""
    from app.analysis_schema import ServiceIssuesAxis
    from app.analysis.universal.service_issues import ServiceIssue

    issues = [
        ServiceIssue(
            category="delay",
            description="Provider was very slow.",
            source="current_provider",
            severity="medium",
            evidence="They took 3 weeks to process my claim.",
            confidence="high",
        ),
        ServiceIssue(
            category="billing_issue",
            description="Wrong charge applied.",
            source="previous_provider",
            severity="high",
            evidence="Me cobraron de más el mes pasado.",
            confidence="high",
        ),
    ]
    axis = ServiceIssuesAxis(issues=issues)
    assert len(axis.issues) == 2
    assert axis.issues[0].category == "delay"
    assert axis.issues[1].category == "billing_issue"


# ---------------------------------------------------------------------------
# ProfileFactsAxis — qora-profile-facts spec
# New contract: operation-based (add/update/remove) with 11 categories
# ---------------------------------------------------------------------------

_VALID_PROFILE_FACT_CATEGORIES = [
    "occupation",
    "availability",
    "communication_preference",
    "decision_style",
    "family_context",
    "lifestyle",
    "financial_attitude",
    "product_knowledge",
    "provider_relationship",
    "personality_tone",
    "other",
]


def test_profile_facts_axis_defaults_to_empty_updates():
    """ProfileFactsAxis.updates defaults to empty list — qora-profile-facts spec."""
    from app.analysis.universal.profile_facts import ProfileFactsAxis

    axis = ProfileFactsAxis()
    assert axis.updates == []


def test_profile_facts_axis_no_longer_has_facts_field():
    """ProfileFactsAxis MUST NOT have a 'facts' field — replaced by 'updates' (qora-profile-facts)."""
    from app.analysis.universal.profile_facts import ProfileFactsAxis

    axis = ProfileFactsAxis()
    assert not hasattr(
        axis, "facts"
    ), "ProfileFactsAxis must not have 'facts' field (qora-profile-facts spec — use 'updates')"
    assert "facts" not in ProfileFactsAxis.model_fields


def test_profile_fact_update_add_without_target_fact_id_is_valid():
    """ProfileFactUpdate with operation=add and target_fact_id=None is valid."""
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    update = ProfileFactUpdate(
        operation="add",
        category="occupation",
        fact="vendedor inmobiliario",
        evidence="Dijo que trabaja vendiendo propiedades",
        confidence="high",
        target_fact_id=None,
    )
    assert update.operation == "add"
    assert update.target_fact_id is None


def test_profile_fact_update_update_without_target_fact_id_raises():
    """ProfileFactUpdate with operation=update and target_fact_id=None raises ValidationError."""
    from pydantic import ValidationError
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    with pytest.raises(ValidationError):
        ProfileFactUpdate(
            operation="update",
            category="occupation",
            fact="nueva ocupacion",
            evidence="Corrigió que ahora es gerente",
            confidence="medium",
            target_fact_id=None,
        )


def test_profile_fact_update_remove_without_target_fact_id_raises():
    """ProfileFactUpdate with operation=remove and target_fact_id=None raises ValidationError."""
    from pydantic import ValidationError
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    with pytest.raises(ValidationError):
        ProfileFactUpdate(
            operation="remove",
            category="lifestyle",
            fact="already removed fact",
            evidence="Lead said this is no longer true",
            confidence="high",
            target_fact_id=None,
        )


def test_profile_facts_axis_rejects_more_than_5_updates():
    """ProfileFactsAxis raises ValidationError when more than 5 updates are provided."""
    from pydantic import ValidationError
    from app.analysis.universal.profile_facts import ProfileFactsAxis, ProfileFactUpdate

    updates = [
        ProfileFactUpdate(
            operation="add",
            category="occupation",
            fact=f"fact {i}",
            evidence=f"evidence {i}",
            confidence="low",
            target_fact_id=None,
        )
        for i in range(6)
    ]
    with pytest.raises(ValidationError):
        ProfileFactsAxis(updates=updates)


def test_profile_facts_axis_accepts_exactly_5_updates():
    """ProfileFactsAxis accepts exactly 5 updates — max boundary is inclusive."""
    from app.analysis.universal.profile_facts import ProfileFactsAxis, ProfileFactUpdate

    updates = [
        ProfileFactUpdate(
            operation="add",
            category="occupation",
            fact=f"fact {i}",
            evidence=f"evidence {i}",
            confidence="medium",
            target_fact_id=None,
        )
        for i in range(5)
    ]
    axis = ProfileFactsAxis(updates=updates)
    assert len(axis.updates) == 5


@pytest.mark.parametrize("category", _VALID_PROFILE_FACT_CATEGORIES)
def test_profile_fact_update_accepts_all_11_categories(category):
    """ProfileFactUpdate accepts each of the 11 valid category values."""
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    update = ProfileFactUpdate(
        operation="add",
        category=category,
        fact="some fact",
        evidence="some evidence",
        confidence="medium",
        target_fact_id=None,
    )
    assert update.category == category


def test_profile_fact_update_rejects_invalid_category():
    """ProfileFactUpdate raises ValidationError for an unknown category."""
    from pydantic import ValidationError
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    with pytest.raises(ValidationError):
        ProfileFactUpdate(
            operation="add",
            category="invalid_category",
            fact="some fact",
            evidence="some evidence",
            confidence="medium",
            target_fact_id=None,
        )


def test_profile_facts_axis_updates_importable_from_post_call_analysis():
    """PostCallAnalysis.profile_facts has an 'updates' attribute (not 'facts')."""
    from app.analysis.schema import PostCallAnalysis

    analysis = PostCallAnalysis()
    pf = analysis.profile_facts
    assert hasattr(
        pf, "updates"
    ), "PostCallAnalysis.profile_facts must have 'updates' field (qora-profile-facts)"
    assert pf.updates == []


def test_profile_fact_update_with_target_fact_id_for_update_is_valid():
    """ProfileFactUpdate with operation=update and a valid target_fact_id passes."""
    from app.analysis.universal.profile_facts import ProfileFactUpdate

    update = ProfileFactUpdate(
        operation="update",
        category="occupation",
        fact="gerente comercial",
        evidence="Dijo que fue promovido",
        confidence="high",
        target_fact_id="profile:occupation:vendedor-inmobiliario",
    )
    assert update.operation == "update"
    assert update.target_fact_id == "profile:occupation:vendedor-inmobiliario"


def test_profile_fact_category_enum_has_11_values():
    """ProfileFactCategory enum has exactly 11 values."""
    from app.analysis.universal.profile_facts import ProfileFactCategory

    assert len(list(ProfileFactCategory)) == 11


def test_profile_facts_axis_is_importable_from_universal():
    """ProfileFactsAxis must still be importable from app.analysis.universal."""
    from app.analysis.universal import ProfileFactsAxis  # noqa: F401

    assert ProfileFactsAxis is not None


def test_profile_fact_update_importable_from_profile_facts_module():
    """ProfileFactUpdate must be importable from app.analysis.universal.profile_facts."""
    from app.analysis.universal.profile_facts import ProfileFactUpdate  # noqa: F401

    assert ProfileFactUpdate is not None


# ---------------------------------------------------------------------------
# CommitmentsAxis
# ---------------------------------------------------------------------------


def test_commitments_axis_defaults_to_empty_list():
    """CommitmentsAxis.commitments defaults to empty list."""
    from app.analysis.universal.commitments import CommitmentsAxis

    axis = CommitmentsAxis()
    assert axis.commitments == []


def test_commitments_axis_accepts_commitment_objects():
    """CommitmentsAxis.commitments accepts a list of Commitment objects."""
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment

    c = Commitment(
        type="callback",
        owner="agent",
        description="Agent will call back.",
        due="tomorrow",
        strength="strong",
        evidence="Le llamo mañana.",
        confidence="high",
    )
    axis = CommitmentsAxis(commitments=[c])
    assert len(axis.commitments) == 1
    assert axis.commitments[0].type == "callback"


# ---------------------------------------------------------------------------
# AbandonmentReasonAxis — qora-abandonment: COMPLETELY REMOVED
# The module abandonment.py was deleted. These tests verify the replacement.
# ---------------------------------------------------------------------------


def test_abandonment_module_deleted_and_not_importable():
    """abandonment.py was deleted — module must not be importable at all.

    qora-abandonment: The AbandonmentReasonAxis class is gone. Its signal
    is now captured by CallOutcome.was_abrupt + CallOutcome.abandonment_trigger.
    """
    import importlib.util

    spec = importlib.util.find_spec("app.analysis.universal.abandonment")
    assert (
        spec is None
    ), "app.analysis.universal.abandonment must be deleted (qora-abandonment spec)"


def test_call_outcome_replaces_abandonment_reason_axis():
    """CallOutcome.was_abrupt + abandonment_trigger replace AbandonmentReasonAxis.

    The old AbandonmentReasonAxis.reason is superseded by two typed fields:
    - was_abrupt: bool | None
    - abandonment_trigger: AbandonmentTrigger | None
    """
    from app.analysis.universal.outcome import CallOutcome

    # Non-completed classification: can have both fields
    outcome = CallOutcome(
        classification="do_not_contact",
        reason="Lead found competitor.",
        confidence="high",
        was_abrupt=False,
        abandonment_trigger="no_interest",
    )
    assert outcome.was_abrupt is False
    assert outcome.abandonment_trigger == "no_interest"


# ---------------------------------------------------------------------------
# PostCallAnalysis now includes 3 new axis fields (service_issues, profile_facts, commitments)
# qora-abandonment: abandonment_reason axis REMOVED from PostCallAnalysis
# ---------------------------------------------------------------------------


def test_post_call_analysis_has_three_new_axes_without_abandonment():
    """PostCallAnalysis includes service_issues, profile_facts, commitments (abandonment_reason REMOVED)."""
    from app.analysis_schema import PostCallAnalysis

    schema = PostCallAnalysis.model_json_schema()
    props = schema.get("properties", {})

    assert "service_issues" in props, "PostCallAnalysis must have service_issues axis"
    assert "profile_facts" in props, "PostCallAnalysis must have profile_facts axis"
    assert "commitments" in props, "PostCallAnalysis must have commitments axis"
    assert (
        "abandonment_reason" not in props
    ), "PostCallAnalysis must NOT have abandonment_reason axis (qora-abandonment)"


def test_post_call_analysis_new_axes_have_correct_defaults():
    """PostCallAnalysis new axes default to empty lists without explicit data.

    qora-abandonment: abandonment_reason removed; service_issues, profile_facts,
    commitments remain. CallOutcome.was_abrupt and abandonment_trigger default to None.
    """
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
    )
    from app.analysis.universal.problem import ProblemAxis
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    analysis = PostCallAnalysis(
        summary="Test.",
        objections=_OA(),
        interest_level=50,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="busy",
            reason="Lead was driving.",
            confidence="low",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=ProblemAxis(),
    )

    assert analysis.service_issues.issues == []
    assert (
        analysis.profile_facts.updates == []
    )  # qora-profile-facts: 'updates' replaces 'facts'
    assert analysis.commitments.commitments == []
    # qora-abandonment: abandonment_reason no longer on PostCallAnalysis
    assert not hasattr(analysis, "abandonment_reason")
    # was_abrupt + abandonment_trigger live on call_outcome now
    assert analysis.call_outcome.was_abrupt is None
    assert analysis.call_outcome.abandonment_trigger is None


def test_post_call_analysis_new_axes_accept_data():
    """PostCallAnalysis accepts populated data for service_issues, profile_facts, commitments.

    qora-abandonment: abandonment_reason field REMOVED. was_abrupt + abandonment_trigger
    now live on call_outcome and are tested separately.
    qora-profile-facts: ProfileFactsAxis.facts replaced by .updates (operation-based).
    """
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        ServiceIssuesAxis,
        ProfileFactsAxis,
    )
    from app.analysis.universal.profile_facts import ProfileFactUpdate
    from app.analysis.universal.problem import ProblemAxis, PainPoint
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment
    from app.analysis.universal.service_issues import ServiceIssue

    c = Commitment(
        type="callback",
        owner="agent",
        description="Will call back Friday.",
        due="this_week",
        strength="strong",
        evidence="Le llamo el viernes.",
        confidence="high",
    )
    issue = ServiceIssue(
        category="billing_issue",
        description="Lead was overcharged.",
        source="current_provider",
        severity="high",
        evidence="Me cobraron de más.",
        confidence="high",
    )
    pp = PainPoint(
        category="cost",
        description="Needs a solution.",
        evidence="Me está saliendo muy caro",
        urgency="medium",
        confidence="high",
        is_primary=True,
    )
    pf_update = ProfileFactUpdate(
        operation="add",
        category="occupation",
        fact="manager at startup",
        evidence="Said he works at a startup",
        confidence="high",
        target_fact_id=None,
    )
    from app.analysis.universal.objections import ObjectionsAxis as _OA

    analysis = PostCallAnalysis(
        summary="Full analysis.",
        objections=_OA(),
        interest_level=75,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead engaged well.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=ProblemAxis(pain_points=[pp]),
        service_issues=ServiceIssuesAxis(issues=[issue]),
        profile_facts=ProfileFactsAxis(updates=[pf_update]),
        commitments=CommitmentsAxis(commitments=[c]),
    )

    assert len(analysis.service_issues.issues) == 1
    assert analysis.service_issues.issues[0].category == "billing_issue"
    # qora-profile-facts: .updates replaces .facts
    assert len(analysis.profile_facts.updates) == 1
    assert analysis.profile_facts.updates[0].fact == "manager at startup"
    assert len(analysis.commitments.commitments) == 1
    assert analysis.commitments.commitments[0].type == "callback"
    # qora-abandonment: abandonment_reason no longer on PostCallAnalysis
    assert not hasattr(analysis, "abandonment_reason")


# ===========================================================================
# Per-dimension analyze() coroutine — every module must have one
# ===========================================================================


@pytest.mark.parametrize(
    "mod",
    [
        __import__("app.analysis.universal.summary", fromlist=["x"]),
        __import__("app.analysis.universal.objections", fromlist=["x"]),
        __import__("app.analysis.universal.next_action", fromlist=["x"]),
        __import__("app.analysis.universal.misc_notes", fromlist=["x"]),
        __import__("app.analysis.universal.data_corrections", fromlist=["x"]),
        __import__("app.analysis.universal.outcome", fromlist=["x"]),
        __import__("app.analysis.universal.problem", fromlist=["x"]),
        __import__("app.analysis.universal.service_issues", fromlist=["x"]),
        # qora-profile-facts: profile_facts removed from DIMENSION_MODULES (10 → 9)
        # qora-abandonment: abandonment module REMOVED from DIMENSION_MODULES
        __import__("app.analysis.universal.commitments", fromlist=["x"]),
    ],
    ids=lambda m: m.DIMENSION["name"],
)
def test_dimension_module_contract(mod):
    """Every dimension module exposes DIMENSION dict, target_field, and async analyze().

    NOTE: interest_level and interests are no longer in DIMENSION_MODULES —
    they are orchestrated by the 2-phase interest pipeline in summarizer.py.
    NOTE: abandonment is no longer in DIMENSION_MODULES (qora-abandonment spec).
    NOTE: profile_facts is no longer in DIMENSION_MODULES (qora-profile-facts spec —
    handled by standalone run_profile_facts_pipeline()).
    """
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
    """Every PostCallAnalysis field is owned by exactly one dimension module OR
    handled by a standalone pipeline.

    qora-interest-pipeline: interest_level and detected_interests are now
    orchestrated by the 2-phase pipeline, NOT by DIMENSION_MODULES.
    qora-profile-facts: profile_facts is now handled by run_profile_facts_pipeline(),
    also NOT in DIMENSION_MODULES (10 → 9).
    """
    from app.analysis import PostCallAnalysis
    from app.analysis.universal import DIMENSION_MODULES

    # Fields managed by standalone pipelines (not in DIMENSION_MODULES)
    _PIPELINE_FIELDS = {"interest_level", "detected_interests", "profile_facts"}

    target_fields = [mod.DIMENSION["target_field"] for mod in DIMENSION_MODULES]
    assert len(target_fields) == len(
        set(target_fields)
    ), f"Duplicate target_field across dimensions: {target_fields}"
    expected = set(PostCallAnalysis.model_fields.keys()) - _PIPELINE_FIELDS
    assert set(target_fields) == expected, (
        f"Mismatch — extra: {set(target_fields) - expected}, "
        f"missing: {expected - set(target_fields)}"
    )


@pytest.mark.asyncio
async def test_dimension_analyze_returns_unwrapped_value_for_simple_axes():
    """Simple-wrapper analyze() returns the inner primitive, not the axis model.

    NOTE: objections was moved to complex-axis group (qora-objections spec —
    analyze() now returns ObjectionsAxis, not an unwrapped list).
    NOTE: interest_level is no longer in DIMENSION_MODULES (qora-interest-pipeline
    spec — it's orchestrated by the 2-phase pipeline, not parallel gather).
    """
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal import (
        SummaryAxis,
        NextActionAxis,
        MiscNotesAxis,
        DataCorrectionsAxis,
        summary as summary_mod,
        next_action as next_action_mod,
        misc_notes as misc_notes_mod,
        data_corrections as data_corrections_mod,
    )

    cases = [
        (summary_mod, SummaryAxis(text="hi"), str, "hi"),
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
        assert isinstance(
            result, expected_type
        ), f"{mod.__name__}.analyze returned {type(result)}, expected {expected_type}"
        assert result == expected_value


@pytest.mark.asyncio
async def test_dimension_analyze_returns_axis_for_complex_axes():
    """Complex-axis analyze() returns the parsed axis model unchanged.

    objections is now a complex axis (qora-objections spec — returns ObjectionsAxis).
    NOTE: interests is no longer in DIMENSION_MODULES (qora-interest-pipeline spec
    — it's orchestrated by the 2-phase pipeline via run_interest_pipeline()).
    NOTE: abandonment is no longer in DIMENSION_MODULES (qora-abandonment spec).
    NOTE: profile_facts is no longer in DIMENSION_MODULES (qora-profile-facts spec
    — orchestrated by run_profile_facts_pipeline()).
    """
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal import (
        CallOutcome,
        ObjectionsAxis,
        ProblemAxis,
        ServiceIssuesAxis,
        CommitmentsAxis,
        outcome as outcome_mod,
        objections as objections_mod,
        problem as problem_mod,
        service_issues as service_issues_mod,
        commitments as commitments_mod,
    )

    cases = [
        (
            outcome_mod,
            CallOutcome(classification="busy", reason="r", confidence="low"),
        ),
        (objections_mod, ObjectionsAxis()),
        (problem_mod, ProblemAxis()),
        (service_issues_mod, ServiceIssuesAxis()),
        (commitments_mod, CommitmentsAxis()),
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
    """DIMENSION_MODULES order is stable so the summarizer fan-out is deterministic.

    qora-interest-pipeline: interest_level and interests are removed from
    DIMENSION_MODULES (11 entries, down from 13). They are now orchestrated
    by the 2-phase interest pipeline.
    qora-abandonment: abandonment_reason removed (10 entries, down from 11).
    qora-profile-facts: profile_facts removed (9 entries, down from 10).
    Handled by standalone run_profile_facts_pipeline().
    """
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert names == [
        "summary",
        "objections",
        "next_action",
        "misc_notes",
        "data_corrections",
        "outcome",
        "problem",
        "service_issues",
        "commitments",
    ]


# ===========================================================================
# Phase 4 — Isolation regression tests
# Prove other dimensions are UNTOUCHED by qora-objections changes
# ===========================================================================


def test_service_issues_axis_unchanged_after_objections_integration():
    """ServiceIssuesAxis still works exactly as before — qora-objections changes did not affect it."""
    from app.analysis.universal.service_issues import ServiceIssue, ServiceIssuesAxis

    issue = ServiceIssue(
        category="delay",
        description="Claim took too long.",
        source="current_provider",
        severity="high",
        evidence="Tardaron 4 semanas.",
        confidence="high",
    )
    axis = ServiceIssuesAxis(issues=[issue])
    assert len(axis.issues) == 1
    assert axis.issues[0].category == "delay"
    assert axis.issues[0].severity == "high"
    # Default is still empty list
    empty = ServiceIssuesAxis()
    assert empty.issues == []


def test_commitments_axis_unchanged_after_objections_integration():
    """CommitmentsAxis still works exactly as before — qora-objections changes did not affect it."""
    from app.analysis.universal.commitments import Commitment, CommitmentsAxis

    c = Commitment(
        type="receive_quote",
        owner="agent",
        description="Agent will send quote by end of day.",
        due="today",
        strength="strong",
        evidence="Le mando la cotización hoy.",
        confidence="high",
    )
    axis = CommitmentsAxis(commitments=[c])
    assert len(axis.commitments) == 1
    assert axis.commitments[0].type == "receive_quote"
    # Default is empty
    empty = CommitmentsAxis()
    assert empty.commitments == []


def test_call_outcome_unchanged_after_objections_integration():
    """CallOutcome still accepts all 11 valid classifications — untouched by qora-objections."""
    from app.analysis_schema import CallOutcome

    for classification in _VALID_11_CLASSIFICATIONS:
        outcome = CallOutcome(
            classification=classification,
            reason=f"Isolation check for {classification}",
            confidence="low",
        )
        assert outcome.classification == classification
        assert not hasattr(outcome, "engagement_quality")


def test_service_issues_target_field_mapping_unchanged():
    """service_issues dimension target_field still maps to 'service_issues' in PostCallAnalysis."""
    from app.analysis.universal import DIMENSION_MODULES, service_issues as si_mod

    # Find service_issues module in DIMENSION_MODULES
    si_dim = next(
        m.DIMENSION
        for m in DIMENSION_MODULES
        if m.DIMENSION["name"] == "service_issues"
    )
    assert si_dim["target_field"] == "service_issues"
    assert si_dim["schema"] is si_mod.ServiceIssuesAxis


def test_objections_target_field_mapping_is_correct():
    """objections dimension target_field maps to 'objections' — now ObjectionsAxis."""
    from app.analysis.universal import DIMENSION_MODULES
    from app.analysis.universal.objections import ObjectionsAxis

    obj_dim = next(
        m.DIMENSION for m in DIMENSION_MODULES if m.DIMENSION["name"] == "objections"
    )
    assert obj_dim["target_field"] == "objections"
    assert obj_dim["schema"] is ObjectionsAxis


def test_dimension_modules_cover_all_post_call_analysis_fields_still_correct():
    """All 9 non-pipeline PostCallAnalysis fields are covered by exactly one dimension.

    qora-interest-pipeline: interest_level and detected_interests are now
    pipeline fields — not in DIMENSION_MODULES.
    qora-abandonment: abandonment_reason removed from PostCallAnalysis.
    qora-profile-facts: profile_facts moved to standalone run_profile_facts_pipeline().
    """
    from app.analysis import PostCallAnalysis
    from app.analysis.universal import DIMENSION_MODULES

    # Fields managed by standalone pipelines (not in DIMENSION_MODULES)
    _PIPELINE_FIELDS = {"interest_level", "detected_interests", "profile_facts"}

    target_fields = [mod.DIMENSION["target_field"] for mod in DIMENSION_MODULES]
    # No duplicates
    assert len(target_fields) == len(
        set(target_fields)
    ), f"Duplicate target_field: {target_fields}"
    # Every non-pipeline field is covered
    expected = set(PostCallAnalysis.model_fields.keys()) - _PIPELINE_FIELDS
    assert set(target_fields) == expected, (
        f"Mismatch — extra: {set(target_fields) - expected}, "
        f"missing: {expected - set(target_fields)}"
    )


# ===========================================================================
# qora-interest-pipeline Phase 5 — Integration isolation tests
# ===========================================================================


def test_dimension_modules_count_is_9_after_interest_pipeline_abandonment_and_profile_facts():
    """DIMENSION_MODULES has exactly 9 entries after qora-interest-pipeline, qora-abandonment,
    and qora-profile-facts.

    interest_level and interests removed (run_interest_pipeline).
    abandonment_reason removed (absorbed into CallOutcome fields).
    profile_facts removed (run_profile_facts_pipeline standalone).
    """
    from app.analysis.universal import DIMENSION_MODULES

    assert len(DIMENSION_MODULES) == 9, (
        f"Expected 9 DIMENSION_MODULES (interest pipeline + abandonment + profile_facts extracted), "
        f"got {len(DIMENSION_MODULES)}: {[m.DIMENSION['name'] for m in DIMENSION_MODULES]}"
    )


def test_interest_item_importable_from_universal():
    """InterestItem must be importable from app.analysis.universal (qora-interest-pipeline spec)."""
    from app.analysis.universal import InterestItem  # noqa: F401

    assert InterestItem is not None


def test_interests_axis_importable_from_universal():
    """InterestsAxis must be importable from app.analysis.universal."""
    from app.analysis.universal import InterestsAxis  # noqa: F401

    assert InterestsAxis is not None


def test_run_interest_pipeline_importable_from_universal():
    """run_interest_pipeline must be importable from app.analysis.universal."""
    from app.analysis.universal import run_interest_pipeline  # noqa: F401

    assert run_interest_pipeline is not None


def test_interest_level_stays_int_in_schema():
    """PostCallAnalysis.interest_level field type is still int (AD-4 — no consumer breakage)."""
    from app.analysis.schema import PostCallAnalysis

    field_info = PostCallAnalysis.model_fields["interest_level"]
    # Field annotation must be int (not a Pydantic model)
    annotation = field_info.annotation
    assert (
        annotation is int
    ), f"interest_level must remain int in PostCallAnalysis (AD-4), got {annotation}"


def test_detected_interests_in_schema_uses_new_model():
    """PostCallAnalysis.detected_interests field type is InterestsAxis (new pipeline model)."""
    from app.analysis.schema import PostCallAnalysis
    from app.analysis.universal.interest.interests import InterestsAxis

    field_info = PostCallAnalysis.model_fields["detected_interests"]
    annotation = field_info.annotation
    assert (
        annotation is InterestsAxis
    ), f"detected_interests must use InterestsAxis from interest/ package, got {annotation}"


def test_interests_axis_default_has_empty_items():
    """InterestsAxis() with no args has items=[] (safe default for pipeline failures)."""
    from app.analysis.universal.interest.interests import InterestsAxis

    axis = InterestsAxis()
    assert axis.items == []


def test_interest_item_has_required_fields():
    """InterestItem has product, needs, evidence, confidence fields."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        product="auto_todo_riesgo",
        needs=["precio_competitivo"],
        evidence="Me interesa el todo riesgo.",
        confidence="high",
    )
    assert item.product == "auto_todo_riesgo"
    assert item.needs == ["precio_competitivo"]
    assert item.evidence == "Me interesa el todo riesgo."
    assert item.confidence == "high"


def test_interest_level_result_importable():
    """InterestLevelResult must be importable from app.analysis.universal."""
    from app.analysis.universal import InterestLevelResult  # noqa: F401

    assert InterestLevelResult is not None


def test_old_interests_module_no_longer_in_dimension_modules():
    """The old interests.py module (universal/interests.py) must NOT be in DIMENSION_MODULES.

    qora-interest-pipeline: interests.py was DELETED. No module should exist there.
    """
    import importlib.util

    # The old module must NOT be importable (it was deleted)
    spec = importlib.util.find_spec("app.analysis.universal.interests")
    assert spec is None, (
        "app.analysis.universal.interests must be DELETED "
        "(qora-interest-pipeline spec — module was moved to interest/interests.py)"
    )

    # Also verify DIMENSION_MODULES doesn't have an interests dimension
    from app.analysis.universal import DIMENSION_MODULES

    dim_names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert "interests" not in dim_names, (
        "interests must be removed from DIMENSION_MODULES "
        "(qora-interest-pipeline spec)"
    )


def test_old_interest_level_module_no_longer_in_dimension_modules():
    """The old interest_level.py module (universal/interest_level.py) must NOT be in DIMENSION_MODULES.

    qora-interest-pipeline: interest_level.py was DELETED. No module should exist there.
    """
    import importlib.util

    # The old module must NOT be importable (it was deleted)
    spec = importlib.util.find_spec("app.analysis.universal.interest_level")
    assert spec is None, (
        "app.analysis.universal.interest_level must be DELETED "
        "(qora-interest-pipeline spec — module was moved to interest/interest_level.py)"
    )

    # Also verify DIMENSION_MODULES doesn't have an interest_level dimension
    from app.analysis.universal import DIMENSION_MODULES

    dim_names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert "interest_level" not in dim_names, (
        "interest_level must be removed from DIMENSION_MODULES "
        "(qora-interest-pipeline spec)"
    )


# ===========================================================================
# qora-abandonment — Task 1.1
# AbandonmentTrigger Literal, new CallOutcome fields, model_validator
# ===========================================================================

_VALID_ABANDONMENT_TRIGGERS = [
    "price_shock",
    "lost_patience",
    "external_interruption",
    "objection_escalation",
    "no_interest",
    "technical_failure",
    "time_constraint",
    "other",
]

_COMPLETED_CLASSIFICATIONS = [
    "completed_positive",
    "completed_neutral",
    "completed_negative",
    "callback_requested",
]

_NON_COMPLETED_CLASSIFICATIONS = [
    "no_answer",
    "busy",
    "do_not_contact",
    "wrong_number",
    "hostile",
    "confused",
    "technical_issue",
]


def test_abandonment_trigger_type_importable_from_outcome():
    """AbandonmentTrigger must be importable from app.analysis.universal.outcome."""
    from app.analysis.universal.outcome import AbandonmentTrigger  # noqa: F401

    assert AbandonmentTrigger is not None


@pytest.mark.parametrize("trigger", _VALID_ABANDONMENT_TRIGGERS)
def test_call_outcome_accepts_all_8_abandonment_triggers(trigger):
    """CallOutcome accepts each of the 8 AbandonmentTrigger values when classification is hostile."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="hostile",
        reason="Lead hung up.",
        confidence="high",
        was_abrupt=True,
        abandonment_trigger=trigger,
    )
    assert outcome.abandonment_trigger == trigger
    assert outcome.was_abrupt is True


def test_call_outcome_rejects_invalid_abandonment_trigger():
    """CallOutcome raises ValidationError for an unknown abandonment_trigger value."""
    from pydantic import ValidationError
    from app.analysis.universal.outcome import CallOutcome

    with pytest.raises(ValidationError):
        CallOutcome(
            classification="hostile",
            reason="Lead hung up.",
            confidence="high",
            was_abrupt=True,
            abandonment_trigger="rage_quit",  # NOT a valid value
        )


def test_call_outcome_new_fields_default_to_none():
    """CallOutcome.was_abrupt and abandonment_trigger default to None."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="no_answer",
        reason="No answer.",
        confidence="low",
    )
    assert outcome.was_abrupt is None
    assert outcome.abandonment_trigger is None


@pytest.mark.parametrize("classification", _COMPLETED_CLASSIFICATIONS)
def test_call_outcome_validator_nullifies_fields_for_completed_outcomes(classification):
    """model_validator: completed/callback classifications force was_abrupt=None, abandonment_trigger=None."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification=classification,
        reason="Call completed.",
        confidence="high",
        was_abrupt=True,
        abandonment_trigger="price_shock",
    )
    # Validator must override the supplied values
    assert (
        outcome.was_abrupt is None
    ), f"was_abrupt must be None for classification={classification!r}"
    assert (
        outcome.abandonment_trigger is None
    ), f"abandonment_trigger must be None for classification={classification!r}"


@pytest.mark.parametrize("classification", _NON_COMPLETED_CLASSIFICATIONS)
def test_call_outcome_validator_preserves_fields_for_non_completed_outcomes(
    classification,
):
    """model_validator: non-completed classifications keep was_abrupt + abandonment_trigger as set."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification=classification,
        reason="Lead disengaged.",
        confidence="medium",
        was_abrupt=True,
        abandonment_trigger="lost_patience",
    )
    assert outcome.was_abrupt is True
    assert outcome.abandonment_trigger == "lost_patience"


def test_call_outcome_paired_fields_both_none_is_valid():
    """CallOutcome with was_abrupt=None and abandonment_trigger=None is valid for any classification."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="no_answer",
        reason="Voicemail.",
        confidence="low",
        was_abrupt=None,
        abandonment_trigger=None,
    )
    assert outcome.was_abrupt is None
    assert outcome.abandonment_trigger is None


def test_call_outcome_was_abrupt_false_with_trigger_is_valid():
    """was_abrupt=False with an abandonment_trigger is valid (polite disengagement with known reason)."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="do_not_contact",
        reason="Lead calmly asked not to be contacted.",
        confidence="high",
        was_abrupt=False,
        abandonment_trigger="no_interest",
    )
    assert outcome.was_abrupt is False
    assert outcome.abandonment_trigger == "no_interest"


def test_call_outcome_model_dump_includes_new_fields():
    """model_dump() includes was_abrupt and abandonment_trigger in the output dict."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="hostile",
        reason="Lead was rude.",
        confidence="high",
        was_abrupt=True,
        abandonment_trigger="lost_patience",
    )
    dumped = outcome.model_dump()
    assert "was_abrupt" in dumped
    assert "abandonment_trigger" in dumped
    assert dumped["was_abrupt"] is True
    assert dumped["abandonment_trigger"] == "lost_patience"


def test_call_outcome_model_dump_new_fields_null_for_completed():
    """model_dump() shows was_abrupt=None + abandonment_trigger=None for completed outcomes."""
    from app.analysis.universal.outcome import CallOutcome

    outcome = CallOutcome(
        classification="completed_positive",
        reason="Lead agreed to a quote.",
        confidence="high",
        was_abrupt=True,
        abandonment_trigger="price_shock",
    )
    dumped = outcome.model_dump()
    assert dumped["was_abrupt"] is None
    assert dumped["abandonment_trigger"] is None


# ===========================================================================
# qora-abandonment — Task 1.2
# Remove abandonment from schema.py + __init__.py (11 → 10)
# ===========================================================================


def test_post_call_analysis_has_no_abandonment_reason_field():
    """PostCallAnalysis MUST NOT have an abandonment_reason field after qora-abandonment."""
    from app.analysis.schema import PostCallAnalysis

    assert (
        "abandonment_reason" not in PostCallAnalysis.model_fields
    ), "PostCallAnalysis.abandonment_reason must be REMOVED (qora-abandonment spec)"


def test_abandonment_reason_axis_not_imported_in_schema():
    """AbandonmentReasonAxis must NOT be imported or used in schema.py."""
    import ast
    import pathlib

    schema_path = (
        pathlib.Path(__file__).parent.parent.parent / "app" / "analysis" / "schema.py"
    )
    source = schema_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names = [alias.name for alias in node.names]
            assert (
                "AbandonmentReasonAxis" not in imported_names
            ), "schema.py must NOT import AbandonmentReasonAxis (qora-abandonment spec)"


def test_dimension_modules_count_is_9_after_abandonment_and_profile_facts():
    """DIMENSION_MODULES has exactly 9 entries after qora-abandonment and qora-profile-facts.

    qora-abandonment removed abandonment_reason (11 → 10).
    qora-profile-facts removed profile_facts (10 → 9).
    """
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert len(DIMENSION_MODULES) == 9, (
        f"Expected 9 DIMENSION_MODULES after qora-abandonment and qora-profile-facts, "
        f"got {len(DIMENSION_MODULES)}: {names}"
    )


def test_abandonment_not_in_dimension_modules():
    """abandonment_reason MUST NOT be in DIMENSION_MODULES after qora-abandonment."""
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert (
        "abandonment_reason" not in names
    ), f"abandonment_reason must be removed from DIMENSION_MODULES: {names}"


def test_abandonment_module_not_exported_from_universal_init():
    """abandonment and AbandonmentReasonAxis must NOT be in __all__ of app.analysis.universal.

    NOTE: Python makes submodules accessible as attributes once imported anywhere in the
    process (sys.modules side-effect). We check __all__ (explicit public API) instead of
    hasattr to avoid false positives from test ordering.
    """
    import app.analysis.universal as univ

    assert (
        "AbandonmentReasonAxis" not in univ.__all__
    ), "AbandonmentReasonAxis must be removed from app.analysis.universal __all__"
    assert (
        "abandonment" not in univ.__all__
    ), "abandonment must be removed from app.analysis.universal __all__"


def test_dimension_modules_order_is_correct_after_abandonment_and_profile_facts():
    """DIMENSION_MODULES order is stable with 9 entries (abandonment + profile_facts removed)."""
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert names == [
        "summary",
        "objections",
        "next_action",
        "misc_notes",
        "data_corrections",
        "outcome",
        "problem",
        "service_issues",
        "commitments",
    ], f"Unexpected DIMENSION_MODULES order: {names}"


# ===========================================================================
# qora-abandonment — Task 2.1
# Outcome prompt includes abandonment instructions + DO NOT block
# ===========================================================================


def test_outcome_prompt_contains_abandonment_was_abrupt_instruction():
    """DIMENSION['prompt'] in outcome.py must contain was_abrupt field instruction."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    assert (
        "was_abrupt" in prompt
    ), "outcome.py DIMENSION prompt must contain was_abrupt instruction"


def test_outcome_prompt_contains_abandonment_trigger_instruction():
    """DIMENSION['prompt'] in outcome.py must contain abandonment_trigger field instruction."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    assert (
        "abandonment_trigger" in prompt
    ), "outcome.py DIMENSION prompt must contain abandonment_trigger instruction"


def test_outcome_prompt_contains_do_not_block_for_completed():
    """DIMENSION['prompt'] must include explicit DO NOT block for completed/callback outcomes."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    assert (
        "DO NOT" in prompt
    ), "outcome.py DIMENSION prompt must contain DO NOT block (canonical pattern)"
    assert "completed_positive" in prompt, "DO NOT block must name completed_positive"
    assert "callback_requested" in prompt, "DO NOT block must name callback_requested"


def test_outcome_prompt_lists_all_8_abandonment_trigger_values():
    """DIMENSION['prompt'] must mention all 8 AbandonmentTrigger values."""
    from app.analysis.universal import outcome as outcome_mod

    prompt = outcome_mod.DIMENSION["prompt"]
    for trigger in [
        "price_shock",
        "lost_patience",
        "external_interruption",
        "objection_escalation",
        "no_interest",
        "technical_failure",
        "time_constraint",
        "other",
    ]:
        assert (
            trigger in prompt
        ), f"outcome.py DIMENSION prompt missing abandonment trigger: {trigger}"


# ===========================================================================
# qora-abandonment — Task 4.1
# Confirm abandonment.py is deleted and all references removed
# ===========================================================================


def test_abandonment_module_is_deleted():
    """abandonment.py must be deleted from app.analysis.universal (qora-abandonment spec)."""
    import importlib.util

    spec = importlib.util.find_spec("app.analysis.universal.abandonment")
    assert (
        spec is None
    ), "app.analysis.universal.abandonment module must be DELETED (qora-abandonment spec)"


def test_abandonment_reason_axis_not_importable_from_analysis():
    """AbandonmentReasonAxis must NOT be importable from app.analysis (qora-abandonment spec)."""
    import app.analysis as analysis_pkg

    assert not hasattr(
        analysis_pkg, "AbandonmentReasonAxis"
    ), "AbandonmentReasonAxis must be removed from app.analysis (qora-abandonment)"
    assert (
        "AbandonmentReasonAxis" not in analysis_pkg.__all__
    ), "AbandonmentReasonAxis must be removed from app.analysis.__all__"


def test_abandonment_trigger_importable_from_universal():
    """AbandonmentTrigger must be importable from app.analysis.universal (qora-abandonment spec)."""
    from app.analysis.universal import AbandonmentTrigger  # noqa: F401

    assert AbandonmentTrigger is not None


def test_abandonment_trigger_importable_from_analysis():
    """AbandonmentTrigger must be importable from app.analysis (qora-abandonment spec)."""
    from app.analysis import AbandonmentTrigger  # noqa: F401

    assert AbandonmentTrigger is not None


def test_analysis_schema_no_forbidden_imports_after_objections():
    """app.analysis package still has no fastapi/sqlalchemy/structlog imports after qora-objections changes."""
    import ast
    import pathlib

    package_root = pathlib.Path(__file__).parent.parent.parent / "app" / "analysis"
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
                    assert not module_name.startswith(
                        prefix
                    ), f"{py_file} must not import '{module_name}'"
                if module_name.startswith("app.") and not module_name.startswith(
                    allowed_app_prefix
                ):
                    raise AssertionError(
                        f"{py_file} must not import '{module_name}' — only "
                        f"'app.analysis.*' internal imports are permitted"
                    )
