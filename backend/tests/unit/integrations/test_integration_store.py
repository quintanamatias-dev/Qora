"""Phase 3 (client-integrations-secrets) — Tasks 3.1-3.3.

Covers:
- IntegrationStore.get() — DB-backed CRMConfig shape, None when unconfigured/disabled
- IntegrationStore cache + TTL + invalidate()
- resolve_client_secret() — DB -> env -> None resolution order (P3-D3)

Design: openspec/changes/client-integrations-secrets/design.md P3-D3, P3-D5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """DB module with a seeded quintana-seguros client, migrated schema."""
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/integration_store_test.db",
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


async def _insert_secret(session, client_id: str, name: str, plaintext: str):
    from app.core.crypto import get_secret_crypto
    from app.tenants.models import ClientSecret

    crypto = get_secret_crypto()
    assert crypto is not None, "test must set QORA_SECRETS_MASTER_KEY before calling _insert_secret"
    ciphertext, key_id = crypto.encrypt(plaintext)
    row = ClientSecret(
        client_id=client_id,
        name=name,
        ciphertext=ciphertext,
        key_id=key_id,
        created_by="test",
        updated_by="test",
    )
    session.add(row)
    await session.commit()
    return row


# ---------------------------------------------------------------------------
# 3.1 — IntegrationStore.get() returns the CRMConfig shape
# ---------------------------------------------------------------------------


async def test_integration_store_get_returns_crm_config_shape(db):
    from app.integrations.crm_config import CRMConfig
    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    async with db.async_session_factory() as session:
        store = IntegrationStore()
        config = await store.get(session, "quintana-seguros", "airtable")

    assert config is not None
    assert isinstance(config, CRMConfig)
    assert config.provider == "airtable"
    assert config.base_id == "appXXXXXXXXXXXXXX"
    assert config.table_id == "tblYYYYYYYYYYYYYY"
    assert config.match_field == "phone"
    assert config.legacy_env_var_name == "QUINTANA_AIRTABLE_API_KEY"


async def test_integration_store_get_returns_none_when_not_configured(db):
    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        store = IntegrationStore()
        config = await store.get(session, "no-such-client", "airtable")

    assert config is None


async def test_integration_store_get_returns_none_when_disabled(db):
    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros", enabled=False)

    async with db.async_session_factory() as session:
        store = IntegrationStore()
        config = await store.get(session, "quintana-seguros", "airtable")

    assert config is None


# ---------------------------------------------------------------------------
# 3.2 — cache + TTL + invalidate
# ---------------------------------------------------------------------------


async def test_integration_store_cache_hit_skips_db(db):
    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    async with db.async_session_factory() as session:
        store = IntegrationStore()
        calls = []
        original_load = store._load_from_db

        async def counting_load(sess, client_id, provider):
            calls.append(1)
            return await original_load(sess, client_id, provider)

        store._load_from_db = counting_load

        first = await store.get(session, "quintana-seguros", "airtable")
        second = await store.get(session, "quintana-seguros", "airtable")

    assert first is not None
    assert second is not None
    assert len(calls) == 1


async def test_integration_store_invalidate_forces_db_reread(db):
    from app.integrations.integration_store import IntegrationStore
    from app.tenants.models import ClientIntegration
    from sqlalchemy import update

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    store = IntegrationStore()

    async with db.async_session_factory() as session:
        first = await store.get(session, "quintana-seguros", "airtable")

    assert first.base_id == "appXXXXXXXXXXXXXX"

    async with db.async_session_factory() as session:
        await session.execute(
            update(ClientIntegration)
            .where(ClientIntegration.client_id == "quintana-seguros")
            .values(config=json.dumps(_config_payload(base_id="appUPDATED")))
        )
        await session.commit()

    # Without invalidate, the cached value would still be returned.
    async with db.async_session_factory() as session:
        still_cached = await store.get(session, "quintana-seguros", "airtable")
    assert still_cached.base_id == "appXXXXXXXXXXXXXX"

    store.invalidate("quintana-seguros")

    async with db.async_session_factory() as session:
        reread = await store.get(session, "quintana-seguros", "airtable")
    assert reread.base_id == "appUPDATED"


async def test_integration_store_ttl_expires_cache(db):
    import asyncio

    from app.integrations.integration_store import IntegrationStore
    from app.tenants.models import ClientIntegration
    from sqlalchemy import update

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    store = IntegrationStore(ttl_seconds=0.05)

    async with db.async_session_factory() as session:
        first = await store.get(session, "quintana-seguros", "airtable")
    assert first.base_id == "appXXXXXXXXXXXXXX"

    async with db.async_session_factory() as session:
        await session.execute(
            update(ClientIntegration)
            .where(ClientIntegration.client_id == "quintana-seguros")
            .values(config=json.dumps(_config_payload(base_id="appUPDATED")))
        )
        await session.commit()

    await asyncio.sleep(0.1)

    async with db.async_session_factory() as session:
        reread = await store.get(session, "quintana-seguros", "airtable")
    assert reread.base_id == "appUPDATED"


async def test_integration_store_peek_cached_misses_before_any_get(db):
    from app.integrations.integration_store import IntegrationStore

    store = IntegrationStore()
    hit, config = store.peek_cached("quintana-seguros", "airtable")

    assert hit is False
    assert config is None


async def test_integration_store_peek_cached_hits_after_get_no_db(db):
    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    store = IntegrationStore()
    async with db.async_session_factory() as session:
        await store.get(session, "quintana-seguros", "airtable")

    # Pure in-memory read — no session needed, no DB call possible.
    hit, config = store.peek_cached("quintana-seguros", "airtable")

    assert hit is True
    assert config is not None
    assert config.base_id == "appXXXXXXXXXXXXXX"


async def test_integration_store_caches_missing_integration(db):
    """A client without a CRM is cached as None so the voice hot path does
    not open a DB session on every turn."""
    from app.integrations.integration_store import IntegrationStore

    store = IntegrationStore()
    async with db.async_session_factory() as session:
        assert await store.get(session, "no-crm-client", "airtable") is None

    hit, config = store.peek_cached("no-crm-client", "airtable")

    assert hit is True
    assert config is None


async def test_integration_store_peek_cached_misses_after_ttl_expires(db):
    import asyncio

    from app.integrations.integration_store import IntegrationStore

    async with db.async_session_factory() as session:
        await _insert_integration(session, "quintana-seguros")

    store = IntegrationStore(ttl_seconds=0.05)
    async with db.async_session_factory() as session:
        await store.get(session, "quintana-seguros", "airtable")

    await asyncio.sleep(0.1)

    hit, config = store.peek_cached("quintana-seguros", "airtable")

    assert hit is False
    assert config is None


# ---------------------------------------------------------------------------
# 3.3 — resolve_client_secret: DB -> env -> None
# ---------------------------------------------------------------------------


async def test_resolve_client_secret_prefers_db_when_configured(db, monkeypatch):
    from cryptography.fernet import Fernet

    from app.integrations.secrets import resolve_client_secret

    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-value")

    async with db.async_session_factory() as session:
        await _insert_secret(session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY", "db-value")

    async with db.async_session_factory() as session:
        resolved = await resolve_client_secret(
            session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY"
        )

    assert resolved == "db-value"


async def test_resolve_client_secret_falls_back_to_env(db, monkeypatch):
    from cryptography.fernet import Fernet

    from app.integrations.secrets import resolve_client_secret

    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-value")

    async with db.async_session_factory() as session:
        resolved = await resolve_client_secret(
            session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY"
        )

    assert resolved == "env-value"


async def test_resolve_client_secret_returns_none_when_neither_resolves(db, monkeypatch):
    from cryptography.fernet import Fernet

    from app.integrations.secrets import resolve_client_secret

    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

    async with db.async_session_factory() as session:
        resolved = await resolve_client_secret(
            session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY"
        )

    assert resolved is None


async def test_resolve_client_secret_skips_db_when_master_key_absent(db, monkeypatch):
    from app.integrations.secrets import resolve_client_secret

    monkeypatch.delenv("QORA_SECRETS_MASTER_KEY", raising=False)
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-value")

    async with db.async_session_factory() as session:
        calls = []
        original_execute = session.execute

        async def counting_execute(*args, **kwargs):
            calls.append(1)
            return await original_execute(*args, **kwargs)

        session.execute = counting_execute

        resolved = await resolve_client_secret(
            session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY"
        )

    assert resolved == "env-value"
    assert len(calls) == 0
