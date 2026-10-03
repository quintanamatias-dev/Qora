"""Phase 3.1 — per-call prompt construction (design.md P5-D5/P5-D6).

Golden regression note: the pre-change prompt string (module-load
construction against catalog.py's PRODUCT_CATALOG/NEED_TAGS, Spanish
default) was captured BEFORE this change via:

    uv run python -c "from app.analysis.universal.interest.interests import \
        DIMENSION; import json; print(json.dumps(DIMENSION['prompt']))"

and is embedded below as ``_PRE_CHANGE_PROMPT`` (via ``repr()`` of the
captured value) for byte-identical comparison.
"""

from __future__ import annotations

_PRE_CHANGE_PROMPT = "LANGUAGE NOTE: Write the `evidence` field in Spanish. Keep product IDs and need tags as the exact canonical values listed above.\n\nYou are an expert at detecting insurance product interests from sales call transcripts.\n\nA product interest exists when the lead explicitly mentions, asks about, or clearly implies interest in a specific insurance product.\n\nFor each detected interest identify:\n- product: the product ID from the list below (EXACT match required)\n- needs: specific needs the lead expressed for this product — pick from the NEED_TAGS list (at most 3, can be empty)\n- evidence: a direct quote or close paraphrase from the transcript that proves this interest (required — no evidence means no interest)\n- confidence: how certain you are the interest was expressed — low, medium, or high\n\nVALID PRODUCTS (use ONLY these IDs — do not invent new ones):\n  - auto_todo_riesgo\n  - auto_terceros_completo\n  - auto_terceros\n  - moto\n  - hogar\n  - vida\n  - comercio\n  - art\n  - caucion\n\nVALID NEED_TAGS (use ONLY these values — at most 3 per product):\n  - precio_competitivo\n  - mayor_cobertura\n  - menor_franquicia\n  - atencion_personalizada\n  - rapidez\n  - financiacion\n  - comparar_con_actual\n  - renovacion_proxima\n  - COMPARANDO_OPCIONES\n  - other\n\nCONSTRAINTS:\n- Return at most 5 items. If more are detectable, return the 5 with highest confidence.\n- Return an empty items array if no product interest is detected.\n- Every item MUST include transcript evidence.\n- Only use product IDs from the VALID PRODUCTS list — do not create new IDs.\n- Only use need tags from the VALID NEED_TAGS list.\n\nDO NOT include in items:\n- Products the agent mentioned but the lead showed no interest in\n- Vague statements like '¿tienen seguros?' without a specific product\n- Products outside the VALID PRODUCTS list\n- Items where the evidence is a commitment or intent to buy (not an interest signal)\n- Speculation — only include what is clearly expressed in the transcript\n\nReturn JSON with: items (array of product interest objects)."


def _make_catalog(*, products=None, need_tags=None, vertical="generic"):
    from app.analysis.profiles.schema import AnalysisProfileConfigV1, NeedTagEntry, ProductEntry

    return AnalysisProfileConfigV1(
        vertical=vertical,
        products=[
            ProductEntry(id=p, label_es=p, label_en=p) for p in (products or [])
        ],
        need_tags=[NeedTagEntry(id=n, label_es=n, label_en=n) for n in (need_tags or [])],
    )


def test_build_prompt_differs_for_different_catalogs_in_same_process():
    """Two different catalogs passed to _build_prompt produce two different prompts."""
    from app.analysis.universal.interest.interests import _build_prompt

    catalog_a = _make_catalog(products=["product_a"], need_tags=["need_a"])
    catalog_b = _make_catalog(products=["product_b", "product_c"], need_tags=[])

    prompt_a = _build_prompt("Spanish", catalog=catalog_a)
    prompt_b = _build_prompt("Spanish", catalog=catalog_b)

    assert prompt_a != prompt_b
    assert "product_a" in prompt_a
    assert "product_a" not in prompt_b
    assert "product_b" in prompt_b
    assert "product_c" in prompt_b


