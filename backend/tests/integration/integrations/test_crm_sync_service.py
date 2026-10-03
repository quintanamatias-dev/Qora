"""Integration tests for crm_sync_service.sync_lead() — TDD RED phase.

Covers spec scenarios:
- CS-1: sync only fires after savepoint commits (not sync service responsibility — tested in Phase 3)
- CS-2: sync runs async / fire-and-forget (tested in Phase 3 summarizer tests)
- CS-3: successful path — DB lead → config → mapped payload → upsert
- CS-4: retry on transient error (tested at adapter unit level in test_airtable_adapter.py)
- CS-5: all retries exhausted — error swallowed in sync_lead, NOT propagated
- CS-6: idempotent upsert (adapter-level behavior; integration proves mapping is consistent)
- FM-4: client without crm.yaml → no-op (silent skip)
- FM-3: missing env var at resolve time → CredentialResolutionError caught and logged

Design constraints (design.md):
- sync_lead reads lead from SQLite (authoritative source), never from Airtable
- adapter is mocked — no live Airtable calls
- CRM config is seeded as a client_integrations row (IntegrationStore)

Test layer: Integration (db_session fixture + mocked adapter + seeded client_integrations rows)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.integration_store import IntegrationStore
from app.tenants.models import ClientIntegration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_crm_integration(session, client_id: str, data: dict) -> None:
    """Seed a client_integrations row shaped like the given crm.yaml dict
    (client-integrations-secrets Phase 4.2: replaces writing a tmp crm.yaml file).
    """
    config = {k: v for k, v in data.items() if k not in ("provider", "api_key_env")}
    if "api_key_env" in data:
        config["legacy_env_var_name"] = data["api_key_env"]
    session.add(
        ClientIntegration(
            client_id=client_id,
            provider=data.get("provider", "airtable"),
            enabled=True,
            config=json.dumps(config),
            status="ok",
            created_by="test",
            updated_by="test",
        )
    )
    await session.flush()


def _fresh_store_patch():
    """Patch crm_sync_service.get_default_store with a brand-new IntegrationStore
    instance (no cache) so each test is isolated from the process-wide singleton.
    """
    return patch(
        "app.integrations.crm_sync_service.get_default_store",
        return_value=IntegrationStore(),
    )


def _valid_crm_yaml_data(api_key_env: str = "TEST_CRM_API_KEY") -> dict:
    return {
        "provider": "airtable",
        "base_id": "appTESTBASEIDXXX",
        "table_id": "tblTESTTABLEIDYY",
        "api_key_env": api_key_env,
        "match_field": "Teléfono",
        "field_mappings": [
            {"source": "name", "target": "Nombre", "type": "string", "required": True},
            {"source": "phone", "target": "Teléfono", "type": "phone", "required": True},
            {"source": "status", "target": "Estado", "type": "string"},
        ],
    }


async def _seed_test_client(session, client_id: str, name: str) -> None:
    """Seed a minimal test client with the required voice_id field."""
    from app.tenants.service import create_client

    await create_client(
        session,
        id=client_id,
        name=name,
        voice_id="EXAMPLEvoiceID00",
    )
    await session.flush()


# ---------------------------------------------------------------------------
# 2.3-A: Successful sync — DB lead → config → mapped upsert (CS-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_success_calls_upsert_with_mapped_payload(
    db_session, tmp_path: Path, monkeypatch
):
    """CS-3: sync_lead reads lead from DB, maps fields, calls adapter.upsert_record."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    # Set up tenant + lead
    await _seed_test_client(db_session, "test-client-001", "Test Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-001",
        name="Ana García",
        phone="+5491155550101",
    )
    await db_session.flush()

    # Set up crm.yaml
    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test_secret")
    await _seed_crm_integration(db_session, "test-client-001", _valid_crm_yaml_data())

    # Mock adapter to capture upsert call
    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recSUCCESS0001")


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="test-client-001",
            lead_id=lead.id,
            db_session=db_session,
        )

    # Adapter was called with mapped payload
    mock_adapter.upsert_record.assert_called_once()
    call_kwargs = mock_adapter.upsert_record.call_args
    assert call_kwargs is not None

    # upsert_record is called with keyword args
    payload = call_kwargs.kwargs["payload"]
    assert "Nombre" in payload
    assert payload["Nombre"] == "Ana García"
    assert "Teléfono" in payload
    assert payload["Teléfono"] == "+5491155550101"


