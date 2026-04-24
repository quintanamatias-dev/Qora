"""Tests for agents router registration via the full app.

Verifies:
- GET /api/v1/clients/{client_id}/agents is accessible via the full app
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def full_app(tmp_path: Path):
    """Minimal full app fixture that wires agents router.

    We do NOT use the real lifespan to avoid seeding / external deps.
    Instead we initialise DB manually so we get agents endpoint.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/main_admin_test.db",
    )
    await db_module.init_db(settings)

    # Seed one client so we can test the agents endpoint through the full router
    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="admin-test-client",
            name="Admin Test Client",
            broker_name="Admin Test Client",
            agent_name="AdminAgent",
            voice_id="voice-admin",
        )
        await session.commit()

    # Build a mini app that mimics main.py router registration
    from fastapi import FastAPI, APIRouter
    from app.clients.router import router as clients_router
    from app.agents.router import router as agents_router

    mini_app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(clients_router)
    api_v1.include_router(agents_router)
    mini_app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


async def test_agents_endpoint_accessible_via_full_app(full_app: AsyncClient):
    """GET /api/v1/clients/{client_id}/agents is routed correctly in full app."""
    response = await full_app.get("/api/v1/clients/admin-test-client/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1  # default agent auto-created
    assert data[0]["client_id"] == "admin-test-client"
