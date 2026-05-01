"""Unit tests for commitments.py — Strict TDD RED phase.

Spec: sdd/qora-commitments/spec — Issue #55
Design: sdd/qora-commitments/design

Tests cover:
- CommitmentType Literal validation
- Commitment model construction and required fields
- CommitmentsAxis max-5 constraint and empty list
- DIMENSION dict contract
- analyze() returns CommitmentsAxis from mocked client
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Phase 1: Commitment schema tests
# ---------------------------------------------------------------------------


def test_commitment_type_valid_values():
    """CommitmentType accepts all 8 valid values."""
    from app.analysis.universal.commitments import CommitmentType
    from pydantic import BaseModel

    class _M(BaseModel):
        t: CommitmentType

    valid_values = [
        "send_document",
        "receive_quote",
        "review_proposal",
        "consult_third_party",
        "callback",
        "continue_by_channel",
        "compare_options",
        "other",
    ]
    for v in valid_values:
        m = _M(t=v)
        assert m.t == v


def test_commitment_type_rejects_invalid_value():
    """CommitmentType raises ValidationError for unknown value."""
    from pydantic import BaseModel, ValidationError
    from app.analysis.universal.commitments import CommitmentType

    class _M(BaseModel):
        t: CommitmentType

    with pytest.raises(ValidationError):
        _M(t="unknown_commitment_type")


def test_commitment_valid_instantiation():
    """Commitment model accepts all required fields with valid values."""
    from app.analysis.universal.commitments import Commitment

    c = Commitment(
        type="callback",
        owner="agent",
        description="Agent will call back tomorrow morning.",
        due="tomorrow",
        strength="strong",
        evidence="Le llamo mañana a primera hora.",
        confidence="high",
    )
    assert c.type == "callback"
    assert c.owner == "agent"
    assert c.description == "Agent will call back tomorrow morning."
    assert c.due == "tomorrow"
    assert c.strength == "strong"
    assert c.evidence == "Le llamo mañana a primera hora."
    assert c.confidence == "high"


def test_commitment_missing_required_field_raises():
    """Commitment raises ValidationError when a required field is missing."""
    from pydantic import ValidationError
    from app.analysis.universal.commitments import Commitment

    with pytest.raises(ValidationError):
        Commitment(
            # type is missing
            owner="lead",
            description="Lead will send the document.",
            due="today",
            strength="medium",
            evidence="Mando el documento hoy.",
            confidence="medium",
        )


def test_commitment_invalid_owner_raises():
    """Commitment raises ValidationError when owner is not a valid Literal."""
    from pydantic import ValidationError
    from app.analysis.universal.commitments import Commitment

    with pytest.raises(ValidationError):
        Commitment(
            type="send_document",
            owner="client",  # invalid — must be lead/agent/both
            description="Send document.",
            due="today",
            strength="weak",
            evidence="Mando el doc.",
            confidence="low",
        )


def test_commitments_axis_empty_list_valid():
    """CommitmentsAxis accepts empty commitments list."""
    from app.analysis.universal.commitments import CommitmentsAxis

    axis = CommitmentsAxis(commitments=[])
    assert axis.commitments == []


def test_commitments_axis_default_is_empty_list():
    """CommitmentsAxis defaults to empty list when no argument provided."""
    from app.analysis.universal.commitments import CommitmentsAxis

    axis = CommitmentsAxis()
    assert axis.commitments == []


def test_commitments_axis_max_5_enforced():
    """CommitmentsAxis raises ValidationError when more than 5 commitments provided."""
    from pydantic import ValidationError
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment

    commitment_data = dict(
        type="callback",
        owner="agent",
        description="Will call back.",
        due="tomorrow",
        strength="strong",
        evidence="Le llamo mañana.",
        confidence="high",
    )
    six_commitments = [Commitment(**commitment_data) for _ in range(6)]

    with pytest.raises(ValidationError):
        CommitmentsAxis(commitments=six_commitments)


def test_commitments_axis_five_items_valid():
    """CommitmentsAxis accepts exactly 5 commitments (boundary)."""
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment

    commitment_data = dict(
        type="send_document",
        owner="lead",
        description="Lead will send document.",
        due="this_week",
        strength="medium",
        evidence="Te mando la documentación esta semana.",
        confidence="medium",
    )
    five_commitments = [Commitment(**commitment_data) for _ in range(5)]
    axis = CommitmentsAxis(commitments=five_commitments)
    assert len(axis.commitments) == 5


# ---------------------------------------------------------------------------
# Phase 2: DIMENSION dict + analyze() contract
# ---------------------------------------------------------------------------


def test_dimension_name_is_commitments():
    """DIMENSION['name'] is 'commitments' (not 'commitment_signals')."""
    from app.analysis.universal.commitments import DIMENSION

    assert DIMENSION["name"] == "commitments"


def test_dimension_target_field_is_commitments():
    """DIMENSION['target_field'] is 'commitments'."""
    from app.analysis.universal.commitments import DIMENSION

    assert DIMENSION["target_field"] == "commitments"


def test_dimension_model_is_gpt4o_mini():
    """DIMENSION['model'] is gpt-4o-mini."""
    from app.analysis.universal.commitments import DIMENSION

    assert DIMENSION["model"] == "gpt-4o-mini"


def test_dimension_schema_is_commitments_axis():
    """DIMENSION['schema'] is CommitmentsAxis."""
    from app.analysis.universal.commitments import DIMENSION, CommitmentsAxis

    assert DIMENSION["schema"] is CommitmentsAxis


def test_dimension_prompt_contains_key_criteria():
    """DIMENSION['prompt'] includes critical detection criteria."""
    from app.analysis.universal.commitments import DIMENSION

    prompt = DIMENSION["prompt"]
    # Must explain what a commitment is
    assert "commit" in prompt.lower() or "action" in prompt.lower()
    # Must mention evidence requirement
    assert "evidence" in prompt.lower()
    # Must mention max 5
    assert "5" in prompt
    # Must have negatives / what NOT to classify
    assert "not" in prompt.lower() or "don't" in prompt.lower() or "never" in prompt.lower()


def test_dimension_prompt_lists_allowed_commitment_types():
    """DIMENSION['prompt'] references the valid commitment types."""
    from app.analysis.universal.commitments import DIMENSION

    prompt = DIMENSION["prompt"]
    # At minimum, some type names should appear in the prompt for GPT guidance
    type_hints = ["send_document", "callback", "review_proposal"]
    found = any(t in prompt for t in type_hints)
    assert found, f"Prompt should mention at least one commitment type value. Got: {prompt[:200]}"


@pytest.mark.asyncio
async def test_analyze_returns_commitments_axis():
    """analyze() returns CommitmentsAxis instance from mocked client."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.commitments import analyze, CommitmentsAxis

    parsed = CommitmentsAxis(commitments=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("Transcript text", client)

    assert result is parsed
    assert isinstance(result, CommitmentsAxis)


@pytest.mark.asyncio
async def test_analyze_returns_axis_with_commitment_data():
    """analyze() returns CommitmentsAxis with commitment data from mocked client."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.commitments import analyze, CommitmentsAxis, Commitment

    c = Commitment(
        type="callback",
        owner="agent",
        description="Agent will call back.",
        due="tomorrow",
        strength="strong",
        evidence="Le llamo mañana sin falta.",
        confidence="high",
    )
    parsed = CommitmentsAxis(commitments=[c])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("Mañana le llamo sin falta.", client)

    assert result is parsed
    assert len(result.commitments) == 1
    assert result.commitments[0].strength == "strong"
    assert result.commitments[0].due == "tomorrow"
