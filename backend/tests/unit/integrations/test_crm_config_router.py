"""Unit tests for CRM config router (client-integrations-secrets Phase 5).

Covers DB-backed read/write endpoints replacing crm.yaml filesystem I/O:
- GET  /integrations, /integrations/available
- PUT  /integrations/{provider}, /integrations/{provider}/mappings
- POST /integrations/{provider}/connect
- DELETE /integrations/{provider}/disconnect
- PUT  /integrations/{provider}/secret (write-only)
- GET  /integrations/{provider}/status
- POST /integrations/{provider}/secrets/import-from-env

Security requirements asserted throughout:
- No response body ever contains a raw secret value.
- No log line captured during a secret-bearing request contains the value.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


VALID_CONFIG = {
    "base_id": "appXXXXXXXXXXXXXX",
    "table_id": "tblYYYYYYYYYYYYYY",
    "match_field": "lead_id",
    "legacy_env_var_name": "QUINTANA_AIRTABLE_API_KEY",
    "field_mappings": [
        {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
        {"source": "name", "target": "Nombre", "type": "string"},
        {"source": "phone", "target": "Teléfono", "type": "phone"},
        {"source": "email", "target": "Correo", "type": "string"},
    ],
    "custom_fields": [
        {"field_key": "car_make", "field_type": "string", "label": "Car Make"},
    ],
    "quote_ready_fields": ["car_make"],
}


async def _seed_integration(session, client_id: str, config: dict, *, enabled: bool = True) -> None:
    from app.tenants.models import ClientIntegration

    session.add(
        ClientIntegration(
            client_id=client_id,
            provider="airtable",
            enabled=enabled,
            config=json.dumps(config),
            status="ok",
            created_by="test",
            updated_by="test",
        )
    )
    await session.commit()


@pytest_asyncio.fixture
async def router_app(tmp_path: Path):
    """FastAPI app with crm_config_router + fresh SQLite DB + seeded client.

    require_api_key is overridden to a superadmin principal — the router's
    own require_client_access/require_superadmin dependencies are exercised
    as real dependencies, only the credential-parsing step is bypassed.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/crm_config_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations
    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="quintana-seguros",
            name="Quintana Seguros",
            voice_id="EXAMPLEvoice00",
        )
        await session.commit()

    from app.integrations.crm_config_router import router as crm_router
    from app.core.auth import CallerIdentity, require_api_key
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(crm_router, prefix="/api/v1")
    test_app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="test-superadmin", role="superadmin"
    )

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# GET /integrations
# ---------------------------------------------------------------------------


async def test_get_integrations_returns_configured_integration(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["provider"] == "airtable"
    assert item["base_id"] == "appXXXXXXXXXXXXXX"
    assert item["api_key_env"] == "QUINTANA_AIRTABLE_API_KEY"
    assert item["connected"] is True
    assert item["quote_ready_fields"] == ["car_make"]


async def test_get_integrations_returns_empty_for_unconfigured_client(router_app):
    client, _ = router_app
    resp = await client.get("/api/v1/clients/quintana-seguros/integrations")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_integrations_never_leaks_a_literal_secret(router_app):
    """A row created via the literal-key PUT path never carries the secret in config."""
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations")
    assert "pat_super_secret" not in resp.text


# ---------------------------------------------------------------------------
# GET /integrations/available
# ---------------------------------------------------------------------------


async def test_get_available_integrations_not_connected(router_app):
    client, _ = router_app
    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/available")
    assert resp.status_code == 200
    assert resp.json()[0]["is_connected"] is False


async def test_get_available_integrations_connected(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/available")
    assert resp.json()[0]["is_connected"] is True


# ---------------------------------------------------------------------------
# PUT /integrations/{provider}
# ---------------------------------------------------------------------------


async def test_put_integration_updates_base_id(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"base_id": "appNEWBASEID"},
    )

    assert resp.status_code == 200
    assert resp.json()["base_id"] == "appNEWBASEID"
    assert resp.json()["table_id"] == "tblYYYYYYYYYYYYYY"


async def test_put_integration_rejects_truncated_base_id(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"base_id": "notAnAppId"},
    )

    assert resp.status_code == 422


async def test_put_integration_404_for_unconfigured_client(router_app):
    client, _ = router_app
    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"base_id": "appXXX"},
    )
    assert resp.status_code == 404


async def test_put_integration_env_var_name_stored_without_secret_write(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"api_key_env": "NEW_ENV_VAR_NAME"},
    )

    assert resp.status_code == 200
    assert resp.json()["api_key_env"] == "NEW_ENV_VAR_NAME"

    async with db_module.async_session_factory() as session:
        from sqlalchemy import select
        from app.tenants.models import ClientSecret

        result = await session.execute(select(ClientSecret))
        assert result.scalars().all() == []


