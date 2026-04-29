"""Abandonment reason dimension — why the lead disengaged, if applicable."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AbandonmentReasonAxis(BaseModel):
    """Why the lead disengaged or wants to stop, if applicable."""

    reason: str | None = Field(
        default=None,
        description="Why the lead disengaged or wants to stop, if applicable",
    )


DIMENSION = {
    "name": "abandonment_reason",
    "display_name": "Abandonment Reason",
    "schema": AbandonmentReasonAxis,
    "prompt": (
        "Determine why the lead disengaged or wants to stop, if applicable. "
        "Return JSON with: reason (string explaining why the lead disengaged, "
        "or null if the lead did not disengage)."
    ),
    "model": "gpt-4o-mini",
}
