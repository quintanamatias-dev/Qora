"""Commitment signals dimension — verbal commitments or intent signals."""

from __future__ import annotations

from openai import AsyncOpenAI
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
    "target_field": "commitment_signals",
    "prompt": (
        "Extract verbal commitments or intent signals from the lead "
        "(e.g. 'will call back Friday', 'send me the quote', 'I'll think about it'). "
        "Return JSON with: signals (list of short commitment statements, "
        "empty list if none)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> CommitmentSignalsAxis:
    """Run this dimension's GPT call and return the parsed CommitmentSignalsAxis."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