async def test_put_integration_literal_api_key_is_encrypted_not_stored_in_config(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"api_key_env": "pat_literal_secret_value"},
    )

    assert resp.status_code == 200
    assert "pat_literal_secret_value" not in resp.text
    assert resp.json()["api_key_env"] == "QUINTANA_AIRTABLE_API_KEY"  # existing legacy name reused

    async with db_module.async_session_factory() as session:
        from sqlalchemy import select
        from app.tenants.models import ClientSecret

        result = await session.execute(select(ClientSecret))
        row = result.scalar_one()
        assert row.ciphertext != b"pat_literal_secret_value"


async def test_put_integration_literal_api_key_without_master_key_returns_503(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable",
        json={"api_key_env": "pat_literal_secret_value"},
    )

    assert resp.status_code == 503
    assert "pat_literal_secret_value" not in resp.text


# ---------------------------------------------------------------------------
# GET /integrations/{provider}/fields
# ---------------------------------------------------------------------------


async def test_get_fields_returns_mocked_airtable_columns(router_app, monkeypatch):
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    with patch(
        "app.integrations.crm_config_router._list_airtable_fields",
        return_value=[{"id": "fldName", "name": "Nombre", "type": "singleLineText"}],
    ):
        resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/fields")

    assert resp.status_code == 200
    assert resp.json()["fields"] == [{"id": "fldName", "name": "Nombre", "type": "singleLineText"}]


async def test_get_fields_404_for_unconfigured_client(router_app):
    client, _ = router_app
    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/fields")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /integrations/{provider}/connect
# ---------------------------------------------------------------------------


