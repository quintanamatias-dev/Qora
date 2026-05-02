"""Unit tests for service_issues.py — Strict TDD.

Spec: sdd/qora-service-issues/spec
Design: sdd/qora-service-issues/design

Tests cover:
- IssueCategoryType Literal validation (10 categories)
- IssueSourceType, IssueSeverityType, IssueConfidenceType Literals
- ServiceIssue model construction and required fields
- ServiceIssuesAxis max-5 constraint and empty list
- DIMENSION dict contract
- analyze() returns ServiceIssuesAxis from mocked client
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Phase 1: ServiceIssue schema tests
# ---------------------------------------------------------------------------


def test_issue_category_type_all_10_valid():
    """IssueCategoryType accepts all 10 valid category values."""
    from pydantic import BaseModel
    from app.analysis.universal.service_issues import IssueCategoryType

    class _M(BaseModel):
        c: IssueCategoryType

    valid_values = [
        "poor_attention",
        "delay",
        "lack_of_response",
        "lack_of_clarity",
        "claim_problem",
        "billing_issue",
        "administrative_problem",
        "bad_experience",
        "communication_problem",
        "other",
    ]
    for v in valid_values:
        m = _M(c=v)
        assert m.c == v


def test_issue_category_type_rejects_invalid_value():
    """IssueCategoryType raises ValidationError for unknown category."""
    from pydantic import BaseModel, ValidationError
    from app.analysis.universal.service_issues import IssueCategoryType

    class _M(BaseModel):
        c: IssueCategoryType

    with pytest.raises(ValidationError):
        _M(c="billing_error")


def test_issue_source_type_valid_values():
    """IssueSourceType accepts all 4 valid source values."""
    from pydantic import BaseModel
    from app.analysis.universal.service_issues import IssueSourceType

    class _M(BaseModel):
        s: IssueSourceType

    for v in ["current_provider", "previous_provider", "our_company", "unknown"]:
        m = _M(s=v)
        assert m.s == v


def test_issue_severity_type_valid_values():
    """IssueSeverityType accepts low/medium/high."""
    from pydantic import BaseModel
    from app.analysis.universal.service_issues import IssueSeverityType

    class _M(BaseModel):
        s: IssueSeverityType

    for v in ["low", "medium", "high"]:
        m = _M(s=v)
        assert m.s == v


def test_issue_confidence_type_valid_values():
    """IssueConfidenceType accepts low/medium/high."""
    from pydantic import BaseModel
    from app.analysis.universal.service_issues import IssueConfidenceType

    class _M(BaseModel):
        c: IssueConfidenceType

    for v in ["low", "medium", "high"]:
        m = _M(c=v)
        assert m.c == v


def test_service_issue_valid_instantiation():
    """ServiceIssue accepts all 6 required fields with valid values."""
    from app.analysis.universal.service_issues import ServiceIssue

    issue = ServiceIssue(
        category="billing_issue",
        description="Lead was overcharged for their premium.",
        source="current_provider",
        severity="high",
        evidence="Me cobraron de más el mes pasado.",
        confidence="high",
    )
    assert issue.category == "billing_issue"
    assert issue.description == "Lead was overcharged for their premium."
    assert issue.source == "current_provider"
    assert issue.severity == "high"
    assert issue.evidence == "Me cobraron de más el mes pasado."
    assert issue.confidence == "high"


def test_service_issue_invalid_category_raises():
    """ServiceIssue raises ValidationError for invalid category."""
    from pydantic import ValidationError
    from app.analysis.universal.service_issues import ServiceIssue

    with pytest.raises(ValidationError):
        ServiceIssue(
            category="billing_error",  # invalid
            description="Wrong charge.",
            source="current_provider",
            severity="medium",
            evidence="Me cobraron mal.",
            confidence="medium",
        )


def test_service_issue_empty_description_raises():
    """ServiceIssue raises ValidationError when description is empty string."""
    from pydantic import ValidationError
    from app.analysis.universal.service_issues import ServiceIssue

    with pytest.raises(ValidationError):
        ServiceIssue(
            category="delay",
            description="",  # invalid — min_length=1
            source="current_provider",
            severity="low",
            evidence="Tardaron mucho.",
            confidence="low",
        )


def test_service_issue_empty_evidence_raises():
    """ServiceIssue raises ValidationError when evidence is empty string."""
    from pydantic import ValidationError
    from app.analysis.universal.service_issues import ServiceIssue

    with pytest.raises(ValidationError):
        ServiceIssue(
            category="delay",
            description="They were very slow.",
            source="current_provider",
            severity="low",
            evidence="",  # invalid — min_length=1
            confidence="low",
        )


def test_service_issues_axis_empty_default():
    """ServiceIssuesAxis defaults to empty issues list."""
    from app.analysis.universal.service_issues import ServiceIssuesAxis

    axis = ServiceIssuesAxis()
    assert axis.issues == []


def test_service_issues_axis_max_5_enforced():
    """ServiceIssuesAxis raises ValidationError when more than 5 issues provided."""
    from pydantic import ValidationError
    from app.analysis.universal.service_issues import ServiceIssuesAxis, ServiceIssue

    issue_data = dict(
        category="delay",
        description="They took too long.",
        source="current_provider",
        severity="medium",
        evidence="Tardaron mucho.",
        confidence="medium",
    )
    six_issues = [ServiceIssue(**issue_data) for _ in range(6)]

    with pytest.raises(ValidationError):
        ServiceIssuesAxis(issues=six_issues)


def test_service_issues_axis_five_items_valid():
    """ServiceIssuesAxis accepts exactly 5 issues (boundary)."""
    from app.analysis.universal.service_issues import ServiceIssuesAxis, ServiceIssue

    issue_data = dict(
        category="billing_issue",
        description="Overcharged.",
        source="current_provider",
        severity="high",
        evidence="Me cobraron de más.",
        confidence="high",
    )
    five_issues = [ServiceIssue(**issue_data) for _ in range(5)]
    axis = ServiceIssuesAxis(issues=five_issues)
    assert len(axis.issues) == 5


# ---------------------------------------------------------------------------
# Phase 2: DIMENSION dict + analyze() contract
# ---------------------------------------------------------------------------


def test_dimension_name_is_service_issues():
    """DIMENSION['name'] is 'service_issues'."""
    from app.analysis.universal.service_issues import DIMENSION

    assert DIMENSION["name"] == "service_issues"


def test_dimension_target_field_is_service_issues():
    """DIMENSION['target_field'] is 'service_issues'."""
    from app.analysis.universal.service_issues import DIMENSION

    assert DIMENSION["target_field"] == "service_issues"


def test_dimension_model_is_gpt4o_mini():
    """DIMENSION['model'] is gpt-4o-mini."""
    from app.analysis.universal.service_issues import DIMENSION

    assert DIMENSION["model"] == "gpt-4o-mini"


def test_dimension_schema_is_service_issues_axis():
    """DIMENSION['schema'] is ServiceIssuesAxis."""
    from app.analysis.universal.service_issues import DIMENSION, ServiceIssuesAxis

    assert DIMENSION["schema"] is ServiceIssuesAxis


def test_dimension_prompt_contains_all_10_categories():
    """DIMENSION['prompt'] includes all 10 category values verbatim."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    categories = [
        "poor_attention",
        "delay",
        "lack_of_response",
        "lack_of_clarity",
        "claim_problem",
        "billing_issue",
        "administrative_problem",
        "bad_experience",
        "communication_problem",
        "other",
    ]
    for cat in categories:
        assert cat in prompt, f"Category '{cat}' not found in prompt"


