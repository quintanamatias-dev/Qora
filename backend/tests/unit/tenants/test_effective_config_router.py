"""Phase 6 (agent-config-inheritance) — Task 6.1: admin effective-config API.

Covers:
  GET /api/v1/clients/{client_id}/agents/{agent_id}/effective-config
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def effective_config_app(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/effective_config_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_qora_demo, seed_quintana

        await seed_qora_demo(session)
        await seed_quintana(session)
        await session.commit()

    from app.agents.router import router as agents_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(agents_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


async def _get_demo_agent_id(client: AsyncClient) -> str:
    response = await client.get("/api/v1/clients/qora-demo/agents")
    response.raise_for_status()
    agents = response.json()
    assert len(agents) == 1
    return agents[0]["agent_id"]


async def test_effective_config_endpoint_returns_value_and_provenance_per_field(
    effective_config_app,
):
    from app.tenants.field_policy import FIELD_POLICY

    agent_id = await _get_demo_agent_id(effective_config_app)
    response = await effective_config_app.get(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/effective-config"
    )
    assert response.status_code == 200
    body = response.json()

    assert set(body["fields"].keys()) == set(FIELD_POLICY.keys())
    for name, policy in FIELD_POLICY.items():
        field = body["fields"][name]
        assert field["policy"] == policy
        assert field["provenance"] in ("standard", "client", "agent")
        if policy == "locked":
            assert field["provenance"] == "standard"

    assert isinstance(body["standard_version"], str) and body["standard_version"]
    assert isinstance(body["config_incomplete"], bool)
    assert isinstance(body["missing_required_fields"], list)


async def test_effective_config_endpoint_is_tenant_isolated(effective_config_app):
    agent_id = await _get_demo_agent_id(effective_config_app)
    response = await effective_config_app.get(
        f"/api/v1/clients/quintana-seguros/agents/{agent_id}/effective-config"
    )
    assert response.status_code == 404


async def test_effective_config_endpoint_404_for_missing_agent(effective_config_app):
    response = await effective_config_app.get(
        "/api/v1/clients/qora-demo/agents/does-not-exist/effective-config"
    )
    assert response.status_code == 404
