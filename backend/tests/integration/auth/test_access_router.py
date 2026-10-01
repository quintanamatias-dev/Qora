"""Integration tests for /api/v1/clients/{client_id}/access (design.md §8)."""

from __future__ import annotations

import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr

from app.auth.access_router import router as access_router
from app.core.auth import CallerIdentity, require_api_key
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
        workos_api_key=SecretStr("sk_test_workos"),
        workos_client_id="client_test",
        qora_auth_redirect_uri="http://localhost:5173/api/v1/auth/callback",
    )
    base.update(overrides)
    return Settings(**base)


def _superadmin() -> CallerIdentity:
    return CallerIdentity(api_key_hash="t")


def _client_principal(*client_ids: str) -> CallerIdentity:
    return CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset(client_ids))


def _make_app(settings: Settings, principal: CallerIdentity) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.include_router(access_router, prefix="/api/v1")
    app.dependency_overrides[require_api_key] = lambda: principal
    return app


@pytest.fixture
async def superadmin_client(test_settings, db_engine):
    settings = _settings(database_url=test_settings.database_url)
    app = _make_app(settings, _superadmin())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, settings, app


async def _seed_client(db_engine, **overrides):
    from app.tenants.models import Client

    kwargs = dict(id="acme", name="Acme", voice_id="v1", is_active=True)
    kwargs.update(overrides)
    async with db_engine.async_session_factory() as session:
        session.add(Client(**kwargs))
        await session.commit()


