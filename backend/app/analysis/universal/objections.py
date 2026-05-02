"""Objections dimension — concerns or pushback raised by the lead."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class ObjectionsAxis(BaseModel):
    """Objections the lead raised during the call."""

    items: list[str] = Field(
        default_factory=list,
        description="Objections the lead raised during the call",
    )


DIMENSION = {
    "name": "objections",
    "display_name": "Objections",
    "schema": ObjectionsAxis,
    "target_field": "objections",
    "prompt": (
        "List the objections the lead raised during the call. "
        "Return JSON with: items (an array of strings, each describing one "
        "concern, hesitation, or pushback the lead expressed; empty array if "
        "no objections were raised)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> list[str]:
    """Run this dimension's GPT call and return the unwrapped list of objections."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: ObjectionsAxis = response.choices[0].message.parsed
    return parsed.items
