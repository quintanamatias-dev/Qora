"""Tests for external_lead_id handling in CRM import and sync.

TDD: tasks 3.1 (RED), 3.2 (RED), 3.3 (RED).

Spec: Domain 2 — CRM External Lead ID
- _create_lead_from_qora_data populates external_lead_id when present
- _update_lead_from_qora_data updates external_lead_id on existing Lead
- _lead_to_dict includes external_lead_id when present, omits/None when absent
- Duplicate external_lead_id during import logs a warning (does not crash)
"""

from __future__ import annotations

import logging


# ---------------------------------------------------------------------------
# Task 3.1 RED — _create_lead_from_qora_data populates external_lead_id
# ---------------------------------------------------------------------------


def test_create_lead_populates_external_lead_id():
    """_create_lead_from_qora_data must set external_lead_id from qora_data.

    GIVEN an Airtable record with a numeric lead_id field (e.g. 123456)
    AND qora_data has been reverse-mapped with external_lead_id = 123456
    WHEN _create_lead_from_qora_data is called
    THEN the returned Lead has external_lead_id = 123456 (integer).
    """
    from app.integrations.crm_import_service import _create_lead_from_qora_data

    qora_data = {
        "name": "Pedro Alonso",
        "phone": "+5491123456789",
        "email": "pedro@example.com",
        "external_lead_id": 123456,
    }

    lead, _pending = _create_lead_from_qora_data(
        client_id="quintana-seguros",
        qora_data=qora_data,
        airtable_id="recABC123",
    )

    assert lead.external_lead_id == 123456, (
        f"Expected external_lead_id=123456, got {lead.external_lead_id!r}"
    )
    assert isinstance(lead.external_lead_id, int), (
        "external_lead_id must be int (Meta IDs are numeric)"
    )
    # Airtable record ID goes to external_crm_id (unchanged)
    assert lead.external_crm_id == "recABC123"


def test_create_lead_external_lead_id_none_when_absent():
    """_create_lead_from_qora_data must leave external_lead_id NULL when absent from qora_data.

    GIVEN an Airtable record with no lead_id field (manually added lead)
    WHEN _create_lead_from_qora_data is called
    THEN the returned Lead has external_lead_id = None.
    """
    from app.integrations.crm_import_service import _create_lead_from_qora_data

    qora_data = {
        "name": "Maria Lopez",
        "phone": "+5491198765432",
        # No external_lead_id key — manually added lead
    }

    lead, _pending = _create_lead_from_qora_data(
        client_id="quintana-seguros",
        qora_data=qora_data,
        airtable_id="recXYZ789",
    )

    assert lead.external_lead_id is None, (
        f"external_lead_id must be None when absent from qora_data, got {lead.external_lead_id!r}"
    )


# ---------------------------------------------------------------------------
# Task 3.2 RED — _update_lead_from_qora_data updates external_lead_id
# ---------------------------------------------------------------------------


def test_update_lead_sets_external_lead_id():
    """_update_lead_from_qora_data must update external_lead_id on existing Lead.

    GIVEN a Lead already exists matched by phone
    AND the Airtable record has a numeric lead_id
    WHEN _update_lead_from_qora_data is called
    THEN lead.external_lead_id is updated to the numeric value.
    """
    from app.integrations.crm_import_service import _update_lead_from_qora_data
    from app.leads.models import Lead

    lead = Lead(
        id="existing-lead-id",
        client_id="quintana-seguros",
        name="Ana Garcia",
        phone="+5491187654321",
        external_lead_id=None,  # not yet populated
    )

    qora_data = {
        "name": "Ana Garcia",
        "phone": "+5491187654321",
        "external_lead_id": 789012,
    }

    _update_lead_from_qora_data(lead, qora_data, airtable_id="recUPDATE01")

    assert lead.external_lead_id == 789012, (
        f"Expected external_lead_id=789012 after update, got {lead.external_lead_id!r}"
    )