@pytest.mark.asyncio
async def test_sync_lead_success_uses_config_match_field(
    db_session, tmp_path: Path, monkeypatch
):
    """CS-3: sync_lead passes config.match_field to adapter.upsert_record."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-002", "Test Client 2")
    lead = await create_lead(
        db_session,
        client_id="test-client-002",
        name="Roberto Silva",
        phone="+5491155550101",
    )
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test_secret")
    await _seed_crm_integration(db_session, "test-client-002", _valid_crm_yaml_data())

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recMATCH0001")


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="test-client-002",
            lead_id=lead.id,
            db_session=db_session,
        )

    call_kwargs = mock_adapter.upsert_record.call_args
    match_field = call_kwargs.kwargs["match_field"]
    assert match_field == "Teléfono"


# ---------------------------------------------------------------------------
# 2.3-B: Missing crm.yaml → no-op, no error (FM-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_no_crm_yaml_is_silent_noop(
    db_session, tmp_path: Path, monkeypatch
):
    """FM-4: client with no crm.yaml → sync_lead returns without any error or call."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-noop", "No CRM Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-noop",
        name="Test Lead",
        phone="+5491155550101",
    )
    await db_session.flush()

    # No crm.yaml created for this client

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock()

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Must NOT raise
        await sync_lead(
            client_id="test-client-noop",
            lead_id=lead.id,
            db_session=db_session,
        )

    # Adapter was never invoked
    mock_adapter.upsert_record.assert_not_called()


# ---------------------------------------------------------------------------
# 2.3-C: Lead not found in DB → no upsert (defensive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_unknown_lead_id_is_noop(
    db_session, tmp_path: Path, monkeypatch
):
    """sync_lead with a non-existent lead_id does nothing (does not raise)."""
    from app.integrations.crm_sync_service import sync_lead

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test")

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock()

    # Config says there IS a crm.yaml — but lead doesn't exist
    await _seed_crm_integration(db_session, "ghost-client", _valid_crm_yaml_data())


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Must NOT raise
        await sync_lead(
            client_id="ghost-client",
            lead_id="nonexistent-lead-999",
            db_session=db_session,
        )

    mock_adapter.upsert_record.assert_not_called()


