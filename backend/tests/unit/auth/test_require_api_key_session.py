"""Unit tests for the session-cookie path of require_api_key (design.md \u00a76)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request
from pydantic import SecretStr

from app.auth.sessions import MappedIdentity, create_session
from app.auth.workos import WorkosUser
from app.core.auth import require_api_key
from app.core.config import Settings


def _settings() -> Settings:
    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
    )


def _request(method: str, cookie: str | None, extra_headers: dict[str, str] | None = None) -> Request:
    headers = []
    if extra_headers:
        headers.extend((k.lower().encode(), v.encode()) for k, v in extra_headers.items())
    scope = {
        "type": "http",
        "method": method,
        "path": "/api/v1/clients",
        "headers": headers,
        "query_string": b"",
    }
    if cookie:
        scope["headers"].append((b"cookie", f"qora_session={cookie}".encode()))
    return Request(scope)


async def _seed_active_client(db_session, client_id: str = "acme") -> None:
    from app.tenants.models import Client

    db_session.add(Client(id=client_id, name=client_id.title(), voice_id="v1", is_active=True))
    await db_session.commit()


class TestRequireApiKeySessionPath:
    async def test_valid_session_cookie_returns_client_identity(self, db_session):
        await _seed_active_client(db_session)
        user = WorkosUser(id="u1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="client", client_ids=["acme"])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id="s1")

        request = _request("GET", raw_token)
        result = await require_api_key(request, _settings(), db_session)

        assert result.auth_method == "session"
        assert result.role == "client"
        assert result.client_ids == frozenset({"acme"})
        assert result.email == "user@acme.com"

    async def test_missing_session_raises_401(self, db_session):
        request = _request("GET", "does-not-exist")
        with pytest.raises(HTTPException) as exc:
            await require_api_key(request, _settings(), db_session)
        assert exc.value.status_code == 401
        assert exc.value.detail["error"] == "authentication_required"

    async def test_no_credentials_at_all_raises_401(self, db_session):
        request = _request("GET", None)
        with pytest.raises(HTTPException) as exc:
            await require_api_key(request, _settings(), db_session)
        assert exc.value.status_code == 401

    async def test_unsafe_method_without_csrf_header_is_403(self, db_session):
        await _seed_active_client(db_session)
        user = WorkosUser(id="u1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="client", client_ids=["acme"])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)

        request = _request("POST", raw_token)
        with pytest.raises(HTTPException) as exc:
            await require_api_key(request, _settings(), db_session)
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "csrf_check_failed"

    async def test_unsafe_method_with_csrf_header_succeeds(self, db_session):
        await _seed_active_client(db_session)
        user = WorkosUser(id="u1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="client", client_ids=["acme"])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)

        request = _request("POST", raw_token, {"X-Qora-Client": "web"})
        result = await require_api_key(request, _settings(), db_session)
        assert result.auth_method == "session"

    async def test_safe_method_does_not_require_csrf_header(self, db_session):
        user = WorkosUser(id="u1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="superadmin", client_ids=[])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)

        request = _request("GET", raw_token)
        result = await require_api_key(request, _settings(), db_session)
        assert result.is_superadmin is True

    async def test_bearer_header_takes_priority_over_cookie(self, db_session):
        await _seed_active_client(db_session)
        user = WorkosUser(id="u1", email="user@acme.com", email_verified=True)
        identity = MappedIdentity(role="client", client_ids=["acme"])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)

        request = _request("GET", raw_token, {"Authorization": "Bearer qora-test-key"})
        result = await require_api_key(request, _settings(), db_session)
        assert result.auth_method == "api_key"
