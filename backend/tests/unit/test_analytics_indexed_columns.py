"""Unit tests for analytics service — indexed column queries for BI-friendly queries.

TDD RED → GREEN → TRIANGULATE → REFACTOR

Covers (task 2.5):
- get_primary_objection_breakdown() uses primary_objection_category column (not json_each)
- get_primary_pain_breakdown() uses primary_pain_category column (not json_each)
- service_issues count queries use service_issues_count column (not json_each)
- Verify no JSON extraction needed for these queries after BI columns added

Acceptance criteria: analytics service indexed-column scenario.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixture: isolated DB with analytics data seeded
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def analytics_bi_db(tmp_path: Path):
    """DB with call_analyses rows having denormalized BI columns set."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analytics_bi_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead A",
            phone="+5411000001",
            lead_id="lead-an-a",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead B",
            phone="+5411000002",
            lead_id="lead-an-b",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_bi_call_analysis(
    db_module,
    *,
    session_id: str | None = None,
    lead_id: str = "lead-an-a",
    client_id: str = "quintana-seguros",
    primary_objection_category: str | None = None,
    primary_pain_category: str | None = None,
    objections_count: int = 0,
    pain_points_count: int = 0,
    service_issues_count: int = 0,
    analyzed_at: datetime | None = None,
):
    """Seed a CallSession + CallAnalysis with BI denormalized columns."""
    from app.calls.models import CallSession, CallAnalysis

    assert db_module.async_session_factory is not None
    sid = session_id or str(uuid.uuid4())
    aid = str(uuid.uuid4())
    ts = analyzed_at or datetime.now(timezone.utc)

    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=sid,
            client_id=client_id,
            lead_id=lead_id,
            status="completed",
            started_at=ts,
            ended_at=ts,
        )
        ca = CallAnalysis(
            id=aid,
            session_id=sid,
            lead_id=lead_id,
            client_id=client_id,
            analyzed_at=ts,
            classification="completed_positive",
            # BI denormalized columns
            primary_objection_category=primary_objection_category,
            primary_pain_category=primary_pain_category,
            objections_count=objections_count,
            pain_points_count=pain_points_count,
            service_issues_count=service_issues_count,
        )
        sess.add(cs)
        sess.add(ca)
        await sess.commit()

    return sid, aid


