"""Identified problem dimension — the underlying need driving the lead."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.analysis.enums import Urgency


class IdentifiedProblem(BaseModel):
    """The underlying need or problem driving the lead's potential purchase."""

    primary_need: str = Field(
        description="One sentence — what the lead actually needs (not just what they said)"
    )
    pain_points: list[str] = Field(
        default_factory=list,
        description="Current pain points driving the lead's interest in insurance",
    )
    urgency: Urgency = Field(
        description="How urgently the lead needs the product: high, medium, low"
    )


DIMENSION = {
    "name": "problem",
    "display_name": "Identified Problem",
    "schema": IdentifiedProblem,
    "prompt": (
        "Identify the underlying problem driving the lead's interest. Return JSON with: "
        "primary_need (one sentence — what the lead ACTUALLY needs, not just what they said), "
        "pain_points (list of current pain points motivating their interest, empty list if unclear), "
        "urgency (one of: high, medium, low)."
    ),
    "model": "gpt-4o-mini",
}
