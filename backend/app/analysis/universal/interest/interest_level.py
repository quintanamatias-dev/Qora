"""Agent 2 — Interest Level dimension.

Scores the lead's interest level based on:
1. The detected product interests from Agent 1 (InterestsAxis)
2. The previous interest score stored for this lead (optional)

Score formula:
    - With previous:  ``round(max(product_scores) * 0.7 + previous * 0.3)``
    - Without previous: ``max(product_scores)`` (100% current signal)
    - No products detected: ``general_score = 0``, level = "very_low"

Level mapping:
    0-20  → very_low
    21-40 → low
    41-60 → medium
    61-80 → high
    81-100 → very_high
"""

from __future__ import annotations

import json
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.analysis.universal.interest.interests import InterestsAxis

DEFAULT_LANGUAGE = "Spanish"

# ---------------------------------------------------------------------------
# Literal type aliases
# ---------------------------------------------------------------------------

InterestLevel = Literal["very_low", "low", "medium", "high", "very_high"]
ConfidenceLevel = Literal["low", "medium", "high"]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProductScore(BaseModel):
    """Per-product interest score assigned by Agent 2."""

    product: str = Field(description="Product ID matching Agent 1 output")
    score: int = Field(
        ge=0,
        le=100,
        description="Interest score for this product, 0-100",
    )
    reason: str = Field(
        min_length=1,
        description="1-sentence explanation of this product's score",
    )


class InterestLevelResult(BaseModel):
    """Structured interest level result from Agent 2."""

    per_product: list[ProductScore] = Field(
        default_factory=list,
        description="Per-product scores produced by the LLM",
    )
    general_score: int = Field(
        ge=0,
        le=100,
        description="Weighted interest score (formula-computed, 0-100)",
    )
    level: InterestLevel = Field(
        description="Categorical interest level derived from general_score",
    )
    reason: str = Field(
        min_length=1,
        description="1-sentence explanation of the overall interest level",
    )
    positive_signals: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Up to 3 signals that indicate positive interest",
    )
    negative_signals: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Up to 3 signals that indicate lower interest or hesitation",
    )
    confidence: ConfidenceLevel = Field(
        description="Confidence in the overall assessment",
    )


# ---------------------------------------------------------------------------
# Pure helper functions (deterministic — no side effects)
# ---------------------------------------------------------------------------


def compute_general_score(
    product_scores: list[int],
    *,
    previous: int | None,
) -> int:
    """Return the weighted general interest score.

    Args:
        product_scores: Raw scores for each detected product (0-100 each).
        previous:       Previous stored interest score, or ``None`` for first call.

    Returns:
        Clamped integer score 0-100.

    Formula:
        - No products → 0 (regardless of previous)
        - No previous → max(product_scores)  [100% current signal]
        - With previous → round(max * 0.7 + previous * 0.3)
    """
    if not product_scores:
        return 0

    current_max = max(product_scores)

    if previous is None:
        raw = current_max
    else:
        raw = current_max * 0.7 + previous * 0.3

    return max(0, min(100, round(raw)))


def score_to_level(score: int) -> str:
    """Map a 0-100 score to a categorical interest level string.

    Buckets:
        0-20  → very_low
        21-40 → low
        41-60 → medium
        61-80 → high
        81-100 → very_high
    """
    if score <= 20:
        return "very_low"
    if score <= 40:
        return "low"
    if score <= 60:
        return "medium"
    if score <= 80:
        return "high"
    return "very_high"


# ---------------------------------------------------------------------------
# Prompt — dynamically built to include detected products from Agent 1
# ---------------------------------------------------------------------------

_BASE_PROMPT = (
    "You are an expert at scoring insurance lead interest level from sales call transcripts.\n\n"
    "You will receive:\n"
    "1. The call transcript\n"
    "2. Products detected by a previous analysis agent (may be empty)\n\n"
    "For each detected product, assign a score (0-100) and a 1-sentence reason.\n"
    "Also assess the overall call for positive and negative interest signals.\n\n"
    "SCORING GUIDE:\n"
    "- 0-20: Lead showed no real interest, was unresponsive or negative\n"
    "- 21-40: Mild curiosity, asked basic questions but no engagement\n"
    "- 41-60: Moderate interest, asked follow-up questions\n"
    "- 61-80: High interest, asked for pricing or specifics\n"
    "- 81-100: Very high interest, ready to buy or requested a quote\n\n"
    "CONSTRAINTS:\n"
    "- per_product: one entry per detected product (empty if no products)\n"
    "- positive_signals: at most 3 concrete signals from the transcript\n"
    "- negative_signals: at most 3 concrete signals from the transcript\n"
    "- level: one of very_low, low, medium, high, very_high\n"
    "- confidence: your confidence in this assessment — low, medium, or high\n"
    "- reason: 1 sentence explaining the overall level\n\n"
    "DO NOT:\n"
    "- Invent products not in the detected list\n"
    "- Assign scores based on commitment or intent to pay (score interest only)\n"
    "- Return more than 3 positive or 3 negative signals\n\n"
    "Return JSON with: per_product, general_score (placeholder — will be overridden), "
    "level (placeholder), reason, positive_signals, negative_signals, confidence."
)

_LANG_NOTE_TEMPLATE = (
    "LANGUAGE NOTE: Write reason, positive_signals, negative_signals, and per_product[].reason "
    "in {language}. Keep level, confidence, and product IDs as canonical English codes.\n\n"
)

DIMENSION = {
    "name": "interest_level",
    "display_name": "Interest Level",
    "schema": InterestLevelResult,
    "target_field": "interest_level",
    "prompt": _BASE_PROMPT,
    "model": "gpt-4o-mini",
}


def _build_prompt(
    interests: InterestsAxis,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Build the full system prompt with injected Agent 1 context and language."""
    if interests.items:
        items_json = json.dumps(
            [item.model_dump() for item in interests.items],
            ensure_ascii=False,
            indent=2,
        )
        products_context = (
            f"DETECTED PRODUCTS (from prior analysis agent):\n{items_json}\n\n"
        )
    else:
        products_context = "DETECTED PRODUCTS: none (no product interest was detected in this call)\n\n"
    lang_note = _LANG_NOTE_TEMPLATE.format(language=language)
    return products_context + lang_note + _BASE_PROMPT


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    interests: InterestsAxis,
    previous_score: int | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> InterestLevelResult:
    """Run Agent 2 and return InterestLevelResult with formula-computed general_score.

    Steps:
    1. Build prompt injecting Agent 1 interests context
    2. Call GPT for per-product scores + signals + raw confidence
    3. Extract product scores from LLM response
    4. Compute general_score using 70/30 formula (pure function)
    5. Derive level from general_score (pure function)
    6. Return validated InterestLevelResult

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        interests: InterestsAxis from Agent 1.
        previous_score: Lead's prior interest score for 70/30 formula.
        language: Output language for reason, signals, and per-product reasons.
            level, confidence, and product IDs stay canonical.
    """
    prompt = _build_prompt(interests, language=language)

    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    llm_result: InterestLevelResult = response.choices[0].message.parsed

    # Override general_score and level with deterministic formula
    product_scores = [ps.score for ps in llm_result.per_product]
    general_score = compute_general_score(product_scores, previous=previous_score)
    level = score_to_level(general_score)

    return InterestLevelResult.model_construct(
        per_product=llm_result.per_product,
        general_score=general_score,
        level=level,
        reason=llm_result.reason,
        positive_signals=llm_result.positive_signals,
        negative_signals=llm_result.negative_signals,
        confidence=llm_result.confidence,
    )
