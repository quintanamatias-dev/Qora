"""Summary dimension — one-sentence factual recap of the call."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# Output language for client-facing fields. Will move to a global config
# variable in the future; for now hardcoded since all calls are in Spanish.
LANGUAGE = "Spanish"


class SummaryAxis(BaseModel):
    """One-sentence factual recap of the call."""

    text: str = Field(
        description="One-sentence factual recap of what happened during the call"
    )


DIMENSION = {
    "name": "summary",
    "display_name": "Summary",
    "schema": SummaryAxis,
    "target_field": "summary",
    "prompt": (
        f"Describe in one sentence what happened during the call. "
        f"Write the response in {LANGUAGE}. "
        f"Third person, factual, descriptive — no opinions, no analysis, no scoring. "
        f"Return JSON with: text (max 40 tokens)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> str:
    """Run this dimension's GPT call and return the unwrapped string."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: SummaryAxis = response.choices[0].message.parsed
    return parsed.text
