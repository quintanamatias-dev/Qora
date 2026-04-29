"""Summary dimension — concise plain-language recap of the call."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SummaryAxis(BaseModel):
    """Concise call summary in plain language."""

    text: str = Field(
        description="Concise call summary, max 150 tokens, plain language"
    )


DIMENSION = {
    "name": "summary",
    "display_name": "Summary",
    "schema": SummaryAxis,
    "prompt": (
        "Write a concise summary of the call in plain language. "
        "Return JSON with: text (a brief recap of what happened during the call, "
        "max 150 tokens, no jargon)."
    ),
    "model": "gpt-4o-mini",
}
