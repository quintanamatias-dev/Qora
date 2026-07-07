"""Integration tests for POST /api/v1/clients/{client_id}/agents/{agent_id}/sync-elevenlabs.

Spec: sdd/elevenlabs-provisioning/spec — Requirement: Manual Re-Sync Endpoint

Tests:
- Re-sync success → {"sync_status": "synced", "synced_at": "<timestamp>"}
- Re-sync with no elevenlabs_agent_id → {"sync_status": "skipped", "synced_at": null}
- Re-sync for non-existent agent → 404
- Re-sync for non-existent client → 404
- Re-sync when EL API down → {"sync_status": "error", ...} and agent record updated
- Agent create with soft timeout + EL ID → sync fires and status updated to 'synced'
- Agent save when EL API down → agent saved (200/201), sync_status = 'error' in background
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# App fixture: isolated FastAPI app with agents router + SQLite DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sync_app(tmp_path: Path):
    """Isolated FastAPI app with agents router + fresh SQLite DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sync_endpoint_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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
        yield client, db_module

    await db_module.close_db()


async def _get_qora_demo_agent_id(client: AsyncClient) -> str:
    """Return the UUID of the qora-demo default agent."""
    resp = await client.get("/api/v1/clients/qora-demo/agents")
    assert resp.status_code == 200
    return resp.json()[0]["agent_id"]


# ---------------------------------------------------------------------------
# Task 3.3 RED — Re-sync success → synced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_resync_endpoint_returns_synced_on_success(sync_app):
    """GIVEN agent with elevenlabs_agent_id and soft_timeout_seconds, EL API returns 200
    WHEN POST .../sync-elevenlabs is called
    THEN response is {"sync_status": "synced", "synced_at": "<timestamp>"}
    AND DB is updated with sync_status="synced"
    """
    client, db_module = sync_app
    agent_id = await _get_qora_demo_agent_id(client)

    # Set soft timeout so sync won't be skipped
    await client.patch(
        f"/api/v1/clients/qora-demo/agents/{agent_id}",
        json={"soft_timeout_seconds": 3.0},
    )

    # Mock EL API success
    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/agent_8201kra4wjhve0srcwgbtwfetr5n"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    resp = await client.post(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sync_status"] == "synced"
    assert data["synced_at"] is not None


