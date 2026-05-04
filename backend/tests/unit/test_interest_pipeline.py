"""Unit tests for the interest pipeline — catalog, schema, Agent 1, Agent 2, orchestration.

Phases covered:
    Phase 1: Catalog + Schema Foundation (tasks 1.1 → 1.4)
    Phase 2: Agent 1 — interests (tasks 2.1 → 2.3)
    Phase 3: Agent 2 — interest_level (tasks 3.1 → 3.3)
    Phase 4: Pipeline orchestration (tasks 4.1 → 4.3)

Products (Issue #51 — authoritative):
    auto_todo_riesgo, auto_terceros_completo, auto_terceros, moto, hogar,
    vida, comercio, art, caucion

Needs (Issue #51 — authoritative):
    precio_competitivo, mayor_cobertura, menor_franquicia,
    atencion_personalizada, rapidez, financiacion,
    comparar_con_actual, renovacion_proxima
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Authoritative catalog values (mirrors Issue #51 + spec)
# ---------------------------------------------------------------------------

_EXPECTED_PRODUCTS = [
    "auto_todo_riesgo",
    "auto_terceros_completo",
    "auto_terceros",
    "moto",
    "hogar",
    "vida",
    "comercio",
    "art",
    "caucion",
]

_EXPECTED_NEEDS = [
    "precio_competitivo",
    "mayor_cobertura",
    "menor_franquicia",
    "atencion_personalizada",
    "rapidez",
    "financiacion",
    "comparar_con_actual",
    "renovacion_proxima",
]


# ===========================================================================
# Phase 1: Catalog + Schema Foundation
# ===========================================================================

# ---------------------------------------------------------------------------
# 1.1 — catalog.py constants
# ---------------------------------------------------------------------------


def test_product_catalog_is_non_empty_list():
    """PRODUCT_CATALOG must be a non-empty list."""
    from app.analysis.universal.interest.catalog import PRODUCT_CATALOG

    assert isinstance(PRODUCT_CATALOG, list)
    assert len(PRODUCT_CATALOG) > 0


def test_need_tags_is_non_empty_list():
    """NEED_TAGS must be a non-empty list."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert isinstance(NEED_TAGS, list)
    assert len(NEED_TAGS) > 0


def test_product_catalog_contains_exactly_9_products():
    """PRODUCT_CATALOG must contain exactly the 9 products from Issue #51."""
    from app.analysis.universal.interest.catalog import PRODUCT_CATALOG

    assert len(PRODUCT_CATALOG) == 9


@pytest.mark.parametrize("product", _EXPECTED_PRODUCTS)
def test_product_catalog_contains_all_9_products(product):
    """PRODUCT_CATALOG must contain each of the 9 authoritative product IDs."""
    from app.analysis.universal.interest.catalog import PRODUCT_CATALOG

    assert product in PRODUCT_CATALOG, f"PRODUCT_CATALOG is missing: {product}"


def test_need_tags_contains_exactly_8_needs():
    """NEED_TAGS must contain exactly the 8 need tags from Issue #51."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert len(NEED_TAGS) == 8


@pytest.mark.parametrize("need", _EXPECTED_NEEDS)
def test_need_tags_contains_all_8_needs(need):
    """NEED_TAGS must contain each of the 8 authoritative need tags."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    assert need in NEED_TAGS, f"NEED_TAGS is missing: {need}"


def test_product_catalog_all_items_are_strings():
    """Every item in PRODUCT_CATALOG must be a string."""
    from app.analysis.universal.interest.catalog import PRODUCT_CATALOG

    for item in PRODUCT_CATALOG:
        assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"


def test_need_tags_all_items_are_strings():
    """Every item in NEED_TAGS must be a string."""
    from app.analysis.universal.interest.catalog import NEED_TAGS

    for item in NEED_TAGS:
        assert isinstance(item, str), f"Expected str, got {type(item)}: {item!r}"


# ---------------------------------------------------------------------------
# 1.2 — InterestItem schema
# ---------------------------------------------------------------------------


def _make_interest_item(**overrides):
    """Return a valid InterestItem kwargs dict; callers can override any field."""
    base = {
        "product": "auto_todo_riesgo",
        "needs": ["precio_competitivo"],
        "evidence": "El cliente preguntó por todo riesgo",
        "confidence": "high",
    }
    base.update(overrides)
    return base


