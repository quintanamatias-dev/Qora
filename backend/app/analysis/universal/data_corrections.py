"""Data corrections dimension — personal data updates the lead provided."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class DataCorrectionsAxis(BaseModel):
    """Corrections to the lead's personal data made during the call."""

    corrections: str = Field(
        default="",
        description=(
            "If the lead corrected any personal data during the call "
            "(car make, car model, car year, name, phone), list each correction "
            "as 'field_name: corrected_value' on a separate line. "
            "Example: 'car_model: Polo Trend\\ncar_year: 2022'. "
            "Empty string if no corrections were made."
        ),
    )


DIMENSION = {
    "name": "data_corrections",
    "display_name": "Data Corrections",
    "schema": DataCorrectionsAxis,
    "target_field": "data_corrections",
    "prompt": (
        "Detect any corrections the lead made to their personal data during "
        "the call (car make, car model, car year, name, phone). "
        "Return JSON with: corrections (a string listing each correction as "
        "'field_name: corrected_value' on a separate line, "
        "e.g. 'car_model: Polo Trend\\ncar_year: 2022'; "
        "empty string if no corrections were made)."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> str:
    """Run this dimension's GPT call and return the unwrapped corrections string."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    parsed: DataCorrectionsAxis = response.choices[0].message.parsed
    return parsed.corrections
