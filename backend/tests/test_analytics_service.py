"""Analytics service unit tests — RED phase (task 2.1, 3.1).

Tests for overview, service issues, interests, and agent stats service functions.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def analytics_service_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + test data seeded."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analytics_svc_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Test Lead",
            phone="+54111111111",
            lead_id="lead-svc-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Helpers for seeding analytics-related data
# ---------------------------------------------------------------------------


async def _seed_call_analysis(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    session_id: str | None = None,
    lead_id: str = "lead-svc-001",
    classification: str = "completed_positive",
    service_issues: list[str] | list[dict] | None = None,
    analyzed_at: datetime | None = None,
    agent_id: str | None = None,
):
    """Seed a CallSession + CallAnalysis for testing."""
    from app.calls.models import CallSession, CallAnalysis

    assert db_module.async_session_factory is not None
    session_id = session_id or str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())
    ts = analyzed_at or datetime.now(timezone.utc)

    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=session_id,
            client_id=client_id,
            lead_id=lead_id,
            status="completed",
            started_at=ts,
            ended_at=ts,
            duration_seconds=120.0,
            agent_id=agent_id,
        )
        ca = CallAnalysis(
            id=analysis_id,
            session_id=session_id,
            lead_id=lead_id,
            client_id=client_id,
            classification=classification,
            service_issues=json.dumps(service_issues or []),
            analyzed_at=ts,
        )
        sess.add(cs)
        sess.add(ca)
        await sess.commit()

    return session_id, analysis_id


async def _seed_interest_history(
    db_module,
    *,
    lead_id: str = "lead-svc-001",
    interest_name: str = "auto_insurance",
    recorded_at: datetime | None = None,
):
    """Seed a LeadProfileFact with signal: namespace for interests."""
    from app.leads.models import LeadProfileFact

    assert db_module.async_session_factory is not None
    fact_id = str(uuid.uuid4())
    ts = recorded_at or datetime.now(timezone.utc)

    async with db_module.async_session_factory() as sess:
        fact = LeadProfileFact(
            id=fact_id,
            lead_id=lead_id,
            fact_key=f"signal:{interest_name}",
            fact_value="detected",
            recorded_at=ts,
        )
        sess.add(fact)
        await sess.commit()

    return fact_id


# ---------------------------------------------------------------------------
# 2.1 RED: get_overview tests
# ---------------------------------------------------------------------------


async def test_overview_empty_period(analytics_service_db):
    """No calls in period → total_calls=0, conversion_rate=None, empty dists."""
    from app.analytics.service import get_overview

    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    date_to = datetime(2025, 1, 31, tzinfo=timezone.utc)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_overview(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["total_calls"] == 0
    assert result["conversion_rate"] is None
    assert result["outcome_distribution"] == {}
    # engagement_distribution must NOT exist (qora-outcome spec)
    assert (
        "engagement_distribution" not in result
    ), "engagement_distribution must be removed from analytics response (qora-outcome spec)"


async def test_overview_counts_calls_in_period(analytics_service_db):
    """Calls within period are counted correctly."""
    from app.analytics.service import get_overview

    ts = datetime.now(timezone.utc)
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_positive",
        analyzed_at=ts,
    )
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_negative",
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_overview(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["total_calls"] == 2
    assert result["outcome_distribution"]["completed_positive"] == 1
    assert result["outcome_distribution"]["completed_negative"] == 1
    # engagement_distribution must NOT be in result
    assert "engagement_distribution" not in result


async def test_overview_conversion_rate(analytics_service_db):
    """Conversion rate = completed_positive / total_calls (qora-outcome spec)."""
    from app.analytics.service import get_overview

    ts = datetime.now(timezone.utc)
    # 2 completed_positive + 2 completed_negative = 50%
    for _ in range(2):
        await _seed_call_analysis(
            analytics_service_db, classification="completed_positive", analyzed_at=ts
        )
    for _ in range(2):
        await _seed_call_analysis(
            analytics_service_db, classification="completed_negative", analyzed_at=ts
        )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_overview(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["total_calls"] == 4
    assert result["conversion_rate"] == pytest.approx(0.5)


async def test_overview_agent_filter(analytics_service_db):
    """Agent filter scopes results to calls for that agent."""
    from app.analytics.service import get_overview
    from app.tenants.models import Agent

    # Create an agent first
    async with analytics_service_db.async_session_factory() as sess:
        agent = Agent(
            id="agent-test-001",
            client_id="quintana-seguros",
            slug="test-agent",
            name="Test Agent",
            voice_id="pNInz6obpgDQGcFmaJgB",
            model="gpt-4o-mini",
            is_active=True,
            is_default=False,
        )
        sess.add(agent)
        await sess.commit()

    ts = datetime.now(timezone.utc)
    # 1 call for agent-test-001
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_positive",
        analyzed_at=ts,
        agent_id="agent-test-001",
    )
    # 1 call without agent
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_negative",
        analyzed_at=ts,
        agent_id=None,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_overview(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id="agent-test-001",
        )

    # Only the agent-test-001 call
    assert result["total_calls"] == 1
    assert result["outcome_distribution"]["completed_positive"] == 1


# ---------------------------------------------------------------------------
# 2.1 RED: get_service_issues tests
# ---------------------------------------------------------------------------


async def test_service_issues_empty_period(analytics_service_db):
    """No service issues → empty list."""
    from app.analytics.service import get_service_issues

    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    date_to = datetime(2025, 1, 31, tzinfo=timezone.utc)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["issues"] == []


async def test_service_issues_ranked_by_frequency(analytics_service_db):
    """Service issues are ranked descending by count."""
    from app.analytics.service import get_service_issues

    ts = datetime.now(timezone.utc)
    # Issue A appears 3 times, Issue B appears 1 time
    for _ in range(3):
        await _seed_call_analysis(
            analytics_service_db,
            service_issues=["billing_error"],
            analyzed_at=ts,
        )
    await _seed_call_analysis(
        analytics_service_db,
        service_issues=["coverage_gap"],
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    issues = result["issues"]
    assert len(issues) == 2
    assert issues[0]["issue"] == "billing_error"
    assert issues[0]["count"] == 3
    assert issues[0]["rank"] == 1
    assert issues[1]["issue"] == "coverage_gap"
    assert issues[1]["count"] == 1
    assert issues[1]["rank"] == 2


async def test_service_issues_structured_row_returns_category(analytics_service_db):
    """Structured JSON row extracts category as the issue key."""
    from app.analytics.service import get_service_issues

    ts = datetime.now(timezone.utc)
    # Seed a structured issue (new format: list of dicts)
    await _seed_call_analysis(
        analytics_service_db,
        service_issues=[
            {
                "category": "billing_issue",
                "description": "Lead was overcharged.",
                "source": "current_provider",
                "severity": "high",
                "evidence": "Me cobraron de más.",
                "confidence": "high",
            }
        ],
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    issues = result["issues"]
    assert len(issues) == 1
    assert issues[0]["issue"] == "billing_issue"
    assert issues[0]["count"] == 1
    assert issues[0]["rank"] == 1


async def test_service_issues_legacy_string_row_returns_string(analytics_service_db):
    """Legacy string row (old format) returns the raw string as issue key."""
    from app.analytics.service import get_service_issues

    ts = datetime.now(timezone.utc)
    # Seed a legacy issue (old format: list of strings)
    await _seed_call_analysis(
        analytics_service_db,
        service_issues=["billing_error"],
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    issues = result["issues"]
    assert len(issues) == 1
    assert issues[0]["issue"] == "billing_error"
    assert issues[0]["count"] == 1
    assert issues[0]["rank"] == 1


async def test_service_issues_mixed_legacy_and_structured(analytics_service_db):
    """Mixed legacy string and structured JSON rows aggregate correctly."""
    from app.analytics.service import get_service_issues

    ts = datetime.now(timezone.utc)
    # Legacy row
    await _seed_call_analysis(
        analytics_service_db,
        service_issues=["billing_error"],
        analyzed_at=ts,
    )
    # Structured row with different category
    await _seed_call_analysis(
        analytics_service_db,
        service_issues=[
            {
                "category": "delay",
                "description": "Provider took too long.",
                "source": "current_provider",
                "severity": "medium",
                "evidence": "Tardaron semanas.",
                "confidence": "high",
            }
        ],
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    issues = result["issues"]
    issue_keys = {i["issue"] for i in issues}
    assert "billing_error" in issue_keys
    assert "delay" in issue_keys
    # Each appears once (different keys)
    billing = next(i for i in issues if i["issue"] == "billing_error")
    delay = next(i for i in issues if i["issue"] == "delay")
    assert billing["count"] == 1
    assert delay["count"] == 1


# ---------------------------------------------------------------------------
# 3.1 RED: get_interests tests
# ---------------------------------------------------------------------------


async def test_interests_empty_period(analytics_service_db):
    """No interests in period → empty list."""
    from app.analytics.service import get_interests

    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    date_to = datetime(2025, 1, 31, tzinfo=timezone.utc)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_interests(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    assert result["interests"] == []


async def test_interests_trend_up(analytics_service_db):
    """Interest appearing more in current vs previous window has trend=up."""
    from app.analytics.service import get_interests

    now = datetime.now(timezone.utc)
    # Current window: now-7d to now — 5 occurrences
    for i in range(5):
        await _seed_interest_history(
            analytics_service_db,
            interest_name="solar_panels",
            recorded_at=now - timedelta(days=3 + i * 0.1),
        )
    # Previous window: now-14d to now-7d — 2 occurrences
    for i in range(2):
        await _seed_interest_history(
            analytics_service_db,
            interest_name="solar_panels",
            recorded_at=now - timedelta(days=8 + i),
        )

    date_from = now - timedelta(days=7)
    date_to = now

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_interests(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    interests = result["interests"]
    assert len(interests) >= 1
    solar = next((i for i in interests if i["interest"] == "solar_panels"), None)
    assert solar is not None
    assert solar["count"] == 5
    assert solar["previous_count"] == 2
    assert solar["trend"] == "up"


async def test_interests_trend_stable(analytics_service_db):
    """Interest with same count (±10%) in both windows has trend=stable."""
    from app.analytics.service import get_interests

    now = datetime.now(timezone.utc)
    # Same count (5) in both windows → stable
    for i in range(5):
        await _seed_interest_history(
            analytics_service_db,
            interest_name="home_insurance",
            recorded_at=now - timedelta(days=3 + i * 0.1),
        )
    for i in range(5):
        await _seed_interest_history(
            analytics_service_db,
            interest_name="home_insurance",
            recorded_at=now - timedelta(days=8 + i * 0.1),
        )

    date_from = now - timedelta(days=7)
    date_to = now

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_interests(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    interests = result["interests"]
    home = next((i for i in interests if i["interest"] == "home_insurance"), None)
    assert home is not None
    assert home["trend"] == "stable"


# ---------------------------------------------------------------------------
# 3.1 RED: get_agent_stats tests
# ---------------------------------------------------------------------------


async def test_agent_stats_empty_period(analytics_service_db):
    """No calls → empty agents list."""
    from app.analytics.service import get_agent_stats

    date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
    date_to = datetime(2025, 1, 31, tzinfo=timezone.utc)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_agent_stats(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
        )

    assert result["agents"] == []


async def test_agent_stats_null_agent_bucketed(analytics_service_db):
    """Calls with NULL agent_id appear as 'unassigned' entry."""
    from app.analytics.service import get_agent_stats

    ts = datetime.now(timezone.utc)
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_positive",
        analyzed_at=ts,
        agent_id=None,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_agent_stats(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
        )

    agents = result["agents"]
    assert len(agents) == 1
    unassigned = agents[0]
    assert unassigned["agent_id"] == "unassigned"
    assert unassigned["total_calls"] == 1
    # avg_engagement_quality must NOT be present (qora-outcome spec)
    assert (
        "avg_engagement_quality" not in unassigned
    ), "avg_engagement_quality must be removed from agent stats (qora-outcome spec)"


async def test_agent_stats_multi_agent(analytics_service_db):
    """Multiple agents each get their own row."""
    from app.analytics.service import get_agent_stats
    from app.tenants.models import Agent

    # Create two agents
    async with analytics_service_db.async_session_factory() as sess:
        for i in range(2):
            agent = Agent(
                id=f"agent-multi-{i:03d}",
                client_id="quintana-seguros",
                slug=f"agent-{i}",
                name=f"Agent {i}",
                voice_id="pNInz6obpgDQGcFmaJgB",
                model="gpt-4o-mini",
                is_active=True,
                is_default=(i == 0),
            )
            sess.add(agent)
        await sess.commit()

    ts = datetime.now(timezone.utc)
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_positive",
        analyzed_at=ts,
        agent_id="agent-multi-000",
    )
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_negative",
        analyzed_at=ts,
        agent_id="agent-multi-001",
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_agent_stats(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
        )

    agents = result["agents"]
    assert len(agents) == 2
    agent_ids = {a["agent_id"] for a in agents}
    assert "agent-multi-000" in agent_ids
    assert "agent-multi-001" in agent_ids


async def test_agent_stats_cross_client_isolation(analytics_service_db):
    """Agents from other clients MUST NOT appear."""
    from app.analytics.service import get_agent_stats
    from app.tenants.service import create_client
    from app.leads.service import create_lead

    # Create a second client with its own data
    async with analytics_service_db.async_session_factory() as sess:
        await create_client(
            sess,
            id="other-client",
            name="Other Corp",
            broker_name="OC",
            agent_name="Bot",
            voice_id="pNInz6obpgDQGcFmaJgB",
        )
        await create_lead(
            sess,
            client_id="other-client",
            name="Other Lead",
            phone="+54999999999",
            lead_id="lead-other",
        )
        await sess.commit()

    ts = datetime.now(timezone.utc)
    # Seed call for other-client
    await _seed_call_analysis(
        analytics_service_db,
        client_id="other-client",
        lead_id="lead-other",
        analyzed_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_agent_stats(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
        )

    # quintana-seguros has NO calls → empty
    assert result["agents"] == []


async def test_agent_stats_conversion_rate_uses_completed_positive(
    analytics_service_db,
):
    """qora-outcome spec: agent stats conversion_rate counts completed_positive (not 'interested')."""
    from app.analytics.service import get_agent_stats
    from app.tenants.models import Agent

    async with analytics_service_db.async_session_factory() as sess:
        agent = Agent(
            id="agent-conv-001",
            client_id="quintana-seguros",
            slug="agent-conv",
            name="Conv Agent",
            voice_id="pNInz6obpgDQGcFmaJgB",
            model="gpt-4o-mini",
            is_active=True,
            is_default=False,
        )
        sess.add(agent)
        await sess.commit()

    ts = datetime.now(timezone.utc)
    # 1 completed_positive + 1 completed_negative → 50% conversion
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_positive",
        analyzed_at=ts,
        agent_id="agent-conv-001",
    )
    await _seed_call_analysis(
        analytics_service_db,
        classification="completed_negative",
        analyzed_at=ts,
        agent_id="agent-conv-001",
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_agent_stats(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
        )

    agents = result["agents"]
    agent_entry = next(a for a in agents if a["agent_id"] == "agent-conv-001")
    assert agent_entry["total_calls"] == 2
    assert agent_entry["conversion_rate"] == pytest.approx(
        0.5
    ), "conversion_rate must count completed_positive only (qora-outcome spec)"
    # avg_engagement_quality must NOT exist
    assert "avg_engagement_quality" not in agent_entry


# ---------------------------------------------------------------------------
# CRITICAL 5: get_interests() agent_id filter
# ---------------------------------------------------------------------------


async def test_interests_agent_filter_scopes_results(analytics_service_db):
    """When agent_id provided, interests are scoped to leads called by that agent."""
    from app.analytics.service import get_interests
    from app.tenants.models import Agent

    # Create an agent
    async with analytics_service_db.async_session_factory() as sess:
        agent = Agent(
            id="agent-interests-001",
            client_id="quintana-seguros",
            slug="agent-interests",
            name="Interests Agent",
            voice_id="pNInz6obpgDQGcFmaJgB",
            model="gpt-4o-mini",
            is_active=True,
            is_default=False,
        )
        sess.add(agent)
        await sess.commit()

    ts = datetime.now(timezone.utc)

    # Seed a call for lead-svc-001 WITH the agent
    await _seed_call_analysis(
        analytics_service_db,
        lead_id="lead-svc-001",
        analyzed_at=ts,
        agent_id="agent-interests-001",
    )

    # Seed interest for lead-svc-001 (should be visible when filtering by agent)
    await _seed_interest_history(
        analytics_service_db,
        lead_id="lead-svc-001",
        interest_name="solar_panels",
        recorded_at=ts,
    )

    # Create a second lead for OTHER interest (no call with agent)
    async with analytics_service_db.async_session_factory() as sess:
        from app.leads.models import Lead

        other_lead = Lead(
            id="lead-other-interests",
            client_id="quintana-seguros",
            name="Other Lead",
            phone="+54222222222",
            status="new",
        )
        sess.add(other_lead)
        await sess.commit()

    # Seed interest for other lead (should NOT appear when filtered by agent)
    await _seed_interest_history(
        analytics_service_db,
        lead_id="lead-other-interests",
        interest_name="auto_insurance",
        recorded_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_interests(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id="agent-interests-001",
        )

    interests = result["interests"]
    interest_names = {i["interest"] for i in interests}
    # Only solar_panels (for the lead that has a call with agent-interests-001)
    assert "solar_panels" in interest_names
    assert "auto_insurance" not in interest_names


async def test_interests_agent_filter_none_returns_all(analytics_service_db):
    """When agent_id is None, all interests for the client are returned."""
    from app.analytics.service import get_interests

    ts = datetime.now(timezone.utc)
    await _seed_interest_history(
        analytics_service_db,
        lead_id="lead-svc-001",
        interest_name="life_insurance",
        recorded_at=ts,
    )

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_interests(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id=None,
        )

    interest_names = {i["interest"] for i in result["interests"]}
    assert "life_insurance" in interest_names


# ---------------------------------------------------------------------------
# CRITICAL 6: get_service_issues() LPF agent_id filter
# ---------------------------------------------------------------------------


async def test_service_issues_lpf_agent_filter(analytics_service_db):
    """LeadProfileFact service issues are scoped by agent when agent_id provided."""
    from app.analytics.service import get_service_issues
    from app.tenants.models import Agent
    from app.leads.models import Lead, LeadProfileFact

    # Create an agent
    async with analytics_service_db.async_session_factory() as sess:
        agent = Agent(
            id="agent-si-001",
            client_id="quintana-seguros",
            slug="agent-si",
            name="Service Issues Agent",
            voice_id="pNInz6obpgDQGcFmaJgB",
            model="gpt-4o-mini",
            is_active=True,
            is_default=False,
        )
        sess.add(agent)
        await sess.commit()

    ts = datetime.now(timezone.utc)

    # Seed a call for lead-svc-001 WITH the agent
    await _seed_call_analysis(
        analytics_service_db,
        lead_id="lead-svc-001",
        analyzed_at=ts,
        agent_id="agent-si-001",
    )

    # Seed LPF service_issue for lead-svc-001 (should appear with agent filter)
    async with analytics_service_db.async_session_factory() as sess:
        fact = LeadProfileFact(
            id=str(uuid.uuid4()),
            lead_id="lead-svc-001",
            fact_key="service_issue:billing_error",
            fact_value="detected",
            recorded_at=ts,
        )
        sess.add(fact)
        await sess.commit()

    # Create another lead (no call with agent)
    async with analytics_service_db.async_session_factory() as sess:
        other_lead = Lead(
            id="lead-si-other",
            client_id="quintana-seguros",
            name="SI Other",
            phone="+54333333333",
            status="new",
        )
        sess.add(other_lead)
        await sess.commit()

    # Seed LPF service_issue for other lead (should NOT appear with agent filter)
    async with analytics_service_db.async_session_factory() as sess:
        other_fact = LeadProfileFact(
            id=str(uuid.uuid4()),
            lead_id="lead-si-other",
            fact_key="service_issue:coverage_gap",
            fact_value="detected",
            recorded_at=ts,
        )
        sess.add(other_fact)
        await sess.commit()

    date_from = ts - timedelta(hours=1)
    date_to = ts + timedelta(hours=1)

    assert analytics_service_db.async_session_factory is not None
    async with analytics_service_db.async_session_factory() as sess:
        result = await get_service_issues(
            sess,
            client_id="quintana-seguros",
            date_from=date_from,
            date_to=date_to,
            agent_id="agent-si-001",
        )

    issue_names = {i["issue"] for i in result["issues"]}
    # billing_error should appear (from lead that has a call with agent-si-001)
    assert "billing_error" in issue_names
    # coverage_gap should NOT appear (from lead with no calls with agent-si-001)
    assert "coverage_gap" not in issue_names


# ---------------------------------------------------------------------------
# prior_window behavior documentation test
# ---------------------------------------------------------------------------


def test_prior_window_custom_range_same_duration():
    """Prior window for custom range uses same-duration rolling window.

    Given: March 2026 (31 days): 2026-03-01 00:00 UTC → 2026-03-31 23:59:59 UTC
    Then: prior_from = 2026-03-01 - 31 days ≈ 2026-01-29
          prior_to = 2026-03-01
    The previous window has the SAME duration, ending where current starts.
    """
    from app.analytics.service import prior_window

    date_from = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    date_to = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

    prior_from, prior_to = prior_window(date_from, date_to)

    # Prior window ends where current starts
    assert prior_to == date_from

    # Duration is preserved (same as current window)
    current_duration = date_to - date_from
    prior_duration = prior_to - prior_from
    assert prior_duration == current_duration

    # Specific dates for March custom range
    assert prior_from.year == 2026
    assert prior_from.month == 1
    assert prior_from.day == 29
