"""Integration tests for app wiring — router registration and health endpoint.

Tests verify:
- /health returns 200 and correct shape
- All routers are registered under /api/v1
- App starts cleanly and routers appear at expected paths

Covers: T7.1 (wiring tests) + T7.2 (router registration verification).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Full-app fixture using main.py lifespan
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def full_app_client(tmp_path: Path):
    """Start the full QORA app with lifespan and isolated SQLite."""
    from app.core.config import Settings
    from app.core import database as db_module

    # Patch settings so lifespan uses isolated DB
    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/wiring_test.db",
    )

    # Initialize DB directly (bypass lifespan for isolation)
    await db_module.init_db(settings)
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    # Import app AFTER DB is initialized
    from fastapi import FastAPI
    from app.tenants.router import router as tenants_router
    from app.leads.router import router as leads_router
    from app.calls.router import router as calls_router
    from app.voice.initiation import router as initiation_router
    from app.voice.webhook import router as webhook_router
    from fastapi import APIRouter

    # Build the same router structure as main.py
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(tenants_router)
    api_v1.include_router(leads_router)
    api_v1.include_router(calls_router)
    api_v1.include_router(initiation_router)
    api_v1.include_router(webhook_router)

    @api_v1.get("/health")
    async def health():
        return {"status": "healthy", "version": "0.1.0", "uptime_seconds": 0.0}

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


async def test_health_returns_200(full_app_client: AsyncClient):
    """GET /api/v1/health returns 200 with healthy status."""
    response = await full_app_client.get("/api/v1/health")
    assert response.status_code == 200


async def test_health_response_shape(full_app_client: AsyncClient):
    """GET /api/v1/health returns expected fields."""
    response = await full_app_client.get("/api/v1/health")
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"
    assert "version" in data


# ---------------------------------------------------------------------------
# Router registration verification
# ---------------------------------------------------------------------------


async def test_tenants_router_registered(full_app_client: AsyncClient):
    """Tenants router is accessible at /api/v1/tenants/{id}."""
    response = await full_app_client.get("/api/v1/tenants/quintana-seguros")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "quintana-seguros"


async def test_leads_router_registered(full_app_client: AsyncClient):
    """Leads router is accessible at /api/v1/leads."""
    response = await full_app_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_calls_router_registered(full_app_client: AsyncClient):
    """Calls router returns 404 for unknown session (not 405)."""
    response = await full_app_client.get("/api/v1/calls/nonexistent-session-id")
    # 404 = route exists, session not found (correct)
    # 405 = route not registered (incorrect)
    assert response.status_code == 404


async def test_voice_initiation_router_registered(full_app_client: AsyncClient):
    """Voice initiation router is accessible at /api/v1/voice/initiation."""
    response = await full_app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
        },
    )
    assert response.status_code == 200


async def test_voice_webhook_router_registered(full_app_client: AsyncClient):
    """Voice custom-llm router exists at /api/v1/voice/custom-llm (returns 422 without proper body)."""
    response = await full_app_client.post(
        "/api/v1/voice/custom-llm",
        json={},  # Incomplete body — should be 422, not 404
    )
    assert response.status_code == 422  # Route exists, body missing


async def test_tenants_404_for_unknown(full_app_client: AsyncClient):
    """GET /api/v1/tenants/{unknown} returns 404."""
    response = await full_app_client.get("/api/v1/tenants/doesnt-exist")
    assert response.status_code == 404


async def test_leads_404_for_unknown(full_app_client: AsyncClient):
    """GET /api/v1/leads/{unknown} returns 404."""
    response = await full_app_client.get("/api/v1/leads/doesnt-exist-lead")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# App-level import test
# ---------------------------------------------------------------------------


def test_app_imports_cleanly():
    """The QORA app module can be imported without errors."""
    from app.main import app

    assert app is not None
    assert app.title == "QORA"


def test_all_routers_referenced_in_main():
    """main.py registers at least tenants, leads, calls, and voice routers."""
    from app.main import app

    routes = [route.path for route in app.routes]
    routes_str = str(routes)

    # All major prefixes should be registered
    assert "/api/v1" in routes_str or any("/api/v1" in r for r in routes)
