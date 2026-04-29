"""Service issues dimension — complaints or problems mentioned by the lead."""

from __future__ import annotations

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
    "prompt": (
        "Extract service problems or complaints the lead raised about their current "
        "or past service provider. Return JSON with: issues (list of complaints, "
        "empty list if none mentioned)."
    ),
    "model": "gpt-4o-mini",
}
