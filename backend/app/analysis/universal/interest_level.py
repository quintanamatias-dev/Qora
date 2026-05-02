"""Interest level dimension — numeric estimate of buying intent."""

from __future__ import annotations

from openai import AsyncOpenAI
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
    "target_field": "interest_level",
    "prompt": (
        "Estimate the lead's interest level on a 0-100 scale. "
        "Return JSON with: score (integer between 0 and 100, where 0 means "
        "completely uninterested and 100 means ready to buy)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> int:
    """Run this dimension's GPT call and return the unwrapped 0-100 score."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: InterestLevelAxis = response.choices[0].message.parsed
    return parsed.score
