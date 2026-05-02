"""Detected interests dimension — products, needs, and buying signals."""

from __future__ import annotations

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class DetectedInterests(BaseModel):
    """Insurance products and needs the lead expressed interest in."""

    products: list[str] = Field(
        default_factory=list,
        description=(
            "Insurance products mentioned or inquired about: "
            "todo_riesgo, terceros_completo, terceros, vida, hogar, etc."
        ),
    )
    specific_needs: list[str] = Field(
        default_factory=list,
        description=(
            "Specific requirements the lead expressed: "
            "precio_competitivo, cobertura_amplia, atencion_personalizada, etc."
        ),
    )
    buying_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete buying signals observed: "
            "asked about price, comparing quotes, has a specific deadline, etc."
        ),
    )


DIMENSION = {
    "name": "interests",
    "display_name": "Detected Interests",
    "schema": DetectedInterests,
    "target_field": "detected_interests",
    "prompt": (
        "Extract what the lead was interested in. Return JSON with three lists: "
        "products (products/services mentioned or inquired about), "
        "specific_needs (concrete requirements expressed by the lead), "
        "buying_signals (indicators of purchase intent: asked about price, "
        "comparing quotes, deadlines, etc.). All three default to empty lists "
        "when nothing was detected."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> DetectedInterests:
    """Run this dimension's GPT call and return the parsed DetectedInterests."""
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": DIMENSION["prompt"]},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
