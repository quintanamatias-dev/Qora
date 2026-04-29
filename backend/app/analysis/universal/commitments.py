"""Commitment signals dimension — verbal commitments or intent signals."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CommitmentSignalsAxis(BaseModel):
    """Verbal commitments or intent signals from the lead."""

    signals: list[str] = Field(
        default_factory=list,
        description="Verbal commitments or intent signals expressed by the lead",
    )


DIMENSION = {
    "name": "commitment_signals",
    "display_name": "Commitment Signals",
    "schema": CommitmentSignalsAxis,
    "prompt": (
        "Extract verbal commitments or intent signals from the lead "
        "(e.g. 'will call back Friday', 'send me the quote', 'I'll think about it'). "
        "Return JSON with: signals (list of short commitment statements, "
        "empty list if none)."
    ),
    "model": "gpt-4o-mini",
}
