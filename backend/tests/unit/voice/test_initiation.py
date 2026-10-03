"""Unit tests for agent resolution in the conversation-initiation webhook (Phase 4a.3).

Covers:
- Resolves the Qora agent via agents.elevenlabs_agent_id == payload agent_id
- Falls back to resolve_single_active_agent when no agent_id is supplied
- Falls back safely (not a hard error) when agent_id is supplied but unmapped
- Fails closed (explicit error) when no agent_id and the client has 0/>1 active agents
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def app_client(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/initiation_agent_resolution_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana, create_agent
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await create_agent(
            sess,
            client_id="quintana-seguros",
            slug="leads-agent",
            name="LeadsAgent",
            voice_id="v-leads",
            elevenlabs_agent_id="el-agent-leads-001",
        )
        await sess.commit()

    from app.voice.initiation import router as initiation_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        yield client

    await db_module.close_db()


async def test_initiation_webhook_resolves_agent_from_elevenlabs_agent_id(app_client):
    """A payload carrying a known EL agent_id resolves to that (non-default) agent."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "el-agent-leads-001",
        },
    )

    assert response.status_code == 200, response.text
    dv = response.json()["dynamic_variables"]
    assert dv["agent_name"] == "LeadsAgent"


async def test_initiation_webhook_without_agent_id_resolves_single_active_agent(
    app_client,
):
    """No agent_id in the payload, but the client has 2 active agents now (seed default
    + leads-agent) -> explicit error, not a silent pick."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
        },
    )

    assert response.status_code == 409, response.text


async def test_initiation_webhook_unmapped_agent_id_falls_back_safely(tmp_path: Path):
    """agent_id supplied but not mapped to any Agent -> falls back to the single-active-agent
    path rather than a hard error (same as if no agent_id had been sent)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/initiation_unmapped_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    from app.voice.initiation import router as initiation_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/voice/initiation",
            json={
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "agent_id": "agent-001",  # unmapped placeholder, e.g. widget test fixture
            },
        )

    assert response.status_code == 200, response.text
    dv = response.json()["dynamic_variables"]
    assert dv["agent_name"] == "Jaumpablo"

    await db_module.close_db()