# ---------------------------------------------------------------------------
# 2.3-D: Credential resolution failure — error isolated (FM-3, CS-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_credential_error_is_swallowed(
    db_session, tmp_path: Path, monkeypatch
):
    """FM-3/CS-5: an unresolvable credential (P3-D4 degraded) is caught — does not propagate."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-cred", "Cred Test Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-cred",
        name="Test Lead",
        phone="+5491155550101",
    )
    await db_session.flush()

    # Config loads successfully but the credential never resolves (DB -> env
    # -> None per P3-D3) — degraded, not a crash.
    mock_config = MagicMock()
    mock_config.resolve_api_key_async = AsyncMock(return_value=None)
    mock_config.provider = "airtable"
    mock_config.base_id = "appXXX"
    mock_config.table_id = "tblYYY"
    mock_config.match_field = "Teléfono"
    mock_config.field_mappings = []

    mock_store = MagicMock()
    mock_store.get = AsyncMock(return_value=mock_config)

    with patch(
        "app.integrations.crm_sync_service.get_default_store",
        return_value=mock_store,
    ):
        # Must NOT raise — CRM errors are fully isolated
        await sync_lead(
            client_id="test-client-cred",
            lead_id=lead.id,
            db_session=db_session,
        )

    # resolve_api_key_async was called (we tried to resolve)
    mock_config.resolve_api_key_async.assert_called_once()


# ---------------------------------------------------------------------------
# 2.3-E: Adapter upsert failure — error isolated, not re-raised (CS-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_adapter_error_is_swallowed(
    db_session, tmp_path: Path, monkeypatch
):
    """CS-5: AirtableUpsertError from adapter is caught — does not propagate."""
    from app.integrations.crm_sync_service import sync_lead
    from app.integrations.adapters.airtable import AirtableUpsertError
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-err", "Error Test Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-err",
        name="Error Lead",
        phone="+5491155550101",
    )
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test")
    await _seed_crm_integration(db_session, "test-client-err", _valid_crm_yaml_data())

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(
        side_effect=AirtableUpsertError("Airtable failed after 3 retries")
    )


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Must NOT raise — CRM failures are isolated from call analysis
        await sync_lead(
            client_id="test-client-err",
            lead_id=lead.id,
            db_session=db_session,
        )

    mock_adapter.upsert_record.assert_called_once()


# ---------------------------------------------------------------------------
# 2.3-E2: Cross-tenant guard — lead belongs to a different client (no upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_cross_client_mismatch_does_not_upsert(
    db_session, tmp_path: Path, monkeypatch
):
    """Tenant isolation: a lead owned by client A must NEVER be synced when
    sync_lead is invoked for client B, even if both have valid crm.yaml configs.

    get_lead() looks up by id only, so the service must verify lead ownership
    before pushing to the CRM — otherwise client A's data leaks into client B's
    Airtable base.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    # Lead belongs to client A.
    await _seed_test_client(db_session, "tenant-a", "Tenant A")
    await _seed_test_client(db_session, "tenant-b", "Tenant B")
    lead = await create_lead(
        db_session,
        client_id="tenant-a",
        name="Owned By A",
        phone="+5491155550101",
    )
    await db_session.flush()

    # client B has a perfectly valid crm.yaml — the only thing stopping the
    # sync is the ownership check.
    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test_secret")
    await _seed_crm_integration(db_session, "tenant-b", _valid_crm_yaml_data())

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recSHOULDNOTHAPPEN")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Invoke for tenant-b with tenant-a's lead id — must be a no-op.
        await sync_lead(
            client_id="tenant-b",
            lead_id=lead.id,
            db_session=db_session,
        )

    # The cross-tenant lead must NOT be pushed to client B's CRM.
    mock_adapter.upsert_record.assert_not_called()


@pytest.mark.asyncio
async def test_sync_lead_matching_client_does_upsert(
    db_session, tmp_path: Path, monkeypatch
):
    """Control case for the tenant guard: when client_id matches the lead's
    owner, the upsert proceeds normally."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "tenant-match", "Tenant Match")
    lead = await create_lead(
        db_session,
        client_id="tenant-match",
        name="Owned Correctly",
        phone="+5491155550101",
    )
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test_secret")
    await _seed_crm_integration(db_session, "tenant-match", _valid_crm_yaml_data())

    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recMATCHOK0001")


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="tenant-match",
            lead_id=lead.id,
            db_session=db_session,
        )

    mock_adapter.upsert_record.assert_called_once()


# ---------------------------------------------------------------------------
# 2.3-G: Unexpected pre-upsert failure (e.g. adapter factory) is isolated (CS-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_factory_error_is_swallowed(
    db_session, tmp_path: Path, monkeypatch
):
    """CS-5: an unexpected error from make_adapter (or any pre-upsert step) must
    be caught and logged — never propagated to the caller."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-factory", "Factory Test")
    lead = await create_lead(
        db_session,
        client_id="test-client-factory",
        name="Factory Lead",
        phone="+5491155550101",
    )
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test_secret")
    await _seed_crm_integration(db_session, "test-client-factory", _valid_crm_yaml_data())


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        side_effect=RuntimeError("factory blew up unexpectedly"),
    ):
        # Must NOT raise — unexpected pre-upsert failures are isolated.
        await sync_lead(
            client_id="test-client-factory",
            lead_id=lead.id,
            db_session=db_session,
        )


