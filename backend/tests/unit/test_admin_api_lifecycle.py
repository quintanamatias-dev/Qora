"""TDD tests for CRITICAL 3: Admin surface behavioral verification.

Verifies:
1. GET /admin returns the admin.html with all expected structural elements
2. Full API lifecycle: client list → agent list → create agent → verify state
3. Admin HTML contains all required tabs, forms, tool checkboxes

RED: These tests will fail if the admin surface is missing required elements
or if the API lifecycle doesn't work end-to-end.
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
    """Full app fixture with admin route + seeded client."""
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

    import os
    from fastapi import FastAPI, APIRouter
    from fastapi.responses import FileResponse
    from app.clients.router import router as clients_router
    from app.agents.router import router as agents_router

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(clients_router)
    api_v1.include_router(agents_router)
    app.include_router(api_v1)

    _static_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "app",
        "static",
    )

    @app.get("/admin")
    async def admin_page():
        admin_path = os.path.join(_static_dir, "admin.html")
        return FileResponse(admin_path, media_type="text/html")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# CRITICAL 3a: Admin HTML structure via /admin endpoint
# ---------------------------------------------------------------------------


async def test_admin_page_contains_clients_tab(admin_app: AsyncClient):
    """GET /admin HTML must contain a Clients tab."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert "Clients" in html, "Admin page must have a Clients tab."


async def test_admin_page_contains_agents_tab(admin_app: AsyncClient):
    """GET /admin HTML must contain an Agents tab."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert "Agents" in html, "Admin page must have an Agents tab."


async def test_admin_page_contains_client_form(admin_app: AsyncClient):
    """GET /admin HTML must contain the client creation form inputs."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert 'id="c-id"' in html, "Client form 'c-id' input missing."
    assert 'id="c-broker"' in html, "Client form 'c-broker' input missing."
    # voice_id is configured per-agent, not at client creation
    assert 'id="c-agent"' in html, "Client form 'c-agent' input missing."


async def test_admin_page_contains_agent_form(admin_app: AsyncClient):
    """GET /admin HTML must contain the agent creation form inputs."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert 'id="a-slug"' in html, "Agent form 'a-slug' input missing."
    assert 'id="a-name"' in html, "Agent form 'a-name' input missing."
    assert 'id="a-voice"' in html, "Agent form 'a-voice' input missing."


async def test_admin_page_contains_tool_checkboxes(admin_app: AsyncClient):
    """GET /admin HTML must contain all 4 tool checkboxes."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert 'value="get_lead_details"' in html
    assert 'value="register_interest"' in html
    assert 'value="mark_not_interested"' in html
    assert 'value="schedule_followup"' in html


async def test_admin_page_contains_agent_count_column(admin_app: AsyncClient):
    """GET /admin HTML clients table must include an agent count column."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert (
        "<th>Agents</th>" in html or "<th>Agent Count</th>" in html
    ), "Admin clients table must have an agent count column."


async def test_admin_page_contains_voice_id_column_for_agents(admin_app: AsyncClient):
    """GET /admin HTML agents table must include a Voice ID column."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert (
        "<th>Voice ID</th>" in html or "<th>Voice</th>" in html
    ), "Admin agents table must have a Voice ID column."


async def test_admin_page_no_alert_calls(admin_app: AsyncClient):
    """GET /admin HTML must not contain alert() error handling."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    html = response.text
    assert (
        "alert(" not in html
    ), "Admin page must not use alert() — use inline error messages instead."


# ---------------------------------------------------------------------------
# CRITICAL 3b: Full API lifecycle via admin surface
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
