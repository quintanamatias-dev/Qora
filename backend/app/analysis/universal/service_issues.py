"""Service issues dimension — structured service complaints and problems.

Each issue tracks: category, description, source (which provider), severity,
a direct transcript evidence quote, and confidence. At most 5 issues per call.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

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

_PROMPT = (
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
    "- Politeness phrases ('thanks', 'goodbye', 'gracias')\n\n"
    "Return JSON with: issues (array of service issue objects)."
)

DIMENSION = {
    "name": "service_issues",
    "display_name": "Service Issues",
    "schema": ServiceIssuesAxis,
    "target_field": "service_issues",
    "prompt": _PROMPT,
    "model": "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(transcript: str, client: AsyncOpenAI) -> ServiceIssuesAxis:
    """Run this dimension's GPT call and return the parsed ServiceIssuesAxis."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