# ---------------------------------------------------------------------------
# 2.3-F: sync_lead does NOT read from Airtable (CS-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_does_not_call_airtable_read_methods(
    db_session, tmp_path: Path, monkeypatch
):
    """CS-7: sync_lead only triggers writes — no Airtable reads in the call path."""
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-ro", "Read-Only Test Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-ro",
        name="Carlos Méndez",
        phone="+5491155550101",
    )
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY", "pat_test")
    await _seed_crm_integration(db_session, "test-client-ro", _valid_crm_yaml_data())

    mock_adapter = MagicMock(spec=["upsert_record", "health_check"])
    mock_adapter.upsert_record = AsyncMock(return_value="recROTEST0001")


    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="test-client-ro",
            lead_id=lead.id,
            db_session=db_session,
        )

    # Only upsert_record should have been called — no read-like methods
    mock_adapter.upsert_record.assert_called_once()
    # If the spec object were to expose get/find/list methods and they were called,
    # the mock.spec would allow the attribute but the call would be tracked.
    # We assert the adapter interface stays write-only at this integration level.


# ---------------------------------------------------------------------------
# Spec: Lead without external_lead_id falls back gracefully (no crash, logs warning)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_null_external_lead_id_skips_gracefully(
    db_session, tmp_path: Path, monkeypatch
):
    """Spec: Lead with external_lead_id=NULL must not crash CRM sync.

    GIVEN a Lead with external_lead_id = NULL (manually created lead)
    WHEN sync_lead() runs with match_field=lead_id
    THEN no upsert is attempted (no crash)
    AND the function returns without raising
    AND a warning is logged indicating the lead was skipped.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    # Seed tenant + lead without external_lead_id
    await _seed_test_client(db_session, "test-client-fallback", "Fallback Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-fallback",
        name="Lead Sin ID",
        phone="+5491155550101",
    )
    # external_lead_id is None by default (not set at creation)
    assert lead.external_lead_id is None

    await db_session.flush()

    # crm.yaml with match_field=lead_id (the config that requires external_lead_id)
    monkeypatch.setenv("TEST_CRM_API_KEY_FB", "pat_test_fallback")
    crm_data = {
        "provider": "airtable",
        "base_id": "appFALLBACKBASE",
        "table_id": "tblFALLBACKTBL",
        "api_key_env": "TEST_CRM_API_KEY_FB",
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "name", "target": "Nombre", "type": "string"},
            {"source": "phone", "target": "Teléfono", "type": "phone"},
        ],
    }
    await _seed_crm_integration(db_session, "test-client-fallback", crm_data)


    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recSHOULDNOTBECALLED")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Must not raise
        await sync_lead(
            client_id="test-client-fallback",
            lead_id=lead.id,
            db_session=db_session,
        )

    # upsert must NOT be called — null lead_id means no safe match key
    mock_adapter.upsert_record.assert_not_called()


# ---------------------------------------------------------------------------
# Spec: Lead without external_lead_id falls back to external_crm_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_null_external_lead_id_falls_back_to_external_crm_id(
    db_session, tmp_path: Path, monkeypatch
):
    """Spec: Lead with external_lead_id=NULL but external_crm_id set → fallback uses external_crm_id.

    GIVEN a Lead with external_lead_id = NULL and external_crm_id = 'recABC123'
    AND crm.yaml has match_field='lead_id' (primary)
    AND crm.yaml field_mappings include external_crm_id → 'CRM ID'
    WHEN sync_lead() runs
    THEN upsert IS called using 'CRM ID' as match_field (not lead_id)
    AND the payload contains the external_crm_id value.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-crm-fallback", "CRM Fallback Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-crm-fallback",
        name="Lead Con CRM ID",
        phone="+5491155550101",
    )
    # Set external_crm_id but NOT external_lead_id
    lead.external_crm_id = "recABC123"
    lead.external_lead_id = None
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY_CRM", "pat_test_crm_fallback")
    crm_data = {
        "provider": "airtable",
        "base_id": "appCRMFALLBACKBASE",
        "table_id": "tblCRMFALLBACKTBL",
        "api_key_env": "TEST_CRM_API_KEY_CRM",
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "external_crm_id", "target": "CRM ID", "type": "string"},
            {"source": "name", "target": "Nombre", "type": "string"},
            {"source": "phone", "target": "Teléfono", "type": "phone"},
        ],
    }
    await _seed_crm_integration(db_session, "test-client-crm-fallback", crm_data)


    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recCRMFALLBACK001")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="test-client-crm-fallback",
            lead_id=lead.id,
            db_session=db_session,
        )

    # upsert MUST be called — fallback to external_crm_id
    mock_adapter.upsert_record.assert_called_once()
    call_kwargs = mock_adapter.upsert_record.call_args
    assert call_kwargs.kwargs["match_field"] == "CRM ID", (
        f"match_field must fall back to 'CRM ID' (external_crm_id target); "
        f"got {call_kwargs.kwargs['match_field']!r}"
    )
    assert call_kwargs.kwargs["payload"]["CRM ID"] == "recABC123", (
        f"payload must contain CRM ID = 'recABC123'; got {call_kwargs.kwargs['payload']}"
    )


