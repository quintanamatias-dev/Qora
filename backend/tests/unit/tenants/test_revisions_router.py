"""Phase 2 (agent-config-revisions-routing) — Tasks 2.4/2.5: revisions API.

Covers:
  PATCH /api/v1/clients/{client_id}/agents/{agent_id}/config
  GET   /api/v1/clients/{client_id}/agents/{agent_id}/revisions
  GET   /api/v1/clients/{client_id}/agents/{agent_id}/revisions/{id}
  POST  /api/v1/clients/{client_id}/agents/{agent_id}/revisions/{id}/rollback
  EL sync wiring on PATCH/rollback (task 2.5)
  Legacy PATCH /agents/{agent_id} also creates a revision (source="api")
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def revisions_app(tmp_path: Path):
    """Isolated FastAPI app with agents router + a seeded second-tenant agent.

    ElevenLabsService.sync_agent_config is mocked throughout so no outbound
    HTTP call is made regardless of elevenlabs_agent_id.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/revisions_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana
        from tests.helpers.second_tenant import seed_second_tenant

        await seed_second_tenant(session)
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


async def _get_second_tenant_agent_id(client: AsyncClient) -> str:
    response = await client.get("/api/v1/clients/acme-widgets/agents")
    response.raise_for_status()
    agents = response.json()
    assert len(agents) == 1
    return agents[0]["agent_id"]


# ---------------------------------------------------------------------------
# Task 2.4: PATCH config
# ---------------------------------------------------------------------------