def test_update_lead_external_lead_id_unchanged_when_absent():
    """_update_lead_from_qora_data must leave external_lead_id unchanged when absent from qora_data.

    GIVEN a Lead with external_lead_id = 555
    AND qora_data does NOT include external_lead_id key
    WHEN _update_lead_from_qora_data is called
    THEN lead.external_lead_id remains 555 (no field → no change).
    """
    from app.integrations.crm_import_service import _update_lead_from_qora_data
    from app.leads.models import Lead

    lead = Lead(
        id="lead-existing-eid",
        client_id="quintana-seguros",
        name="Carlos Ruiz",
        phone="+5491100001111",
        external_lead_id=555,
    )

    qora_data = {
        "name": "Carlos Ruiz Updated",
        # No external_lead_id — Airtable field was missing
    }

    _update_lead_from_qora_data(lead, qora_data, airtable_id="recNO_EID")

    assert lead.external_lead_id == 555, (
        "external_lead_id must remain unchanged when not present in qora_data"
    )


# ---------------------------------------------------------------------------
# Task 3.3 RED — _lead_to_dict includes external_lead_id when present
# ---------------------------------------------------------------------------


def test_lead_to_dict_includes_external_lead_id_when_set():
    """_lead_to_dict must include external_lead_id in output when Lead has it.

    GIVEN a Lead with external_lead_id = 123456
    WHEN _lead_to_dict() is called
    THEN the returned dict includes 'external_lead_id': 123456.
    """
    from app.integrations.crm_sync_service import _lead_to_dict
    from app.leads.models import Lead

    lead = Lead(
        id="sync-lead-id",
        client_id="quintana-seguros",
        name="Roberto Mendez",
        phone="+5491122334455",
        external_lead_id=654321,
    )

    result = _lead_to_dict(lead)

    assert "external_lead_id" in result, (
        "_lead_to_dict must include 'external_lead_id' key when Lead has it"
    )
    assert result["external_lead_id"] == 654321, (
        f"Expected external_lead_id=654321, got {result['external_lead_id']!r}"
    )


def test_lead_to_dict_external_lead_id_none_when_not_set():
    """_lead_to_dict must include external_lead_id as None when Lead has no value.

    GIVEN a Lead with external_lead_id = None
    WHEN _lead_to_dict() is called
    THEN external_lead_id key exists in dict with value None.
    """
    from app.integrations.crm_sync_service import _lead_to_dict
    from app.leads.models import Lead

    lead = Lead(
        id="sync-lead-no-eid",
        client_id="quintana-seguros",
        name="Elena Vargas",
        phone="+5491155667788",
        external_lead_id=None,
    )

    result = _lead_to_dict(lead)

    assert "external_lead_id" in result, (
        "_lead_to_dict must include 'external_lead_id' key (with None) even when not set"
    )
    assert result["external_lead_id"] is None


# ---------------------------------------------------------------------------
# Duplicate external_lead_id detection — RED
# ---------------------------------------------------------------------------


def test_update_lead_logs_warning_on_duplicate_external_lead_id(caplog):
    """Updating a lead with an external_lead_id that collides with an existing lead
    must log a warning. The update still proceeds (no crash).

    GIVEN two Lead instances where one already has external_lead_id = 999
    AND a qora_data update arrives with the same external_lead_id = 999
    WHEN _update_lead_from_qora_data is called with collision_check=True
    THEN a WARNING is logged mentioning 'duplicate external_lead_id'
    AND the target lead is still updated (no exception raised)
    """
    from app.integrations.crm_import_service import _update_lead_from_qora_data
    from app.leads.models import Lead

    target_lead = Lead(
        id="lead-update-target",
        client_id="quintana-seguros",
        name="Carlos Lopez",
        phone="+5491100000001",
        external_lead_id=None,
    )
    # Another existing lead already claims this external_lead_id
    existing_occupant_id = "lead-occupant-001"

    qora_data = {"name": "Carlos Lopez Updated", "external_lead_id": 999}

    with caplog.at_level(logging.WARNING, logger="app.integrations.crm_import_service"):
        _update_lead_from_qora_data(
            target_lead,
            qora_data,
            airtable_id="recDUPTEST001",
            existing_external_lead_id_holder=existing_occupant_id,
        )

    # Warning must have been emitted
    assert any("duplicate" in r.message.lower() for r in caplog.records), (
        "Expected a WARNING about duplicate external_lead_id, got: "
        + str([r.message for r in caplog.records])
    )

    # Update still applied — no crash
    assert target_lead.name == "Carlos Lopez Updated"
    assert target_lead.external_lead_id == 999
