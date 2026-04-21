"""Unit tests for call metrics — service aggregation and endpoint.

Covers REQ-1 (service), REQ-2 (endpoint), REQ-3 (schema).
Strict TDD: tests written FIRST, then implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + two leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/metrics_test.db",
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
            name="Lead One",
            phone="+54111111111",
            lead_id="lead-001",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead Two",
            phone="+54222222222",
            lead_id="lead-002",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_call(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "lead-001",
    status: str = "completed",
    duration_seconds: float | None = 120.0,
    billable_minutes: int | None = 2,
    started_at: datetime | None = None,
):
    """Helper: insert a CallSession directly into DB with given attributes."""
    import uuid
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            status=status,
            duration_seconds=duration_seconds,
            billable_minutes=billable_minutes,
            started_at=started_at or datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# Capability 1: Service aggregation — happy path and empty state
# REQ-1: get_call_metrics() must count total, completed, abandoned + avg/sum duration
# ---------------------------------------------------------------------------


async def test_get_call_metrics_happy_path(seeded_db):
    """3 completed + 1 abandoned → correct counts and aggregates (REQ-1 happy path)."""
    from app.calls.service import get_call_metrics

    # Seed 3 completed + 1 abandoned
    await _seed_call(seeded_db, status="completed", duration_seconds=60.0, billable_minutes=1)
    await _seed_call(seeded_db, status="completed", duration_seconds=120.0, billable_minutes=2)
    await _seed_call(seeded_db, status="completed", duration_seconds=180.0, billable_minutes=3)
    await _seed_call(seeded_db, status="abandoned", duration_seconds=None, billable_minutes=None)

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await get_call_metrics(sess, client_id="quintana-seguros")

    assert result["total_calls"] == 4
    assert result["completed_calls"] == 3
    assert result["abandoned_calls"] == 1
    # Average duration over 3 completed: (60+120+180)/3 = 120.0
    assert result["average_duration_seconds"] == 120.0
    # Total duration sum of completed
    assert result["total_duration_seconds"] == 360.0
    # Total billable minutes sum of completed
    assert result["total_billable_minutes"] == 6


async def test_get_call_metrics_empty_state(seeded_db):
    """No calls for client → all numeric fields are 0 / 0.0 (REQ-1 empty state)."""
    from app.calls.service import get_call_metrics

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await get_call_metrics(sess, client_id="quintana-seguros")

    assert result["total_calls"] == 0
    assert result["completed_calls"] == 0
    assert result["abandoned_calls"] == 0
    assert result["total_duration_seconds"] == 0.0
    assert result["average_duration_seconds"] == 0.0
    assert result["total_billable_minutes"] == 0


# ---------------------------------------------------------------------------
# Capability 2: Service filters and tenant safety
# REQ-1: date_from/date_to filter, lead_id filter, client isolation
# ---------------------------------------------------------------------------


async def test_get_call_metrics_date_range_filter(seeded_db):
    """Date range filter includes only calls within window (REQ-1 date range scenario)."""
    from app.calls.service import get_call_metrics

    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2026, 3, 1, tzinfo=timezone.utc)

    await _seed_call(seeded_db, status="completed", duration_seconds=60.0, billable_minutes=1, started_at=early)
    await _seed_call(seeded_db, status="completed", duration_seconds=90.0, billable_minutes=2, started_at=late)

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await get_call_metrics(
            sess,
            client_id="quintana-seguros",
            date_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

    # Only the late (2026-03-01) call qualifies
    assert result["total_calls"] == 1
    assert result["completed_calls"] == 1
    assert result["total_duration_seconds"] == 90.0


async def test_get_call_metrics_lead_filter(seeded_db):
    """lead_id filter scopes aggregates to that lead only (REQ-1 lead scenario)."""
    from app.calls.service import get_call_metrics

    await _seed_call(seeded_db, lead_id="lead-001", status="completed", duration_seconds=60.0, billable_minutes=1)
    await _seed_call(seeded_db, lead_id="lead-002", status="completed", duration_seconds=120.0, billable_minutes=2)

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await get_call_metrics(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-001",
        )

    assert result["total_calls"] == 1
    assert result["completed_calls"] == 1
    assert result["total_duration_seconds"] == 60.0


async def test_get_call_metrics_client_isolation(seeded_db, tmp_path):
    """Client B calls MUST NOT appear in Client A metrics (REQ-1 client isolation)."""
    from app.calls.service import get_call_metrics
    from app.tenants.service import create_client
    from app.leads.service import create_lead

    # Seed a second client + lead
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
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

    # Seed 2 calls for quintana-seguros, 1 for other-client
    await _seed_call(seeded_db, client_id="quintana-seguros", lead_id="lead-001", status="completed", duration_seconds=60.0, billable_minutes=1)
    await _seed_call(seeded_db, client_id="quintana-seguros", lead_id="lead-001", status="completed", duration_seconds=60.0, billable_minutes=1)
    await _seed_call(seeded_db, client_id="other-client", lead_id="lead-other", status="completed", duration_seconds=999.0, billable_minutes=17)

    async with seeded_db.async_session_factory() as sess:
        result = await get_call_metrics(sess, client_id="quintana-seguros")

    # Only 2 quintana-seguros calls, NOT 3
    assert result["total_calls"] == 2
    assert result["completed_calls"] == 2
    # other-client's 999s MUST NOT appear
    assert result["total_duration_seconds"] == 120.0


# ---------------------------------------------------------------------------
# Capability 3: Metrics endpoint wiring
# REQ-2: GET /api/v1/calls/metrics
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to calls router with isolated DB."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


async def test_metrics_endpoint_returns_200_with_data(seeded_db, app_client):
    """GET /calls/metrics?client_id=... returns 200 with populated body (REQ-2 happy path)."""
    from app.calls.schemas import CallMetricsResponse

    await _seed_call(seeded_db, status="completed", duration_seconds=120.0, billable_minutes=2)

    response = await app_client.get(
        "/api/v1/calls/metrics",
        params={"client_id": "quintana-seguros"},
    )

    assert response.status_code == 200
    data = response.json()
    # Deserialize to verify schema (REQ-3)
    metrics = CallMetricsResponse(**data)
    assert metrics.total_calls == 1
    assert metrics.completed_calls == 1
    assert metrics.total_duration_seconds == 120.0


async def test_metrics_endpoint_missing_client_id_returns_422(app_client):
    """GET /calls/metrics with no client_id → 422 (REQ-2 validation error)."""
    response = await app_client.get("/api/v1/calls/metrics")
    assert response.status_code == 422


async def test_metrics_endpoint_no_matching_calls_returns_zeros(seeded_db, app_client):
    """GET /calls/metrics for client with no calls → 200 with all zeros (REQ-2 empty)."""
    response = await app_client.get(
        "/api/v1/calls/metrics",
        params={"client_id": "quintana-seguros"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_calls"] == 0
    assert data["completed_calls"] == 0
    assert data["total_duration_seconds"] == 0.0
    assert data["average_duration_seconds"] == 0.0
    assert data["total_billable_minutes"] == 0


# ---------------------------------------------------------------------------
# Capability 4: Filter echo and period in response
# REQ-3: period.date_from / period.date_to echo applied values
# ---------------------------------------------------------------------------


async def test_metrics_endpoint_all_filters_passed(seeded_db, app_client):
    """GET /calls/metrics with all optional filters returns ONLY the one matching session.

    Conflicting data is seeded to prove each filter is actually applied:
    - A session for a different client → excluded by client_id
    - A session for a different lead (same client) → excluded by lead_id
    - A session outside the date window → excluded by date_from/date_to
    """
    from app.tenants.service import create_client
    from app.leads.service import create_lead

    # Set up a second client so we can seed cross-tenant noise
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        await create_client(
            sess,
            id="other-client-metrics",
            name="Other Corp Metrics",
            broker_name="OCM",
            agent_name="Bot",
            voice_id="pNInz6obpgDQGcFmaJgB",
        )
        await create_lead(
            sess,
            client_id="other-client-metrics",
            name="Other Lead Metrics",
            phone="+54888888888",
            lead_id="lead-other-metrics",
        )
        await sess.commit()

    # THE ONE session that matches ALL filters
    await _seed_call(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="lead-001",
        status="completed",
        duration_seconds=60.0,
        billable_minutes=1,
        started_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )

    # Noise 1: different client — excluded by client_id filter
    await _seed_call(
        seeded_db,
        client_id="other-client-metrics",
        lead_id="lead-other-metrics",
        status="completed",
        duration_seconds=999.0,
        billable_minutes=17,
        started_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )

    # Noise 2: different lead (same client, same date) — excluded by lead_id filter
    await _seed_call(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="lead-002",
        status="completed",
        duration_seconds=200.0,
        billable_minutes=4,
        started_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )

    # Noise 3: outside date window (same client, same lead) — excluded by date filter
    await _seed_call(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="lead-001",
        status="completed",
        duration_seconds=300.0,
        billable_minutes=5,
        started_at=datetime(2025, 6, 1, tzinfo=timezone.utc),  # before date_from
    )

    response = await app_client.get(
        "/api/v1/calls/metrics",
        params={
            "client_id": "quintana-seguros",
            "lead_id": "lead-001",
            "date_from": "2026-01-01T00:00:00Z",
            "date_to": "2026-06-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Only the ONE matching session must be counted; the 3 noisy sessions are excluded
    assert data["total_calls"] == 1
    assert data["completed_calls"] == 1
    assert data["total_duration_seconds"] == 60.0
    assert data["total_billable_minutes"] == 1


async def test_metrics_endpoint_period_echoes_filters(seeded_db, app_client):
    """Period in response echoes supplied date_from/date_to values (REQ-3 period scenario)."""
    response = await app_client.get(
        "/api/v1/calls/metrics",
        params={
            "client_id": "quintana-seguros",
            "date_from": "2026-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    data = response.json()
    period = data["period"]
    # date_from must be echoed
    assert period["date_from"] is not None
    assert "2026-01-01" in period["date_from"]
    # date_to was not supplied → null
    assert period["date_to"] is None


async def test_metrics_endpoint_period_null_when_no_filters(seeded_db, app_client):
    """Period date_from/date_to are null when no date filters supplied (REQ-3)."""
    response = await app_client.get(
        "/api/v1/calls/metrics",
        params={"client_id": "quintana-seguros"},
    )

    assert response.status_code == 200
    data = response.json()
    period = data["period"]
    assert period["date_from"] is None
    assert period["date_to"] is None
