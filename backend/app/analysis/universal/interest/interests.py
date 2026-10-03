"""Agent 1 — Interests dimension.

Detects insurance products the lead expressed interest in, the specific needs
behind each product, direct transcript evidence, and detection confidence.

Returns ``InterestsAxis`` with at most 5 ``InterestItem`` entries, each
validated against the authoritative catalog from ``catalog.py``.

Catalog injection:
    The prompt is built PER CALL by ``_build_prompt``/``analyze``, taking the
    resolved client catalog (``AnalysisProfileConfigV1``) as a parameter
    (design.md P5-D5/P5-D6). ``DIMENSION["prompt"]`` is still computed once at
    module load using the ``insurance`` template as the default catalog, so
    direct callers/tests that read ``DIMENSION["prompt"]`` without a client
    context keep working unchanged.
"""

from __future__ import annotations

from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from app.analysis.profiles.schema import AnalysisProfileConfigV1
from app.analysis.profiles.templates import insurance as _insurance_template
from app.analysis.universal.interest.catalog import NEED_TAGS

_DEFAULT_CATALOG: AnalysisProfileConfigV1 = _insurance_template.config

DEFAULT_LANGUAGE = "Spanish"

# Fallback tag for any need that is not in the NEED_TAGS allowlist.
_OTHER_NEED_TAG = "other"
_NEED_TAGS_SET = frozenset(NEED_TAGS)


def _normalize_need_tags(needs: list[str]) -> list[str]:
    """Normalize a needs list to the default (insurance) NEED_TAGS allowlist.

    Any tag NOT in NEED_TAGS is replaced with the ``other`` fallback. The result
    is de-duplicated while preserving first-seen order so that multiple invalid
    near-duplicate tags (e.g. ``"buscando alternativas"``, ``"viendo precios"``)
    collapse to a single ``other`` entry instead of inflating the list.

    This is the BI-friendly controlled-output guarantee for direct InterestItem
    construction with no client context (tests, the default/insurance catalog).
    Per-call enforcement against a client's OWN catalog happens afterwards in
    ``analyze()`` via ``_normalize_needs_for_catalog`` (Gap B) — this function
    is unaffected by that and keeps its global-default behavior unchanged.
    """
    normalized: list[str] = []
    for tag in needs:
        mapped = tag if tag in _NEED_TAGS_SET else _OTHER_NEED_TAG
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _normalize_needs_for_catalog(needs: list[str], need_ids: frozenset[str]) -> list[str]:
    """Normalize a needs list against a PER-CALL catalog's own need-tag ids
    (Gap B), independent of the global NEED_TAGS allowlist.

    Any tag not in ``need_ids`` maps to this catalog's own ``other`` entry
    when it has one, or is dropped otherwise. An empty ``need_ids`` (no
    need-tag taxonomy configured) clears every tag. De-duplicated, first-seen
    order preserved.
    """
    if not need_ids:
        return []
    normalized: list[str] = []
    for tag in needs:
        if tag in need_ids:
            mapped = tag
        elif _OTHER_NEED_TAG in need_ids:
            mapped = _OTHER_NEED_TAG
        else:
            continue
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
# Prompt — injected with the resolved client catalog's product/need-tag IDs
# so the LLM stays constrained to the exact values we validate against.
# Built PER CALL (design.md P5-D5/P5-D6) — catalog defaults to the
# ``insurance`` template so direct callers that pass no catalog keep the
# pre-change prompt text exactly (golden regression, task 3.4).
# ---------------------------------------------------------------------------


def _prompt_body(catalog: AnalysisProfileConfigV1) -> str:
    products_block = "\n".join(f"  - {p.id}" for p in catalog.products)
    needs_block = "\n".join(f"  - {n.id}" for n in catalog.need_tags)
    return (
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
        f"{products_block}\n\n"
        "VALID NEED_TAGS (use ONLY these values — at most 3 per product):\n"
        f"{needs_block}\n\n"
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


def _build_prompt(
    language: str = DEFAULT_LANGUAGE,
    *,
    catalog: AnalysisProfileConfigV1 | None = None,
) -> str:
    """Build the dimension prompt with the given output language and catalog.

    ``catalog`` defaults to the ``insurance`` template when omitted, so
    existing direct callers that only pass ``language`` keep producing the
    pre-change prompt text exactly (golden regression, task 3.4).
    """
    if catalog is None:
        catalog = _DEFAULT_CATALOG
    lang_note = (
        f"LANGUAGE NOTE: Write the `evidence` field in {language}. "
        f"Keep product IDs and need tags as the exact canonical values listed above.\n\n"
    )
    return lang_note + _prompt_body(catalog)


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


def _normalize_result_for_catalog(
    result: InterestsAxis, catalog: AnalysisProfileConfigV1
) -> InterestsAxis:
    """Final per-call catalog enforcement (Gap B) — drop items whose product
    is not in THIS catalog's products, and normalize each surviving item's
    needs against THIS catalog's own need_tags. Returns the SAME object
    unchanged when nothing needs to change (identity-preserving — callers
    may rely on ``is`` for the common case where the LLM already returned
    catalog-valid data).
    """
    product_ids = frozenset(p.id for p in catalog.products)
    need_ids = frozenset(n.id for n in catalog.need_tags)
    changed = False
    new_items: list[InterestItem] = []
    for item in result.items:
        if product_ids and item.product not in product_ids:
            changed = True
            continue
        normalized_needs = _normalize_needs_for_catalog(item.needs, need_ids)
        if normalized_needs != item.needs:
            changed = True
            item = item.model_copy(update={"needs": normalized_needs})
        new_items.append(item)
    if not changed:
        return result
    return InterestsAxis(items=new_items)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


async def analyze(
    transcript: str,
    client: AsyncOpenAI,
    *,
    language: str = DEFAULT_LANGUAGE,
    catalog: AnalysisProfileConfigV1 | None = None,
) -> InterestsAxis:
    """Run Agent 1 and return the parsed InterestsAxis.

    The returned axis is validated by Pydantic (``InterestItem.product``
    must be a string; Pydantic's ``max_length`` constraints are enforced).
    After parsing, every item is normalized against the PER-CALL ``catalog``
    (Gap B): an item whose product id is not in ``catalog.products`` is
    dropped, and each surviving item's ``needs`` is normalized against
    ``catalog.need_tags`` (not the global NEED_TAGS allowlist).

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        language: Output language for the `evidence` field.
            product IDs and need tags stay canonical.
        catalog: Resolved client analysis profile catalog (products/need_tags
            the prompt is built from). Defaults to the ``insurance`` template
            when omitted (design.md P5-D5). When ``catalog.need_tags`` is
            empty, every detected item's ``needs`` is discarded/emptied —
            the client has no need-tag taxonomy configured.
    """
    if catalog is None:
        catalog = _DEFAULT_CATALOG
    prompt = _build_prompt(language, catalog=catalog)
    response = await client.beta.chat.completions.parse(
        model=DIMENSION["model"],
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        response_format=DIMENSION["schema"],
    )
    result: InterestsAxis = response.choices[0].message.parsed
    result = _normalize_result_for_catalog(result, catalog)
    return result