def test_interest_item_valid_construction():
    """InterestItem accepts a fully valid kwargs dict."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(**_make_interest_item())
    assert item.product == "auto_todo_riesgo"
    assert item.needs == ["precio_competitivo"]
    assert item.evidence == "El cliente preguntó por todo riesgo"
    assert item.confidence == "high"


def test_interest_item_empty_evidence_raises():
    """InterestItem raises ValidationError when evidence is empty string (min_length=1)."""
    from app.analysis.universal.interest.interests import InterestItem

    with pytest.raises(ValidationError):
        InterestItem(**_make_interest_item(evidence=""))


def test_interest_item_confidence_only_accepts_low_medium_high():
    """InterestItem rejects any confidence value outside low/medium/high."""
    from app.analysis.universal.interest.interests import InterestItem

    with pytest.raises(ValidationError):
        InterestItem(**_make_interest_item(confidence="certain"))


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_interest_item_accepts_valid_confidence(confidence):
    """InterestItem accepts low, medium, and high as confidence values."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(**_make_interest_item(confidence=confidence))
    assert item.confidence == confidence


def test_interest_item_needs_accepts_up_to_3():
    """InterestItem accepts needs list with exactly 3 items (boundary — valid)."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(
        **_make_interest_item(
            needs=["precio_competitivo", "mayor_cobertura", "rapidez"]
        )
    )
    assert len(item.needs) == 3


def test_interest_item_needs_rejects_more_than_3():
    """InterestItem raises ValidationError when needs has more than 3 items."""
    from app.analysis.universal.interest.interests import InterestItem

    with pytest.raises(ValidationError):
        InterestItem(
            **_make_interest_item(
                needs=[
                    "precio_competitivo",
                    "mayor_cobertura",
                    "rapidez",
                    "financiacion",
                ]
            )
        )


def test_interest_item_needs_can_be_empty():
    """InterestItem accepts an empty needs list (no specific needs detected)."""
    from app.analysis.universal.interest.interests import InterestItem

    item = InterestItem(**_make_interest_item(needs=[]))
    assert item.needs == []


# ---------------------------------------------------------------------------
# 1.3 — InterestsAxis schema
# ---------------------------------------------------------------------------


def test_interests_axis_defaults_to_empty_items():
    """InterestsAxis() with no arguments yields items=[]."""
    from app.analysis.universal.interest.interests import InterestsAxis

    axis = InterestsAxis()
    assert axis.items == []


def test_interests_axis_accepts_up_to_5_items():
    """InterestsAxis accepts exactly 5 InterestItem objects (boundary — valid)."""
    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis

    items = [
        InterestItem(**_make_interest_item(product=p)) for p in _EXPECTED_PRODUCTS[:5]
    ]
    axis = InterestsAxis(items=items)
    assert len(axis.items) == 5


def test_interests_axis_rejects_6_items():
    """InterestsAxis raises ValidationError when given 6 items (max_length=5)."""
    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis

    items = [
        InterestItem(**_make_interest_item(product=p)) for p in _EXPECTED_PRODUCTS[:6]
    ]
    with pytest.raises(ValidationError):
        InterestsAxis(items=items)


def test_interests_axis_preserves_item_fields():
    """InterestsAxis preserves all fields of contained InterestItems."""
    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis

    item = InterestItem(
        product="hogar",
        needs=["mayor_cobertura", "financiacion"],
        evidence="Quiere asegurar la casa",
        confidence="medium",
    )
    axis = InterestsAxis(items=[item])
    assert axis.items[0].product == "hogar"
    assert axis.items[0].confidence == "medium"
    assert axis.items[0].needs == ["mayor_cobertura", "financiacion"]


# ===========================================================================
# Phase 2: Agent 1 — interests
# ===========================================================================

# ---------------------------------------------------------------------------
# 2.1 — Prompt contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("product", _EXPECTED_PRODUCTS)
def test_prompt_contains_all_9_products(product):
    """DIMENSION['prompt'] contains each of the 9 product IDs verbatim."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert product in DIMENSION["prompt"], f"Prompt is missing product: {product}"


