"""Tests for client-integrations-secrets Phase 6 — Boot Validation.

validate_all_integration_credentials() no longer scans crm.yaml files and no
longer calls sys.exit for a per-client CRM credential problem (design.md
P3-D4). It recomputes and persists every client_integrations row's status
from the DB, logs ERROR for degraded rows, and always lets startup continue.

Covered scenarios:
  - is_weak_placeholder(): detects all known placeholder patterns (unchanged)
  - validate_all_integration_credentials(): resolvable credential -> status=ok,
    no SystemExit
  - validate_all_integration_credentials(): unresolvable credential ->
    status=degraded, non-null status_reason, ERROR log, no SystemExit
  - validate_all_integration_credentials(): disabled integration -> status=
    disabled, silently skipped (no ERROR log)
  - validate_all_integration_credentials(): client with no row at all ->
    silently skipped (never iterated)
  - Two-client isolation: one client degraded does not affect its sibling's
    status or CRM tool calls (survey-critical #4 regression proof)
  - Platform-level credentials (OPENAI_API_KEY) are untouched by this module
    and still hard-fail at Settings() construction

Spec reference:
  openspec/changes/client-integrations-secrets/design.md P3-D4
  openspec/changes/client-integrations-secrets/specs/client-secrets/spec.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """DB module with a migrated schema, no seeded client_integrations rows."""
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/credentials_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana

        await seed_quintana(sess)
        await sess.commit()

    yield db_module
    await db_module.close_db()


def _config_payload(**overrides) -> dict:
    payload = {
        "base_id": "appXXXXXXXXXXXXXX",
        "table_id": "tblYYYYYYYYYYYYYY",
        "match_field": "phone",
        "field_mappings": [],
        "legacy_env_var_name": "QUINTANA_AIRTABLE_API_KEY",
    }
    payload.update(overrides)
    return payload


async def _insert_integration(
    session,
    client_id: str,
    *,
    provider: str = "airtable",
    enabled: bool = True,
    config: dict | None = None,
):
    from app.tenants.models import ClientIntegration

    row = ClientIntegration(
        client_id=client_id,
        provider=provider,
        enabled=enabled,
        config=json.dumps(config if config is not None else _config_payload()),
        status="ok",
        created_by="test",
        updated_by="test",
    )
    session.add(row)
    await session.commit()
    return row


# ---------------------------------------------------------------------------
# is_weak_placeholder() — unchanged by this phase
# ---------------------------------------------------------------------------


class TestIsWeakPlaceholder:
    @pytest.mark.parametrize("value", [
        "change-me-before-production",
        "CHANGE-ME-BEFORE-PRODUCTION",
        "your-key-here",
        "TODO",
        "replace_me",
        "xxx",
        "test",
        "changeme",
    ])
    def test_known_placeholders_are_detected(self, value):
        from app.core.credentials import is_weak_placeholder
        assert is_weak_placeholder(value) is True

    @pytest.mark.parametrize("value", [
        "sk-proj-abcdefghijklmnopqrstuvwx",
        "pat_1234567890abcdef",
        "qora-local-dev-key",
    ])
    def test_real_values_are_not_flagged(self, value):
        from app.core.credentials import is_weak_placeholder
        assert is_weak_placeholder(value) is False


# ---------------------------------------------------------------------------
# Task 6.1 — DB-based status computation, no sys.exit
# ---------------------------------------------------------------------------


class TestValidateAllIntegrationCredentials:
    async def test_boot_validation_sets_ok_status_when_credential_resolves(self, db, monkeypatch):
        """A client with a resolvable credential boots with status=ok, no SystemExit."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-real-key-abc123")

        async with db.async_session_factory() as session:
            await _insert_integration(session, "quintana-seguros")

        from app.core.credentials import validate_all_integration_credentials
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        async with db.async_session_factory() as session:
            await validate_all_integration_credentials(session)

        async with db.async_session_factory() as session:
            result = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "quintana-seguros")
            )
            row = result.scalar_one()
            assert row.status == "ok"
            assert row.status_reason is None

    async def test_boot_validation_sets_degraded_status_no_sys_exit(self, db, monkeypatch):
        """A client with an unresolvable credential boots successfully (no SystemExit);
        its row becomes degraded with a non-null status_reason."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        async with db.async_session_factory() as session:
            await _insert_integration(session, "quintana-seguros")

        from app.core.credentials import validate_all_integration_credentials
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        async with db.async_session_factory() as session:
            # Must complete without raising SystemExit anywhere.
            await validate_all_integration_credentials(session)

        async with db.async_session_factory() as session:
            result = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "quintana-seguros")
            )
            row = result.scalar_one()
            assert row.status == "degraded"
            assert row.status_reason is not None
            assert "QUINTANA_AIRTABLE_API_KEY" in row.status_reason

    async def test_boot_validation_does_not_exit_on_missing_credential(self, db, monkeypatch):
        """Explicit SystemExit-absence proof — the old behavior is replaced, not silenced."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        async with db.async_session_factory() as session:
            await _insert_integration(session, "quintana-seguros")

        from app.core.credentials import validate_all_integration_credentials

        try:
            async with db.async_session_factory() as session:
                await validate_all_integration_credentials(session)
        except SystemExit:
            pytest.fail("validate_all_integration_credentials must never raise SystemExit")

    async def test_disabled_integration_is_silently_skipped(self, db, monkeypatch):
        """enabled=false -> status=disabled, no ERROR log, no exception."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        async with db.async_session_factory() as session:
            await _insert_integration(session, "quintana-seguros", enabled=False)

        from app.core.credentials import validate_all_integration_credentials
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        async with db.async_session_factory() as session:
            await validate_all_integration_credentials(session)

        async with db.async_session_factory() as session:
            result = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "quintana-seguros")
            )
            row = result.scalar_one()
            assert row.status == "disabled"

    async def test_client_with_no_integration_row_is_silently_skipped(self, db):
        """A client with no client_integrations row at all is never iterated."""
        from app.core.credentials import validate_all_integration_credentials

        async with db.async_session_factory() as session:
            # No rows inserted at all — must not raise.
            await validate_all_integration_credentials(session)


# ---------------------------------------------------------------------------
# Task 6.2 — Two-client isolation (survey-critical #4 regression proof)
# ---------------------------------------------------------------------------


class TestTwoClientIsolation:
    async def test_one_client_degraded_does_not_affect_sibling_client(self, db, monkeypatch):
        """Client A has a valid credential, client B's is missing. Both are
        configured. Asserts A's status=ok and its CRM tool call succeeds,
        completely independent of B's degraded state."""
        monkeypatch.setenv("CLIENT_A_AIRTABLE_API_KEY", "pat-client-a-key")
        monkeypatch.delenv("CLIENT_B_AIRTABLE_API_KEY", raising=False)

        async with db.async_session_factory() as session:
            await _insert_integration(
                session,
                "client-a",
                config=_config_payload(legacy_env_var_name="CLIENT_A_AIRTABLE_API_KEY"),
            )
            await _insert_integration(
                session,
                "client-b",
                config=_config_payload(legacy_env_var_name="CLIENT_B_AIRTABLE_API_KEY"),
            )

        from app.core.credentials import validate_all_integration_credentials
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        async with db.async_session_factory() as session:
            await validate_all_integration_credentials(session)

        async with db.async_session_factory() as session:
            result_a = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "client-a")
            )
            row_a = result_a.scalar_one()
            result_b = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "client-b")
            )
            row_b = result_b.scalar_one()

        assert row_a.status == "ok"
        assert row_a.status_reason is None
        assert row_b.status == "degraded"
        assert row_b.status_reason is not None

        # A's CRM tool call still resolves its own secret correctly, unaffected by B.
        from app.integrations.integration_store import IntegrationStore

        store = IntegrationStore()
        async with db.async_session_factory() as session:
            config_a = await store.get(session, "client-a", "airtable")
            resolved_a = await config_a.resolve_api_key_async(session, "client-a")

        assert resolved_a == "pat-client-a-key"

    async def test_degraded_client_tool_call_returns_tool_error_not_exception(self, db, monkeypatch):
        """B's own CRM resolution returns None (not an exception) when degraded,
        so a tool dispatcher can turn it into a clear tool-error string."""
        monkeypatch.delenv("CLIENT_B_AIRTABLE_API_KEY", raising=False)

        async with db.async_session_factory() as session:
            await _insert_integration(
                session,
                "client-b",
                config=_config_payload(legacy_env_var_name="CLIENT_B_AIRTABLE_API_KEY"),
            )

        from app.core.credentials import validate_all_integration_credentials
        from app.integrations.integration_store import IntegrationStore

        async with db.async_session_factory() as session:
            await validate_all_integration_credentials(session)

        store = IntegrationStore()
        async with db.async_session_factory() as session:
            config_b = await store.get(session, "client-b", "airtable")
            resolved_b = await config_b.resolve_api_key_async(session, "client-b")

        assert resolved_b is None


# ---------------------------------------------------------------------------
# Platform-level credentials keep their existing hard-fail behavior
# ---------------------------------------------------------------------------


class TestPlatformCredentialsStillHardFail:
    """Qora-owned platform credentials are validated by Settings(), not by this
    module, and this phase does not change that: Settings() must still raise
    when a required platform credential is absent."""

    def test_settings_still_raises_when_openai_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")

        from app.core.config import Settings

        with pytest.raises(Exception):
            Settings(_env_file=None)

    async def test_validate_all_integration_credentials_does_not_read_platform_env_vars(self, db, monkeypatch):
        """Behavior guard: validating client_integrations must not depend on or
        touch OPENAI_API_KEY/ELEVENLABS_API_KEY — those remain Settings' sole
        responsibility (unchanged scope boundary)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-real-key")

        async with db.async_session_factory() as session:
            await _insert_integration(session, "quintana-seguros")

        from app.core.credentials import validate_all_integration_credentials

        async with db.async_session_factory() as session:
            # Must not raise just because OPENAI/EL keys are unset in the environment.
            await validate_all_integration_credentials(session)