def test_dimension_prompt_contains_max_5_and_empty_array():
    """DIMENSION['prompt'] references max 5 issues and empty array fallback."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "5" in prompt, "Prompt should mention max 5 issues"
    # Must reference what to return when no issues found (empty array / empty list)
    assert "empty" in prompt.lower() or "[]" in prompt, (
        "Prompt should reference empty array for no-issue case"
    )


def test_dimension_prompt_contains_exclusion_guidance():
    """DIMENSION['prompt'] includes negation language for what NOT to classify."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    has_negation = any(
        word in prompt.lower()
        for word in ["not", "don't", "never", "no cuentes", "no incluyas", "exclude"]
    )
    assert has_negation, f"Prompt should have exclusion guidance. Got: {prompt[:300]}"


def test_dimension_prompt_contains_source_types():
    """DIMENSION['prompt'] instructs to detect issues from known sources."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    # Should reference at least provider sources
    assert "current_provider" in prompt or "previous_provider" in prompt or "provider" in prompt.lower()


def test_dimension_prompt_contains_severity_and_confidence():
    """DIMENSION['prompt'] mentions severity and confidence fields."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "severity" in prompt.lower()
    assert "confidence" in prompt.lower()


def test_dimension_prompt_contains_evidence_guidance():
    """DIMENSION['prompt'] mentions evidence (direct transcript quote)."""
    from app.analysis.universal.service_issues import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "evidence" in prompt.lower()


@pytest.mark.asyncio
async def test_analyze_returns_service_issues_axis():
    """analyze() returns ServiceIssuesAxis instance from mocked client."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.service_issues import analyze, ServiceIssuesAxis

    parsed = ServiceIssuesAxis(issues=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("Transcript text", client)

    assert result is parsed
    assert isinstance(result, ServiceIssuesAxis)


@pytest.mark.asyncio
async def test_analyze_propagates_structured_issues():
    """analyze() returns ServiceIssuesAxis with ServiceIssue data from mocked client."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.service_issues import analyze, ServiceIssuesAxis, ServiceIssue

    issue = ServiceIssue(
        category="billing_issue",
        description="Overcharged on premium.",
        source="current_provider",
        severity="high",
        evidence="Me cobraron de más el mes pasado.",
        confidence="high",
    )
    parsed = ServiceIssuesAxis(issues=[issue])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("Me cobraron de más el mes pasado.", client)

    assert result is parsed
    assert len(result.issues) == 1
    assert result.issues[0].category == "billing_issue"
    assert result.issues[0].severity == "high"
