"""Real-router tests: a client-role session is tenant-scoped (design.md, tasks.md).

Uses the full app.main app (all routers mounted) with _TESTING_BYPASS disabled,
so require_client_access / require_superadmin run for real against a session
cookie created through the actual login/session machinery.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import app.core.auth as auth_module
from app.auth.sessions import MappedIdentity, create_session
from app.auth.workos import WorkosUser
from app.core.config import Settings
from pydantic import SecretStr


def _settings(database_url: str) -> Settings:
    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
        database_url=database_url,
    )


@pytest.fixture
async def real_app_client(test_settings, db_engine):
    from app.main import create_app

    auth_module._TESTING_BYPASS = False
    app = create_app(docs_enabled=True)
    app.state.settings = _settings(test_settings.database_url)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    auth_module._TESTING_BYPASS = True


async def _seed_two_clients(db_engine):
    from app.tenants.models import Client

    async with db_engine.async_session_factory() as session:
        session.add(Client(id="acme", name="Acme", voice_id="v1", is_active=True))
        session.add(Client(id="globex", name="Globex", voice_id="v1", is_active=True))
        await session.commit()


async def _client_session_cookie(db_engine, settings, *, client_ids: list[str]) -> str:
    async with db_engine.async_session_factory() as session:
        user = WorkosUser(id="user_1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="client", client_ids=client_ids)
        return await create_session(session, settings, user=user, identity=identity, workos_session_id=None)


class TestSessionScopedTenantAccess:
    async def test_client_session_hitting_foreign_tenant_gets_403_tenant_forbidden(
        self, real_app_client, db_engine, test_settings
    ):
        await _seed_two_clients(db_engine)
        settings = _settings(test_settings.database_url)
        token = await _client_session_cookie(db_engine, settings, client_ids=["acme"])

        real_app_client.cookies.set("qora_session", token)
        resp = await real_app_client.get("/api/v1/clients/globex")
        assert resp.status_code == 403
        assert resp.json()["error"]["reason"] == "tenant_forbidden"

    async def test_client_session_hitting_own_tenant_succeeds(self, real_app_client, db_engine, test_settings):
        await _seed_two_clients(db_engine)
        settings = _settings(test_settings.database_url)
        token = await _client_session_cookie(db_engine, settings, client_ids=["acme"])

        real_app_client.cookies.set("qora_session", token)
        resp = await real_app_client.get("/api/v1/clients/acme")
        assert resp.status_code == 200

    async def test_client_session_hitting_superadmin_only_route_gets_403(
        self, real_app_client, db_engine, test_settings
    ):
        await _seed_two_clients(db_engine)
        settings = _settings(test_settings.database_url)
        token = await _client_session_cookie(db_engine, settings, client_ids=["acme"])

        real_app_client.cookies.set("qora_session", token)
        resp = await real_app_client.get("/api/v1/clients/acme/access")
        assert resp.status_code == 403
        assert resp.json()["error"]["reason"] == "superadmin_required"
