"""Objections dimension — concerns, hesitations, or pushback raised by the lead.

Each objection tracks: category, strength, resolution_status, evidence (direct
quote), description, confidence, an optional agent response summary, and
whether it is the primary objection. At most 5 objections per call.

Locale-aware: description, evidence, and agent_response_summary are written in
the client's configured analysis_language. Category, strength, resolution_status,
and confidence remain canonical English codes.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

DEFAULT_LANGUAGE = "Spanish"

# ---------------------------------------------------------------------------
# Literal type aliases — consistent with service_issues.py / commitments.py
# ---------------------------------------------------------------------------

ObjectionCategory = Literal[
    "price",
    "current_provider",
    "timing",
    "authority",
    "trust",
    "need",
    "information_gap",
    "coverage_or_product_fit",
    "payment_or_budget",
    "documentation_or_data",
    "channel_preference",
    "bad_experience",
    "hard_rejection",
    "other",
]

ObjectionStrength = Literal["low", "medium", "high"]

ResolutionStatus = Literal[
    "resolved",
    "partially_resolved",
    "unresolved",
    "bypassed",
    "unknown",
]

ObjectionConfidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Objection(BaseModel):
    """A single objection or pushback identified in the transcript."""

    category: ObjectionCategory
    strength: ObjectionStrength
    resolution_status: ResolutionStatus
    evidence: str = Field(
        min_length=1,
        description="Direct quote from transcript supporting this objection",
    )
    description: str = Field(
        min_length=1,
        description="Brief 1-2 sentence summary of the objection",
    )
    confidence: ObjectionConfidence
    agent_response_summary: str = Field(
        default="",
        description="How the agent handled or addressed this objection",
    )
    is_primary: bool = Field(
        default=False,
        description="True if this is the main objection of the call (at most 1 per call)",
    )


class ObjectionsAxis(BaseModel):
    """Structured objections extracted from the call — at most 5."""

    objections: list[Objection] = Field(
        default_factory=list,
        max_length=5,
        description="Objections or pushback the lead raised during the call",
    )


# ---------------------------------------------------------------------------
# DIMENSION configuration
# ---------------------------------------------------------------------------

_CANONICAL_NOTE = (
    "LANGUAGE NOTE: Write description, evidence, and agent_response_summary in {language}. "
    "Keep category, strength, resolution_status, and confidence as the exact English codes listed above.\n\n"
)

_PROMPT_BODY = (
    "You are an expert at detecting objections and pushback from sales call transcripts.\n\n"
    "An objection exists when the lead explicitly expresses a concern, hesitation, or resistance "
    "to purchasing or moving forward. Examples: price complaints, distrust, bad past experiences, "
    "needing more time, lacking decision authority, or outright rejection.\n\n"
    "For each objection identify:\n"
    "- category: one of price, current_provider, timing, authority, trust, need, "
    "information_gap, coverage_or_product_fit, payment_or_budget, documentation_or_data, "
    "channel_preference, bad_experience, hard_rejection, other\n"
    "- strength: how strongly the lead expressed the objection — low, medium, or high\n"
    "- resolution_status: how was it handled — resolved, partially_resolved, unresolved, "
    "bypassed, or unknown\n"
    "- evidence: direct quote from the transcript that proves this objection\n"
    "- description: brief 1-2 sentence summary of the objection\n"
    "- confidence: your confidence in the detection — low, medium, or high\n"
    "- agent_response_summary: briefly describe how the agent responded (optional)\n"
    "- is_primary: true only for the single most significant objection of the call\n\n"
    "CONSTRAINTS:\n"
    "- Return at most 5 objections. If more are detectable, return the 5 strongest.\n"
    "- Return empty array if no objections are present.\n"
    "- Every objection MUST include transcript evidence.\n"
    "- At most 1 objection can have is_primary=true.\n\n"
    "DO NOT count as objections:\n"
    "- Genuine questions without pushback ('¿Cuáles son las coberturas disponibles?')\n"
    "- Politeness phrases ('muchas gracias', 'hasta luego', 'bye')\n"
    "- Vague expressions of interest ('ya veo', 'me parece interesante')\n"
    "- Information requests that are not resistant to purchasing\n"
    "- Scheduling preferences or logistics ('I'm busy today, send it tomorrow', "
    "'call me in the afternoon') — unless the lead uses scheduling to AVOID engagement entirely\n"
    "- Expressed needs or interest in a product ('I need home insurance', "
    "'my wife says we should get coverage') — these are buying signals, not objections\n"
    "- Dissatisfaction with a PREVIOUS or CURRENT provider's service that motivates "
    "the lead to SEEK alternatives — that is a pain point or service issue, not resistance "
    "to YOUR offering. Only count current_provider if the lead uses their satisfaction with "
    "the current provider as a reason to REJECT your offer.\n\n"
    "CURRENT_PROVIDER BOUNDARY — contextual sales blocker (traba) rule:\n"
    "- current_provider fires ONLY when the lead uses their current provider as an active "
    "reason to resist or slow down the sale — a traba (sales blocker).\n"
    "- Examples of contextual blockers (SHOULD classify as current_provider):\n"
    "  'recién cambié hace 6 meses, no vale la pena moverme ahora'\n"
    "  'estoy bien con mi compañía actual, no me apuro'\n"
    "  'X me cubre bien, no necesito moverme'\n"
    "  'no me interesa cambiar, estoy conforme'\n"
    "- A neutral mention such as 'actualmente estoy con Sancor' or 'tengo Mercantil Andina' "
    "with NO resistance expressed is NOT a current_provider objection — mere mention is not "
    "enough. There must be explicit friction or reluctance framing.\n"
    "- Dissatisfaction motivating the lead to LOOK for alternatives is a pain point, not "
    "a current_provider objection.\n\n"
    "Return JSON with: objections (array of objection objects)."
)


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    return _CANONICAL_NOTE.format(language=language) + _PROMPT_BODY


DIMENSION = {
    "name": "objections",
    "display_name": "Objections",
    "schema": ObjectionsAxis,
    "target_field": "objections",
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
) -> ObjectionsAxis:
    """Run this dimension's GPT call and return the parsed ObjectionsAxis.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for customer-facing text fields (description,
            evidence, agent_response_summary). Canonical code fields stay in English.
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
