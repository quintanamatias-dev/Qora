"""Service issues dimension — complaints or problems mentioned by the lead."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class ServiceIssuesAxis(BaseModel):
    """Service problems or complaints the lead mentioned during the call."""

    issues: list[str] = Field(
        default_factory=list,
        description="Service problems or complaints mentioned by the lead",
    )


DIMENSION = {
    "name": "service_issues",
    "display_name": "Service Issues",
    "schema": ServiceIssuesAxis,
    "target_field": "service_issues",
    "prompt": (
        "Extract service problems or complaints the lead raised about their current "
        "or past service provider. Return JSON with: issues (list of complaints, "
        "empty list if none mentioned)."
    ),
    "model": "gpt-4o-mini",
}


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