@pytest.mark.parametrize("need", _EXPECTED_NEEDS)
def test_prompt_contains_all_8_need_tags(need):
    """DIMENSION['prompt'] contains each of the 8 need tags verbatim."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert need in DIMENSION["prompt"], f"Prompt is missing need tag: {need}"


def test_prompt_has_constraints_block():
    """Prompt contains a CONSTRAINTS block with max 5 and empty-if-none guidance."""
    from app.analysis.universal.interest.interests import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "CONSTRAINTS" in prompt, "Prompt must have a CONSTRAINTS block"
    assert "5" in prompt, "Prompt must mention max 5 constraint"
    # Accept 'empty' or '[]' as empty-if-none indicator
    assert (
        "empty" in prompt or "[]" in prompt
    ), "Prompt must mention empty fallback when no interests detected"


def test_prompt_has_do_not_block():
    """Prompt contains a DO NOT block with exclusion guidance."""
    from app.analysis.universal.interest.interests import DIMENSION

    prompt = DIMENSION["prompt"]
    assert "DO NOT" in prompt, "Prompt must have a DO NOT block"


def test_prompt_requires_evidence():
    """Prompt mentions evidence as a required field."""
    from app.analysis.universal.interest.interests import DIMENSION

    assert "evidence" in DIMENSION["prompt"], "Prompt must reference 'evidence'"


# ---------------------------------------------------------------------------
# 2.2 — DIMENSION dict contract
# ---------------------------------------------------------------------------


def test_dimension_dict_contract():
    """DIMENSION dict has correct name, target_field, schema, and model."""
    from app.analysis.universal.interest.interests import DIMENSION, InterestsAxis

    assert DIMENSION["name"] == "interests"
    assert DIMENSION["target_field"] == "detected_interests"
    assert DIMENSION["schema"] is InterestsAxis
    assert DIMENSION["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 2.3 — analyze() returns InterestsAxis (mocked client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_returns_interests_axis():
    """analyze() returns InterestsAxis with items when LLM returns valid data."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import (
        InterestItem,
        InterestsAxis,
        analyze,
    )

    expected = InterestsAxis(
        items=[
            InterestItem(
                product="auto_todo_riesgo",
                needs=["precio_competitivo"],
                evidence="Quiero asegurar el auto",
                confidence="high",
            )
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("some transcript", client)

    assert isinstance(
        result, InterestsAxis
    ), f"analyze() must return InterestsAxis, got {type(result)}"
    assert result is expected


@pytest.mark.asyncio
async def test_analyze_returns_empty_interests_axis():
    """analyze() with no product mentions returns InterestsAxis with empty items."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interests import InterestsAxis, analyze

    expected = InterestsAxis()  # empty items

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("greeting only", client)

    assert isinstance(result, InterestsAxis)
    assert result.items == []


# ===========================================================================
# Phase 3: Agent 2 — interest_level
# ===========================================================================

# ---------------------------------------------------------------------------
# 3.1 — ProductScore schema
# ---------------------------------------------------------------------------


def _make_product_score(**overrides):
    """Return a valid ProductScore kwargs dict."""
    base = {
        "product": "auto_todo_riesgo",
        "score": 75,
        "reason": "El cliente mostró mucho interés",
    }
    base.update(overrides)
    return base


def test_product_score_valid_construction():
    """ProductScore accepts product, score, and reason."""
    from app.analysis.universal.interest.interest_level import ProductScore

    ps = ProductScore(**_make_product_score())
    assert ps.product == "auto_todo_riesgo"
    assert ps.score == 75
    assert ps.reason == "El cliente mostró mucho interés"


def test_product_score_score_is_0_to_100():
    """ProductScore accepts boundary values 0 and 100."""
    from app.analysis.universal.interest.interest_level import ProductScore

    ps_min = ProductScore(**_make_product_score(score=0))
    ps_max = ProductScore(**_make_product_score(score=100))
    assert ps_min.score == 0
    assert ps_max.score == 100


def test_product_score_rejects_score_above_100():
    """ProductScore raises ValidationError when score > 100."""
    from pydantic import ValidationError

    from app.analysis.universal.interest.interest_level import ProductScore

    with pytest.raises(ValidationError):
        ProductScore(**_make_product_score(score=101))


def test_product_score_rejects_score_below_0():
    """ProductScore raises ValidationError when score < 0."""
    from pydantic import ValidationError

    from app.analysis.universal.interest.interest_level import ProductScore

    with pytest.raises(ValidationError):
        ProductScore(**_make_product_score(score=-1))


# ---------------------------------------------------------------------------
# 3.1 — InterestLevelResult schema
# ---------------------------------------------------------------------------


def _make_interest_level_result(**overrides):
    """Return a valid InterestLevelResult kwargs dict."""
    base = {
        "per_product": [{"product": "auto_todo_riesgo", "score": 75, "reason": "ok"}],
        "general_score": 71,
        "level": "high",
        "reason": "El cliente mostró interés claro",
        "positive_signals": ["preguntó por coberturas"],
        "negative_signals": [],
        "confidence": "high",
    }
    base.update(overrides)
    return base


def test_interest_level_result_valid_construction():
    """InterestLevelResult accepts all valid fields."""
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    result = InterestLevelResult(**_make_interest_level_result())
    assert result.general_score == 71
    assert result.level == "high"
    assert result.confidence == "high"


@pytest.mark.parametrize(
    "level",
    ["very_low", "low", "medium", "high", "very_high"],
)
def test_interest_level_result_accepts_all_5_levels(level):
    """InterestLevelResult accepts all 5 valid level values."""
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    result = InterestLevelResult(**_make_interest_level_result(level=level))
    assert result.level == level


def test_interest_level_result_rejects_invalid_level():
    """InterestLevelResult raises ValidationError for unknown level."""
    from pydantic import ValidationError

    from app.analysis.universal.interest.interest_level import InterestLevelResult

    with pytest.raises(ValidationError):
        InterestLevelResult(**_make_interest_level_result(level="none"))


def test_interest_level_result_positive_signals_max_3():
    """InterestLevelResult rejects more than 3 positive_signals."""
    from pydantic import ValidationError

    from app.analysis.universal.interest.interest_level import InterestLevelResult

    with pytest.raises(ValidationError):
        InterestLevelResult(
            **_make_interest_level_result(positive_signals=["a", "b", "c", "d"])
        )


def test_interest_level_result_negative_signals_max_3():
    """InterestLevelResult rejects more than 3 negative_signals."""
    from pydantic import ValidationError

    from app.analysis.universal.interest.interest_level import InterestLevelResult

    with pytest.raises(ValidationError):
        InterestLevelResult(
            **_make_interest_level_result(negative_signals=["a", "b", "c", "d"])
        )


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_interest_level_result_accepts_valid_confidence(confidence):
    """InterestLevelResult accepts low, medium, high as confidence."""
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    result = InterestLevelResult(**_make_interest_level_result(confidence=confidence))
    assert result.confidence == confidence


# ---------------------------------------------------------------------------
# 3.1 — compute_general_score() — pure function
# ---------------------------------------------------------------------------


def test_compute_general_score_with_previous():
    """70/30 formula: max(scores)*0.7 + previous*0.3, clamped to int."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    # max([80, 60]) = 80; 80*0.7 + 50*0.3 = 56 + 15 = 71
    result = compute_general_score([80, 60], previous=50)
    assert result == 71


def test_compute_general_score_no_previous():
    """Without previous score, result equals max of product scores (100% current)."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    result = compute_general_score([75, 40], previous=None)
    assert result == 75


def test_compute_general_score_single_product_with_previous():
    """Single product score with previous applies 70/30 correctly."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    # 90*0.7 + 30*0.3 = 63 + 9 = 72
    result = compute_general_score([90], previous=30)
    assert result == 72


def test_compute_general_score_empty_products_returns_0():
    """Empty product scores list yields general_score=0."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    result = compute_general_score([], previous=None)
    assert result == 0


def test_compute_general_score_empty_products_ignores_previous():
    """Empty product scores: general_score=0 even if previous is set."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    result = compute_general_score([], previous=80)
    assert result == 0


def test_compute_general_score_clamped_to_100():
    """Result is clamped to maximum 100."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    result = compute_general_score([100], previous=100)
    assert result == 100


def test_compute_general_score_clamped_to_0():
    """Result is clamped to minimum 0 (can't go negative)."""
    from app.analysis.universal.interest.interest_level import compute_general_score

    result = compute_general_score([0], previous=0)
    assert result == 0


# ---------------------------------------------------------------------------
# 3.1 — score_to_level() — pure function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, expected_level",
    [
        (0, "very_low"),
        (20, "very_low"),
        (21, "low"),
        (40, "low"),
        (41, "medium"),
        (60, "medium"),
        (61, "high"),
        (80, "high"),
        (81, "very_high"),
        (100, "very_high"),
    ],
)
def test_score_to_level_boundaries(score, expected_level):
    """score_to_level maps scores to the correct level bucket."""
    from app.analysis.universal.interest.interest_level import score_to_level

    assert score_to_level(score) == expected_level


def test_score_to_level_no_products_returns_very_low():
    """score_to_level(0) when no products → very_low."""
    from app.analysis.universal.interest.interest_level import score_to_level

    assert score_to_level(0) == "very_low"


# ---------------------------------------------------------------------------
# 3.2 — DIMENSION dict contract for interest_level
# ---------------------------------------------------------------------------


def test_interest_level_dimension_dict_contract():
    """interest_level DIMENSION dict has required keys with correct values."""
    from app.analysis.universal.interest.interest_level import (
        DIMENSION,
        InterestLevelResult,
    )

    assert DIMENSION["name"] == "interest_level"
    assert DIMENSION["target_field"] == "interest_level"
    assert DIMENSION["schema"] is InterestLevelResult
    assert DIMENSION["model"] == "gpt-4o-mini"


def test_interest_level_prompt_has_products_context():
    """interest_level DIMENSION prompt references detected products dynamically."""
    from app.analysis.universal.interest.interest_level import DIMENSION

    # The prompt should indicate it uses injected product context
    prompt = DIMENSION["prompt"]
    assert "product" in prompt.lower(), "Prompt must reference products"
    assert "score" in prompt.lower(), "Prompt must reference scoring"


def test_interest_level_prompt_has_constraints():
    """interest_level prompt contains CONSTRAINTS block."""
    from app.analysis.universal.interest.interest_level import DIMENSION

    assert "CONSTRAINTS" in DIMENSION["prompt"]


# ---------------------------------------------------------------------------
# 3.2 — analyze() returns InterestLevelResult (mocked client)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interest_level_analyze_returns_result():
    """analyze() returns InterestLevelResult with correct formula-computed score."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interest_level import (
        InterestLevelResult,
        analyze,
    )
    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis

    interests = InterestsAxis(
        items=[
            InterestItem(
                product="auto_todo_riesgo",
                needs=["precio_competitivo"],
                evidence="Quiero asegurar el auto",
                confidence="high",
            )
        ]
    )
    # LLM returns per_product with score=80; previous_score=None → general_score=80
    llm_raw = InterestLevelResult(
        per_product=[
            {
                "product": "auto_todo_riesgo",
                "score": 80,
                "reason": "expressed clear interest",
            }
        ],
        general_score=99,  # LLM placeholder — will be overridden by formula
        level="very_high",
        reason="Strong buying signals",
        positive_signals=["asked about coverage"],
        negative_signals=[],
        confidence="high",
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = llm_raw
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze(
        "some transcript", client, interests=interests, previous_score=None
    )

    assert isinstance(result, InterestLevelResult)
    # Formula: no previous → general_score = max([80]) = 80
    # score_to_level(80) → "high" (61-80 bucket)
    assert result.general_score == 80
    assert result.level == "high"
    assert result.confidence == "high"
    assert result.reason == "Strong buying signals"
    assert len(result.per_product) == 1
    assert result.per_product[0].product == "auto_todo_riesgo"


@pytest.mark.asyncio
async def test_interest_level_analyze_with_previous_score():
    """analyze() with previous_score passes it for formula computation."""
    from unittest.mock import AsyncMock, MagicMock

    from app.analysis.universal.interest.interest_level import (
        InterestLevelResult,
        analyze,
    )
    from app.analysis.universal.interest.interests import InterestsAxis

    interests = InterestsAxis()

    # LLM returns per_product with scores
    llm_result = InterestLevelResult(
        per_product=[{"product": "hogar", "score": 80, "reason": "ok"}],
        general_score=71,  # LLM's raw answer; we override with formula
        level="high",
        reason="Some reason",
        positive_signals=[],
        negative_signals=[],
        confidence="medium",
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = llm_result
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await analyze("transcript", client, interests=interests, previous_score=50)

    assert isinstance(result, InterestLevelResult)
    # general_score must be computed from formula: max([80])*0.7 + 50*0.3 = 71
    assert result.general_score == 71


# ===========================================================================
# Phase 4: Pipeline Orchestration
# ===========================================================================

# ---------------------------------------------------------------------------
# 4.1 — run_interest_pipeline() — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_returns_both_results_on_success():
    """run_interest_pipeline() returns (InterestsAxis, InterestLevelResult) on success."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline
    from app.analysis.universal.interest.interest_level import InterestLevelResult
    from app.analysis.universal.interest.interests import InterestsAxis

    fake_interests = InterestsAxis()
    fake_level = InterestLevelResult(
        per_product=[],
        general_score=60,
        level="medium",
        reason="ok",
        positive_signals=[],
        negative_signals=[],
        confidence="medium",
    )

    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ),
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(return_value=fake_level),
        ),
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client, previous_score=None
        )

    assert interests_result is fake_interests
    assert level_result is fake_level


