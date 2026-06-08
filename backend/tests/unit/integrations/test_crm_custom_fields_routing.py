"""Unit tests for CRM custom field routing — TDD RED phase (WU-2).

Spec requirements covered:
- CRM Export: _lead_to_dict merges custom fields from lead_custom_fields table (AC-7)
  - GIVEN lead L1 with custom fields {car_make: "Toyota", car_year: "2021"}
  - WHEN _lead_to_dict is called
  - THEN the returned dict includes car_make and car_year
  - AND base Lead fields are still included
- CRM Export: no custom fields → safe path (edge case from spec)
  - GIVEN lead L1 has no rows in lead_custom_fields
  - WHEN _lead_to_dict is called
  - THEN dict contains only base Lead fields, no error raised
- CRM Import: _update_lead_from_qora_data routes non-base fields to lead_custom_fields (AC-8)
  - GIVEN Airtable record with name="Ana", car_make="Ford", age="35" (reverse-mapped)
  - WHEN _update_lead_from_qora_data processes the record
  - THEN lead.name is set to "Ana"
  - AND lead_custom_fields rows for car_make and age are upserted
- CRM Import: _create_lead_from_qora_data routes non-base fields to lead_custom_fields (AC-8)
  - GIVEN new Airtable record with phone, name, car_make, car_year
  - WHEN _create_lead_from_qora_data processes the record
  - THEN Lead is created with base fields only
  - AND the returned pending_custom_fields dict contains car_make, car_year
- CRM Import: base fields only → no custom field upsert (safe path)
  - GIVEN Airtable record with only name and phone (all base fields)
  - WHEN import processes the record
  - THEN no custom field upserts happen

Design constraints (design.md):
- DUAL-WRITE: custom field data also written to legacy Lead columns (backward compat)
- _lead_to_dict reads from lead_custom_fields as PRIMARY source, fallback to legacy columns
- Import classifies base-vs-custom against BASE_LEAD_FIELDS set
- The FieldMapper itself does NOT change — already dynamic

Test layer: Unit (mocked DB session, no live SQLite)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# BASE_LEAD_FIELDS reference set (mirrors implementation)
# ---------------------------------------------------------------------------

BASE_LEAD_FIELDS = frozenset({
    "id", "client_id", "name", "phone", "email", "status", "notes",
    "external_lead_id", "external_crm_id", "call_count", "do_not_call",
    "summary_last_call", "interest_level", "objections_heard",
    "extracted_facts", "next_action", "next_action_at",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(
    *,
    id: str = "lead-001",
    client_id: str = "quintana-seguros",
    name: str = "Ana García",
    phone: str = "+5491155500001",
    email: str | None = None,
    status: str = "new",
    # legacy columns — still present in DB during transition
    car_make: str | None = None,
    car_model: str | None = None,
    car_year: str | None = None,
    current_insurance: str | None = None,
    age: str | None = None,
    zona: str | None = None,
) -> MagicMock:
    """Build a minimal Lead-like mock object."""
    lead = MagicMock()
    lead.id = id
    lead.client_id = client_id
    lead.name = name
    lead.phone = phone
    lead.email = email
    lead.status = status
    lead.notes = None
    lead.external_lead_id = None
    lead.external_crm_id = None
    lead.call_count = 0
    lead.do_not_call = False
    lead.summary_last_call = None
    lead.interest_level = None
    lead.objections_heard = None
    lead.extracted_facts = None
    lead.next_action = None
    lead.next_action_at = None
    # legacy custom columns
    lead.car_make = car_make
    lead.car_model = car_model
    lead.car_year = car_year
    lead.current_insurance = current_insurance
    lead.age = age
    lead.zona = zona
    return lead


# ===========================================================================
# Task 2.1A: _lead_to_dict merges custom fields
# ===========================================================================


class TestLeadToDictCustomFieldMerge:
    """_lead_to_dict(lead, custom_fields) merges pre-loaded custom fields into the flat dict."""

    def test_lead_to_dict_includes_custom_fields_in_output(self):
        """Export includes car_make and car_year from custom_fields dict."""
        from app.integrations.crm_sync_service import _lead_to_dict

        lead = _make_lead()
        custom_fields = {"car_make": "Toyota", "car_year": "2021"}

        result = _lead_to_dict(lead, custom_fields=custom_fields)

        assert result["car_make"] == "Toyota", (
            f"_lead_to_dict must include car_make from custom_fields; got {result}"
        )
        assert result["car_year"] == "2021", (
            f"_lead_to_dict must include car_year from custom_fields; got {result}"
        )

    def test_lead_to_dict_base_fields_still_present_with_custom_fields(self):
        """Base Lead fields (name, phone, status) remain present when custom_fields are merged."""
        from app.integrations.crm_sync_service import _lead_to_dict

        lead = _make_lead(name="Ana García", phone="+5491155500001", status="new")
        custom_fields = {"car_make": "Ford"}

        result = _lead_to_dict(lead, custom_fields=custom_fields)

        assert result["name"] == "Ana García"
        assert result["phone"] == "+5491155500001"
        assert result["status"] == "new"

    def test_lead_to_dict_no_custom_fields_returns_base_fields_only(self):
        """Export with empty custom_fields dict → only base Lead fields, no error raised."""
        from app.integrations.crm_sync_service import _lead_to_dict

        lead = _make_lead()

        # Both calling conventions: empty dict and default (no arg)
        result = _lead_to_dict(lead, custom_fields={})

        # Must not raise; must contain base fields
        assert "name" in result
        assert "phone" in result
        assert "car_make" not in result or result.get("car_make") is None, (
            "With empty custom_fields and no legacy value, car_make should not appear "
            "or should be None"
        )

    def test_lead_to_dict_multiple_custom_fields_all_merged(self):
        """All entries from custom_fields dict appear in the export dict."""
        from app.integrations.crm_sync_service import _lead_to_dict

        lead = _make_lead()
        custom_fields = {
            "car_make": "Toyota",
            "car_model": "Corolla",
            "car_year": "2020",
            "current_insurance": "MAPFRE",
            "age": "35",
            "zona": "Norte",
        }

        result = _lead_to_dict(lead, custom_fields=custom_fields)

        for key, value in custom_fields.items():
            assert result.get(key) == value, (
                f"custom field {key!r} must appear in _lead_to_dict output; "
                f"got {result.get(key)!r}"
            )

    def test_lead_to_dict_custom_fields_override_legacy_column_values(self):
        """Custom fields from lead_custom_fields take priority over legacy Lead column values."""
        from app.integrations.crm_sync_service import _lead_to_dict

        # Lead has old column value (legacy transition state)
        lead = _make_lead(car_make="OldValueInColumn")
        # custom_fields has the authoritative new value
        custom_fields = {"car_make": "NewValueFromTable"}

        result = _lead_to_dict(lead, custom_fields=custom_fields)

        assert result["car_make"] == "NewValueFromTable", (
            "custom_fields dict must override legacy Lead column; "
            f"got {result['car_make']!r}"
        )

    def test_lead_to_dict_accepts_no_custom_fields_kwarg_backward_compat(self):
        """Calling _lead_to_dict(lead) without custom_fields must not raise (backward compat)."""
        from app.integrations.crm_sync_service import _lead_to_dict

        lead = _make_lead()

        # Must not raise TypeError
        result = _lead_to_dict(lead)

        assert isinstance(result, dict)
        assert "name" in result


# ===========================================================================
# Task 2.1B: CRM import — base-vs-custom field classification
# ===========================================================================


class TestImportBaseVsCustomFieldClassification:
    """_update_lead_from_qora_data and _create_lead_from_qora_data classify
    non-base fields as custom and route them appropriately."""

    def test_update_lead_writes_name_to_lead_column(self):
        """name is a base field → written directly to Lead.name."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-update-001",
            client_id="quintana-seguros",
            name="Old Name",
            phone="+5491155500002",
            status=LeadStatus.NEW.value,
        )
        qora_data = {"name": "New Name"}
        pending = _update_lead_from_qora_data(lead, qora_data, "recTEST001")

        assert lead.name == "New Name", f"lead.name must be updated; got {lead.name!r}"

    def test_update_lead_returns_custom_fields_for_non_base_fields(self):
        """Non-base fields (car_make, age) are returned as pending_custom_fields, not written to Lead."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-update-002",
            client_id="quintana-seguros",
            name="Ana García",
            phone="+5491155500003",
            status=LeadStatus.NEW.value,
        )
        qora_data = {"name": "Ana García", "car_make": "Ford", "age": "35"}
        pending = _update_lead_from_qora_data(lead, qora_data, "recTEST002")

        # car_make and age must NOT be written to Lead columns
        # (Lead columns are not the target for custom fields)
        assert "car_make" in pending, (
            f"_update_lead_from_qora_data must return car_make as pending custom field; "
            f"pending={pending}"
        )
        assert pending["car_make"] == "Ford", (
            f"pending['car_make'] must be 'Ford'; got {pending['car_make']!r}"
        )
        assert "age" in pending, (
            f"_update_lead_from_qora_data must return age as pending custom field; "
            f"pending={pending}"
        )
        assert pending["age"] == "35", (
            f"pending['age'] must be '35'; got {pending['age']!r}"
        )

    def test_update_lead_all_quintana_custom_fields_are_classified_as_custom(self):
        """All 6 Quintana custom fields routed as custom, not written to Lead."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-update-003",
            client_id="quintana-seguros",
            name="Carlos",
            phone="+5491155500004",
            status=LeadStatus.NEW.value,
        )
        qora_data = {
            "car_make": "Toyota",
            "car_model": "Corolla",
            "car_year": "2020",
            "current_insurance": "MAPFRE",
            "age": "40",
            "zona": "Sur",
        }
        pending = _update_lead_from_qora_data(lead, qora_data, "recTEST003")

        for key in ["car_make", "car_model", "car_year", "current_insurance", "age", "zona"]:
            assert key in pending, (
                f"{key!r} must be in pending_custom_fields; pending={pending}"
            )

    def test_update_lead_base_fields_not_in_pending_custom_fields(self):
        """Base fields (name, email, status) must NOT appear in pending_custom_fields."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-update-004",
            client_id="quintana-seguros",
            name="Old Name",
            phone="+5491155500005",
            status=LeadStatus.NEW.value,
        )
        qora_data = {"name": "New Name", "email": "test@example.com", "status": "called"}
        pending = _update_lead_from_qora_data(lead, qora_data, "recTEST004")

        assert "name" not in pending, "name is a base field — must not be in pending_custom_fields"
        assert "email" not in pending, "email is a base field — must not be in pending_custom_fields"
        assert "status" not in pending, "status is a base field — must not be in pending_custom_fields"

    def test_update_lead_base_fields_only_returns_empty_pending(self):
        """When qora_data has only base fields, pending_custom_fields is empty."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-update-005",
            client_id="quintana-seguros",
            name="Test",
            phone="+5491155500006",
            status=LeadStatus.NEW.value,
        )
        qora_data = {"name": "Test Updated", "email": "test@example.com"}
        pending = _update_lead_from_qora_data(lead, qora_data, "recTEST005")

        assert pending == {}, (
            f"No custom fields in qora_data → pending must be empty; got {pending}"
        )

    def test_create_lead_returns_base_lead_and_pending_custom_fields(self):
        """_create_lead_from_qora_data returns (Lead, pending_custom_fields) tuple."""
        from app.integrations.crm_import_service import _create_lead_from_qora_data

        qora_data = {
            "name": "New Lead",
            "phone": "+5491155500010",
            "email": "new@example.com",
            "car_make": "Honda",
            "car_year": "2019",
        }
        result = _create_lead_from_qora_data(
            client_id="quintana-seguros",
            qora_data=qora_data,
            airtable_id="recNEW001",
        )

        # Function must return a 2-tuple: (Lead, dict)
        assert isinstance(result, tuple), (
            f"_create_lead_from_qora_data must return a (Lead, dict) tuple; got {type(result)}"
        )
        assert len(result) == 2, f"tuple must have 2 elements; got {len(result)}"

        lead, pending = result

        # Lead has base fields
        assert lead.name == "New Lead"
        assert lead.phone == "+5491155500010"
        assert lead.email == "new@example.com"
        assert lead.client_id == "quintana-seguros"
        assert lead.external_crm_id == "recNEW001"

        # custom fields in pending
        assert pending.get("car_make") == "Honda", (
            f"car_make must be in pending; got pending={pending}"
        )
        assert pending.get("car_year") == "2019", (
            f"car_year must be in pending; got pending={pending}"
        )

    def test_create_lead_base_fields_not_in_pending(self):
        """Base fields are set on Lead, NOT in pending_custom_fields."""
        from app.integrations.crm_import_service import _create_lead_from_qora_data

        qora_data = {
            "name": "Ana",
            "phone": "+5491155500011",
            "car_make": "Ford",
        }
        lead, pending = _create_lead_from_qora_data(
            client_id="quintana-seguros",
            qora_data=qora_data,
            airtable_id="recNEW002",
        )

        assert "name" not in pending, "name is base — must not be in pending_custom_fields"
        assert "phone" not in pending, "phone is base — must not be in pending_custom_fields"

    def test_create_lead_no_custom_fields_returns_empty_pending(self):
        """No custom fields in qora_data → pending is empty; Lead created normally."""
        from app.integrations.crm_import_service import _create_lead_from_qora_data

        qora_data = {"name": "Only Base", "phone": "+5491155500012"}
        lead, pending = _create_lead_from_qora_data(
            client_id="quintana-seguros",
            qora_data=qora_data,
            airtable_id="recNEW003",
        )

        assert pending == {}, f"No custom fields → pending must be empty; got {pending}"
        assert lead.name == "Only Base"


