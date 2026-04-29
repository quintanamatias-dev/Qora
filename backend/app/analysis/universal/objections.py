"""Objections dimension — concerns or pushback raised by the lead."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ObjectionsAxis(BaseModel):
    """Objections the lead raised during the call."""

    items: list[str] = Field(
        default_factory=list,
        description="Objections the lead raised during the call",
    )


DIMENSION = {
    "name": "objections",
    "display_name": "Objections",
    "schema": ObjectionsAxis,
    "prompt": (
        "List the objections the lead raised during the call. "
        "Return JSON with: items (an array of strings, each describing one "
        "concern, hesitation, or pushback the lead expressed; empty array if "
        "no objections were raised)."
    ),
    "model": "gpt-4o-mini",
}
