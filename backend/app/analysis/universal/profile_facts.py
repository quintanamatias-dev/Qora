"""Profile facts dimension — personal/professional facts revealed by the lead."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileFactsAxis(BaseModel):
    """Personal or professional facts about the lead revealed during the call."""

    facts: list[str] = Field(
        default_factory=list,
        description="Personal/professional facts about the lead revealed during the call",
    )


DIMENSION = {
    "name": "profile_facts",
    "display_name": "Profile Facts",
    "schema": ProfileFactsAxis,
    "prompt": (
        "Extract personal or professional facts about the lead revealed during the call "
        "(occupation, family, location, hobbies, vehicles owned, etc.). Return JSON with: "
        "facts (list of short factual statements, empty list if none revealed)."
    ),
    "model": "gpt-4o-mini",
}
