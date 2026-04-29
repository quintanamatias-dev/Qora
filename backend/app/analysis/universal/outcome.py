"""Call outcome dimension — semantic classification of how a call went."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analysis.enums import EngagementQuality, OutcomeClassification


class CallOutcome(BaseModel):
    """Semantic classification of a call's result and lead engagement."""

    classification: OutcomeClassification = Field(
        description="Overall call result: interested, not_interested, busy, follow_up, no_answer, hostile, confused"
    )
    reason: str = Field(
        description="One sentence explaining WHY this classification was chosen"
    )
    engagement_quality: EngagementQuality = Field(
        description="How actively the lead participated: high, medium, low, none"
    )


DIMENSION = {
    "name": "outcome",
    "display_name": "Call Outcome",
    "schema": CallOutcome,
    "prompt": (
        "Classify the call outcome. Return JSON with: "
        "classification (one of: interested, not_interested, busy, follow_up, "
        "no_answer, hostile, confused), reason (one sentence explaining WHY), "
        "engagement_quality (one of: high, medium, low, none — 'none' if the lead "
        "said nothing meaningful, 'no_answer' classification if the call never connected)."
    ),
    "model": "gpt-4o-mini",
}
