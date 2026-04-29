"""Composite root schema — PostCallAnalysis.

Used as ``response_format`` for OpenAI Structured Outputs
(``client.chat.completions.parse(response_format=PostCallAnalysis)``).
The summarizer imports this model and uses it as the response schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analysis.universal import (
    AbandonmentReasonAxis,
    CallOutcome,
    CommitmentSignalsAxis,
    DetectedInterests,
    IdentifiedProblem,
    ProfileFactsAxis,
    ServiceIssuesAxis,
)


class PostCallAnalysis(BaseModel):
    """Complete post-call analysis output."""

    summary: str = Field(
        description="Concise call summary, max 150 tokens, plain language"
    )
    objections: list[str] = Field(
        default_factory=list,
        description="Objections the lead raised during the call",
    )
    interest_level: int = Field(
        description="0-100 estimated interest level: 0 = completely uninterested, 100 = ready to buy"
    )
    next_action_suggested: str = Field(
        description="One of: call_again, send_quote, wait, do_not_call"
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
        description="Semantic classification of the call result and lead engagement quality"
    )
    detected_interests: DetectedInterests = Field(
        description="Insurance products, specific needs, and buying signals detected in the transcript"
    )
    identified_problem: IdentifiedProblem = Field(
        description="The underlying need or problem driving the lead's potential purchase"
    )

    service_issues: ServiceIssuesAxis = Field(
        default_factory=ServiceIssuesAxis,
        description="Service problems or complaints the lead mentioned",
    )
    profile_facts: ProfileFactsAxis = Field(
        default_factory=ProfileFactsAxis,
        description="Personal or professional facts about the lead revealed during the call",
    )
    commitment_signals: CommitmentSignalsAxis = Field(
        default_factory=CommitmentSignalsAxis,
        description="Verbal commitments or intent signals expressed by the lead",
    )
    abandonment_reason: AbandonmentReasonAxis = Field(
        default_factory=AbandonmentReasonAxis,
        description="Why the lead disengaged or wants to stop, if applicable",
    )