def test_build_prompt_with_insurance_catalog_matches_pre_change_prompt():
    """The insurance catalog's built prompt is byte-identical to the
    pre-change module-load DIMENSION["prompt"] value for the same inputs."""
    from app.analysis.universal.interest.interests import _build_prompt, _DEFAULT_CATALOG

    prompt = _build_prompt("Spanish", catalog=_DEFAULT_CATALOG)
    assert prompt == _PRE_CHANGE_PROMPT


def test_dimension_prompt_still_matches_pre_change_prompt_at_module_load():
    """DIMENSION["prompt"] (module-load, default insurance catalog) is unchanged."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert DIMENSION["prompt"] == _PRE_CHANGE_PROMPT


def test_build_prompt_without_catalog_defaults_to_insurance():
    """_build_prompt(language) with no catalog kwarg keeps working (backward compat)."""
    from app.analysis.universal.interest.interests import _build_prompt

    prompt = _build_prompt("English")
    assert "auto_todo_riesgo" in prompt
    assert "English" in prompt


async def test_analyze_passes_catalog_into_prompt():
    """analyze() builds its prompt from the passed catalog, not the module default."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestsAxis, analyze

    catalog = _make_catalog(products=["only_product"], need_tags=["only_need"])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = InterestsAxis(items=[])
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    await analyze("transcript", client, catalog=catalog)

    _, kwargs = client.beta.chat.completions.parse.call_args
    sent_prompt = kwargs["messages"][0]["content"]
    assert "only_product" in sent_prompt
    assert "only_need" in sent_prompt


async def test_analyze_discards_needs_when_catalog_has_no_need_tags():
    """analyze() empties every item's needs when catalog.need_tags is empty."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis, analyze

    catalog = _make_catalog(products=["only_product"], need_tags=[])

    llm_result = InterestsAxis(
        items=[
            InterestItem(
                product="only_product",
                needs=["other"],
                evidence="dijo que le interesa",
                confidence="high",
            )
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = llm_result
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("transcript", client, catalog=catalog)

    assert result.items[0].needs == []


# ---------------------------------------------------------------------------
# Gap B — analyze() normalizes needs/products against the PER-CALL catalog,
# not the global NEED_TAGS/PRODUCT_CATALOG constants.
# ---------------------------------------------------------------------------


async def test_analyze_drops_item_whose_product_is_not_in_the_per_call_catalog():
    """An item whose product id is not in THIS catalog's products is dropped,
    even though it may be a valid id in the global PRODUCT_CATALOG."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis, analyze

    catalog = _make_catalog(products=["only_product"], need_tags=["only_need"])

    llm_result = InterestsAxis(
        items=[
            InterestItem(
                product="only_product",
                needs=[],
                evidence="le interesa",
                confidence="high",
            ),
            InterestItem(
                product="auto_todo_riesgo",  # valid in the global catalog, NOT in this one
                needs=[],
                evidence="tambien mencionó el auto",
                confidence="high",
            ),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = llm_result
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("transcript", client, catalog=catalog)

    assert [item.product for item in result.items] == ["only_product"]


async def test_analyze_normalizes_needs_to_per_call_catalogs_other_fallback():
    """A need tag outside THIS catalog's need_tags normalizes to this
    catalog's own 'other' fallback, independent of the global NEED_TAGS set."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis, analyze
    from app.analysis.profiles.schema import AnalysisProfileConfigV1, NeedTagEntry, ProductEntry

    catalog = AnalysisProfileConfigV1(
        vertical="custom",
        products=[ProductEntry(id="only_product", label_es="x", label_en="x")],
        need_tags=[
            NeedTagEntry(id="only_need", label_es="x", label_en="x"),
            NeedTagEntry(id="other", label_es="Otro", label_en="Other"),
        ],
    )

    llm_result = InterestsAxis(
        items=[
            InterestItem(
                product="only_product",
                needs=["precio_competitivo"],  # valid globally, not in this catalog
                evidence="le interesa",
                confidence="high",
            )
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = llm_result
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("transcript", client, catalog=catalog)

    assert result.items[0].needs == ["other"]


async def test_analyze_preserves_result_identity_when_nothing_changes():
    """When every item already matches the catalog, analyze() returns the
    SAME object the LLM call produced — no unnecessary rebuild."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestsAxis, analyze

    expected = InterestsAxis(items=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("transcript", client)

    assert result is expected
