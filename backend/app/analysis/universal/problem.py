"""Problem dimension — structured pain points driving the lead's interest.

Each pain point tracks: category, description, evidence (direct quote),
urgency, confidence, and whether it is the primary pain point. At most
5 pain points per call.

Locale-aware: description and evidence are written in the client's configured
analysis_language. category, urgency, and confidence remain canonical codes.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

DEFAULT_LANGUAGE = "Spanish"

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

_PROMPT_BODY = (
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
    "- bad_experience: a PAST bad experience that MOTIVATES the lead to search for alternatives IS a pain point "
    "(e.g. 'I had a terrible experience with insurance companies years ago'). "
    "However, a SPECIFIC complaint about a provider's service quality (slow claims, no response, "
    "billing errors, poor attention) belongs to service_issues, NOT here — even if it motivates the search. "
    "The test: if the complaint describes a concrete service failure, it is a service issue. "
    "If it describes a general pattern or emotional motivation, it is a pain point.\n"
    "- cost: a background cost concern that DRIVES the lead to explore options = cost pain point "
    "(e.g. 'prices keep going up every year'). "
    "Active resistance to a specific price during negotiation = price objection, NOT a pain point.\n"
    "- coverage: a gap in coverage the lead NEEDS filled = pain point. "
    "Pushback against specific coverage OFFERED by the agent = objection.\n\n"
    "Return JSON with: pain_points (array of pain point objects)."
)


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    lang_note = (
        f"LANGUAGE NOTE: Write description and evidence fields in {language}. "
        f"Keep category, urgency, and confidence as the exact English codes listed above.\n\n"
    )
    return lang_note + _PROMPT_BODY


DIMENSION = {
    "name": "problem",
    "display_name": "Identified Problem",
    "schema": ProblemAxis,
    "target_field": "identified_problem",
    "prompt": _build_prompt(DEFAULT_LANGUAGE),
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


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> ProblemAxis:
    """Run this dimension's GPT call and return the parsed ProblemAxis.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for description and evidence fields.
            category, urgency, and confidence stay canonical English codes.
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