# ---------------------------------------------------------------------------
# Task 2.5 tests — indexed column queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_primary_objection_breakdown_uses_indexed_column(analytics_bi_db):
    """get_primary_objection_breakdown() returns counts per primary_objection_category.

    The query MUST use the primary_objection_category column directly (not json_each).
    Two calls with 'price', one with 'current_provider' → price count=2, current_provider=1.

    Acceptance: analytics service indexed-column scenario.
    """
    from app.analytics.service import get_primary_objection_breakdown

    ts = datetime.now(timezone.utc)
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_objection_category="price",
        objections_count=2,
        analyzed_at=ts,
    )
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_objection_category="price",
        objections_count=1,
        analyzed_at=ts,
    )
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_objection_category="current_provider",
        objections_count=1,
        analyzed_at=ts,
    )
    # A call with no primary objection (NULL) — should NOT appear in breakdown
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_objection_category=None,
        objections_count=0,
        analyzed_at=ts,
    )

    from datetime import timedelta

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_bi_db.async_session_factory is not None
    async with analytics_bi_db.async_session_factory() as sess:
        result = await get_primary_objection_breakdown(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    categories = {item["category"]: item["count"] for item in result["breakdown"]}
    assert categories.get("price") == 2, (
        f"Expected price count=2, got {categories.get('price')!r}. Full breakdown: {result}"
    )
    assert categories.get("current_provider") == 1, (
        f"Expected current_provider count=1, got {categories.get('current_provider')!r}"
    )
    assert None not in categories, "NULL primary_objection_category must not appear in breakdown"


@pytest.mark.asyncio
async def test_get_primary_pain_breakdown_uses_indexed_column(analytics_bi_db):
    """get_primary_pain_breakdown() returns counts per primary_pain_category.

    The query MUST use the primary_pain_category column directly (not json_each).
    Two calls with 'price_too_high', one with 'service_quality' → counts 2 and 1.
    A NULL primary_pain_category row must NOT appear in the breakdown.

    Acceptance: analytics service indexed-column scenario (primary pain).
    """
    from app.analytics.service import get_primary_pain_breakdown

    ts = datetime.now(timezone.utc)
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_pain_category="price_too_high",
        pain_points_count=2,
        analyzed_at=ts,
    )
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_pain_category="price_too_high",
        pain_points_count=1,
        analyzed_at=ts,
    )
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_pain_category="service_quality",
        pain_points_count=1,
        analyzed_at=ts,
    )
    # A call with no primary pain (NULL) — should NOT appear in breakdown
    await _seed_bi_call_analysis(
        analytics_bi_db,
        primary_pain_category=None,
        pain_points_count=0,
        analyzed_at=ts,
    )

    from datetime import timedelta

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_bi_db.async_session_factory is not None
    async with analytics_bi_db.async_session_factory() as sess:
        result = await get_primary_pain_breakdown(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    categories = {item["category"]: item["count"] for item in result["breakdown"]}
    assert categories.get("price_too_high") == 2, (
        f"Expected price_too_high count=2, got {categories.get('price_too_high')!r}. "
        f"Full breakdown: {result}"
    )
    assert categories.get("service_quality") == 1, (
        f"Expected service_quality count=1, got {categories.get('service_quality')!r}"
    )
    assert None not in categories, (
        "NULL primary_pain_category must not appear in breakdown"
    )
    # Ranked descending by count: price_too_high (2) before service_quality (1)
    ranks = {item["category"]: item["rank"] for item in result["breakdown"]}
    assert ranks["price_too_high"] == 1, (
        f"Highest-count category must rank first. Got ranks: {ranks}"
    )


@pytest.mark.asyncio
async def test_get_primary_pain_breakdown_respects_agent_filter(analytics_bi_db):
    """get_primary_pain_breakdown() filters by agent_id when provided.

    Seeds one pain category under a specific agent and another with no agent.
    Filtering by the agent returns only that agent's call.

    Acceptance: analytics service indexed-column scenario (agent scoping).
    """
    import uuid as _uuid

    from app.analytics.service import get_primary_pain_breakdown
    from app.calls.models import CallSession, CallAnalysis

    ts = datetime.now(timezone.utc)
    agent_id = "agent-pain-1"

    assert analytics_bi_db.async_session_factory is not None
    async with analytics_bi_db.async_session_factory() as sess:
        # Call attributed to the agent
        sid_a = str(_uuid.uuid4())
        sess.add(
            CallSession(
                id=sid_a,
                client_id="quintana-seguros",
                lead_id="lead-an-a",
                agent_id=agent_id,
                status="completed",
                started_at=ts,
                ended_at=ts,
            )
        )
        sess.add(
            CallAnalysis(
                id=str(_uuid.uuid4()),
                session_id=sid_a,
                lead_id="lead-an-a",
                client_id="quintana-seguros",
                analyzed_at=ts,
                classification="completed_positive",
                primary_pain_category="coverage_gap",
                pain_points_count=1,
            )
        )
        # Call with a different (NULL) agent — must be excluded by the filter
        sid_b = str(_uuid.uuid4())
        sess.add(
            CallSession(
                id=sid_b,
                client_id="quintana-seguros",
                lead_id="lead-an-b",
                agent_id=None,
                status="completed",
                started_at=ts,
                ended_at=ts,
            )
        )
        sess.add(
            CallAnalysis(
                id=str(_uuid.uuid4()),
                session_id=sid_b,
                lead_id="lead-an-b",
                client_id="quintana-seguros",
                analyzed_at=ts,
                classification="completed_positive",
                primary_pain_category="price_too_high",
                pain_points_count=1,
            )
        )
        await sess.commit()

    from datetime import timedelta

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    async with analytics_bi_db.async_session_factory() as sess:
        result = await get_primary_pain_breakdown(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=agent_id,
        )

    categories = {item["category"]: item["count"] for item in result["breakdown"]}
    assert categories == {"coverage_gap": 1}, (
        f"Agent filter must scope to the agent's calls only. Got: {categories}"
    )


@pytest.mark.asyncio
async def test_get_service_issues_uses_count_column(analytics_bi_db):
    """get_service_issues_count_total() uses service_issues_count column (not json_each).

    Two calls with service_issues_count=2 and one with count=1.
    Returns total service issue occurrences across calls.

    Acceptance: analytics service indexed-column scenario.
    """
    from app.analytics.service import get_service_issues_count_total

    ts = datetime.now(timezone.utc)
    await _seed_bi_call_analysis(
        analytics_bi_db,
        service_issues_count=2,
        analyzed_at=ts,
    )
    await _seed_bi_call_analysis(
        analytics_bi_db,
        service_issues_count=1,
        analyzed_at=ts,
    )
    # Call with no service issues — count=0 should not contribute
    await _seed_bi_call_analysis(
        analytics_bi_db,
        service_issues_count=0,
        analyzed_at=ts,
    )

    from datetime import timedelta

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_bi_db.async_session_factory is not None
    async with analytics_bi_db.async_session_factory() as sess:
        result = await get_service_issues_count_total(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["total_service_issues"] == 3, (
        f"Expected total_service_issues=3 (2+1+0), got {result['total_service_issues']!r}"
    )
    assert result["calls_with_issues"] == 2, (
        f"Expected calls_with_issues=2, got {result['calls_with_issues']!r}"
    )