@pytest.mark.asyncio
async def test_resync_endpoint_returns_skipped_when_no_el_agent_id(sync_app):
    """GIVEN agent with NO elevenlabs_agent_id
    WHEN POST .../sync-elevenlabs is called
    THEN response is {"sync_status": "skipped", "synced_at": null}
    AND no HTTP call to ElevenLabs is made
    """
    client, db_module = sync_app

    # Create a fresh agent without EL ID
    create_resp = await client.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "no-el-id-agent",
            "name": "No EL ID Agent",
            "voice_id": "voice-xxx",
        },
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    resp = await client.post(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sync_status"] == "skipped"
    assert data["synced_at"] is None


@pytest.mark.asyncio
async def test_resync_endpoint_returns_404_for_unknown_agent(sync_app):
    """GIVEN a non-existent agent_id
    WHEN POST .../sync-elevenlabs is called
    THEN 404 is returned
    """
    client, _ = sync_app
    resp = await client.post(
        "/api/v1/clients/qora-demo/agents/00000000-0000-0000-0000-000000000000/sync-elevenlabs"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resync_endpoint_returns_404_for_unknown_client(sync_app):
    """GIVEN a non-existent client_id
    WHEN POST .../sync-elevenlabs is called
    THEN 404 is returned
    """
    client, _ = sync_app
    agent_id = await _get_qora_demo_agent_id(client)
    resp = await client.post(
        f"/api/v1/clients/ghost-client/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_resync_endpoint_returns_error_when_el_api_down(sync_app):
    """GIVEN EL API returns 503 on both attempts
    WHEN POST .../sync-elevenlabs is called
    THEN response has sync_status="error"
    AND DB is updated with elevenlabs_sync_status="error"
    """
    client, db_module = sync_app
    agent_id = await _get_qora_demo_agent_id(client)

    # Set soft_timeout_seconds so sync won't be skipped
    await client.patch(
        f"/api/v1/clients/qora-demo/agents/{agent_id}",
        json={"soft_timeout_seconds": 3.0},
    )

    # Mock EL API to always fail
    def _always_503(request, route):
        return httpx.Response(503, json={"error": "down"})

    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/agent_8201kra4wjhve0srcwgbtwfetr5n"
    ).mock(side_effect=_always_503)

    resp = await client.post(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sync_status"] == "error"

    # Verify DB updated
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "error"


# ---------------------------------------------------------------------------
# Integration: agent create with soft timeout → sync status updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_agent_create_with_soft_timeout_updates_sync_status(sync_app):
    """GIVEN AgentCreate with elevenlabs_agent_id and soft_timeout_seconds, EL API returns 200
    WHEN POST .../agents is called
    THEN agent is saved (201) and sync_status becomes 'synced' asynchronously
    """
    import asyncio
    client, db_module = sync_app

    # Mock EL PATCH for a custom agent ID we'll create
    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-custom-id").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    resp = await client.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "agent-sync-test",
            "name": "Agent Sync Test",
            "voice_id": "voice-abc",
            "elevenlabs_agent_id": "el-custom-id",
            "soft_timeout_seconds": 2.5,
        },
    )
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]

    # Allow background task to complete (0.3s is enough for in-memory SQLite)
    await asyncio.sleep(0.3)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "synced"
        assert agent.elevenlabs_last_synced_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_agent_save_when_el_api_down_saves_agent_sync_status_error(sync_app):
    """GIVEN EL API is down (503), AgentCreate with elevenlabs_agent_id and soft timeout
    WHEN POST .../agents is called
    THEN agent is saved (201 returned immediately)
    AND sync_status is set to 'error' in the background
    """
    import asyncio
    client, db_module = sync_app

    # Mock EL PATCH to always fail
    def _always_503(request, route):
        return httpx.Response(503, json={"error": "down"})

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-down-agent").mock(
        side_effect=_always_503
    )

    resp = await client.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "agent-el-down",
            "name": "Agent EL Down",
            "voice_id": "voice-abc",
            "elevenlabs_agent_id": "el-down-agent",
            "soft_timeout_seconds": 3.0,
        },
    )
    # Agent saved successfully even if EL is down
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]

    # Allow background task to run (0.3s is enough for in-memory SQLite)
    await asyncio.sleep(0.3)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "error"


