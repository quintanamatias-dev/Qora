"""Call outcome dimension — semantic classification of how a call went.

Issue #50: 11 Literal classifications, confidence level, no engagement_quality.
Mirrors commitments.py / service_issues.py pattern — inline Literal types,
no imports from enums.py.

qora-abandonment: Added AbandonmentTrigger (8 values), was_abrupt + abandonment_trigger
fields on CallOutcome, and model_validator(mode="after") that nullifies both fields
when classification is in the completed/callback set (AD-1).
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator


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

# qora-abandonment: 8 exit-trigger categories (generic, no insurance-specific language)
AbandonmentTrigger = Literal[
    "price_shock",
    "lost_patience",
    "external_interruption",
    "objection_escalation",
    "no_interest",
    "technical_failure",
    "time_constraint",
    "other",
]

# qora-abandonment: outcomes where abandonment fields MUST be null (AD-1)
_COMPLETED_OUTCOMES = {
    "completed_positive",
    "completed_neutral",
    "completed_negative",
    "callback_requested",
}


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
    # qora-abandonment: new optional fields — null for completed/callback outcomes
    was_abrupt: bool | None = Field(
        default=None,
        description=(
            "True if the call ended abruptly (mid-sentence disconnect, sudden hang-up, "
            "no goodbye). False if the ending was polite/expected. "
            "null for completed or callback_requested outcomes."
        ),
    )
    abandonment_trigger: AbandonmentTrigger | None = Field(
        default=None,
        description=(
            "What caused the lead to disengage — one of the 8 AbandonmentTrigger values. "
            "null for completed or callback_requested outcomes."
        ),
    )

    @model_validator(mode="after")
    def _nullify_abandonment_for_completed(self) -> "CallOutcome":
        """Enforce conditional null rule (AD-1): completed/callback outcomes must have
        was_abrupt=None and abandonment_trigger=None regardless of what the model returned."""
        if self.classification in _COMPLETED_OUTCOMES:
            self.was_abrupt = None
            self.abandonment_trigger = None
        return self


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
        "- confidence: how confident you are in this classification — low, medium, or high\n"
        "\n"
        "ABANDONMENT ANALYSIS (fill ONLY for non-completed outcomes):\n"
        "- was_abrupt: true if the call ended abruptly (mid-sentence disconnect, sudden hang-up, "
        "no goodbye). false if the ending was polite/expected. null for completed outcomes.\n"
        "- abandonment_trigger: what caused the lead to disengage — one of: "
        "price_shock, lost_patience, external_interruption, objection_escalation, "
        "no_interest, technical_failure, time_constraint, other. null for completed outcomes.\n"
        "\n"
        "DO NOT populate was_abrupt or abandonment_trigger when classification is "
        "completed_positive, completed_neutral, completed_negative, or callback_requested. "
        "Leave both as null for those outcomes."
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
