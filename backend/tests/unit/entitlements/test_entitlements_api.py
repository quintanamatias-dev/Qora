"""Entitlements API (multi-tenant-readiness WU2).

Spec: openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md
      Requirement: Entitlements API
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.auth import CallerIdentity, require_api_key
from app.entitlements.catalog import FEATURES, LIMITS, PLANS

CLIENT = "acme"


@pytest_asyncio.fixture
async def clients(tmp_path: Path):
    """Yields (superadmin_http, tenant_user_http) over the real API router."""
    from app.calls.models import CallSession
    from app.core import database as db_module
    from app.core.config import Settings
    from app.main import api_v1_router
    from app.tenants.service import create_client
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/ent_api.db",
    )
    await init_db_with_migrations(db_module, settings)
    async with db_module.async_session_factory() as sess:
        await create_client(sess, id=CLIENT, name="Acme", voice_id="v")
        sess.add(
            CallSession(
                id=str(uuid.uuid4()),
                client_id=CLIENT,
                lead_id=None,
                status="completed",
                started_at=datetime.now(timezone.utc),
                duration_seconds=125,
            )
        )
        await sess.commit()

    def _http(principal: CallerIdentity) -> AsyncClient:
        app = FastAPI()
        app.include_router(api_v1_router)
        app.dependency_overrides[require_api_key] = lambda: principal
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")

    admin = _http(CallerIdentity(api_key_hash="t"))
    tenant = _http(CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset({CLIENT})))
    async with admin, tenant:
        yield admin, tenant
    await db_module.close_db()


async def test_get_returns_plan_features_limits_and_usage(clients):
    _, tenant = clients
    resp = await tenant.get(f"/api/v1/clients/{CLIENT}/entitlements")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client_id"] == CLIENT
    assert body["plan"] == "pilot"
    assert set(body["features"]) == set(FEATURES)
    assert set(body["limits"]) == set(LIMITS)
    assert body["usage"]["monthly_calls"] == 1
    assert body["usage"]["monthly_minutes"] == 3  # ceil(125 / 60)
    assert body["usage"]["active_agents"] == 1
    assert "period_start" in body["usage"]
    assert body["overrides"] == {}


async def test_superadmin_updates_plan_and_overrides(clients):
    admin, tenant = clients
    resp = await admin.put(
        f"/api/v1/clients/{CLIENT}/entitlements",
        json={"plan": "starter", "overrides": {"features": {"live_monitor": True}, "limits": {"max_agents": 2}}},
    )
    assert resp.status_code == 200, resp.text

    body = (await tenant.get(f"/api/v1/clients/{CLIENT}/entitlements")).json()
    assert body["plan"] == "starter"
    assert body["features"]["live_monitor"] is True
    assert body["features"]["auto_dialer"] is False
    assert body["limits"]["max_agents"] == 2
    assert body["limits"]["max_monthly_minutes"] == 200


async def test_clearing_overrides_restores_plan_defaults(clients):
    admin, _ = clients
    await admin.put(f"/api/v1/clients/{CLIENT}/entitlements", json={"plan": "pro", "overrides": {"limits": {"max_agents": 9}}})
    resp = await admin.put(f"/api/v1/clients/{CLIENT}/entitlements", json={"plan": "pro", "overrides": {}})
    assert resp.json()["limits"]["max_agents"] == PLANS["pro"].limits["max_agents"]
    assert resp.json()["overrides"] == {}


async def test_tenant_user_cannot_change_plan(clients):
    _, tenant = clients
    resp = await tenant.put(f"/api/v1/clients/{CLIENT}/entitlements", json={"plan": "business"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "superadmin_required"


async def test_rejects_unknown_plan_and_invalid_overrides(clients):
    admin, _ = clients
    bad_plan = await admin.put(f"/api/v1/clients/{CLIENT}/entitlements", json={"plan": "gold"})
    bad_override = await admin.put(
        f"/api/v1/clients/{CLIENT}/entitlements",
        json={"plan": "pro", "overrides": {"features": {"teleport": True}}},
    )
    assert bad_plan.status_code == 422
    assert bad_override.status_code == 422


async def test_unknown_client_is_not_found(clients):
    admin, _ = clients
    assert (await admin.get("/api/v1/clients/nobody/entitlements")).status_code == 404
    assert (await admin.put("/api/v1/clients/nobody/entitlements", json={"plan": "pro"})).status_code == 404


async def test_foreign_tenant_is_forbidden(clients):
    _, tenant = clients
    resp = await tenant.get("/api/v1/clients/someone-else/entitlements")
    assert resp.status_code == 403


async def test_plan_catalog(clients):
    admin, tenant = clients
    resp = await admin.get("/api/v1/entitlements/plans")

    assert resp.status_code == 200
    body = resp.json()
    assert body["features"] == list(FEATURES)
    assert body["limits"] == list(LIMITS)
    assert [p["name"] for p in body["plans"]] == list(PLANS)
    assert (await tenant.get("/api/v1/entitlements/plans")).status_code == 403


async def test_client_response_includes_plan(clients):
    admin, _ = clients
    resp = await admin.get(f"/api/v1/clients/{CLIENT}")
    assert resp.json()["plan"] == "pilot"
