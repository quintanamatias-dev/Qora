"""Phase 3.2 — per-call catalog injection + empty-catalog skip (design.md P5-D5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def _make_catalog(*, products=None, need_tags=None, vertical="generic"):
    from app.analysis.profiles.schema import AnalysisProfileConfigV1, NeedTagEntry, ProductEntry

    return AnalysisProfileConfigV1(
        vertical=vertical,
        products=[
            ProductEntry(id=p, label_es=p, label_en=p) for p in (products or [])
        ],
        need_tags=[NeedTagEntry(id=n, label_es=n, label_en=n) for n in (need_tags or [])],
    )


async def test_run_interest_pipeline_skips_both_agents_when_products_empty():
    """Empty-products catalog: zero OpenAI calls, normal empty (non-error) result."""
    from app.analysis.universal.interest.pipeline import run_interest_pipeline
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    catalog = _make_catalog(products=[], need_tags=[])
    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(),
        ) as mock_agent1,
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(),
        ) as mock_agent2,
    ):
        interests_result, level_result = await run_interest_pipeline(
            "transcript", client, catalog=catalog
        )

    mock_agent1.assert_not_called()
    mock_agent2.assert_not_called()

    assert isinstance(interests_result, InterestsAxis)
    assert interests_result.items == []
    assert isinstance(level_result, InterestLevelResult)
    assert level_result.general_score == 0
    # Normal result, not an error marker
    assert not isinstance(interests_result, dict)
    assert not isinstance(level_result, dict)


async def test_run_interest_pipeline_runs_agent_1_when_needs_empty_but_products_not():
    """Non-empty products + empty need tags: Agent 1 still runs (no pipeline-level skip)."""
    from app.analysis.universal.interest.pipeline import run_interest_pipeline
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    catalog = _make_catalog(products=["only_product"], need_tags=[])
    fake_interests = InterestsAxis(items=[])
    fake_level = InterestLevelResult.model_construct(
        per_product=[],
        general_score=0,
        level="very_low",
        reason="ok",
        positive_signals=[],
        negative_signals=[],
        confidence="low",
    )

    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ) as mock_agent1,
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(return_value=fake_level),
        ) as mock_agent2,
    ):
        await run_interest_pipeline("transcript", client, catalog=catalog)

    mock_agent1.assert_called_once()
    mock_agent2.assert_called_once()
    _, kwargs = mock_agent1.call_args
    assert kwargs["catalog"] is catalog


async def test_run_interest_pipeline_without_catalog_defaults_to_insurance():
    """No catalog kwarg: defaults to the insurance template (backward compat)."""
    from app.analysis.universal.interest.pipeline import run_interest_pipeline
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    fake_interests = InterestsAxis(items=[])
    fake_level = InterestLevelResult.model_construct(
        per_product=[],
        general_score=0,
        level="very_low",
        reason="ok",
        positive_signals=[],
        negative_signals=[],
        confidence="low",
    )
    client = AsyncMock()

    with (
        patch(
            "app.analysis.universal.interest.pipeline.interests_analyze",
            new=AsyncMock(return_value=fake_interests),
        ) as mock_agent1,
        patch(
            "app.analysis.universal.interest.pipeline.interest_level_analyze",
            new=AsyncMock(return_value=fake_level),
        ),
    ):
        await run_interest_pipeline("transcript", client)

    mock_agent1.assert_called_once()
    _, kwargs = mock_agent1.call_args
    assert kwargs["catalog"].vertical == "insurance"
