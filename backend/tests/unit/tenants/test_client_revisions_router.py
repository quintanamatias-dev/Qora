"""Phase 3 (agent-config-inheritance) — Task 3.4: client revisions API.

Covers:
  PATCH /api/v1/clients/{client_id}/config
  GET   /api/v1/clients/{client_id}/revisions
  GET   /api/v1/clients/{client_id}/revisions/{id}
  POST  /api/v1/clients/{client_id}/revisions/{id}/rollback

No EL sync wiring in this slice (task 5.5, out of scope here).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def client_revisions_app(tmp_path: Path):
    """Isolated FastAPI app with the clients router + a seeded quintana client."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/client_revisions_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana

        await seed_quintana(session)
        await session.commit()

    from app.clients.router import router as clients_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(clients_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# PATCH /clients/{client_id}/config
# ---------------------------------------------------------------------------


async def test_patch_client_config_creates_and_activates_revision(client_revisions_app):
    before = await client_revisions_app.get("/api/v1/clients/quintana-seguros")
    assert before.status_code == 200

    response = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["language"] == "es"
    assert body["source"] == "api"
    assert body["client_id"] == "quintana-seguros"

    list_response = await client_revisions_app.get(
        "/api/v1/clients/quintana-seguros/revisions"
    )
    revisions = list_response.json()
    assert revisions[0]["id"] == body["id"]


async def test_patch_client_config_rejects_locked_field(client_revisions_app):
    response = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config",
        json={"end_call_tool_enabled": False},
    )
    assert response.status_code == 422


async def test_patch_client_config_rejects_agent_required_field(client_revisions_app):
    response = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config",
        json={"voice_id": "some-voice"},
    )
    assert response.status_code == 422


async def test_patch_client_config_null_removes_override(client_revisions_app):
    first = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
    )
    assert first.json()["config"]["language"] == "es"

    second = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": None}
    )
    assert second.status_code == 200
    assert "language" not in second.json()["config"]


async def test_patch_client_config_404_for_unknown_client(client_revisions_app):
    response = await client_revisions_app.patch(
        "/api/v1/clients/does-not-exist/config", json={"language": "es"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/revisions[/{id}]
# ---------------------------------------------------------------------------


async def test_list_client_revisions_returns_ordered_history(client_revisions_app):
    await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
    )
    await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "en"}
    )

    response = await client_revisions_app.get(
        "/api/v1/clients/quintana-seguros/revisions"
    )
    assert response.status_code == 200
    revisions = response.json()
    numbers = [r["revision_number"] for r in revisions]
    assert numbers == sorted(numbers, reverse=True)
    assert len(numbers) >= 2


async def test_get_single_client_revision(client_revisions_app):
    patch_response = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
    )
    revision_id = patch_response.json()["id"]

    response = await client_revisions_app.get(
        f"/api/v1/clients/quintana-seguros/revisions/{revision_id}"
    )
    assert response.status_code == 200
    assert response.json()["id"] == revision_id


async def test_get_single_client_revision_404_for_unknown_id(client_revisions_app):
    response = await client_revisions_app.get(
        "/api/v1/clients/quintana-seguros/revisions/does-not-exist"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/revisions/{id}/rollback
# ---------------------------------------------------------------------------


async def test_client_rollback_endpoint_activates_new_revision(client_revisions_app):
    first = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
    )
    first_revision_id = first.json()["id"]

    await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"language": "en"}
    )

    rollback_response = await client_revisions_app.post(
        f"/api/v1/clients/quintana-seguros/revisions/{first_revision_id}/rollback"
    )
    assert rollback_response.status_code == 200
    body = rollback_response.json()
    assert body["source"] == "rollback"
    assert body["id"] != first_revision_id
    assert body["config"]["language"] == "es"

    client_response = await client_revisions_app.get(
        "/api/v1/clients/quintana-seguros"
    )
    assert client_response.status_code == 200


# ---------------------------------------------------------------------------
# Propagation (task 5.5, design.md D19): PATCH/rollback client config
# re-materializes every ACTIVE agent of that client, and triggers the
# existing EL sync for agents whose mirrored columns changed and that have
# an elevenlabs_agent_id.
# ---------------------------------------------------------------------------