# ===========================================================================
# Task 2.1C: DUAL-WRITE — legacy Lead columns still populated during transition
# ===========================================================================


class TestDualWriteLeadColumns:
    """During transition, custom fields must ALSO be written to legacy Lead columns (backward compat)."""

    def test_update_lead_dual_writes_car_make_to_legacy_column(self):
        """car_make in qora_data → upserted to custom_fields AND written to lead.car_make (dual-write)."""
        from app.integrations.crm_import_service import _update_lead_from_qora_data

        from app.leads.models import Lead, LeadStatus
        lead = Lead(
            id="lead-dual-001",
            client_id="quintana-seguros",
            name="Test",
            phone="+5491155500020",
            status=LeadStatus.NEW.value,
        )
        qora_data = {"car_make": "Toyota", "car_year": "2021"}
        pending = _update_lead_from_qora_data(lead, qora_data, "recDUAL001")

        # Legacy columns must still be written (dual-write)
        assert lead.car_make == "Toyota", (
            f"Dual-write: lead.car_make must be set to 'Toyota'; got {lead.car_make!r}"
        )
        assert lead.car_year == "2021", (
            f"Dual-write: lead.car_year must be set to '2021'; got {lead.car_year!r}"
        )

    def test_create_lead_dual_writes_custom_fields_to_legacy_columns(self):
        """Create: car_make/car_year also set on Lead ORM columns during transition."""
        from app.integrations.crm_import_service import _create_lead_from_qora_data

        qora_data = {
            "name": "Dual Write Lead",
            "phone": "+5491155500021",
            "car_make": "Fiat",
            "car_year": "2018",
            "zona": "Sur",
            "age": "30",
            "current_insurance": "None",
        }
        lead, pending = _create_lead_from_qora_data(
            client_id="quintana-seguros",
            qora_data=qora_data,
            airtable_id="recDUAL002",
        )

        # Legacy columns on the Lead must also be set (backward compat)
        assert lead.car_make == "Fiat", (
            f"Dual-write: lead.car_make must be 'Fiat'; got {lead.car_make!r}"
        )
        assert lead.car_year == "2018", (
            f"Dual-write: lead.car_year must be '2018'; got {lead.car_year!r}"
        )
        assert lead.zona == "Sur", (
            f"Dual-write: lead.zona must be 'Sur'; got {lead.zona!r}"
        )
        assert lead.age == "30", (
            f"Dual-write: lead.age must be '30'; got {lead.age!r}"
        )


