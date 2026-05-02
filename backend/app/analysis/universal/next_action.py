"""Next action dimension — recommended follow-up step after the call."""

from __future__ import annotations

from openai import AsyncOpenAI
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
    "target_field": "next_action_suggested",
    "prompt": (
        "Recommend the next action to take with this lead. "
        "Return JSON with: action (one of: call_again, send_quote, wait, do_not_call)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> str:
    """Run this dimension's GPT call and return the unwrapped action string."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: NextActionAxis = response.choices[0].message.parsed
    return parsed.action
