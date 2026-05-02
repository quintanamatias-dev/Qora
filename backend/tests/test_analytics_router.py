"""Analytics router integration tests — RED phase (task 1.1).

Tests for period parsing, custom-date 400s, and response shapes
for all analytics endpoints.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def analytics_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros seeded."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analytics_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana

        await seed_quintana(sess)
        await sess.commit()

    yield db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def analytics_client(analytics_db):
    """HTTP client with analytics router mounted."""
    from fastapi import FastAPI, APIRouter
    from app.analytics.router import router as analytics_router

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(analytics_router)

    test_app = FastAPI()
    test_app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# 1.1 RED: Schema / period validation
# ---------------------------------------------------------------------------


async def test_overview_invalid_period_returns_400(analytics_client):
    """Invalid period value returns 400 with helpful detail."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
        params={"period": "quarterly"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "Invalid period" in data["detail"]


async def test_overview_custom_period_missing_dates_returns_400(analytics_client):
    """Custom period without start_date/end_date returns 400."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
        params={"period": "custom"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "start_date and end_date required" in data["detail"]


async def test_overview_custom_period_missing_start_date_returns_400(analytics_client):
    """Custom period with only end_date returns 400."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
        params={"period": "custom", "end_date": "2026-01-31"},
    )
    assert response.status_code == 400


async def test_overview_default_period_returns_200(analytics_client):
    """Default period (month) returns 200 with correct response shape."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_calls" in data
    assert "outcome_distribution" in data
    assert "conversion_rate" in data
    assert "period" in data
    assert "start_date" in data
    assert "end_date" in data
    assert data["period"] == "month"


async def test_overview_week_period_returns_200(analytics_client):
    """Week period returns 200 with period=week."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
        params={"period": "week"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "week"


async def test_overview_custom_period_with_dates_returns_200(analytics_client):
    """Custom period with valid dates returns 200."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/overview",
        params={
            "period": "custom",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "custom"


async def test_service_issues_invalid_period_returns_400(analytics_client):
    """Service issues endpoint rejects invalid period with 400."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/service-issues",
        params={"period": "quarterly"},
    )
    assert response.status_code == 400


async def test_service_issues_default_period_returns_200(analytics_client):
    """Service issues returns 200 with correct shape."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/service-issues",
    )
    assert response.status_code == 200
    data = response.json()
    assert "issues" in data
    assert "period" in data
    assert "start_date" in data
    assert "end_date" in data
    assert isinstance(data["issues"], list)


async def test_interests_default_period_returns_200(analytics_client):
    """Interests endpoint returns 200 with correct shape."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/interests",
    )
    assert response.status_code == 200
    data = response.json()
    assert "interests" in data
    assert "period" in data
    assert isinstance(data["interests"], list)


async def test_agent_stats_default_period_returns_200(analytics_client):
    """Agent stats endpoint returns 200 with correct shape."""
    response = await analytics_client.get(
        "/api/v1/analytics/quintana-seguros/agent-stats",
    )
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert "period" in data
    assert isinstance(data["agents"], list)


# ---------------------------------------------------------------------------
# CRITICAL 1: Router registered in app.main.app
# ---------------------------------------------------------------------------


def test_analytics_router_registered_in_main_app():
    """Analytics router MUST be registered in app.main.app — returns 200 not 404."""
    from app.main import app

    # Check that the analytics route is registered by inspecting route paths
    route_paths = {route.path for route in app.routes if hasattr(route, "path")}
    # The included sub-routes are on api_v1_router which is included in app
    # We verify by checking that the analytics prefix is reachable
    # Routes come in as "/api/v1/analytics/{client_id}/overview" etc.
    analytics_routes = [p for p in route_paths if "analytics" in p]
    assert (
        len(analytics_routes) > 0
    ), "No analytics routes found in app.main.app — analytics_router not registered!"


# ---------------------------------------------------------------------------
# CRITICAL 3: Non-existent client returns 404
# ---------------------------------------------------------------------------


async def test_overview_nonexistent_client_returns_404(analytics_client):
    """Endpoint returns 404 for a client_id that does not exist."""
    response = await analytics_client.get(
        "/api/v1/analytics/no-such-client-xyz/overview",
    )
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


async def test_service_issues_nonexistent_client_returns_404(analytics_client):
    """Service issues endpoint returns 404 for unknown client."""
    response = await analytics_client.get(
        "/api/v1/analytics/no-such-client-xyz/service-issues",
    )
    assert response.status_code == 404


async def test_interests_nonexistent_client_returns_404(analytics_client):
    """Interests endpoint returns 404 for unknown client."""
    response = await analytics_client.get(
        "/api/v1/analytics/no-such-client-xyz/interests",
    )
    assert response.status_code == 404


async def test_agent_stats_nonexistent_client_returns_404(analytics_client):
    """Agent stats endpoint returns 404 for unknown client."""
    response = await analytics_client.get(
        "/api/v1/analytics/no-such-client-xyz/agent-stats",
    )
    assert response.status_code == 404
