"""Unit test: creating an agent with elevenlabs_phone_number_id persists it.

Covers the defect where AgentCreate declared elevenlabs_phone_number_id but
the router never forwarded it to tenant_service.create_agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr

_BASE = "/api/v1/clients/test-client/agents"


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    """Isolated FastAPI app with agents router + a fresh SQLite DB.

    Mirrors the agents_app fixture in test_router.py: patches sync_to_elevenlabs
    so no test here makes a real outbound HTTP call.
    """
    from unittest.mock import AsyncMock, patch
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agents_phone_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="test-client",
            name="Test Client SA",
            agent_name="Test Client Agent",
            voice_id="voice-default",
        )
        await session.commit()

    from app.agents.router import router as agents_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(agents_router, prefix="/api/v1")

    with patch("app.agents.router.sync_to_elevenlabs", AsyncMock()):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
            follow_redirects=True,
        ) as c:
            yield c

    await db_module.close_db()


async def test_create_agent_persists_elevenlabs_phone_number_id(client):
    payload = {
        "slug": "phone-agent",
        "name": "Phone Agent",
        "voice_id": "voice-abc123",
        "elevenlabs_phone_number_id": "phnum_123",
    }
    resp = await client.post(_BASE, json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["elevenlabs_phone_number_id"] == "phnum_123"

    resp_get = await client.get(f"{_BASE}/{body['agent_id']}")
    assert resp_get.status_code == 200
    assert resp_get.json()["elevenlabs_phone_number_id"] == "phnum_123"
