"""Summary dimension — one-sentence factual recap of the call."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# Default output language — "Spanish" preserves backward-compat for existing clients.
# The summarizer reads the client's configured analysis_language and passes it down.
# Do NOT change this constant to another language; configure it at the client level.
DEFAULT_LANGUAGE = "Spanish"

# Legacy alias kept for any external reference (will be removed in a future cleanup).
LANGUAGE = DEFAULT_LANGUAGE


class SummaryAxis(BaseModel):
    """One-sentence factual recap of the call."""

    text: str = Field(
        description="One-sentence factual recap of what happened during the call"
    )


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    return (
        f"Describe in one sentence what happened during the call. "
        f"Write the response in {language}. "
        f"Third person, factual, descriptive — no opinions, no analysis, no scoring. "
        f"Return JSON with: text (max 40 tokens)."
    )


DIMENSION = {
    "name": "summary",
    "display_name": "Summary",
    "schema": SummaryAxis,
    "target_field": "summary",
    "prompt": _build_prompt(DEFAULT_LANGUAGE),
    "model": "gpt-4o-mini",
}


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Run this dimension's GPT call and return the unwrapped string.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for customer-facing text fields.
            Defaults to DEFAULT_LANGUAGE ("Spanish") for backward compat.
    """
    prompt = _build_prompt(language)
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: SummaryAxis = response.choices[0].message.parsed
    return parsed.text
