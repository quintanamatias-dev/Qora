"""Unit tests for ElevenLabs sync-on-save trigger in agent router.

Spec: sdd/elevenlabs-provisioning/spec — Requirement: Sync-on-Save (Fire-and-Forget)

Tests:
- create_agent with elevenlabs_agent_id + soft_timeout_seconds → asyncio.create_task called
- create_agent without elevenlabs_agent_id → no create_task
- create_agent with no soft timeout fields → no create_task
- update_agent with elevenlabs_agent_id + soft_timeout field change → create_task called
- update_agent without elevenlabs_agent_id → no create_task
- EL sync background helper updates sync_status to "synced" after success
- EL sync background helper updates sync_status to "error" after failure
- EL sync background helper skips update when outcome="skipped"
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import respx
import httpx
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# App fixture: isolated FastAPI app with agents router + SQLite DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def agents_app(tmp_path: Path):
    """Isolated FastAPI app with agents router + fresh SQLite DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sync_trigger_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_qora_demo
        await seed_qora_demo(sess)
        await sess.commit()

    from app.agents.router import router as agents_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(agents_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Helper: get an existing agent ID from qora-demo
# ---------------------------------------------------------------------------


async def _get_qora_demo_agent_id(agents_app: AsyncClient) -> str:
    """Return the UUID of the qora-demo agent via the agents API."""
    resp = await agents_app.get("/api/v1/clients/qora-demo/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) >= 1
    return agents[0]["agent_id"]


# ---------------------------------------------------------------------------
# Task 3.1 RED — create with EL ID + soft timeout → create_task called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_with_el_id_and_soft_timeout_fires_sync(agents_app):
    """GIVEN AgentCreate with elevenlabs_agent_id and soft_timeout_seconds
    WHEN POST /api/v1/clients/qora-demo/agents is called
    THEN sync_to_elevenlabs is scheduled (sync is triggered)

    We test the behavior by patching sync_to_elevenlabs with an AsyncMock.
    asyncio.create_task will schedule the coroutine returned by the mock,
    and the test verifies the mock was called (= sync was triggered).
    """
    mock_sync = AsyncMock()
    with patch("app.agents.router.sync_to_elevenlabs", mock_sync):
        resp = await agents_app.post(
            "/api/v1/clients/qora-demo/agents",
            json={
                "slug": "test-agent-sync",
                "name": "Test Agent Sync",
                "voice_id": "voice-123",
                "elevenlabs_agent_id": "el-test-agent-id",
                "soft_timeout_seconds": 3.0,
            },
        )
        # Allow pending tasks to run
        import asyncio as _asyncio
        await _asyncio.sleep(0)
    assert resp.status_code == 201
    mock_sync.assert_called_once()


@pytest.mark.asyncio
async def test_create_agent_without_el_id_does_not_fire_sync(agents_app):
    """GIVEN AgentCreate without elevenlabs_agent_id
    WHEN POST is called
    THEN sync_to_elevenlabs is NOT called
    """
    mock_sync = AsyncMock()
    with patch("app.agents.router.sync_to_elevenlabs", mock_sync):
        resp = await agents_app.post(
            "/api/v1/clients/qora-demo/agents",
            json={
                "slug": "test-agent-no-el",
                "name": "Test Agent No EL",
                "voice_id": "voice-123",
                "soft_timeout_seconds": 3.0,
            },
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0)
    assert resp.status_code == 201
    mock_sync.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_without_soft_timeout_fields_does_not_fire_sync(agents_app):
    """GIVEN AgentCreate with elevenlabs_agent_id but NO soft_timeout fields
    WHEN POST is called
    THEN sync_to_elevenlabs is NOT called (nothing to sync)
    """
    mock_sync = AsyncMock()
    with patch("app.agents.router.sync_to_elevenlabs", mock_sync):
        resp = await agents_app.post(
            "/api/v1/clients/qora-demo/agents",
            json={
                "slug": "test-agent-no-timeout",
                "name": "Test Agent No Timeout",
                "voice_id": "voice-123",
                "elevenlabs_agent_id": "el-test-agent-id",
            },
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0)
    assert resp.status_code == 201
    mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Task 3.1 RED — update with EL ID + soft timeout change → sync triggered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_agent_with_soft_timeout_fires_sync(agents_app):
    """GIVEN PATCH on an agent that has elevenlabs_agent_id, updating soft_timeout_seconds
    WHEN PATCH /api/v1/clients/qora-demo/agents/{agent_id} is called
    THEN sync_to_elevenlabs is scheduled (sync triggered)
    """
    agent_id = await _get_qora_demo_agent_id(agents_app)

    mock_sync = AsyncMock()
    with patch("app.agents.router.sync_to_elevenlabs", mock_sync):
        resp = await agents_app.patch(
            f"/api/v1/clients/qora-demo/agents/{agent_id}",
            json={"soft_timeout_seconds": 4.0},
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0)
    assert resp.status_code == 200
    mock_sync.assert_called_once()


@pytest.mark.asyncio
async def test_update_agent_without_soft_timeout_fields_does_not_fire_sync(agents_app):
    """GIVEN PATCH on agent updating only name (no soft_timeout fields)
    WHEN PATCH is called
    THEN sync_to_elevenlabs is NOT called
    """
    agent_id = await _get_qora_demo_agent_id(agents_app)

    mock_sync = AsyncMock()
    with patch("app.agents.router.sync_to_elevenlabs", mock_sync):
        resp = await agents_app.patch(
            f"/api/v1/clients/qora-demo/agents/{agent_id}",
            json={"name": "Updated Name"},
        )
        import asyncio as _asyncio
        await _asyncio.sleep(0)
    assert resp.status_code == 200
    mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Task 3.1 RED — Background sync helper updates DB status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_background_sync_updates_status_to_synced(agents_app, tmp_path):
    """GIVEN agent with elevenlabs_agent_id + soft_timeout, EL API returns 200
    WHEN background sync runs directly
    THEN agent.elevenlabs_sync_status is set to 'synced'
    """
    from app.core import database as db_module
    from app.core.config import Settings

    # Set up the EL mock
    respx.patch("https://api.elevenlabs.io/v1/convai/agents/agent_8201kra4wjhve0srcwgbtwfetr5n").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    # Get the agent ID
    resp = await agents_app.get("/api/v1/clients/qora-demo/agents")
    agent_id = resp.json()[0]["agent_id"]

    # Set soft timeout + keep existing elevenlabs_agent_id via patch
    await agents_app.patch(
        f"/api/v1/clients/qora-demo/agents/{agent_id}",
        json={"soft_timeout_seconds": 3.0},
    )

    # Now invoke the background helper directly with mocked settings
    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sync_trigger_test.db",
    )

    from app.elevenlabs.service import sync_to_elevenlabs
    await sync_to_elevenlabs(agent_id=agent_id, settings=settings)

    # Verify DB updated
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "synced"
        assert agent.elevenlabs_last_synced_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_background_sync_updates_status_to_error_when_el_down(agents_app, tmp_path):
    """GIVEN EL API returns 503 on both attempts
    WHEN background sync runs
    THEN agent.elevenlabs_sync_status is set to 'error'
    """
    from app.core import database as db_module
    from app.core.config import Settings

    # Use a counter-based side_effect to avoid StopIteration in async context
    call_count = 0

    def _always_503(request, route):
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, json={"error": "down"})

    # Mock EL API to always fail
    respx.patch("https://api.elevenlabs.io/v1/convai/agents/agent_8201kra4wjhve0srcwgbtwfetr5n").mock(
        side_effect=_always_503
    )

    resp = await agents_app.get("/api/v1/clients/qora-demo/agents")
    agent_id = resp.json()[0]["agent_id"]

    # Ensure soft_timeout_seconds is set
    await agents_app.patch(
        f"/api/v1/clients/qora-demo/agents/{agent_id}",
        json={"soft_timeout_seconds": 3.0},
    )

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sync_trigger_test.db",
    )

    from app.elevenlabs.service import sync_to_elevenlabs
    await sync_to_elevenlabs(agent_id=agent_id, settings=settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "error"


@pytest.mark.asyncio
async def test_background_sync_skipped_outcome_leaves_status_unchanged(agents_app, tmp_path):
    """GIVEN agent has no elevenlabs_agent_id
    WHEN background sync runs (outcome will be 'skipped')
    THEN sync_status remains NULL (not updated)
    """
    from app.core import database as db_module
    from app.core.config import Settings

    # Create an agent without EL ID
    create_resp = await agents_app.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "no-el-agent",
            "name": "No EL Agent",
            "voice_id": "voice-xxx",
            "soft_timeout_seconds": 3.0,
            # No elevenlabs_agent_id
        },
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sync_trigger_test.db",
    )

    from app.elevenlabs.service import sync_to_elevenlabs
    await sync_to_elevenlabs(agent_id=agent_id, settings=settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        # skipped → status not updated (remains NULL)
        assert agent.elevenlabs_sync_status is None
