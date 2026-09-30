"""Integration tests for /api/v1/auth (design.md §7)."""

from __future__ import annotations


import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr

from app.auth.router import router as auth_router
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
        workos_api_key=SecretStr("sk_test_workos"),
        workos_client_id="client_test",
        qora_auth_redirect_uri="http://localhost:5173/api/v1/auth/callback",
        qora_superadmin_emails="admin@qora.dev",
    )
    base.update(overrides)
    return Settings(**base)


def _make_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.include_router(auth_router, prefix="/api/v1")
    return app


@pytest.fixture
async def client(test_settings, db_engine):
    # db_engine fixture (conftest) already ran migrations + init_db against
    # an isolated tmp_path SQLite DB, so app.core.database module state is ready.
    settings = _settings(database_url=test_settings.database_url)
    app = _make_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, settings


class TestAuthConfig:
    async def test_login_enabled_true_when_configured(self, client):
        c, _ = client
        resp = await c.get("/api/v1/auth/config")
        assert resp.status_code == 200
        assert resp.json() == {"login_enabled": True}

    async def test_login_enabled_false_when_unconfigured(self, test_settings, db_engine):
        settings = _settings(database_url=test_settings.database_url, workos_api_key=None)
        app = _make_app(settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/auth/config")
        assert resp.json() == {"login_enabled": False}


class TestLogin:
    async def test_not_configured_redirects_to_auth_not_configured(self, test_settings, db_engine):
        settings = _settings(database_url=test_settings.database_url, workos_client_id=None)
        app = _make_app(settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/auth/login", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?error=auth_not_configured"

    async def test_configured_redirects_to_workos_authorize_and_sets_cookies(self, client):
        c, settings = client
        resp = await c.get("/api/v1/auth/login?return_to=/app/acme/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("https://api.workos.com/user_management/authorize?")
        assert "client_id=client_test" in location
        assert "provider=authkit" in location
        assert "qora_auth_state" in resp.cookies
        assert resp.cookies["qora_auth_return"].strip('"') == "/app/acme/dashboard"

    async def test_unsafe_return_to_is_sanitized_to_root(self, client):
        c, _ = client
        resp = await c.get("/api/v1/auth/login?return_to=//evil.com", follow_redirects=False)
        assert resp.cookies["qora_auth_return"].strip('"') == "/"


class TestCallback:
    async def test_invalid_state_redirects_with_error(self, client):
        c, _ = client
        c.cookies.set("qora_auth_state", "state-a")
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-b", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?error=invalid_state"

    async def test_missing_state_cookie_redirects_with_error(self, client):
        c, _ = client
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-b", follow_redirects=False)
        assert resp.headers["location"] == "/login?error=invalid_state"

    async def test_workos_error_param_redirects_login_failed(self, client):
        c, _ = client
        c.cookies.set("qora_auth_state", "state-a")
        resp = await c.get("/api/v1/auth/callback?error=access_denied&state=state-a", follow_redirects=False)
        assert resp.headers["location"] == "/login?error=login_failed"

    @respx.mock
    async def test_organization_selection_required_redirects(self, client):
        c, _ = client
        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(400, json={"code": "organization_selection_required"})
        )
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert resp.headers["location"] == "/login?error=organization_selection_required"

    @respx.mock
    async def test_workos_network_failure_redirects_login_failed(self, client):
        c, _ = client
        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(500, json={"error": "server_error"})
        )
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert resp.headers["location"] == "/login?error=login_failed"

    @respx.mock
    async def test_no_access_when_org_unmapped(self, client):
        c, _ = client
        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(
                200,
                json={
                    "user": {"id": "user_1", "email": "nobody@nowhere.com", "email_verified": True},
                    "organization_id": "org_unknown",
                    "access_token": "h.e.s",
                },
            )
        )
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert resp.headers["location"] == "/login?error=no_access"

    @respx.mock
    async def test_success_superadmin_sets_session_cookie_and_redirects_return_to(self, client):
        c, settings = client
        c.cookies.set("qora_auth_state", "state-a")
        c.cookies.set("qora_auth_return", "/admin")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(
                200,
                json={
                    "user": {"id": "user_1", "email": "admin@qora.dev", "email_verified": True},
                    "organization_id": None,
                    "access_token": "h.e.s",
                },
            )
        )
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin"
        assert "qora_session" in resp.cookies
        assert "qora_auth_state" not in resp.cookies

    @respx.mock
    async def test_success_client_role_maps_to_own_client(self, client, db_engine):
        c, settings = client
        async with db_engine.async_session_factory() as session:
            from app.tenants.models import Client

            session.add(Client(id="acme", name="Acme", voice_id="v1", is_active=True, workos_organization_id="org_1"))
            await session.commit()

        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(
                200,
                json={
                    "user": {"id": "user_2", "email": "user@acme.com", "email_verified": True},
                    "organization_id": "org_1",
                    "access_token": "h.e.s",
                },
            )
        )
        resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        assert "qora_session" in resp.cookies


class TestMeAndLogout:
    async def test_me_with_bearer_returns_superadmin(self, client):
        c, _ = client
        resp = await c.get("/api/v1/auth/me", headers={"Authorization": "Bearer qora-test-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_method"] == "api_key"
        assert body["role"] == "superadmin"

    @respx.mock
    async def test_me_with_session_cookie(self, client):
        c, settings = client
        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(
                200,
                json={
                    "user": {
                        "id": "user_1",
                        "email": "admin@qora.dev",
                        "email_verified": True,
                        "first_name": "Ada",
                        "last_name": "Min",
                    },
                    "organization_id": None,
                    "access_token": "h.e.s",
                },
            )
        )
        login_resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        assert "qora_session" in login_resp.cookies

        resp = await c.get("/api/v1/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_method"] == "session"
        assert body["role"] == "superadmin"
        assert body["email"] == "admin@qora.dev"
        assert body["name"] == "Ada Min"

    async def test_me_without_credentials_is_401(self, client):
        c, _ = client
        resp = await c.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_logout_requires_csrf_header(self, client):
        c, _ = client
        resp = await c.post("/api/v1/auth/logout")
        assert resp.status_code == 403
        assert resp.json()["error"] == "csrf_check_failed"

    @respx.mock
    async def test_logout_revokes_session_and_returns_logout_url(self, client):
        c, settings = client
        c.cookies.set("qora_auth_state", "state-a")
        respx.post("https://api.workos.com/user_management/authenticate").mock(
            return_value=Response(
                200,
                json={
                    "user": {"id": "user_1", "email": "admin@qora.dev", "email_verified": True},
                    "organization_id": None,
                    "access_token": (
                        "eyJhbGciOiJIUzI1NiJ9."
                        "eyJzaWQiOiJzZXNzXzEyMyJ9."
                        "sig"
                    ),
                },
            )
        )
        login_resp = await c.get("/api/v1/auth/callback?code=abc&state=state-a", follow_redirects=False)
        session_cookie = login_resp.cookies["qora_session"]

        resp = await c.post("/api/v1/auth/logout", headers={"X-Qora-Client": "web"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["logout_url"] == "https://api.workos.com/user_management/sessions/logout?session_id=sess_123"

        # Session must now be revoked — a follow-up /me with the same cookie is 401.
        c.cookies.set("qora_session", session_cookie)
        me_resp = await c.get("/api/v1/auth/me")
        assert me_resp.status_code == 401

    async def test_logout_without_session_still_succeeds(self, client):
        c, _ = client
        resp = await c.post("/api/v1/auth/logout", headers={"X-Qora-Client": "web"})
        assert resp.status_code == 200
        assert resp.json()["logout_url"] is None
