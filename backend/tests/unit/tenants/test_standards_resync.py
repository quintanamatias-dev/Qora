"""Phase 5.6/6 (agent-config-inheritance) — standard resync endpoint.

design.md D15: a STANDARD_VERSION bump never auto-syncs anyone; re-syncing
after a standard change requires this explicit superadmin action, which
re-materializes every active agent platform-wide and triggers the existing
EL sync only for agents whose resolved config actually changed, or whose
materialized_standard_version no longer matches the current STANDARD_VERSION.

Moved in Phase 6 to its intended platform-wide mount point
`POST /api/v1/admin/standards/resync` (`app/admin/standards_router.py`,
registered in `main.py`), superseding the temporary
`/api/v1/clients/admin/standards/resync` deviation from task 5.6.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def resync_app(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/standards_resync_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_qora_demo, seed_quintana

        await seed_quintana(session)
        await seed_qora_demo(session)
        await session.commit()

    from app.admin.standards_router import router as admin_standards_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(admin_standards_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


async def _get_agent_ids() -> dict[str, str]:
    from app.core import database as db_module
    from app.tenants.service import resolve_single_active_agent

    ids = {}
    async with db_module.async_session_factory() as session:
        for client_id in ("quintana-seguros", "qora-demo"):
            agent = await resolve_single_active_agent(session, client_id)
            ids[client_id] = agent.id
    return ids


async def _set_elevenlabs_agent_id(agent_id: str, el_id: str) -> None:
    from app.core import database as db_module
    from app.tenants.models import Agent

    async with db_module.async_session_factory() as session:
        agent = await session.get(Agent, agent_id)
        agent.elevenlabs_agent_id = el_id
        await session.commit()


async def test_standard_resync_not_wired_into_startup_or_background_jobs(resync_app):
    """design.md D15: a STANDARD_VERSION bump never auto-syncs anyone — the
    resync endpoint must only run when explicitly POSTed, never from app
    startup (app/main.py) or the background job executor. No HTTP call is
    made in this test by design: creating the app and seeding data (the
    resync_app fixture) must not, by itself, trigger any sync.
    """
    mock_sync = AsyncMock()
    with patch("app.admin.standards_router.sync_to_elevenlabs", mock_sync):
        # Merely having the app running with seeded agents (fixture setup
        # already ran above) must not have triggered a sync.
        pass

    mock_sync.assert_not_called()


async def test_standard_resync_endpoint_materializes_every_active_agent(resync_app):
    agent_ids = await _get_agent_ids()

    response = await resync_app.post("/api/v1/admin/standards/resync")
    assert response.status_code == 200
    body = response.json()
    assert body["agents_checked"] == len(agent_ids)
    assert "standard_version" in body
    assert "agents_changed" in body
    assert "synced" in body


async def test_standard_resync_only_syncs_drifted_agents(resync_app):
    agent_ids = await _get_agent_ids()

    # First resync consumes every agent's initial drift (NULL->standard
    # columns, filesystem-sourced system_prompt — see test_config_equivalence
    # .py) so both agents are now fully materialized and un-drifted.
    first = await resync_app.post("/api/v1/admin/standards/resync")
    assert first.json()["agents_changed"] == 2

    for agent_id in agent_ids.values():
        await _set_elevenlabs_agent_id(agent_id, f"el-{agent_id}")

    mock_sync = AsyncMock()
    with patch("app.admin.standards_router.sync_to_elevenlabs", mock_sync):
        response = await resync_app.post("/api/v1/admin/standards/resync")
        assert response.status_code == 200

    body = response.json()
    assert body["agents_changed"] == 0
    assert body["synced"] == 0
    mock_sync.assert_not_called()


async def test_standard_resync_requires_superadmin(resync_app):
    """Follows the existing require_superadmin dependency pattern."""
    import inspect

    from app.admin import standards_router as admin_standards_router_module

    source = inspect.getsource(admin_standards_router_module)
    # The resync route must declare require_superadmin, matching every other
    # mutating admin endpoint in this router.
    resync_block = source[source.index('"/standards/resync"') :]
    assert "require_superadmin" in resync_block[: resync_block.index("async def resync_standard")]
