"""Next action dimension — recommended follow-up step after the call."""

from __future__ import annotations

from pydantic import BaseModel, Field


class NextActionAxis(BaseModel):
    """Recommended next action after the call."""

    action: str = Field(
        description="One of: call_again, send_quote, wait, do_not_call"
    )


DIMENSION = {
    "name": "next_action",
    "display_name": "Next Action",
    "schema": NextActionAxis,
    "prompt": (
        "Recommend the next action to take with this lead. "
        "Return JSON with: action (one of: call_again, send_quote, wait, do_not_call)."
    ),
    "model": "gpt-4o-mini",
}
