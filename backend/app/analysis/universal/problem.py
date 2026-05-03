"""Problem dimension — structured pain points driving the lead's interest.

Each pain point tracks: category, description, evidence (direct quote),
urgency, confidence, and whether it is the primary pain point. At most
5 pain points per call.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literal type aliases — consistent with objections.py / service_issues.py
# ---------------------------------------------------------------------------

PainPointCategory = Literal[
    "cost",
    "coverage",
    "renewal",
    "bad_experience",
    "lack_of_clarity",
    "new_need",
    "risk_exposure",
    "comparison",
    "deadline",
    "dissatisfaction",
    "other",
]

PainUrgency = Literal["low", "medium", "high", "unknown"]

PainConfidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PainPoint(BaseModel):
    """A single pain point or underlying need identified in the transcript."""

    category: PainPointCategory
    description: str = Field(
        min_length=1,
        description="Brief 1-2 sentence description of the pain point",
    )
    evidence: str = Field(
        min_length=1,
        description="Direct quote from transcript supporting this pain point",
    )
    urgency: PainUrgency
    confidence: PainConfidence
    is_primary: bool = Field(
        default=False,
        description="True if this is the main pain point of the call (at most 1 per call)",
    )


class ProblemAxis(BaseModel):
    """Structured pain points extracted from the call — at most 5."""

    pain_points: list[PainPoint] = Field(
        default_factory=list,
        max_length=5,
        description="Pain points or underlying needs the lead expressed during the call",
    )


# ---------------------------------------------------------------------------
# DIMENSION configuration
# ---------------------------------------------------------------------------

_PROMPT = (
    "You are an expert at detecting underlying pain points and unmet needs from sales call transcripts.\n\n"
    "A pain point exists when the lead reveals a problem, dissatisfaction, fear, unmet need, or urgency "
    "that motivates their interest. Examples: cost concerns, missing coverage or capability, upcoming renewal "
    "deadlines, bad past experiences, lack of clarity about options, new needs they have identified, "
    "risk exposure they want to address, active comparison with competitors, or general dissatisfaction.\n\n"
    "For each pain point identify:\n"
    "- category: one of cost, coverage, renewal, bad_experience, lack_of_clarity, new_need, "
    "risk_exposure, comparison, deadline, dissatisfaction, other\n"
    "- description: brief 1-2 sentence description of the pain point\n"
    "- evidence: direct quote from the transcript that proves this pain point\n"
    "- urgency: how urgently the lead needs to resolve this pain — low, medium, high, or unknown\n"
    "- confidence: your confidence in the detection — low, medium, or high\n"
    "- is_primary: true only for the single most significant pain point of the call\n\n"
    "CONSTRAINTS:\n"
    "- Return at most 5 pain points. If more are detectable, return the 5 most significant.\n"
    "- Return empty array if no pain points are present.\n"
    "- Every pain point MUST include transcript evidence.\n"
    "- At most 1 pain point can have is_primary=true.\n\n"
    "DO NOT count as pain points:\n"
    "- Active objections to purchasing (price complaints during negotiation → use objections dimension)\n"
    "- General questions without underlying need\n"
    "- Polite expressions without substance\n"
    "- Information requests that do not reveal a problem\n\n"
    "BOUNDARY RULES — avoid cross-dimension overlap:\n"
    "- bad_experience: a PAST bad experience motivating their search IS a pain point. "
    "An active pushback against THIS provider during negotiation is an OBJECTION — do NOT duplicate.\n"
    "- cost: background cost concern = cost pain point. "
    "Current negotiation price resistance = price objection, NOT a pain point.\n"
    "- coverage: missing coverage or capability the lead NEEDS = pain point. "
    "Objection to coverage or feature OFFERED = objection.\n\n"
    "Return JSON with: pain_points (array of pain point objects)."
)

DIMENSION = {
    "name": "problem",
    "display_name": "Identified Problem",
    "schema": ProblemAxis,
    "target_field": "identified_problem",
    "prompt": _PROMPT,
    "model": "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Backward-compat alias (schema.py, __init__.py, analysis/__init__.py)
# Existing consumers that import IdentifiedProblem continue to work.
# Will be removed in a subsequent cleanup PR.
# ---------------------------------------------------------------------------

IdentifiedProblem = ProblemAxis  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(transcript: str, client: AsyncOpenAI) -> ProblemAxis:
    """Run this dimension's GPT call and return the parsed ProblemAxis."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