async def _get_quintana_agent_id() -> str:
    from app.core import database as db_module
    from app.tenants.service import resolve_single_active_agent

    async with db_module.async_session_factory() as session:
        agent = await resolve_single_active_agent(session, "quintana-seguros")
        return agent.id


async def _set_elevenlabs_agent_id(agent_id: str, el_id: str) -> None:
    from app.core import database as db_module
    from app.tenants.models import Agent

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, agent_id)
        agent.elevenlabs_agent_id = el_id
        await session.commit()


async def _get_agent_max_call_duration(agent_id: str) -> int | None:
    from app.core import database as db_module
    from app.tenants.models import Agent

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, agent_id)
        return agent.max_call_duration_seconds


async def test_patch_client_config_materializes_every_active_agent(
    client_revisions_app,
):
    agent_id = await _get_quintana_agent_id()
    assert await _get_agent_max_call_duration(agent_id) is None

    response = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config",
        json={"max_call_duration_seconds": 90},
    )
    assert response.status_code == 200

    assert await _get_agent_max_call_duration(agent_id) == 90


async def test_patch_client_config_syncs_changed_agent_with_elevenlabs_id(
    client_revisions_app,
):
    agent_id = await _get_quintana_agent_id()
    await _set_elevenlabs_agent_id(agent_id, "el-agent-quintana")

    mock_sync = AsyncMock()
    with patch("app.clients.router.sync_to_elevenlabs", mock_sync):
        response = await client_revisions_app.patch(
            "/api/v1/clients/quintana-seguros/config",
            json={"max_call_duration_seconds": 90},
        )
        assert response.status_code == 200

    mock_sync.assert_called_once()
    _, kwargs = mock_sync.call_args
    assert kwargs["agent_id"] == agent_id


async def test_patch_client_config_skips_sync_when_no_column_changed(
    client_revisions_app,
):
    agent_id = await _get_quintana_agent_id()
    await _set_elevenlabs_agent_id(agent_id, "el-agent-quintana")

    # First patch materializes jaumpablo for the first time ever, which
    # always surfaces design.md D19's documented NULL->standard exceptions
    # (voicemail_detection_enabled, max_call_duration_seconds) regardless of
    # what the patch itself touches — consume that one-time transition before
    # asserting the no-op case below.
    await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config", json={"turn_eagerness": "normal"}
    )

    # language is client_only with no Agent.* column mirror — never changes a
    # materialized column, so no sync should fire even with an EL id set.
    mock_sync = AsyncMock()
    with patch("app.clients.router.sync_to_elevenlabs", mock_sync):
        response = await client_revisions_app.patch(
            "/api/v1/clients/quintana-seguros/config", json={"language": "es"}
        )
        assert response.status_code == 200

    mock_sync.assert_not_called()


async def test_patch_client_config_skips_sync_without_elevenlabs_id(
    client_revisions_app,
):
    agent_id = await _get_quintana_agent_id()
    # No elevenlabs_agent_id set on this agent.

    mock_sync = AsyncMock()
    with patch("app.clients.router.sync_to_elevenlabs", mock_sync):
        response = await client_revisions_app.patch(
            "/api/v1/clients/quintana-seguros/config",
            json={"max_call_duration_seconds": 90},
        )
        assert response.status_code == 200

    assert await _get_agent_max_call_duration(agent_id) == 90
    mock_sync.assert_not_called()


async def test_client_rollback_syncs_changed_agent_with_elevenlabs_id(
    client_revisions_app,
):
    agent_id = await _get_quintana_agent_id()
    await _set_elevenlabs_agent_id(agent_id, "el-agent-quintana")

    first = await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config",
        json={"max_call_duration_seconds": 90},
    )
    first_revision_id = first.json()["id"]

    await client_revisions_app.patch(
        "/api/v1/clients/quintana-seguros/config",
        json={"max_call_duration_seconds": 60},
    )
    assert await _get_agent_max_call_duration(agent_id) == 60

    mock_sync = AsyncMock()
    with patch("app.clients.router.sync_to_elevenlabs", mock_sync):
        rollback_response = await client_revisions_app.post(
            f"/api/v1/clients/quintana-seguros/revisions/{first_revision_id}/rollback"
        )
        assert rollback_response.status_code == 200

    assert await _get_agent_max_call_duration(agent_id) == 90
    mock_sync.assert_called_once()
    _, kwargs = mock_sync.call_args
    assert kwargs["agent_id"] == agent_id