async def test_patch_agent_config_creates_and_activates_revision(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config",
        AsyncMock(return_value=AsyncMock(outcome="skipped", error_detail=None)),
    ):
        response = await revisions_app.patch(
            f"{base_url}/config", json={"temperature": 0.33}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["temperature"] == 0.33
    assert body["source"] == "api"

    list_response = await revisions_app.get(f"{base_url}/revisions")
    revisions = list_response.json()
    assert revisions[0]["id"] == body["id"]
    assert revisions[0]["revision_number"] == body["revision_number"]


async def test_patch_agent_config_rejects_invalid_merged_config(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    response = await revisions_app.patch(
        f"{base_url}/config", json={"tts_speed": 99.0}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Task 2.4: GET revisions list + single
# ---------------------------------------------------------------------------


async def test_list_revisions_returns_ordered_history(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config",
        AsyncMock(return_value=AsyncMock(outcome="skipped", error_detail=None)),
    ):
        await revisions_app.patch(f"{base_url}/config", json={"temperature": 0.4})
        await revisions_app.patch(f"{base_url}/config", json={"temperature": 0.5})

    response = await revisions_app.get(f"{base_url}/revisions")
    assert response.status_code == 200
    revisions = response.json()
    numbers = [r["revision_number"] for r in revisions]
    assert numbers == sorted(numbers, reverse=True)
    assert len(numbers) >= 3


async def test_get_single_revision(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    list_response = await revisions_app.get(f"{base_url}/revisions")
    revision_id = list_response.json()[0]["id"]

    response = await revisions_app.get(f"{base_url}/revisions/{revision_id}")
    assert response.status_code == 200
    assert response.json()["id"] == revision_id


async def test_get_single_revision_404_for_unknown_id(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    response = await revisions_app.get(f"{base_url}/revisions/does-not-exist")
    assert response.status_code == 404


async def test_revision_of_another_agent_is_unreachable_via_api(revisions_app):
    """Tenant isolation at the API layer: quintana's revision is invisible via acme-widgets's agent_id."""
    second_tenant_agent_id = await _get_second_tenant_agent_id(revisions_app)

    quintana_response = await revisions_app.get(
        "/api/v1/clients/quintana-seguros/agents"
    )
    quintana_agent_id = quintana_response.json()[0]["agent_id"]

    quintana_revisions = await revisions_app.get(
        f"/api/v1/clients/quintana-seguros/agents/{quintana_agent_id}/revisions"
    )
    quintana_revision_id = quintana_revisions.json()[0]["id"]

    leaked = await revisions_app.get(
        f"/api/v1/clients/acme-widgets/agents/{second_tenant_agent_id}/revisions/{quintana_revision_id}"
    )
    assert leaked.status_code == 404


# ---------------------------------------------------------------------------
# Task 2.3/2.4: rollback endpoint
# ---------------------------------------------------------------------------


async def test_rollback_endpoint_activates_new_revision(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    revisions_before = (await revisions_app.get(f"{base_url}/revisions")).json()
    revision_1_id = revisions_before[-1]["id"]

    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config",
        AsyncMock(return_value=AsyncMock(outcome="skipped", error_detail=None)),
    ):
        await revisions_app.patch(f"{base_url}/config", json={"temperature": 0.6})

        rollback_response = await revisions_app.post(
            f"{base_url}/revisions/{revision_1_id}/rollback"
        )
    assert rollback_response.status_code == 200
    body = rollback_response.json()
    assert body["source"] == "rollback"
    assert body["id"] != revision_1_id

    agent_response = await revisions_app.get(f"{base_url}")
    assert agent_response.status_code == 200


# ---------------------------------------------------------------------------
# Task 2.5: EL sync wiring
# ---------------------------------------------------------------------------


async def test_patch_agent_config_enqueues_el_sync(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    mock_sync = AsyncMock(return_value=AsyncMock(outcome="synced", error_detail=None))
    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config", mock_sync
    ):
        response = await revisions_app.patch(
            f"{base_url}/config", json={"temperature": 0.42}
        )

    assert response.status_code == 200
    mock_sync.assert_awaited_once()
    body = response.json()
    assert body["elevenlabs_sync_status"] == "synced"


async def test_rollback_also_triggers_sync(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    revisions_before = (await revisions_app.get(f"{base_url}/revisions")).json()
    revision_1_id = revisions_before[-1]["id"]

    mock_sync = AsyncMock(return_value=AsyncMock(outcome="synced", error_detail=None))
    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config", mock_sync
    ):
        response = await revisions_app.post(
            f"{base_url}/revisions/{revision_1_id}/rollback"
        )

    assert response.status_code == 200
    mock_sync.assert_awaited_once()
    assert response.json()["elevenlabs_sync_status"] == "synced"


# ---------------------------------------------------------------------------
# Legacy PATCH /agents/{agent_id} also creates a revision (source="api")
# ---------------------------------------------------------------------------


async def test_legacy_patch_agent_also_creates_revision(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    revisions_before = (await revisions_app.get(f"{base_url}/revisions")).json()
    count_before = len(revisions_before)

    with patch("app.agents.router.sync_to_elevenlabs", AsyncMock()):
        response = await revisions_app.patch(base_url, json={"temperature": 0.55})
    assert response.status_code == 200
    assert response.json()["temperature"] == 0.55

    revisions_after = (await revisions_app.get(f"{base_url}/revisions")).json()
    assert len(revisions_after) == count_before + 1
    assert revisions_after[0]["source"] == "api"
    assert revisions_after[0]["config"]["temperature"] == 0.55


async def test_legacy_patch_writes_sparse_v2_revision_without_repinning_dropped_override(
    revisions_app,
):
    """gap fix: legacy PATCH must write through the sparse V2 path, not a full
    V1 snapshot — a field the agent previously dropped (inherits) must stay
    dropped, not get re-pinned as an agent override by an unrelated field edit.
    """
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    # Promote to V2 overrides, explicitly dropping the `model` override (null
    # removes it — the agent now inherits `model` from client/standard).
    with patch(
        "app.elevenlabs.service.ElevenLabsService.sync_agent_config",
        AsyncMock(return_value=AsyncMock(outcome="skipped", error_detail=None)),
    ):
        setup_response = await revisions_app.patch(
            f"{base_url}/config", json={"temperature": 0.5, "model": None}
        )
    assert setup_response.status_code == 200
    assert "model" not in setup_response.json()["config"]

    # Legacy PATCH of an unrelated config field (tts_speed) — must not re-pin model.
    with patch("app.agents.router.sync_to_elevenlabs", AsyncMock()):
        response = await revisions_app.patch(base_url, json={"tts_speed": 1.1})
    assert response.status_code == 200
    assert response.json()["tts_speed"] == 1.1

    revisions = (await revisions_app.get(f"{base_url}/revisions")).json()
    latest_config = revisions[0]["config"]
    assert revisions[0]["schema_version"] == "v2"
    assert "model" not in latest_config
    assert latest_config["tts_speed"] == 1.1
    assert latest_config["temperature"] == 0.5


async def test_legacy_patch_of_non_config_field_creates_no_revision(revisions_app):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    revisions_before = (await revisions_app.get(f"{base_url}/revisions")).json()
    count_before = len(revisions_before)

    response = await revisions_app.patch(base_url, json={"name": "Renamed Agent"})
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Agent"

    revisions_after = (await revisions_app.get(f"{base_url}/revisions")).json()
    assert len(revisions_after) == count_before


async def test_legacy_patch_removing_required_field_returns_422_and_no_change(
    revisions_app,
):
    agent_id = await _get_second_tenant_agent_id(revisions_app)
    base_url = f"/api/v1/clients/acme-widgets/agents/{agent_id}"

    before = await revisions_app.get(base_url)
    voice_id_before = before.json()["voice_id"]
    revisions_before = (await revisions_app.get(f"{base_url}/revisions")).json()
    count_before = len(revisions_before)

    response = await revisions_app.patch(base_url, json={"voice_id": None})
    assert response.status_code == 422

    after = await revisions_app.get(base_url)
    assert after.json()["voice_id"] == voice_id_before
    revisions_after = (await revisions_app.get(f"{base_url}/revisions")).json()
    assert len(revisions_after) == count_before