@pytest.mark.asyncio
async def test_pipeline_passes_interests_output_to_agent2():
    """run_interest_pipeline() feeds Agent 1 output into Agent 2 call."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline
    from app.analysis.universal.interest.interest_level import InterestLevelResult
    from app.analysis.universal.interest.interests import InterestItem, InterestsAxis

    fake_interests = InterestsAxis(
        items=[
            InterestItem(
                product="hogar",
                needs=[],
                evidence="quiero asegurar la casa",
                confidence="high",
            )
        ]
    )
    fake_level = InterestLevelResult(
        per_product=[],
        general_score=70,
        level="high",
        reason="ok",
        positive_signals=[],
        negative_signals=[],
        confidence="high",
    )
    mock_agent2 = AsyncMock(return_value=fake_level)

    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ),
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=mock_agent2,
        ),
    ):
        await run_interest_pipeline("transcript", client, previous_score=42)

    # Agent 2 MUST be called with interests=fake_interests and previous_score=42
    mock_agent2.assert_called_once()
    _, kwargs = mock_agent2.call_args
    assert kwargs["interests"] is fake_interests
    assert kwargs["previous_score"] == 42


# ---------------------------------------------------------------------------
# 4.1 — Agent 1 failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_agent1_fail_returns_error_markers_for_both():
    """When Agent 1 raises, Agent 2 does NOT run and both results are error dicts."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline

    mock_agent2 = AsyncMock()

    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(side_effect=RuntimeError("LLM timeout")),
        ),
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=mock_agent2,
        ),
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client
        )

    # Agent 2 must NOT have been called
    mock_agent2.assert_not_called()

    # Both results must be error dicts with "error" key
    assert isinstance(interests_result, dict), "interests_result must be error dict"
    assert "error" in interests_result, "interests_result must have 'error' key"
    assert isinstance(level_result, dict), "level_result must be error dict"
    assert "error" in level_result, "level_result must have 'error' key"