@pytest.mark.asyncio
async def test_sync_lead_null_external_lead_id_and_crm_id_falls_back_to_email(
    db_session, tmp_path: Path, monkeypatch
):
    """Spec: Lead with both external_lead_id=NULL and external_crm_id=NULL → fallback to email.

    GIVEN a Lead with external_lead_id = NULL, external_crm_id = NULL, email = 'test@example.com'
    AND crm.yaml has match_field='lead_id' (primary)
    AND crm.yaml field_mappings include email → 'Email'
    WHEN sync_lead() runs
    THEN upsert IS called using 'Email' as match_field
    AND the payload contains the email value.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-email-fallback", "Email Fallback Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-email-fallback",
        name="Lead Con Email",
        phone="+5491155550101",
    )
    lead.external_crm_id = None
    lead.external_lead_id = None
    lead.email = "test@example.com"
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY_EMAIL", "pat_test_email_fallback")
    crm_data = {
        "provider": "airtable",
        "base_id": "appEMAILFALLBACKBASE",
        "table_id": "tblEMAILFALLBACKTBL",
        "api_key_env": "TEST_CRM_API_KEY_EMAIL",
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "external_crm_id", "target": "CRM ID", "type": "string"},
            {"source": "email", "target": "Email", "type": "string"},
            {"source": "name", "target": "Nombre", "type": "string"},
            {"source": "phone", "target": "Teléfono", "type": "phone"},
        ],
    }
    await _seed_crm_integration(db_session, "test-client-email-fallback", crm_data)


    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recEMAILFALLBACK001")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        await sync_lead(
            client_id="test-client-email-fallback",
            lead_id=lead.id,
            db_session=db_session,
        )

    # upsert MUST be called — fallback to email
    mock_adapter.upsert_record.assert_called_once()
    call_kwargs = mock_adapter.upsert_record.call_args
    assert call_kwargs.kwargs["match_field"] == "Email", (
        f"match_field must fall back to 'Email' (email target); "
        f"got {call_kwargs.kwargs['match_field']!r}"
    )
    assert call_kwargs.kwargs["payload"]["Email"] == "test@example.com", (
        f"payload must contain Email = 'test@example.com'; got {call_kwargs.kwargs['payload']}"
    )


@pytest.mark.asyncio
async def test_sync_lead_all_fallbacks_null_skips_with_warning(
    db_session, tmp_path: Path, monkeypatch
):
    """Spec: Lead with external_lead_id=NULL, external_crm_id=NULL, email=NULL → skip with warning.

    GIVEN a Lead with no external_lead_id, no external_crm_id, no email
    WHEN sync_lead() runs
    THEN upsert is NOT called
    AND the function returns without raising
    AND a warning is logged.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-no-ids", "No IDs Client")
    lead = await create_lead(
        db_session,
        client_id="test-client-no-ids",
        name="Lead Sin IDs",
        phone="+5491155550101",
    )
    lead.external_crm_id = None
    lead.external_lead_id = None
    # email defaults to None
    assert lead.email is None
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY_NOIDS", "pat_test_noids")
    crm_data = {
        "provider": "airtable",
        "base_id": "appNOIDSBASE",
        "table_id": "tblNOIDSTBL",
        "api_key_env": "TEST_CRM_API_KEY_NOIDS",
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "external_crm_id", "target": "CRM ID", "type": "string"},
            {"source": "email", "target": "Email", "type": "string"},
            {"source": "name", "target": "Nombre", "type": "string"},
            {"source": "phone", "target": "Teléfono", "type": "phone"},
        ],
    }
    await _seed_crm_integration(db_session, "test-client-no-ids", crm_data)


    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recSHOULDNOTBECALLED")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ):
        # Must not raise
        await sync_lead(
            client_id="test-client-no-ids",
            lead_id=lead.id,
            db_session=db_session,
        )

    # No fallback available — upsert must NOT be called
    mock_adapter.upsert_record.assert_not_called()


