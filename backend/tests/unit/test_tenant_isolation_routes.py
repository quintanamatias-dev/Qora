"""Cross-tenant isolation over the real API router (multi-tenant-readiness WU1).

A principal scoped to tenant ``acme`` attacks every route with data that
belongs to ``quintana-seguros``. The test proves the tenant-isolation spec for
principals that are NOT superadmin — the global API key is superadmin, so these
guarantees only become observable with a scoped principal.

Spec: openspec/changes/multi-tenant-readiness/specs/tenant-access/spec.md
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.auth import CallerIdentity, require_api_key

OWN = "acme"
FOREIGN = "quintana-seguros"


@pytest_asyncio.fixture
async def world(tmp_path: Path):
    """Two tenants, each with a lead, a call session, a transcript turn and an analysis."""
    from app.calls.models import CallAnalysis, TranscriptTurn
    from app.calls.service import create_session
    from app.core import database as db_module
    from app.core.config import Settings
    from app.leads.service import create_lead
    from app.tenants.service import create_client, seed_quintana
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/isolation.db",
    )
    await init_db_with_migrations(db_module, settings)

    ids: dict[str, dict[str, str]] = {}
    async with db_module.async_session_factory() as sess:
        await seed_quintana(sess)
        await create_client(sess, id=OWN, name="Acme", voice_id="voice-acme")
        await sess.flush()
        for tenant in (OWN, FOREIGN):
            lead = await create_lead(sess, client_id=tenant, name=f"Lead {tenant}", phone="+5491100000000")
            cs = await create_session(sess, client_id=tenant, lead_id=lead.id)
            sess.add(TranscriptTurn(id=str(uuid.uuid4()), session_id=cs.id, role="user", content="hola"))
            sess.add(CallAnalysis(id=str(uuid.uuid4()), session_id=cs.id, lead_id=lead.id, client_id=tenant))
            ids[tenant] = {"lead": lead.id, "session": cs.id}
        await sess.commit()

    yield ids
    await db_module.close_db()


def _api(principal: CallerIdentity) -> FastAPI:
    from app.main import api_v1_router

    app = FastAPI()
    app.include_router(api_v1_router)
    app.dependency_overrides[require_api_key] = lambda: principal
    return app


@pytest_asyncio.fixture
async def tenant_user(world):
    principal = CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset({OWN}))
    async with AsyncClient(transport=ASGITransport(app=_api(principal)), base_url="http://t") as c:
        yield c


# ---------------------------------------------------------------------------
# Foreign resources addressed by id → 404 (indistinguishable from missing)
# ---------------------------------------------------------------------------

_FOREIGN_BY_ID = [
    ("GET", "/api/v1/calls/{session}"),
    ("GET", "/api/v1/calls/{session}/status"),
    ("GET", "/api/v1/calls/{session}/transcript"),
    ("GET", "/api/v1/calls/{session}/analysis"),
    ("GET", "/api/v1/leads/{lead}"),
    ("PATCH", "/api/v1/leads/{lead}/status"),
    ("GET", "/api/v1/leads/{lead}/history"),
    ("GET", "/api/v1/leads/{lead}/context-preview"),
    ("GET", "/api/v1/leads/{lead}/dimension-rollups?client_id=" + OWN),
]


@pytest.mark.parametrize(("method", "path"), _FOREIGN_BY_ID)
async def test_foreign_resource_by_id_is_not_found(tenant_user, world, method, path):
    url = path.format(**world[FOREIGN])
    resp = await tenant_user.request(method, url, json={"status": "called"} if method == "PATCH" else None)
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Explicit foreign tenant in path/query → 403
# ---------------------------------------------------------------------------

_FOREIGN_SCOPED = [
    ("GET", f"/api/v1/leads?client_id={FOREIGN}"),
    ("POST", f"/api/v1/leads?client_id={FOREIGN}"),
    ("GET", f"/api/v1/calls?client_id={FOREIGN}"),
    ("GET", f"/api/v1/calls/metrics?client_id={FOREIGN}"),
    ("GET", f"/api/v1/calls/active?client_id={FOREIGN}"),
    ("GET", f"/api/v1/analytics/{FOREIGN}/overview"),
    ("GET", f"/api/v1/analytics/{FOREIGN}/agent-stats"),
    ("GET", f"/api/v1/clients/{FOREIGN}/scheduled-calls"),
    ("GET", f"/api/v1/scheduler/{FOREIGN}/queue"),
    ("POST", f"/api/v1/clients/{FOREIGN}/leads/{{lead}}/call"),
    ("GET", f"/api/v1/clients/{FOREIGN}"),
    ("GET", f"/api/v1/clients/{FOREIGN}/agents"),
    ("GET", f"/api/v1/clients/{FOREIGN}/integrations"),
    ("GET", f"/api/v1/clients/{FOREIGN}/integrations/available"),
    ("POST", f"/api/v1/clients/{FOREIGN}/crm/import"),
    ("GET", f"/api/v1/tenants/{FOREIGN}"),
]


@pytest.mark.parametrize(("method", "path"), _FOREIGN_SCOPED)
async def test_foreign_tenant_scope_is_forbidden(tenant_user, world, method, path):
    url = path.format(**world[FOREIGN])
    body = {"name": "x", "phone": "+5491100000001"} if method == "POST" else None
    resp = await tenant_user.request(method, url, json=body)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "tenant_forbidden"


# ---------------------------------------------------------------------------
# Superadmin-only administration → 403 even on the principal's own tenant
# ---------------------------------------------------------------------------

_SUPERADMIN_ONLY = [
    ("POST", "/api/v1/clients"),
    ("PATCH", f"/api/v1/clients/{OWN}"),
    ("DELETE", f"/api/v1/clients/{OWN}"),
    ("POST", f"/api/v1/clients/{OWN}/agents"),
    ("PATCH", f"/api/v1/clients/{OWN}/agents/some-agent"),
    ("POST", f"/api/v1/clients/{OWN}/agents/some-agent/sync-elevenlabs"),
    ("POST", f"/api/v1/clients/{OWN}/agents/some-agent/deactivate"),
    ("POST", f"/api/v1/clients/{OWN}/agents/some-agent/make-default"),
    ("PUT", f"/api/v1/clients/{OWN}/integrations/airtable"),
    ("POST", f"/api/v1/clients/{OWN}/integrations/airtable/test"),
    ("PUT", f"/api/v1/clients/{OWN}/integrations/airtable/mappings"),
    ("POST", f"/api/v1/clients/{OWN}/integrations/airtable/connect"),
    ("DELETE", f"/api/v1/clients/{OWN}/integrations/airtable/disconnect"),
    ("POST", "/api/v1/calls/some-conversation/end"),
    ("GET", "/api/v1/voice/signed-url"),
]


@pytest.mark.parametrize(("method", "path"), _SUPERADMIN_ONLY)
async def test_administration_requires_superadmin(tenant_user, method, path):
    resp = await tenant_user.request(method, path, json={} if method in {"POST", "PUT", "PATCH"} else None)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "superadmin_required"


# ---------------------------------------------------------------------------
# The principal's own tenant keeps working
# ---------------------------------------------------------------------------


async def test_own_resources_remain_accessible(tenant_user, world):
    own = world[OWN]
    for url in (
        f"/api/v1/leads?client_id={OWN}",
        f"/api/v1/leads/{own['lead']}",
        f"/api/v1/leads/{own['lead']}/history",
        f"/api/v1/calls?client_id={OWN}",
        f"/api/v1/calls/{own['session']}",
        f"/api/v1/calls/{own['session']}/transcript",
        f"/api/v1/calls/{own['session']}/analysis",
        f"/api/v1/clients/{OWN}",
        f"/api/v1/clients/{OWN}/agents",
        f"/api/v1/tenants/{OWN}",
    ):
        resp = await tenant_user.get(url)
        assert resp.status_code == 200, f"{url}: {resp.status_code} {resp.text}"


async def test_client_list_returns_only_accessible_tenants(tenant_user):
    resp = await tenant_user.get("/api/v1/clients")
    assert resp.status_code == 200
    assert [c["client_id"] for c in resp.json()] == [OWN]


async def test_foreign_lead_history_does_not_leak_sessions(tenant_user, world):
    resp = await tenant_user.get(f"/api/v1/leads/{world[FOREIGN]['lead']}/history")
    assert world[FOREIGN]["session"] not in resp.text


# ---------------------------------------------------------------------------
# Previously unauthenticated routes now require a credential
# ---------------------------------------------------------------------------


class TestAdminRoutesRequireAuth:
    """Named so conftest does not install the test auth bypass."""

    @pytest.mark.parametrize("path", ["/api/v1/tenants/quintana-seguros", "/api/v1/voice/signed-url"])
    async def test_route_rejects_anonymous_caller(self, world, path):
        from app.main import api_v1_router

        app = FastAPI()
        app.include_router(api_v1_router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get(path)
        assert resp.status_code == 401
