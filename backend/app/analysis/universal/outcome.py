"""Call outcome dimension — semantic classification of how a call went.

Issue #50: 11 Literal classifications, confidence level, no engagement_quality.
Mirrors commitments.py / service_issues.py pattern — inline Literal types,
no imports from enums.py.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Literal type aliases — inline, no enums.py dependency
# ---------------------------------------------------------------------------

OutcomeClassificationType = Literal[
    "no_answer",
    "busy",
    "callback_requested",
    "completed_positive",
    "completed_neutral",
    "completed_negative",
    "do_not_contact",
    "wrong_number",
    "hostile",
    "confused",
    "technical_issue",
]

OutcomeConfidenceType = Literal["low", "medium", "high"]


class CallOutcome(BaseModel):
    """Semantic classification of a call's result."""

    classification: OutcomeClassificationType = Field(
        description=(
            "Overall call result — one of: no_answer, busy, callback_requested, "
            "completed_positive, completed_neutral, completed_negative, "
            "do_not_contact, wrong_number, hostile, confused, technical_issue"
        )
    )
    reason: str = Field(
        min_length=1,
        description="One sentence explaining WHY this classification was chosen",
    )
    confidence: OutcomeConfidenceType = Field(
        description="How confident the model is: low, medium, or high",
    )


DIMENSION = {
    "name": "outcome",
    "display_name": "Call Outcome",
    "schema": CallOutcome,
    "target_field": "call_outcome",
    "prompt": (
        "Classify the call outcome. Return JSON with:\n"
        "- classification: one of no_answer, busy, callback_requested, "
        "completed_positive, completed_neutral, completed_negative, "
        "do_not_contact, wrong_number, hostile, confused, technical_issue\n"
        "  * no_answer: call was not answered or dropped immediately\n"
        "  * busy: lead said they were busy and could not talk\n"
        "  * callback_requested: lead asked to be called back at another time\n"
        "  * completed_positive: call ended with a positive outcome (purchase, quote accepted, strong interest)\n"
        "  * completed_neutral: call completed but no clear commitment either way\n"
        "  * completed_negative: call completed and lead clearly declined\n"
        "  * do_not_contact: lead explicitly asked not to be contacted again\n"
        "  * wrong_number: wrong person answered or number does not belong to lead\n"
        "  * hostile: lead was aggressive, rude, or threatened\n"
        "  * confused: lead was confused about purpose of call or product\n"
        "  * technical_issue: call dropped, audio problems, or system failure\n"
        "- reason: one sentence explaining WHY this classification was chosen\n"
        "- confidence: how confident you are in this classification — low, medium, or high"
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> CallOutcome:
    """Run this dimension's GPT call and return the parsed CallOutcome."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