class TestAccessRouter:
    async def test_superadmin_only_client_principal_forbidden(self, test_settings, db_engine):
        settings = _settings(database_url=test_settings.database_url)
        app = _make_app(settings, _client_principal("acme"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/clients/acme/access")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "superadmin_required"

    async def test_login_not_configured_returns_503(self, test_settings, db_engine):
        settings = _settings(database_url=test_settings.database_url, workos_client_id=None)
        app = _make_app(settings, _superadmin())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await _seed_client(db_engine)
            resp = await c.get("/api/v1/clients/acme/access")
        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "auth_not_configured"

    async def test_unknown_client_returns_404(self, superadmin_client):
        c, _, _ = superadmin_client
        resp = await c.get("/api/v1/clients/does-not-exist/access")
        assert resp.status_code == 404

    async def test_get_access_unlinked_returns_empty_state(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine)
        resp = await c.get("/api/v1/clients/acme/access")
        assert resp.status_code == 200
        assert resp.json() == {"organization_id": None, "members": [], "invitations": []}

    @respx.mock
    async def test_link_organization_creates_when_not_found(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine)

        respx.get("https://api.workos.com/organizations/external_id/acme").mock(
            return_value=Response(404, json={"error": "not_found"})
        )
        respx.post("https://api.workos.com/organizations").mock(
            return_value=Response(201, json={"id": "org_new", "name": "Acme", "external_id": "acme"})
        )
        respx.get("https://api.workos.com/user_management/users").mock(
            return_value=Response(200, json={"data": []})
        )
        respx.get("https://api.workos.com/user_management/invitations").mock(
            return_value=Response(200, json={"data": []})
        )

        resp = await c.post("/api/v1/clients/acme/access/organization")
        assert resp.status_code == 200
        assert resp.json()["organization_id"] == "org_new"

    @respx.mock
    async def test_link_organization_is_idempotent_when_already_linked(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_existing")

        respx.get("https://api.workos.com/user_management/users").mock(
            return_value=Response(200, json={"data": []})
        )
        respx.get("https://api.workos.com/user_management/invitations").mock(
            return_value=Response(200, json={"data": []})
        )

        resp = await c.post("/api/v1/clients/acme/access/organization")
        assert resp.status_code == 200
        assert resp.json()["organization_id"] == "org_existing"
        assert respx.calls.call_count == 2  # no organization lookup/create calls made

    @respx.mock
    async def test_link_organization_adopts_existing_by_external_id(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine)

        respx.get("https://api.workos.com/organizations/external_id/acme").mock(
            return_value=Response(200, json={"id": "org_found", "name": "Acme", "external_id": "acme"})
        )
        respx.get("https://api.workos.com/user_management/users").mock(
            return_value=Response(200, json={"data": []})
        )
        respx.get("https://api.workos.com/user_management/invitations").mock(
            return_value=Response(200, json={"data": []})
        )

        resp = await c.post("/api/v1/clients/acme/access/organization")
        assert resp.json()["organization_id"] == "org_found"

    async def test_invite_without_linked_organization_returns_409(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine)
        resp = await c.post("/api/v1/clients/acme/access/invitations", json={"email": "new@acme.com"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "organization_not_linked"

    @respx.mock
    async def test_invite_success(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_1")

        respx.post("https://api.workos.com/user_management/invitations").mock(
            return_value=Response(
                201,
                json={"id": "inv_1", "email": "new@acme.com", "state": "pending", "expires_at": "2026-10-01T00:00:00Z", "organization_id": "org_1"},
            )
        )
        resp = await c.post("/api/v1/clients/acme/access/invitations", json={"email": "new@acme.com"})
        assert resp.status_code == 201
        assert resp.json()["id"] == "inv_1"

    @respx.mock
    async def test_invite_workos_error_returns_502(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_1")

        respx.post("https://api.workos.com/user_management/invitations").mock(
            return_value=Response(500, json={"error": "server_error"})
        )
        resp = await c.post("/api/v1/clients/acme/access/invitations", json={"email": "new@acme.com"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "identity_provider_error"

    @respx.mock
    async def test_revoke_invitation_success(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_1")

        respx.get("https://api.workos.com/user_management/invitations/inv_1").mock(
            return_value=Response(
                200,
                json={"id": "inv_1", "email": "a@a.com", "state": "pending", "expires_at": "2026-10-01T00:00:00Z", "organization_id": "org_1"},
            )
        )
        respx.post("https://api.workos.com/user_management/invitations/inv_1/revoke").mock(
            return_value=Response(200, json={"id": "inv_1", "email": "a@a.com", "state": "revoked", "expires_at": "2026-10-01T00:00:00Z", "organization_id": "org_1"})
        )
        resp = await c.delete("/api/v1/clients/acme/access/invitations/inv_1")
        assert resp.status_code == 204

    @respx.mock
    async def test_revoke_invitation_belonging_to_other_org_is_404(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_1")

        respx.get("https://api.workos.com/user_management/invitations/inv_1").mock(
            return_value=Response(
                200,
                json={"id": "inv_1", "email": "a@a.com", "state": "pending", "expires_at": "2026-10-01T00:00:00Z", "organization_id": "org_other"},
            )
        )
        resp = await c.delete("/api/v1/clients/acme/access/invitations/inv_1")
        assert resp.status_code == 404

    @respx.mock
    async def test_revoke_on_unlinked_client_returns_409_without_touching_workos(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine)

        get_route = respx.get("https://api.workos.com/user_management/invitations/inv_1").mock(
            return_value=Response(
                200,
                json={"id": "inv_1", "email": "a@a.com", "state": "pending", "expires_at": "2026-10-01T00:00:00Z", "organization_id": None},
            )
        )
        revoke_route = respx.post("https://api.workos.com/user_management/invitations/inv_1/revoke").mock(
            return_value=Response(200, json={"id": "inv_1", "email": "a@a.com", "state": "revoked", "expires_at": "2026-10-01T00:00:00Z", "organization_id": None})
        )
        resp = await c.delete("/api/v1/clients/acme/access/invitations/inv_1")
        assert resp.status_code == 409
        assert resp.json()["detail"] == {"error": "organization_not_linked"}
        assert not get_route.called
        assert not revoke_route.called

    @respx.mock
    async def test_revoke_unknown_invitation_is_404(self, superadmin_client, db_engine):
        c, _, _ = superadmin_client
        await _seed_client(db_engine, workos_organization_id="org_1")

        respx.get("https://api.workos.com/user_management/invitations/inv_missing").mock(
            return_value=Response(404, json={"error": "not_found"})
        )
        resp = await c.delete("/api/v1/clients/acme/access/invitations/inv_missing")
        assert resp.status_code == 404
