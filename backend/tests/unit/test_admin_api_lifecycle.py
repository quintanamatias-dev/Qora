"""Tests for admin API lifecycle verification.

Verifies:
- Full API lifecycle: client list → agent list → create agent → verify state
- Agent CRUD operations through the API surface
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_app(tmp_path: Path):
    """Full app fixture with seeded client for API lifecycle tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/admin_lifecycle_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="lifecycle-client",
            name="Lifecycle Client SA",
            broker_name="Lifecycle Broker",
            agent_name="LifecycleAgent",
            voice_id="voice-lifecycle",
        )
        await session.commit()

    from fastapi import FastAPI, APIRouter
    from app.clients.router import router as clients_router
    from app.agents.router import router as agents_router

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(clients_router)
    api_v1.include_router(agents_router)
    app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# API lifecycle tests
# ---------------------------------------------------------------------------


async def test_admin_client_list_returns_seeded_client(admin_app: AsyncClient):
    """GET /api/v1/clients returns the seeded client."""
    response = await admin_app.get("/api/v1/clients")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    client_ids = [c["client_id"] for c in data]
    assert "lifecycle-client" in client_ids


async def test_admin_agent_list_returns_default_agent(admin_app: AsyncClient):
    """GET /api/v1/clients/{client_id}/agents returns the auto-created default agent."""
    response = await admin_app.get("/api/v1/clients/lifecycle-client/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    agent = data[0]
    assert agent["client_id"] == "lifecycle-client"
    assert agent["is_default"] is True
    assert agent["is_active"] is True
    # tools_enabled must be a list in response
    assert isinstance(agent["tools_enabled"], list)


async def test_admin_create_agent_and_verify_list(admin_app: AsyncClient):
    """POST /agents creates a new agent; GET /agents returns both agents."""
    # Create a second agent
    response = await admin_app.post(
        "/api/v1/clients/lifecycle-client/agents",
        json={
            "slug": "second-agent",
            "name": "Second Agent",
            "voice_id": "voice-second",
            "tools_enabled": ["get_lead_details", "register_interest"],
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["slug"] == "second-agent"
    assert created["voice_id"] == "voice-second"
    assert isinstance(created["tools_enabled"], list)
    assert set(created["tools_enabled"]) == {"get_lead_details", "register_interest"}

    # Verify the list now shows 2 agents
    list_response = await admin_app.get("/api/v1/clients/lifecycle-client/agents")
    assert list_response.status_code == 200
    agents = list_response.json()
    assert len(agents) == 2
    slugs = {a["slug"] for a in agents}
    assert "second-agent" in slugs


async def test_admin_full_lifecycle_make_default_and_deactivate(admin_app: AsyncClient):
    """Full lifecycle: create agent → make default → deactivate original → verify."""
    base = "/api/v1/clients/lifecycle-client/agents"

    # Get the default agent
    list_resp = await admin_app.get(base)
    agents = list_resp.json()
    original_default = next(a for a in agents if a["is_default"])
    original_id = original_default["agent_id"]

    # Create a new agent
    create_resp = await admin_app.post(
        base,
        json={
            "slug": "new-default",
            "name": "New Default",
            "voice_id": "voice-new",
        },
    )
    assert create_resp.status_code == 201
    new_agent_id = create_resp.json()["agent_id"]

    # Make new agent the default
    swap_resp = await admin_app.post(f"{base}/{new_agent_id}/make-default")
    assert swap_resp.status_code == 200
    assert swap_resp.json()["is_default"] is True

    # Deactivate the original (no longer sole default)
    deact_resp = await admin_app.post(f"{base}/{original_id}/deactivate")
    assert deact_resp.status_code == 200
    assert deact_resp.json()["is_active"] is False

    # Verify: only the new agent is the active default
    final_resp = await admin_app.get(base)
    active_agents = final_resp.json()
    assert len(active_agents) == 1  # original deactivated, excluded from list
    assert active_agents[0]["agent_id"] == new_agent_id
    assert active_agents[0]["is_default"] is True
