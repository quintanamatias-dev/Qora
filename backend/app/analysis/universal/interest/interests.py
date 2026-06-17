"""Agent 1 — Interests dimension.

Detects insurance products the lead expressed interest in, the specific needs
behind each product, direct transcript evidence, and detection confidence.

Returns ``InterestsAxis`` with at most 5 ``InterestItem`` entries, each
validated against the authoritative catalog from ``catalog.py``.

Catalog injection:
    The prompt is generated once at module load time by injecting
    ``PRODUCT_CATALOG`` and ``NEED_TAGS`` from ``catalog.py``.  When those
    lists are swapped for a per-client registry, this module needs no changes.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from app.analysis.universal.interest.catalog import NEED_TAGS, PRODUCT_CATALOG

DEFAULT_LANGUAGE = "Spanish"

# Fallback tag for any need that is not in the NEED_TAGS allowlist.
_OTHER_NEED_TAG = "other"
_NEED_TAGS_SET = frozenset(NEED_TAGS)


def _normalize_need_tags(needs: list[str]) -> list[str]:
    """Normalize a needs list to the NEED_TAGS allowlist (pure function).

    Any tag NOT in NEED_TAGS is replaced with the ``other`` fallback. The result
    is de-duplicated while preserving first-seen order so that multiple invalid
    near-duplicate tags (e.g. ``"buscando alternativas"``, ``"viendo precios"``)
    collapse to a single ``other`` entry instead of inflating the list.

    This is the BI-friendly controlled-output guarantee: after validation every
    emitted need tag is guaranteed to be in the catalog, so arbitrary free-form
    near-duplicates can never be stored or aggregated.
    """
    normalized: list[str] = []
    for tag in needs:
        mapped = tag if tag in _NEED_TAGS_SET else _OTHER_NEED_TAG
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class InterestItem(BaseModel):
    """A single detected product interest with supporting context."""

    product: str = Field(
        description=("Insurance product ID — must be one of the listed catalog values"),
    )
    needs: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Specific needs behind this product interest — "
            "at most 3 items, each from the NEED_TAGS catalog"
        ),
    )
    evidence: str = Field(
        min_length=1,
        description=(
            "Direct quote or close paraphrase from the transcript that "
            "proves the lead expressed interest in this product"
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="Confidence that the interest was genuinely expressed"
    )

    @field_validator("needs", mode="after")
    @classmethod
    def _enforce_need_tags_allowlist(cls, needs: list[str]) -> list[str]:
        """Normalize need tags to the NEED_TAGS allowlist.

        Runs AFTER the ``max_length=3`` field constraint, so a raw list of more
        than 3 items still fails validation. Any tag outside NEED_TAGS becomes
        ``other`` and the result is de-duplicated, preventing arbitrary free-form
        near-duplicates from surviving (spec: call-analysis-dimensions).
        """
        return _normalize_need_tags(needs)


class InterestsAxis(BaseModel):
    """Structured product interests extracted from the call — at most 5."""

    items: list[InterestItem] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Detected product interests in descending confidence order. "
            "Empty when no product interest was detected."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt — injected with authoritative catalog values so the LLM stays
# constrained to the exact product IDs and need tags we validate against.
# ---------------------------------------------------------------------------

_PRODUCTS_BLOCK = "\n".join(f"  - {p}" for p in PRODUCT_CATALOG)
_NEEDS_BLOCK = "\n".join(f"  - {n}" for n in NEED_TAGS)

_PROMPT_BODY = (
    "You are an expert at detecting insurance product interests from sales call transcripts.\n\n"
    "A product interest exists when the lead explicitly mentions, asks about, "
    "or clearly implies interest in a specific insurance product.\n\n"
    "For each detected interest identify:\n"
    "- product: the product ID from the list below (EXACT match required)\n"
    "- needs: specific needs the lead expressed for this product — "
    "pick from the NEED_TAGS list (at most 3, can be empty)\n"
    "- evidence: a direct quote or close paraphrase from the transcript that "
    "proves this interest (required — no evidence means no interest)\n"
    "- confidence: how certain you are the interest was expressed — "
    "low, medium, or high\n\n"
    "VALID PRODUCTS (use ONLY these IDs — do not invent new ones):\n"
    f"{_PRODUCTS_BLOCK}\n\n"
    "VALID NEED_TAGS (use ONLY these values — at most 3 per product):\n"
    f"{_NEEDS_BLOCK}\n\n"
    "CONSTRAINTS:\n"
    "- Return at most 5 items. If more are detectable, return the 5 with highest confidence.\n"
    "- Return an empty items array if no product interest is detected.\n"
    "- Every item MUST include transcript evidence.\n"
    "- Only use product IDs from the VALID PRODUCTS list — do not create new IDs.\n"
    "- Only use need tags from the VALID NEED_TAGS list.\n\n"
    "DO NOT include in items:\n"
    "- Products the agent mentioned but the lead showed no interest in\n"
    "- Vague statements like '¿tienen seguros?' without a specific product\n"
    "- Products outside the VALID PRODUCTS list\n"
    "- Items where the evidence is a commitment or intent to buy (not an interest signal)\n"
    "- Speculation — only include what is clearly expressed in the transcript\n\n"
    "Return JSON with: items (array of product interest objects)."
)


def _build_prompt(language: str) -> str:
    """Build the dimension prompt with the given output language."""
    lang_note = (
        f"LANGUAGE NOTE: Write the `evidence` field in {language}. "
        f"Keep product IDs and need tags as the exact canonical values listed above.\n\n"
    )
    return lang_note + _PROMPT_BODY


# ---------------------------------------------------------------------------
# DIMENSION configuration — aligns with sibling dimension modules
# ---------------------------------------------------------------------------

DIMENSION = {
    "name": "interests",
    "display_name": "Detected Interests",
    "schema": InterestsAxis,
    "target_field": "detected_interests",
    "prompt": _build_prompt(DEFAULT_LANGUAGE),
    "model": "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> InterestsAxis:
    """Run Agent 1 and return the parsed InterestsAxis.

    The returned axis is validated by Pydantic (``InterestItem.product``
    must be a string; Pydantic's ``max_length`` constraints are enforced).
    Invalid product IDs returned by the LLM are NOT automatically discarded
    here — the prompt constrains the model; post-processing / filtering
    against the catalog happens in the pipeline orchestrator (``__init__.py``)
    if strict enforcement is required.

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for the `evidence` field.
            product IDs and need tags stay canonical.
    """
    prompt = _build_prompt(language)
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    return response.choices[0].message.parsed