# ===========================================================================
# Task 2.1D: Integration — import_leads_from_crm upserts custom fields via service
# ===========================================================================


class TestImportLeadsCustomFieldIntegration:
    """import_leads_from_crm must call lead_custom_fields_service.upsert_many
    for non-base fields when processing each record."""

    @pytest.mark.asyncio
    async def test_import_calls_upsert_many_for_custom_fields_on_new_lead(self):
        """When creating a new lead with custom fields, upsert_many is called with the custom data."""
        from app.integrations import crm_import_service
        from app.integrations.crm_config import CRMConfig, CRMFieldDef, CustomFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
            CRMFieldDef(source="car_make", target="Marca", type="string"),
            CRMFieldDef(source="car_year", target="Año", type="integer"),
        ]
        mock_config.custom_fields = [
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make"),
            CustomFieldDef(field_key="car_year", field_type="integer", label="Car Year"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_records = [
            {
                "id": "recCF001",
                "fields": {
                    "Nombre": "Test Lead",
                    "Teléfono": "+5491155500030",
                    "Marca": "Toyota",
                    "Año": "2021",
                },
            }
        ]

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        upsert_many_calls = []

        async def mock_upsert_many(db, *, lead_id, client_id, fields, field_types=None):
            upsert_many_calls.append({
                "lead_id": lead_id,
                "client_id": client_id,
                "fields": fields,
                "field_types": field_types,
            })
            return len(fields)

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter, patch(
            "app.integrations.crm_import_service.lead_custom_fields_service.upsert_many",
            side_effect=mock_upsert_many,
        ):
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "quintana-seguros", mock_db
            )

        assert result.created == 1, f"Expected 1 created; got {result.created}"
        assert len(upsert_many_calls) >= 1, (
            "upsert_many must be called at least once for custom fields"
        )
        # Check the custom fields were passed
        all_fields = {}
        for call in upsert_many_calls:
            all_fields.update(call["fields"])
        assert "car_make" in all_fields, f"car_make must be in upserted fields; got {all_fields}"
        assert all_fields["car_make"] == "Toyota"

    @pytest.mark.asyncio
    async def test_import_calls_upsert_many_for_custom_fields_on_update(self):
        """When updating an existing lead with custom fields, upsert_many is called."""
        from app.integrations import crm_import_service
        from app.integrations.crm_config import CRMConfig, CRMFieldDef, CustomFieldDef
        from app.leads.models import Lead, LeadStatus

        existing_lead = Lead(
            id="existing-cf-001",
            client_id="quintana-seguros",
            name="Old Name",
            phone="+5491155500031",
            status=LeadStatus.NEW.value,
        )

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
            CRMFieldDef(source="zona", target="Zona", type="string"),
        ]
        mock_config.custom_fields = [
            CustomFieldDef(field_key="zona", field_type="string", label="Zone"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_records = [
            {
                "id": "recCF002",
                "fields": {
                    "Teléfono": "+5491155500031",
                    "Zona": "Norte",
                },
            }
        ]

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=existing_lead)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        upsert_many_calls = []

        async def mock_upsert_many(db, *, lead_id, client_id, fields, field_types=None):
            upsert_many_calls.append({
                "lead_id": lead_id,
                "client_id": client_id,
                "fields": fields,
            })
            return len(fields)

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter, patch(
            "app.integrations.crm_import_service.lead_custom_fields_service.upsert_many",
            side_effect=mock_upsert_many,
        ):
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "quintana-seguros", mock_db
            )

        assert result.updated == 1, f"Expected 1 updated; got {result.updated}"
        assert len(upsert_many_calls) >= 1, (
            "upsert_many must be called when custom fields are present in update"
        )
        all_fields = {}
        for call in upsert_many_calls:
            all_fields.update(call["fields"])
        assert "zona" in all_fields, f"zona must be in upserted fields; got {all_fields}"

    @pytest.mark.asyncio
    async def test_import_no_custom_fields_config_does_not_call_upsert_many(self):
        """When config has no custom_fields definitions, upsert_many is never called."""
        from app.integrations import crm_import_service
        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
        ]
        mock_config.custom_fields = []  # no custom field definitions
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_records = [
            {
                "id": "recCF003",
                "fields": {
                    "Nombre": "Test Only Base",
                    "Teléfono": "+5491155500032",
                },
            }
        ]

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        upsert_many_calls = []

        async def mock_upsert_many(db, *, lead_id, client_id, fields, field_types=None):
            upsert_many_calls.append(fields)
            return len(fields)

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter, patch(
            "app.integrations.crm_import_service.lead_custom_fields_service.upsert_many",
            side_effect=mock_upsert_many,
        ):
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "quintana-seguros", mock_db
            )

        assert result.created == 1
        assert len(upsert_many_calls) == 0, (
            f"No custom fields in config → upsert_many must NOT be called; "
            f"got {upsert_many_calls}"
        )
