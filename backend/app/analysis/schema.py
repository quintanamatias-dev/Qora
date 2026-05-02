"""Composite root schema — PostCallAnalysis.

Aggregates the 13 universal dimensions into one Pydantic model. Each field
has a default so the summarizer's per-dimension orchestrator can leave a
field unset when its dimension call fails (asyncio.gather with
return_exceptions=True), and the model still validates.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analysis.universal import (
    AbandonmentReasonAxis,
    CallOutcome,
    CommitmentsAxis,
    DetectedInterests,
    IdentifiedProblem,
    ObjectionsAxis,
    ProfileFactsAxis,
    ServiceIssuesAxis,
)
from app.analysis.enums import Urgency


def _default_call_outcome() -> CallOutcome:
    return CallOutcome(
        classification="no_answer",
        reason="dimension analysis failed or not produced",
        confidence="low",
    )


def _default_identified_problem() -> IdentifiedProblem:
    return IdentifiedProblem(
        primary_need="",
        pain_points=[],
        urgency=Urgency.low,
    )


class PostCallAnalysis(BaseModel):
    """Complete post-call analysis output."""

    summary: str = Field(
        default="",
        description="Concise call summary, max 150 tokens, plain language",
    )
    objections: ObjectionsAxis = Field(
        default_factory=ObjectionsAxis,
        description="Objections the lead raised during the call",
    )
    interest_level: int = Field(
        default=0,
        description="0-100 estimated interest level: 0 = completely uninterested, 100 = ready to buy",
    )
    next_action_suggested: str = Field(
        default="wait",
        description="One of: call_again, send_quote, wait, do_not_call",
    )
    misc_notes: str = Field(
        default="",
        description="Any other relevant facts or observations not covered by the structured fields above, as a brief text note",
    )

    # str (NOT dict) so the schema stays compatible with OpenAI Structured Outputs.
    data_corrections: str = Field(
        default="",
        description=(
            "If the lead corrected any personal data during the call "
            "(car make, car model, car year, name, phone), list each correction "
            "as 'field_name: corrected_value' on a separate line. "
            "Example: 'car_model: Polo Trend\\ncar_year: 2022'. "
            "Empty string if no corrections were made."
        ),
    )

    call_outcome: CallOutcome = Field(
        default_factory=_default_call_outcome,
        description="Semantic classification of the call result",
    )
    detected_interests: DetectedInterests = Field(
        default_factory=DetectedInterests,
        description="Insurance products, specific needs, and buying signals detected in the transcript",
    )
    identified_problem: IdentifiedProblem = Field(
        default_factory=_default_identified_problem,
        description="The underlying need or problem driving the lead's potential purchase",
    )

    service_issues: ServiceIssuesAxis = Field(
        default_factory=ServiceIssuesAxis,
        description="Service problems or complaints the lead mentioned",
    )
    profile_facts: ProfileFactsAxis = Field(
        default_factory=ProfileFactsAxis,
        description="Personal or professional facts about the lead revealed during the call",
    )
    commitments: CommitmentsAxis = Field(
        default_factory=CommitmentsAxis,
        description="Concrete commitments and next-step actions identified in the call",
    )
    abandonment_reason: AbandonmentReasonAxis = Field(
        default_factory=AbandonmentReasonAxis,
        description="Why the lead disengaged or wants to stop, if applicable",
    )
