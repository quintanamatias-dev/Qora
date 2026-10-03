"""HTTP feature gates and the agent limit (multi-tenant-readiness WU2).

Spec: openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md
      Requirements: Feature Gating, Agent Limit
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.auth import CallerIdentity, require_api_key

CLIENT = "acme"


@pytest_asyncio.fixture
async def api(tmp_path: Path):
    """Real API router over a migrated DB with one client; yields (http, set_plan)."""
    from app.core import database as db_module
    from app.core.config import Settings
    from app.main import api_v1_router
    from app.tenants.models import Client
    from app.tenants.service import create_client
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gates.db",
    )
    await init_db_with_migrations(db_module, settings)
    async with db_module.async_session_factory() as sess:
        await create_client(sess, id=CLIENT, name="Acme", voice_id="v")
        await sess.commit()

    async def set_plan(plan: str, overrides: dict | None = None) -> None:
        async with db_module.async_session_factory() as sess:
            client = await sess.get(Client, CLIENT)
            client.plan = plan
            client.entitlement_overrides = json.dumps(overrides) if overrides else None
            await sess.commit()

    app = FastAPI()
    app.include_router(api_v1_router)
    principal = CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset({CLIENT}))
    app.dependency_overrides[require_api_key] = lambda: principal
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        yield http, set_plan
    await db_module.close_db()


_GATED = [
    ("analytics", "GET", f"/api/v1/analytics/{CLIENT}/overview"),
    ("analytics", "GET", f"/api/v1/analytics/{CLIENT}/interests"),
    ("live_monitor", "GET", f"/api/v1/calls/active?client_id={CLIENT}"),
    ("crm_integration", "POST", f"/api/v1/clients/{CLIENT}/crm/import"),
]


@pytest.mark.parametrize(("feature", "method", "path"), _GATED)
async def test_route_is_forbidden_when_feature_is_off(api, feature, method, path):
    http, set_plan = api
    await set_plan("pro", {"features": {feature: False}})

    resp = await http.request(method, path)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == {
        "error": "feature_not_in_plan",
        "feature": feature,
        "message": f"Your plan does not include '{feature}'.",
    }


@pytest.mark.parametrize(("feature", "method", "path"), _GATED[:3])
async def test_route_works_when_feature_is_on(api, feature, method, path):
    http, set_plan = api
    await set_plan("pro")

    resp = await http.request(method, path)

    assert resp.status_code == 200, resp.text


async def test_feature_gate_runs_after_tenant_check(api):
    http, set_plan = api
    await set_plan("pro", {"features": {"analytics": False}})

    resp = await http.get("/api/v1/analytics/someone-else/overview")

    assert resp.json()["detail"]["error"] == "tenant_forbidden"


class TestAgentLimit:
    @pytest_asyncio.fixture
    async def admin(self, api, tmp_path):
        """Same DB, superadmin principal (agent creation is superadmin-only)."""
        from app.main import api_v1_router

        _, set_plan = api
        app = FastAPI()
        app.include_router(api_v1_router)
        app.dependency_overrides[require_api_key] = lambda: CallerIdentity(api_key_hash="t")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            yield http, set_plan

    @staticmethod
    def _agent(slug: str) -> dict:
        return {
            "slug": slug,
            "name": slug.title(),
            "voice_id": "voice-1",
            "goal": "Book a demo call.",
        }

    async def test_agent_creation_blocked_at_plan_limit(self, admin):
        http, set_plan = admin
        # create_client already provisions one default agent.
        await set_plan("starter", {"limits": {"max_agents": 2}})

        first = await http.post(f"/api/v1/clients/{CLIENT}/agents", json=self._agent("first"))
        second = await http.post(f"/api/v1/clients/{CLIENT}/agents", json=self._agent("second"))

        assert first.status_code == 201, first.text
        assert second.status_code == 403
        assert second.json()["detail"]["error"] == "plan_limit_reached"
        assert second.json()["detail"]["limit"] == "max_agents"

    async def test_unlimited_plan_allows_more_agents(self, admin):
        http, set_plan = admin
        await set_plan("pilot")

        for slug in ("a", "b", "c"):
            resp = await http.post(f"/api/v1/clients/{CLIENT}/agents", json=self._agent(slug))
            assert resp.status_code == 201, resp.text
