"""Interest level dimension — numeric estimate of buying intent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InterestLevelAxis(BaseModel):
    """Estimated interest level on a 0-100 scale."""

    score: int = Field(
        description="0-100 estimated interest level: 0 = completely uninterested, 100 = ready to buy"
    )


DIMENSION = {
    "name": "interest_level",
    "display_name": "Interest Level",
    "schema": InterestLevelAxis,
    "prompt": (
        "Estimate the lead's interest level on a 0-100 scale. "
        "Return JSON with: score (integer between 0 and 100, where 0 means "
        "completely uninterested and 100 means ready to buy)."
    ),
    "model": "gpt-4o-mini",
}