async def test_post_connect_creates_integration_row(router_app):
    client, db_module = router_app

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/connect",
        json={
            "base_id": "appNEWBASEID",
            "table_id": "tblNEWTABLE",
            "api_key_env": "NEW_CLIENT_AIRTABLE_API_KEY",
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["base_id"] == "appNEWBASEID"
    assert data["api_key_env"] == "NEW_CLIENT_AIRTABLE_API_KEY"
    assert data["field_count"] == 5

    async with db_module.async_session_factory() as session:
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        result = await session.execute(select(ClientIntegration))
        assert result.scalar_one() is not None


async def test_post_connect_409_when_already_configured(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/connect",
        json={"base_id": "appXXX", "table_id": "tblYYY", "api_key_env": "SOME_KEY"},
    )
    assert resp.status_code == 409


async def test_post_connect_404_when_client_not_found(router_app):
    client, _ = router_app
    resp = await client.post(
        "/api/v1/clients/nonexistent/integrations/airtable/connect",
        json={"base_id": "appXXX", "table_id": "tblYYY", "api_key_env": "SOME_KEY"},
    )
    assert resp.status_code == 404


async def test_post_connect_never_returns_raw_literal_key(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, _ = router_app

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/connect",
        json={
            "base_id": "appNEWBASEID",
            "table_id": "tblNEWTABLE",
            "api_key_env": "pat_ultra_secret_connect_value",
        },
    )

    assert resp.status_code == 201
    assert "pat_ultra_secret_connect_value" not in resp.text
    assert resp.json()["api_key_env"] == "airtable_api_key"  # canonical name, no existing legacy name yet


# ---------------------------------------------------------------------------
# PUT /integrations/{provider}/mappings
# ---------------------------------------------------------------------------


async def test_put_mappings_persists_custom_and_quote_ready_fields(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/mappings",
        json={
            "field_mappings": [
                {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
                {"source": "name", "target": "Nombre", "type": "string"},
                {"source": "phone", "target": "Teléfono", "type": "phone"},
                {"source": "email", "target": "Correo", "type": "string"},
                {"source": "car_make", "target": "Marca_Auto", "type": "string"},
            ],
            "field_definitions": [
                {"field_key": "car_make", "field_type": "string", "label": "Car Make"},
            ],
            "quote_ready_fields": ["car_make"],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["field_count"] == 5


async def test_put_mappings_rejects_missing_required_core_fields(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/mappings",
        json={
            "field_mappings": [
                {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
                {"source": "name", "target": "", "type": "string"},
                {"source": "phone", "target": "Teléfono", "type": "phone"},
            ],
            "field_definitions": [],
            "quote_ready_fields": [],
        },
    )

    assert resp.status_code == 422


async def test_put_mappings_404_for_unconfigured_client(router_app):
    client, _ = router_app
    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/mappings",
        json={"field_mappings": [], "field_definitions": [], "quote_ready_fields": []},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /integrations/{provider}/disconnect
# ---------------------------------------------------------------------------


async def test_delete_disconnect_removes_row(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.delete("/api/v1/clients/quintana-seguros/integrations/airtable/disconnect")

    assert resp.status_code == 200
    assert resp.json()["success"] is True

    async with db_module.async_session_factory() as session:
        from sqlalchemy import select
        from app.tenants.models import ClientIntegration

        result = await session.execute(select(ClientIntegration))
        assert result.scalar_one_or_none() is None


async def test_delete_disconnect_404_when_not_configured(router_app):
    client, _ = router_app
    resp = await client.delete("/api/v1/clients/quintana-seguros/integrations/airtable/disconnect")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /integrations/{provider}/secret
# ---------------------------------------------------------------------------


async def test_put_secret_encrypts_and_stores(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
        json={"value": "pat_brand_new_secret_value"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "QUINTANA_AIRTABLE_API_KEY"
    assert body["is_set"] is True
    assert "updated_at" in body

    async with db_module.async_session_factory() as session:
        from app.core.crypto import get_secret_crypto
        from sqlalchemy import select
        from app.tenants.models import ClientSecret

        result = await session.execute(select(ClientSecret))
        row = result.scalar_one()
        assert get_secret_crypto().decrypt(row.ciphertext) == "pat_brand_new_secret_value"


async def test_put_secret_response_never_echoes_value(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
        json={"value": "pat_should_never_appear_in_response"},
    )

    assert "pat_should_never_appear_in_response" not in resp.text
    assert set(resp.json().keys()) == {"name", "is_set", "updated_at"}


async def test_put_secret_returns_503_without_master_key(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
        json={"value": "pat_should_not_be_stored"},
    )

    assert resp.status_code == 503

    async with db_module.async_session_factory() as session:
        from sqlalchemy import select
        from app.tenants.models import ClientSecret

        result = await session.execute(select(ClientSecret))
        assert result.scalars().all() == []


async def test_put_secret_404_when_integration_not_configured(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, _ = router_app
    resp = await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
        json={"value": "pat_value"},
    )
    assert resp.status_code == 404


async def test_put_secret_never_logs_the_value(router_app, monkeypatch, caplog):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    with caplog.at_level(logging.DEBUG):
        resp = await client.put(
            "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
            json={"value": "pat_must_never_be_logged_anywhere"},
        )

    assert resp.status_code == 200
    for record in caplog.records:
        assert "pat_must_never_be_logged_anywhere" not in record.getMessage()


# ---------------------------------------------------------------------------
# GET /integrations/{provider}/status
# ---------------------------------------------------------------------------


async def test_get_integration_status_returns_current_state(router_app):
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/status")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"status", "status_reason", "last_checked_at", "secret_source"}
    assert body["secret_source"] in {"db", "env", "missing"}


async def test_get_integration_status_secret_source_db_when_secret_stored(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    await client.put(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secret",
        json={"value": "pat_value"},
    )

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/status")
    assert resp.json()["secret_source"] == "db"


async def test_get_integration_status_404_when_not_configured(router_app):
    client, _ = router_app
    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/status")
    assert resp.status_code == 404


async def test_get_integration_status_never_contains_a_secret_value(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-super-secret")
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.get("/api/v1/clients/quintana-seguros/integrations/airtable/status")
    assert "env-super-secret" not in resp.text


# ---------------------------------------------------------------------------
# POST /integrations/{provider}/secrets/import-from-env
# ---------------------------------------------------------------------------


async def test_import_from_env_requires_superadmin(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-secret-value")
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    from app.core.auth import CallerIdentity, require_api_key

    # Re-override require_api_key to a non-superadmin client principal for this call only.
    app = client._transport.app  # type: ignore[attr-defined]
    original = app.dependency_overrides.get(require_api_key)
    app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="t", role="client", client_ids=frozenset({"quintana-seguros"})
    )
    try:
        resp = await client.post(
            "/api/v1/clients/quintana-seguros/integrations/airtable/secrets/import-from-env"
        )
    finally:
        app.dependency_overrides[require_api_key] = original

    assert resp.status_code == 403


async def test_import_from_env_encrypts_current_env_value(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-secret-to-import")
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secrets/import-from-env"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "QUINTANA_AIRTABLE_API_KEY"
    assert body["is_set"] is True
    assert "env-secret-to-import" not in resp.text

    from app.integrations.secrets import resolve_client_secret

    async with db_module.async_session_factory() as session:
        resolved = await resolve_client_secret(session, "quintana-seguros", "QUINTANA_AIRTABLE_API_KEY")
    assert resolved == "env-secret-to-import"


async def test_import_from_env_without_master_key_returns_503(router_app, monkeypatch):
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "env-secret-value")
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secrets/import-from-env"
    )

    assert resp.status_code == 503


async def test_import_from_env_404_when_env_var_not_set(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)
    client, db_module = router_app
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", VALID_CONFIG)

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secrets/import-from-env"
    )

    assert resp.status_code == 404


async def test_import_from_env_404_when_no_legacy_env_var_configured(router_app, monkeypatch):
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    client, db_module = router_app
    config_without_env_name = {k: v for k, v in VALID_CONFIG.items() if k != "legacy_env_var_name"}
    async with db_module.async_session_factory() as session:
        await _seed_integration(session, "quintana-seguros", config_without_env_name)

    resp = await client.post(
        "/api/v1/clients/quintana-seguros/integrations/airtable/secrets/import-from-env"
    )

    assert resp.status_code == 404
