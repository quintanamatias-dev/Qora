"""Abandonment reason dimension — why the lead disengaged, if applicable."""

from __future__ import annotations

from openai import AsyncOpenAI
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
    "target_field": "abandonment_reason",
    "prompt": (
        "Determine why the lead disengaged or wants to stop, if applicable. "
        "Return JSON with: reason (string explaining why the lead disengaged, "
        "or null if the lead did not disengage)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> AbandonmentReasonAxis:
    """Run this dimension's GPT call and return the parsed AbandonmentReasonAxis."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