# ---------------------------------------------------------------------------
# Spec: Duplicate external_lead_id detection during CRM sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_duplicate_external_lead_id_logs_warning_but_still_pushes(
    db_session, tmp_path: Path, monkeypatch
):
    """Spec: CRM sync detects duplicate external_lead_id, logs warning, still upserts.

    GIVEN two leads share the same external_lead_id (e.g. due to bad import data)
    WHEN sync_lead() is called for one of them
    THEN a warning is logged about the duplicate
    AND the upsert IS still called (do NOT crash or skip)
    AND the pushed lead's data is sent to the CRM.
    """
    from app.integrations.crm_sync_service import sync_lead
    from app.leads.service import create_lead

    await _seed_test_client(db_session, "test-client-dup", "Dup Detection Client")

    # Create two leads with the same external_lead_id
    lead_a = await create_lead(
        db_session,
        client_id="test-client-dup",
        name="Lead A Duplicate",
        phone="+5491155550101",
    )
    lead_a.external_lead_id = 99999

    lead_b = await create_lead(
        db_session,
        client_id="test-client-dup",
        name="Lead B Duplicate",
        phone="+5491155550101",
    )
    lead_b.external_lead_id = 99999  # same as lead_a — duplicate!
    await db_session.flush()

    monkeypatch.setenv("TEST_CRM_API_KEY_DUP", "pat_test_dup")
    crm_data = {
        "provider": "airtable",
        "base_id": "appDUPBASE",
        "table_id": "tblDUPTBL",
        "api_key_env": "TEST_CRM_API_KEY_DUP",
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "name", "target": "Nombre", "type": "string"},
            {"source": "phone", "target": "Teléfono", "type": "phone"},
        ],
    }
    await _seed_crm_integration(db_session, "test-client-dup", crm_data)


    mock_adapter = MagicMock()
    mock_adapter.upsert_record = AsyncMock(return_value="recDUP001")

    with _fresh_store_patch(), patch(
        "app.integrations.crm_sync_service.make_adapter",
        return_value=mock_adapter,
    ), patch("app.integrations.crm_sync_service.logger") as mock_logger:
        await sync_lead(
            client_id="test-client-dup",
            lead_id=lead_a.id,
            db_session=db_session,
        )
        # Warning MUST be logged about the duplicate
        warning_calls = [
            call for call in mock_logger.warning.call_args_list
            if "duplicate" in str(call).lower()
        ]
        assert warning_calls, (
            "sync_lead must log a warning about duplicate external_lead_id; "
            f"warning calls: {mock_logger.warning.call_args_list}"
        )

    # Upsert MUST still be called — duplicate is a warning, not a block
    mock_adapter.upsert_record.assert_called_once()
    call_kwargs = mock_adapter.upsert_record.call_args
    assert call_kwargs.kwargs["payload"]["lead_id"] == 99999, (
        f"payload must contain lead_id = 99999; got {call_kwargs.kwargs['payload']}"
    )
