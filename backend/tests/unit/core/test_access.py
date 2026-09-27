"""Tests for the tenant access layer (multi-tenant-readiness WU1).

Spec: openspec/changes/multi-tenant-readiness/specs/tenant-access/spec.md
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.access import (
    ensure_resource_access,
    require_client_access,
    require_superadmin,
)
from app.core.auth import CallerIdentity, require_api_key


def _client_principal(*client_ids: str) -> CallerIdentity:
    return CallerIdentity(api_key_hash="t", role="client", client_ids=frozenset(client_ids))


def _superadmin() -> CallerIdentity:
    return CallerIdentity(api_key_hash="t")


# ---------------------------------------------------------------------------
# CallerIdentity
# ---------------------------------------------------------------------------


class TestCallerIdentity:
    def test_default_principal_is_superadmin(self):
        caller = CallerIdentity(api_key_hash="abc")
        assert caller.is_superadmin is True
        assert caller.can_access("any-tenant") is True

    def test_client_principal_accesses_only_its_tenants(self):
        caller = _client_principal("tenant-a")
        assert caller.is_superadmin is False
        assert caller.can_access("tenant-a") is True
        assert caller.can_access("tenant-b") is False

    def test_tenant_match_is_case_insensitive(self):
        caller = _client_principal("tenant-a")
        assert caller.can_access("TENANT-A") is True

    def test_client_principal_never_accesses_missing_tenant(self):
        assert _client_principal("tenant-a").can_access(None) is False
        assert _client_principal("tenant-a").can_access("") is False

    def test_rejects_unknown_role(self):
        with pytest.raises(ValueError):
            CallerIdentity(api_key_hash="t", role="owner")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ensure_resource_access
# ---------------------------------------------------------------------------


class TestEnsureResourceAccess:
    def test_allows_own_resource(self):
        ensure_resource_access(_client_principal("tenant-a"), "tenant-a")

    def test_foreign_resource_is_reported_as_not_found(self):
        with pytest.raises(HTTPException) as exc:
            ensure_resource_access(_client_principal("tenant-a"), "tenant-b", detail="Lead not found")
        assert exc.value.status_code == 404
        assert exc.value.detail == "Lead not found"

    def test_superadmin_accesses_everything(self):
        ensure_resource_access(_superadmin(), "tenant-b")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def _app(principal: CallerIdentity) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[require_api_key] = lambda: principal

    @app.get("/clients/{client_id}/thing")
    async def by_path(caller: CallerIdentity = Depends(require_client_access)):
        return {"ok": True, "superadmin": caller.is_superadmin}

    @app.get("/things")
    async def by_query(caller: CallerIdentity = Depends(require_client_access)):
        return {"ok": True}

    @app.get("/admin-only")
    async def admin_only(caller: CallerIdentity = Depends(require_superadmin)):
        return {"ok": True}

    return app


async def _get(principal: CallerIdentity, path: str):
    async with AsyncClient(transport=ASGITransport(app=_app(principal)), base_url="http://t") as c:
        return await c.get(path)


class TestRequireClientAccess:
    async def test_own_tenant_in_path_is_allowed(self):
        resp = await _get(_client_principal("tenant-a"), "/clients/tenant-a/thing")
        assert resp.status_code == 200

    async def test_foreign_tenant_in_path_is_forbidden(self):
        resp = await _get(_client_principal("tenant-a"), "/clients/tenant-b/thing")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "tenant_forbidden"

    async def test_foreign_tenant_in_query_is_forbidden(self):
        resp = await _get(_client_principal("tenant-a"), "/things?client_id=tenant-b")
        assert resp.status_code == 403

    async def test_own_tenant_in_query_is_allowed(self):
        resp = await _get(_client_principal("tenant-a"), "/things?client_id=tenant-a")
        assert resp.status_code == 200

    async def test_superadmin_accesses_any_tenant(self):
        resp = await _get(_superadmin(), "/clients/tenant-b/thing")
        assert resp.status_code == 200
        assert resp.json()["superadmin"] is True


class TestRequireSuperadmin:
    async def test_client_principal_is_forbidden(self):
        resp = await _get(_client_principal("tenant-a"), "/admin-only")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "superadmin_required"

    async def test_superadmin_is_allowed(self):
        resp = await _get(_superadmin(), "/admin-only")
        assert resp.status_code == 200
