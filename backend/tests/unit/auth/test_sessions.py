"""Unit tests for app.auth.sessions (design.md §4, §5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import SecretStr

from app.auth.sessions import (
    MappedIdentity,
    NoAccessError,
    create_session,
    hash_token,
    lookup_session,
    map_identity,
    revoke_session,
    sanitize_return_to,
)
from app.auth.workos import WorkosUser
from app.core.config import Settings


# ---------------------------------------------------------------------------
# sanitize_return_to
# ---------------------------------------------------------------------------


class TestSanitizeReturnTo:
    def test_none_falls_back_to_root(self):
        assert sanitize_return_to(None) == "/"

    def test_empty_falls_back_to_root(self):
        assert sanitize_return_to("") == "/"

    def test_valid_path_is_kept(self):
        assert sanitize_return_to("/app/acme/dashboard") == "/app/acme/dashboard"

    def test_missing_leading_slash_falls_back(self):
        assert sanitize_return_to("evil.com/path") == "/"

    def test_protocol_relative_falls_back(self):
        assert sanitize_return_to("//evil.com") == "/"

    def test_backslash_falls_back(self):
        assert sanitize_return_to("/\\evil.com") == "/"

    def test_api_path_falls_back(self):
        assert sanitize_return_to("/api/v1/clients") == "/"

    def test_too_long_falls_back(self):
        assert sanitize_return_to("/" + "a" * 512) == "/"

    def test_max_length_is_kept(self):
        path = "/" + "a" * 511
        assert sanitize_return_to(path) == path


# ---------------------------------------------------------------------------
# map_identity
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    base = dict(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
        qora_superadmin_emails="admin@qora.dev, Owner@Qora.dev",
    )
    base.update(overrides)
    return Settings(**base)


class TestMapIdentity:
    @pytest.mark.asyncio
    async def test_verified_superadmin_email_maps_to_superadmin(self, db_session):
        user = WorkosUser(id="user_1", email="admin@qora.dev", email_verified=True)
        identity = await map_identity(db_session, _settings(), user=user, organization_id=None)
        assert identity.role == "superadmin"
        assert identity.client_ids == []

    @pytest.mark.asyncio
    async def test_superadmin_email_match_is_case_insensitive(self, db_session):
        user = WorkosUser(id="user_1", email="OWNER@QORA.DEV", email_verified=True)
        identity = await map_identity(db_session, _settings(), user=user, organization_id=None)
        assert identity.role == "superadmin"

    @pytest.mark.asyncio
    async def test_unverified_superadmin_email_is_rejected(self, db_session):
        user = WorkosUser(id="user_1", email="admin@qora.dev", email_verified=False)
        with pytest.raises(NoAccessError):
            await map_identity(db_session, _settings(), user=user, organization_id=None)

    @pytest.mark.asyncio
    async def test_active_client_org_maps_to_client_role(self, db_session):
        from app.tenants.models import Client

        client = Client(id="acme", name="Acme", voice_id="v1", is_active=True, workos_organization_id="org_1")
        db_session.add(client)
        await db_session.commit()

        user = WorkosUser(id="user_2", email="user@acme.com", email_verified=True)
        identity = await map_identity(db_session, _settings(), user=user, organization_id="org_1")
        assert identity.role == "client"
        assert identity.client_ids == ["acme"]

    @pytest.mark.asyncio
    async def test_inactive_client_org_has_no_access(self, db_session):
        from app.tenants.models import Client

        client = Client(id="inactive-co", name="Inactive Co", voice_id="v1", is_active=False, workos_organization_id="org_2")
        db_session.add(client)
        await db_session.commit()

        user = WorkosUser(id="user_3", email="user@inactive.com", email_verified=True)
        with pytest.raises(NoAccessError):
            await map_identity(db_session, _settings(), user=user, organization_id="org_2")

    @pytest.mark.asyncio
    async def test_unmapped_org_has_no_access(self, db_session):
        user = WorkosUser(id="user_4", email="user@nowhere.com", email_verified=True)
        with pytest.raises(NoAccessError):
            await map_identity(db_session, _settings(), user=user, organization_id="org_unknown")

    @pytest.mark.asyncio
    async def test_no_organization_and_not_superadmin_has_no_access(self, db_session):
        user = WorkosUser(id="user_5", email="random@nowhere.com", email_verified=True)
        with pytest.raises(NoAccessError):
            await map_identity(db_session, _settings(), user=user, organization_id=None)


# ---------------------------------------------------------------------------
# session create / lookup / revoke
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_create_then_lookup_returns_valid_session(self, db_session):
        user = WorkosUser(id="user_1", email="a@b.com", email_verified=True, first_name="Ann", last_name="Bee")
        identity = MappedIdentity(role="client", client_ids=["acme"])
        raw_token = await create_session(
            db_session, _settings(), user=user, identity=identity, workos_session_id="sess_x"
        )
        assert raw_token

        found = await lookup_session(db_session, raw_token)
        assert found is not None
        assert found.role == "client"
        assert found.email == "a@b.com"
        assert found.display_name == "Ann Bee"
        assert found.token_hash == hash_token(raw_token)

    @pytest.mark.asyncio
    async def test_raw_token_is_never_the_stored_hash(self, db_session):
        user = WorkosUser(id="user_1", email="a@b.com", email_verified=True)
        identity = MappedIdentity(role="superadmin", client_ids=[])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)
        found = await lookup_session(db_session, raw_token)
        assert found.token_hash != raw_token

    @pytest.mark.asyncio
    async def test_lookup_unknown_token_returns_none(self, db_session):
        assert await lookup_session(db_session, "does-not-exist") is None

    @pytest.mark.asyncio
    async def test_lookup_expired_session_returns_none(self, db_session):
        from app.auth.models import AuthSession

        now = datetime.now(timezone.utc)
        raw_token = "expired-token"
        db_session.add(
            AuthSession(
                token_hash=hash_token(raw_token),
                workos_user_id="user_x",
                email="x@x.com",
                role="client",
                client_ids="[]",
                created_at=now - timedelta(hours=13),
                expires_at=now - timedelta(hours=1),
            )
        )
        await db_session.commit()
        assert await lookup_session(db_session, raw_token) is None

    @pytest.mark.asyncio
    async def test_lookup_revoked_session_returns_none(self, db_session):
        user = WorkosUser(id="user_1", email="a@b.com", email_verified=True)
        identity = MappedIdentity(role="superadmin", client_ids=[])
        raw_token = await create_session(db_session, _settings(), user=user, identity=identity, workos_session_id=None)

        await revoke_session(db_session, raw_token)
        assert await lookup_session(db_session, raw_token) is None

    @pytest.mark.asyncio
    async def test_revoke_unknown_token_is_noop(self, db_session):
        assert await revoke_session(db_session, "unknown") is None
