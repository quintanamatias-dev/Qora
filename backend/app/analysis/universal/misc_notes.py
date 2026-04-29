"""Misc notes dimension — free-form observations not covered by other fields."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MiscNotesAxis(BaseModel):
    """Free-form notes for facts not captured by structured fields."""

    notes: str = Field(
        default="",
        description="Any other relevant facts or observations not covered by the structured fields above, as a brief text note",
    )


DIMENSION = {
    "name": "misc_notes",
    "display_name": "Misc Notes",
    "schema": MiscNotesAxis,
    "prompt": (
        "Capture any other relevant facts or observations from the call that "
        "are not already covered by the structured fields. "
        "Return JSON with: notes (a brief text note, or empty string if there "
        "is nothing extra to record)."
    ),
    "model": "gpt-4o-mini",
}
