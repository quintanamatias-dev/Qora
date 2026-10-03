"""Admin API for ElevenLabs reconciliation reports.

Spec: openspec/changes/elevenlabs-reconciler/design.md - R-D2.

GET /api/v1/admin/elevenlabs/reconciliation   (superadmin)
POST /api/v1/admin/elevenlabs/reconciliation/run  (superadmin)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr

from app.core.auth import CallerIdentity, require_api_key


def _superadmin() -> CallerIdentity:
    return CallerIdentity(api_key_hash="t", role="superadmin", client_ids=frozenset())


def _client_principal(client_id: str) -> CallerIdentity:
    return CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset({client_id}))


@pytest_asyncio.fixture
async def router_app(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/reconciliation_router_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.models import Agent, Client

        client = Client(id="test-client", name="test-client", voice_id="voice-1")
        session.add(client)
        agent = Agent(
            id="agent-1",
            client_id="test-client",
            slug="main",
            name="Main Agent",
            voice_id="voice-1",
            elevenlabs_agent_id="el-agent-1",
            is_active=True,
        )
        session.add(agent)
        await session.commit()

    yield settings

    await db_module.close_db()


def _make_app(settings, principal: CallerIdentity) -> FastAPI:
    from app.admin.elevenlabs_reconciliation_router import router as reconciliation_router

    app = FastAPI()
    app.state.settings = settings
    app.include_router(reconciliation_router, prefix="/api/v1")
    app.dependency_overrides[require_api_key] = lambda: principal
    return app


# ---------------------------------------------------------------------------
# GET /api/v1/admin/elevenlabs/reconciliation
# ---------------------------------------------------------------------------


async def test_get_reconciliation_requires_superadmin(router_app):
    app = _make_app(router_app, _client_principal("test-client"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/admin/elevenlabs/reconciliation")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "superadmin_required"


async def test_get_reconciliation_returns_latest_reports(router_app):
    from app.core import database as db_module
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from datetime import datetime, timezone

    async with db_module.async_session_factory() as session:
        session.add(
            ElevenLabsReconciliationReport(
                agent_id="agent-1",
                client_id="test-client",
                status="in_sync",
                drift_fields=None,
                status_reason=None,
                checked_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    app = _make_app(router_app, _superadmin())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/v1/admin/elevenlabs/reconciliation")

    assert resp.status_code == 200
    body = resp.json()
    assert "reports" in body
    assert len(body["reports"]) == 1
    assert body["reports"][0]["agent_id"] == "agent-1"
    assert body["reports"][0]["status"] == "in_sync"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/elevenlabs/reconciliation/run
# ---------------------------------------------------------------------------


async def test_post_run_requires_superadmin(router_app):
    app = _make_app(router_app, _client_principal("test-client"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/v1/admin/elevenlabs/reconciliation/run")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "superadmin_required"


async def test_post_run_returns_fresh_results(router_app):
    app = _make_app(router_app, _superadmin())

    matching_actual = {
        "conversation_config": {
            "tts": {
                "voice_id": "voice-1",
                "model_id": "eleven_v4_turbo",
                "speed": 0.95,
                "stability": 0.4,
                "similarity_boost": 0.75,
            }
        }
    }
    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(return_value=matching_actual),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            run_resp = await c.post("/api/v1/admin/elevenlabs/reconciliation/run")
            assert run_resp.status_code == 200

            get_resp = await c.get("/api/v1/admin/elevenlabs/reconciliation")
            assert get_resp.status_code == 200
            body = get_resp.json()
            assert len(body["reports"]) == 1
            assert body["reports"][0]["status"] == "in_sync"
