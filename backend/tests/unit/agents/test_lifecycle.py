"""Full lifecycle integration test for Client + Agent Admin CRUD.

Task 4.2: End-to-end flow:
  1. Create a new client
  2. Verify default agent is auto-created
  3. Create a second agent
  4. Make the second agent the default
  5. Deactivate the old (first) default agent
  6. Verify final state: second agent is active+default; first is inactive

This test exercises the complete happy path through the actual HTTP API
using an isolated in-memory SQLite DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def lifecycle_app(tmp_path: Path):
    """Full API surface app: clients router + agents router + fresh DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/lifecycle_test.db",
    )
    await db_module.init_db(settings)

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


async def test_full_admin_lifecycle(lifecycle_app: AsyncClient):
    """Complete lifecycle: create client → default agent → second agent → swap → deactivate."""
    base_url = "/api/v1"

    # ----------------------------------------------------------------
    # Step 1: Create a new client
    # ----------------------------------------------------------------
    create_resp = await lifecycle_app.post(
        f"{base_url}/clients",
        json={
            "client_id": "lifecycle-broker",
            "broker_name": "Lifecycle Broker SA",
            "agent_name": "LifeAgent",
            "voice_id": "voice-lifecycle",
        },
    )
    assert create_resp.status_code == 201, f"Create client failed: {create_resp.text}"
    client_data = create_resp.json()
    assert client_data["client_id"] == "lifecycle-broker"

    # ----------------------------------------------------------------
    # Step 2: Verify default agent auto-created on client creation
    # ----------------------------------------------------------------
    agents_resp = await lifecycle_app.get(f"{base_url}/clients/lifecycle-broker/agents")
    assert agents_resp.status_code == 200
    agents = agents_resp.json()
    assert (
        len(agents) == 1
    ), "Exactly one default agent should exist after client creation"
    first_agent = agents[0]
    assert first_agent["is_default"] is True
    assert first_agent["is_active"] is True
    assert first_agent["client_id"] == "lifecycle-broker"
    first_agent_id = first_agent["agent_id"]

    # ----------------------------------------------------------------
    # Step 3: Create a second agent
    # ----------------------------------------------------------------
    create_agent_resp = await lifecycle_app.post(
        f"{base_url}/clients/lifecycle-broker/agents",
        json={
            "slug": "second-lifecycle-agent",
            "name": "Second Lifecycle Agent",
            "voice_id": "voice-second",
        },
    )
    assert create_agent_resp.status_code == 201
    second_agent = create_agent_resp.json()
    second_agent_id = second_agent["agent_id"]
    assert second_agent["is_default"] is False
    assert second_agent["is_active"] is True

    # Confirm two active agents now
    agents_resp2 = await lifecycle_app.get(
        f"{base_url}/clients/lifecycle-broker/agents"
    )
    assert len(agents_resp2.json()) == 2

    # ----------------------------------------------------------------
    # Step 4: Make the second agent the default
    # ----------------------------------------------------------------
    make_default_resp = await lifecycle_app.post(
        f"{base_url}/clients/lifecycle-broker/agents/{second_agent_id}/make-default"
    )
    assert make_default_resp.status_code == 200
    new_default = make_default_resp.json()
    assert new_default["is_default"] is True
    assert new_default["agent_id"] == second_agent_id

    # ----------------------------------------------------------------
    # Step 5: Deactivate the old (first) default agent
    # ----------------------------------------------------------------
    deactivate_resp = await lifecycle_app.post(
        f"{base_url}/clients/lifecycle-broker/agents/{first_agent_id}/deactivate"
    )
    assert deactivate_resp.status_code == 200
    deactivated = deactivate_resp.json()
    assert deactivated["is_active"] is False
    assert deactivated["agent_id"] == first_agent_id

    # ----------------------------------------------------------------
    # Step 6: Verify final state
    # ----------------------------------------------------------------
    # Only active agents in default list
    final_resp = await lifecycle_app.get(f"{base_url}/clients/lifecycle-broker/agents")
    assert final_resp.status_code == 200
    final_agents = final_resp.json()

    # Only the second agent is active
    assert len(final_agents) == 1
    assert final_agents[0]["agent_id"] == second_agent_id
    assert final_agents[0]["is_default"] is True
    assert final_agents[0]["is_active"] is True

    # ----------------------------------------------------------------
    # Bonus: confirm old default cannot be made default (inactive guard)
    # ----------------------------------------------------------------
    inactive_make_default_resp = await lifecycle_app.post(
        f"{base_url}/clients/lifecycle-broker/agents/{first_agent_id}/make-default"
    )
    assert inactive_make_default_resp.status_code == 409
    assert "inactive" in inactive_make_default_resp.json()["detail"]["error"]