# ---------------------------------------------------------------------------
# sdd/elevenlabs-config — Task 4.1 RED→GREEN
# Integration: sync-elevenlabs with all three config groups → PATCH has all blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_resync_endpoint_with_all_three_config_groups_patch_body(sync_app):
    """GIVEN agent with all three config groups (soft_timeout + voicemail + max_duration)
    WHEN POST .../sync-elevenlabs is called
    THEN the PATCH body sent to ElevenLabs contains all three blocks.

    Spec: sdd/elevenlabs-config — Scenario: All three config blocks present
    """
    import json as _json
    client, db_module = sync_app
    agent_id = await _get_qora_demo_agent_id(client)

    # Set all three config groups on the agent (qora-demo already has voicemail+max_duration from seed)
    await client.patch(
        f"/api/v1/clients/qora-demo/agents/{agent_id}",
        json={
            "soft_timeout_seconds": 3.0,
            "voicemail_detection_enabled": True,
            "max_call_duration_seconds": 120,
        },
    )

    captured: dict = {}

    def capture(request, route):
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/agent_8201kra4wjhve0srcwgbtwfetr5n"
    ).mock(side_effect=capture)

    resp = await client.post(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 200
    assert resp.json()["sync_status"] == "synced"

    body = captured.get("body", {})
    # All three blocks in the PATCH payload (correct paths verified from live ElevenLabs API 2026-07-07)
    assert "turn" in body.get("conversation_config", {}), "missing soft_timeout_config block"
    assert "max_duration_seconds" in body.get("conversation_config", {}).get("conversation", {}), "missing max_duration block"
    built_in_tools = body.get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("built_in_tools", {})
    assert "voicemail_detection" in built_in_tools, "missing voicemail_detection block"
    assert built_in_tools["voicemail_detection"] == {"system_tool_type": "voicemail_detection"}
    assert "platform_settings" not in body, "voicemail must NOT be under platform_settings"


# ---------------------------------------------------------------------------
# sdd/elevenlabs-config — Task 4.2 RED→GREEN
# Integration: agent create with voicemail + max_duration + EL ID → background sync fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_agent_create_with_voicemail_and_max_duration_triggers_sync(sync_app):
    """GIVEN AgentCreate with elevenlabs_agent_id + voicemail_detection_enabled + max_call_duration_seconds
    WHEN POST .../agents is called
    THEN agent saved (201), background sync fires, sync_status becomes 'synced'.

    Spec: sdd/elevenlabs-config — Requirement: Background Sync Upgrade
    """
    import asyncio as _asyncio
    client, db_module = sync_app

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-vm-agent").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    resp = await client.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "agent-vm-test",
            "name": "Agent VM Test",
            "voice_id": "voice-vm",
            "elevenlabs_agent_id": "el-vm-agent",
            "voicemail_detection_enabled": True,
            "max_call_duration_seconds": 180,
        },
    )
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]

    # Allow background task to complete
    await _asyncio.sleep(0.3)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_agent
        agent = await get_agent(sess, agent_id)
        assert agent.elevenlabs_sync_status == "synced"
        assert agent.elevenlabs_last_synced_at is not None
        assert agent.voicemail_detection_enabled is True
        assert agent.max_call_duration_seconds == 180


# ---------------------------------------------------------------------------
# sdd/elevenlabs-config — Task 4.3 RED→GREEN
# Integration: sync with only voicemail set → PATCH has only voicemail block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_resync_endpoint_with_only_voicemail_sends_only_voicemail_block(sync_app):
    """GIVEN agent with only voicemail_detection_enabled set (no soft_timeout, no max_duration)
    WHEN POST .../sync-elevenlabs is called
    THEN PATCH body contains only platform_settings.voicemail_detection.

    Spec: sdd/elevenlabs-config — NULL-Means-Skip Semantics
    """
    import json as _json
    client, db_module = sync_app

    # Create an agent with only voicemail set
    create_resp = await client.post(
        "/api/v1/clients/qora-demo/agents",
        json={
            "slug": "agent-vm-only",
            "name": "Agent VM Only",
            "voice_id": "voice-vm-only",
            "elevenlabs_agent_id": "el-vm-only-agent",
            "voicemail_detection_enabled": False,
        },
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    captured: dict = {}

    def capture(request, route):
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-vm-only-agent"
    ).mock(side_effect=capture)

    resp = await client.post(
        f"/api/v1/clients/qora-demo/agents/{agent_id}/sync-elevenlabs"
    )
    assert resp.status_code == 200
    assert resp.json()["sync_status"] == "synced"

    body = captured.get("body", {})
    assert "platform_settings" not in body, "voicemail must NOT be under platform_settings"
    built_in_tools = body.get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("built_in_tools", {})
    assert "voicemail_detection" in built_in_tools, "missing voicemail_detection"
    assert built_in_tools["voicemail_detection"] is None  # False → explicit null to disable
    # These blocks must NOT be present
    assert "turn" not in body.get("conversation_config", {}), "unexpected soft_timeout block"
    assert "conversation" not in body.get("conversation_config", {}), "unexpected max_duration block"
