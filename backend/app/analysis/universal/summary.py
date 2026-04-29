"""Summary dimension — one-sentence factual recap of the call."""

from __future__ import annotations

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
    "prompt": (
        f"Describe in one sentence what happened during the call. "
        f"Write the response in {LANGUAGE}. "
        f"Third person, factual, descriptive — no opinions, no analysis, no scoring. "
        f"Return JSON with: text (max 40 tokens)."
    ),
    "model": "gpt-4o-mini",
}