@pytest.mark.asyncio
async def test_pipeline_agent1_fail_error_marker_has_agent_name():
    """Agent 1 failure error dicts include 'failed_agent' identifying the agent."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline

    client = AsyncMock()

    with patch(
        "app.analysis.universal.interest.pipeline.interests_analyze",
        new=AsyncMock(side_effect=ValueError("parse error")),
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client
        )

    assert interests_result.get("failed_agent") == "interests"
    assert level_result.get("failed_agent") == "interest_level"


# ---------------------------------------------------------------------------
# 4.1 — Agent 2 failure path (Agent 1 succeeded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_agent2_fail_keeps_agent1_result():
    """When Agent 2 raises, Agent 1 result is preserved; level gets error dict."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline
    from app.analysis.universal.interest.interests import InterestsAxis

    fake_interests = InterestsAxis()
    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ),
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(side_effect=RuntimeError("scoring failed")),
        ),
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client
        )

    # Agent 1 result preserved
    assert interests_result is fake_interests

    # Agent 2 gets error dict
    assert isinstance(level_result, dict)
    assert "error" in level_result
    assert level_result.get("failed_agent") == "interest_level"


@pytest.mark.asyncio
async def test_pipeline_error_markers_are_distinguishable_from_empty_success():
    """Error dicts are distinguishable from a valid empty InterestsAxis."""
    from unittest.mock import AsyncMock, patch

    from app.analysis.universal.interest import run_interest_pipeline
    from app.analysis.universal.interest.interests import InterestsAxis

    # Success path: empty interests (no products detected)
    fake_interests = InterestsAxis()
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    fake_level = InterestLevelResult(
        per_product=[],
        general_score=0,
        level="very_low",
        reason="no products",
        positive_signals=[],
        negative_signals=[],
        confidence="low",
    )
    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ),
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(return_value=fake_level),
        ),
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client
        )

    # Success result is InterestsAxis, NOT a dict → distinguishable from error
    assert isinstance(
        interests_result, InterestsAxis
    ), "Success path must return InterestsAxis, not a dict"
    assert isinstance(
        level_result, InterestLevelResult
    ), "Success path must return InterestLevelResult, not a dict"
