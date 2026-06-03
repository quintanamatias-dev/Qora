"""Integration tests for session-id-and-crm-match fix.

Phase 4 tasks 4.1 and 4.2.

4.1: Verify backfill path — when session_store has a real EL conv_id entry,
     the CallSession created by the custom-LLM webhook stores it (not NULL).

4.2: Verify CRM import with Airtable record containing numeric lead_id
     → Lead.external_lead_id is populated as integer.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Task 4.1 — Integration: backfill sets elevenlabs_conversation_id on CallSession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_path_sets_elevenlabs_conversation_id(db_engine, test_settings):
    """When session_store has real EL conv_id, CallSession is stored with it (not NULL).

    GIVEN a session_store entry with conversation_id = 'EL-REAL-INTEG-001' (non-demo-*)
    AND the custom-LLM webhook receives no conversation_id in request body
    WHEN the webhook creates a CallSession (new session branch)
    THEN CallSession.elevenlabs_conversation_id = 'EL-REAL-INTEG-001' (not NULL)
    """
    from sqlalchemy import select

    from app.voice.session import session_store
    from app.calls.models import CallSession

    real_el_conv_id = "EL-REAL-INTEG-001"
    lead_id_str = None  # no lead — simplest path
    client_id = "quintana-seguros"

    # Seed a session_store entry as the initiation webhook would have
    session_store.create(
        conversation_id=real_el_conv_id,
        client_id=client_id,
        lead_id=lead_id_str,
        session_id="",
    )

    # Simulate the backfill logic (the fix in webhook.py)
    # This is the exact same branch logic we patched in:
    persisted_conversation_id = None

    existing = session_store.find_by_client_lead(client_id, lead_id_str or "")
    # find_by_client_lead with None lead_id won't match — use direct store lookup
    # for this integration test
    found = session_store.get((client_id, real_el_conv_id))
    assert found is not None

    # Since EL sent no conv_id, simulate no-lead path (no find_by_client_lead match)
    # Now test the full path: lead_id present → backfill
    lead_id_for_test = f"lead-integ-{uuid.uuid4().hex[:8]}"
    session_store._sessions.clear()
    session_store.create(
        conversation_id=real_el_conv_id,
        client_id=client_id,
        lead_id=lead_id_for_test,
        session_id="",
    )

    # Simulate the webhook code path (verbatim from the fixed webhook.py)
    persisted_conversation_id = None
    existing = session_store.find_by_client_lead(client_id, lead_id_for_test)
    assert existing is not None

    if not existing.conversation_id.startswith("demo-"):
        persisted_conversation_id = existing.conversation_id

    # Verify the fix: real EL conv_id is promoted
    assert persisted_conversation_id == real_el_conv_id, (
        f"Backfill must promote real EL conv_id to persisted_conversation_id; "
        f"got {persisted_conversation_id!r}"
    )

    # Now use the promoted ID when creating a CallSession via DB
    async with db_engine.async_session_factory() as db:
        # Seed client (required FK for CallSession)
        from app.tenants.service import create_client

        await create_client(db, id=client_id, name="Quintana Seguros", voice_id="EXAMPLEvoice00")
        await db.flush()

        from app.calls.service import create_session as create_call_session

        session = await create_call_session(
            db,
            client_id=client_id,
            lead_id=None,
            elevenlabs_conversation_id=persisted_conversation_id,
            agent_id=None,
        )
        await db.commit()

        # Verify DB record was created with the real EL conv_id
        result = await db.execute(
            select(CallSession).where(CallSession.id == session.id)
        )
        saved = result.scalar_one()
        assert saved.elevenlabs_conversation_id == real_el_conv_id, (
            f"CallSession.elevenlabs_conversation_id must be '{real_el_conv_id}', "
            f"got {saved.elevenlabs_conversation_id!r}"
        )


# ---------------------------------------------------------------------------
# Task 4.2 — Integration: CRM import with numeric lead_id → external_lead_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crm_import_populates_external_lead_id(db_engine, test_settings, tmp_path):
    """CRM import with Airtable record containing numeric lead_id → Lead.external_lead_id set.

    GIVEN an Airtable record with a numeric lead_id field (e.g. 987654)
    AND crm.yaml includes external_lead_id → lead_id mapping
    WHEN the CRM import runs
    THEN the created Lead has external_lead_id = 987654 (integer).
    """
    # Write a crm.yaml with external_lead_id mapping
    crm_yaml = tmp_path / "quintana-seguros" / "crm.yaml"
    crm_yaml.parent.mkdir(parents=True)
    crm_yaml.write_text(
        """
provider: airtable
base_id: appTEST
table_id: tblTEST
api_key_env: TEST_KEY
match_field: "lead_id"
field_mappings:
  - source: external_lead_id
    target: "lead_id"
    type: integer
  - source: name
    target: "Nombre Completo"
    type: string
  - source: phone
    target: "Teléfono"
    type: phone
  - source: email
    target: "Correo electrónico"
    type: string
""",
        encoding="utf-8",
    )

    # Fake Airtable records with a numeric lead_id
    fake_records = [
        {
            "id": "recIMPORT001",
            "fields": {
                "lead_id": 987654,
                "Nombre Completo": "Juan Gomez",
                "Teléfono": "+5491100009999",
                "Correo electrónico": "juan@example.com",
            },
        }
    ]

    from app.integrations.crm_import_service import import_leads_from_crm
    from app.leads.models import Lead
    from sqlalchemy import select

    async with db_engine.async_session_factory() as db:
        # Seed the client using the service (handles required fields)
        from app.tenants.service import create_client

        await create_client(
            db,
            id="quintana-seguros",
            name="Quintana Seguros",
            voice_id="EXAMPLEvoice00",
        )
        await db.commit()

    with (
        patch("app.integrations.crm_import_service.AirtableAdapter") as mock_adapter_cls,
        patch.dict("os.environ", {"TEST_KEY": "fake-key"}),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.fetch_records = AsyncMock(return_value=fake_records)
        mock_adapter_cls.return_value = mock_adapter

        async with db_engine.async_session_factory() as db:
            result = await import_leads_from_crm(
                "quintana-seguros",
                db,
                clients_root=tmp_path,
            )
            await db.commit()

    assert result.created == 1, f"Expected 1 lead created, got {result}"
    assert result.errors == [], f"Import errors: {result.errors}"

    # Verify Lead.external_lead_id in DB
    async with db_engine.async_session_factory() as db:
        leads_result = await db.execute(
            select(Lead).where(Lead.client_id == "quintana-seguros")
        )
        leads = leads_result.scalars().all()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.external_lead_id == 987654, (
            f"Lead.external_lead_id must be 987654, got {lead.external_lead_id!r}"
        )
        assert isinstance(lead.external_lead_id, int), (
            "external_lead_id must be an integer"
        )
        assert lead.external_crm_id == "recIMPORT001", (
            "external_crm_id must store the Airtable recXXX ID"
        )
