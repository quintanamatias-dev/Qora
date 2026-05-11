"""Service issues dimension — structured service complaints and problems.

Each issue tracks: category, description, source (which provider), severity,
a direct transcript evidence quote, and confidence. At most 5 issues per call.

Locale-aware: description and evidence are written in the client's configured
analysis_language. category, source, severity, and confidence remain canonical codes.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

DEFAULT_LANGUAGE = "Spanish"

# ---------------------------------------------------------------------------
# Literal type aliases — consistent with commitments.py convention
# ---------------------------------------------------------------------------

IssueCategoryType = Literal[
    "poor_attention",
    "delay",
    "lack_of_response",
    "lack_of_clarity",
    "claim_problem",
    "billing_issue",
    "administrative_problem",
    "bad_experience",
    "communication_problem",
    "other",
]

IssueSourceType = Literal[
    "current_provider",
    "previous_provider",
    "our_company",
    "unknown",
]

IssueSeverityType = Literal["low", "medium", "high"]

IssueConfidenceType = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ServiceIssue(BaseModel):
    """A single service complaint or problem identified in the transcript."""

    category: IssueCategoryType
    description: str = Field(min_length=1)
    source: IssueSourceType
    severity: IssueSeverityType
    evidence: str = Field(
        min_length=1,
        description="Direct quote from transcript supporting this issue",
    )
    confidence: IssueConfidenceType


class ServiceIssuesAxis(BaseModel):
    """Structured service issues extracted from the call — at most 5."""

    issues: list[ServiceIssue] = Field(
        default_factory=list,
        max_length=5,
        description="Service problems or complaints mentioned during the call",
    )


# ---------------------------------------------------------------------------
# DIMENSION configuration
# ---------------------------------------------------------------------------

_PROMPT_BODY = (
    "You are an expert at detecting service complaints and problems from sales call transcripts.\n\n"
    "A service issue exists when the lead explicitly mentions a problem, complaint, or negative "
    "experience with a service provider (current_provider, previous_provider, or our_company).\n\n"
    "For each issue identify:\n"
    "- category: one of poor_attention, delay, lack_of_response, lack_of_clarity, claim_problem, "
    "billing_issue, administrative_problem, bad_experience, communication_problem, other\n"
    "- description: brief description of the issue (1-2 sentences)\n"
    "- source: which provider is the issue about — current_provider, previous_provider, "
    "our_company, or unknown\n"
    "- severity: how severe is the issue — low, medium, or high\n"
    "- evidence: direct quote from the transcript that proves this issue\n"
    "- confidence: your confidence in the detection — low, medium, or high\n\n"
    "CONSTRAINTS:\n"
    "- Return at most 5 issues. If more than 5 are detectable, return the 5 most severe.\n"
    "- Return empty array if no service issues are present.\n"
    "- Every issue MUST include transcript evidence.\n\n"
    "DO NOT count as service issues:\n"
    "- General price inquiries or quote requests without complaints\n"
    "- Hypothetical scenarios ('what if my claim is rejected?')\n"
    "- Vague dissatisfaction without specific details ('it's okay' / 'not great')\n"
    "- Politeness phrases ('thanks', 'goodbye', 'gracias')\n"
    "- Lead rejecting the call or asking not to be contacted — that is a sales rejection, "
    "NOT a service failure (even if the lead is angry or frustrated)\n"
    "- General frustration with receiving marketing/telemarketing calls — that is not "
    "a service problem with any specific provider\n"
    "- General price complaints ('insurance is a robbery', 'everything is too expensive') "
    "without describing a concrete billing error, overcharge, or pricing discrepancy\n"
    "- The agent's sales approach or pitch style — unless the lead explicitly complains "
    "about a service interaction (not the sales call itself)\n\n"
    "Return JSON with: issues (array of service issue objects)."
)


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    lang_note = (
        f"LANGUAGE NOTE: Write description and evidence fields in {language}. "
        f"Keep category, source, severity, and confidence as the exact English codes listed above.\n\n"
    )
    return lang_note + _PROMPT_BODY


DIMENSION = {
    "name": "service_issues",
    "display_name": "Service Issues",
    "schema": ServiceIssuesAxis,
    "target_field": "service_issues",
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
) -> ServiceIssuesAxis:
    """Run this dimension's GPT call and return the parsed ServiceIssuesAxis.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for description and evidence fields.
            category, source, severity, and confidence stay canonical English codes.
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
