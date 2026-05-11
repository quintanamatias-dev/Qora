"""Commitments dimension — bilateral commitments and concrete next-step actions.

Each commitment tracks: type, owner (lead/agent/both), description, due date,
strength (weak/medium/strong), a direct transcript evidence quote, and
confidence. At most 5 commitments are returned per call.

Locale-aware: description and evidence are written in the client's configured
analysis_language. type, owner, due, strength, and confidence remain canonical codes.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

DEFAULT_LANGUAGE = "Spanish"

# ---------------------------------------------------------------------------
# Literal type aliases — follow service_issues.py convention (not Enum)
# ---------------------------------------------------------------------------

CommitmentType = Literal[
    "send_document",
    "receive_quote",
    "review_proposal",
    "consult_third_party",
    "callback",
    "continue_by_channel",
    "compare_options",
    "other",
]

CommitmentOwner = Literal["lead", "agent", "both"]

CommitmentStrength = Literal["weak", "medium", "strong"]

CommitmentDue = Literal["today", "tomorrow", "this_week", "specific_date", "unknown"]

CommitmentConfidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Commitment(BaseModel):
    """A single concrete commitment or next-step action identified in the transcript."""

    type: CommitmentType
    owner: CommitmentOwner
    description: str = Field(min_length=1)
    due: CommitmentDue
    strength: CommitmentStrength
    evidence: str = Field(
        min_length=1,
        description="Direct quote from transcript supporting this commitment",
    )
    confidence: CommitmentConfidence


class CommitmentsAxis(BaseModel):
    """Structured commitments extracted from the call — at most 5."""

    commitments: list[Commitment] = Field(
        default_factory=list,
        max_length=5,
        description="Concrete commitments or next-step actions identified in the transcript",
    )


# ---------------------------------------------------------------------------
# DIMENSION configuration
# ---------------------------------------------------------------------------

_PROMPT_BODY = (
    "You are an expert at detecting concrete commitments and next-step actions from sales call transcripts.\n\n"
    "A commitment exists when the lead or agent explicitly assumed, accepted, or requested a concrete next step. "
    "Examples: agreeing to send a document, scheduling a callback, committing to review a proposal.\n\n"
    "For each commitment identify:\n"
    "- type: one of send_document, receive_quote, review_proposal, consult_third_party, callback, "
    "continue_by_channel, compare_options, other\n"
    "- owner: who made the commitment — lead, agent, or both\n"
    "- description: brief description of the commitment (1-2 sentences)\n"
    "- due: when — today, tomorrow, this_week, specific_date, or unknown\n"
    "- strength: weak (conditional/vague), medium (clear intent but missing timeline), "
    "strong (explicit action with concrete timeline)\n"
    "- evidence: direct quote from the transcript that proves this commitment\n"
    "- confidence: your confidence in the detection — low, medium, or high\n\n"
    "CONSTRAINTS:\n"
    "- Return at most 5 commitments. If more than 5 are detectable, return the 5 strongest.\n"
    "- Return empty array if no commitments are present.\n"
    "- Every commitment MUST include transcript evidence.\n\n"
    "DO NOT count as commitments:\n"
    "- Vague interest ('maybe I'll think about it', 'ya vemos', 'sí, me parece interesante')\n"
    "- Politeness phrases ('thanks, bye', 'gracias')\n"
    "- Questions without commitment ('how much would it cost?')\n"
    "- General expressions of interest without a concrete action\n\n"
    "Return JSON with: commitments (array of commitment objects)."
)


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    lang_note = (
        f"LANGUAGE NOTE: Write description and evidence fields in {language}. "
        f"Keep type, owner, due, strength, and confidence as the exact English codes listed above.\n\n"
    )
    return lang_note + _PROMPT_BODY


DIMENSION = {
    "name": "commitments",
    "display_name": "Commitments",
    "schema": CommitmentsAxis,
    "target_field": "commitments",
    "prompt": _build_prompt(DEFAULT_LANGUAGE),
    "model": "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> CommitmentsAxis:
    """Run this dimension's GPT call and return the parsed CommitmentsAxis.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for description and evidence fields.
            type, owner, due, strength, and confidence stay canonical English codes.
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
    return response.choices[0].message.parsed
