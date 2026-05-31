"""Unit tests for Airtable → Qora lead import (PULL direction).

TDD RED phase — these tests define the expected behaviour of:
1. FieldMapper.reverse_map()  — Airtable fields → Qora fields
2. AirtableAdapter.fetch_records() — async read of all records
3. crm_import_service.import_leads_from_crm() — orchestrator
4. POST /api/v1/clients/{client_id}/crm/import — API endpoint

All external I/O (Airtable calls, DB) is mocked. No live network.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def sample_crm_config(tmp_path: Path):
    """Write a minimal crm.yaml and return its CRMConfig."""
    crm_yaml = tmp_path / "quintana-seguros" / "crm.yaml"
    crm_yaml.parent.mkdir(parents=True)
    crm_yaml.write_text(
        """
provider: airtable
base_id: appTEST123
table_id: tblTEST456
api_key_env: TEST_AIRTABLE_KEY
match_field: lead_id
status_mapping:
  new: "Nuevo!"
  called: "Contactado (en espera)"
  quoted: "Cotizado"
  interested: "COMPRÓ"
  not_interested: "Perdido"
  follow_up: "Recontactar"
import_status_mapping:
  "Nuevo!": new
  "Contactado (en espera)": called
  "Cotizado": quoted
  "COMPRÓ": interested
  "Perdido": not_interested
  "Recontactar": follow_up
field_mappings:
  - source: name
    target: "Nombre Completo"
    type: string
  - source: phone
    target: "Teléfono"
    type: phone
  - source: email
    target: "Correo electrónico"
    type: string
  - source: status
    target: "Status"
    type: string
  - source: current_insurance
    target: "Poliza_Actual"
    type: string
""",
        encoding="utf-8",
    )
    from app.integrations.crm_config import CRMConfigLoader

    return CRMConfigLoader.load("quintana-seguros", clients_root=tmp_path)


@pytest.fixture
def field_defs(sample_crm_config):
    """Return field_defs from sample config."""
    return sample_crm_config.field_mappings


@pytest.fixture
def airtable_record():
    """A realistic Airtable record shape."""
    return {
        "id": "recARjXh5o5iP1qkK",
        "createdTime": "2024-01-15T10:00:00.000Z",
        "fields": {
            "Nombre Completo": "Matias Quintana",
            "Teléfono": "+5491140485464",
            "Correo electrónico": "matiasquintana12.6@gmail.com",
            "Status": "Nuevo!",
            "Poliza_Actual": "No, sería mi primer seguro",
        },
    }


# ===========================================================================
# Task 1: FieldMapper.reverse_map()
# ===========================================================================


class TestReverseFieldMapping:
    """FieldMapper.reverse_map() maps Airtable fields → Qora fields."""

    def test_reverse_map_returns_qora_field_names(self, field_defs, airtable_record):
        """reverse_map() returns dict keyed by Qora source field names."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs)
        result = mapper.reverse_map(airtable_record["fields"])

        assert "name" in result
        assert result["name"] == "Matias Quintana"

    def test_reverse_map_phone_preserved(self, field_defs, airtable_record):
        """Phone is preserved as-is (Airtable stores E.164)."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs)
        result = mapper.reverse_map(airtable_record["fields"])

        assert result["phone"] == "+5491140485464"

    def test_reverse_map_email_preserved(self, field_defs, airtable_record):
        """Email is mapped back to 'email' Qora field."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs)
        result = mapper.reverse_map(airtable_record["fields"])

        assert result["email"] == "matiasquintana12.6@gmail.com"

    def test_reverse_map_ignores_unmapped_airtable_fields(self, field_defs):
        """Airtable fields with no corresponding Qora mapping are silently skipped."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs)
        airtable_fields = {
            "Nombre Completo": "Test User",
            "Canal_preferido": "Llamada",  # No mapping → ignored
            "Momento_de_decision": "En estos días",  # No mapping → ignored
        }
        result = mapper.reverse_map(airtable_fields)

        assert "name" in result
        assert "Canal_preferido" not in result
        assert "Momento_de_decision" not in result

    def test_reverse_map_with_status_and_import_mapping(self, field_defs):
        """If import_status_mapping provided, Status is reverse-translated."""
        from app.integrations.field_mapping import FieldMapper

        import_status_mapping = {"Nuevo!": "new", "Contactado (en espera)": "called"}
        mapper = FieldMapper(field_defs, import_status_mapping=import_status_mapping)
        airtable_fields = {"Status": "Nuevo!"}
        result = mapper.reverse_map(airtable_fields)

        assert result["status"] == "new"

    def test_reverse_map_status_fallback_when_not_in_import_mapping(self, field_defs):
        """Status value not in import_status_mapping is passed through as-is."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs, import_status_mapping={})
        airtable_fields = {"Status": "SomeUnknownStatus"}
        result = mapper.reverse_map(airtable_fields)

        assert result["status"] == "SomeUnknownStatus"

    def test_reverse_map_missing_optional_airtable_field_skipped(self, field_defs):
        """Missing Airtable fields (not in record) are not included in result."""
        from app.integrations.field_mapping import FieldMapper

        mapper = FieldMapper(field_defs)
        # Only name is present — email/phone/status/current_insurance are absent
        airtable_fields = {"Nombre Completo": "Solo Name"}
        result = mapper.reverse_map(airtable_fields)

        assert result == {"name": "Solo Name"}


# ===========================================================================
# Task 2: AirtableAdapter.fetch_records()
# ===========================================================================


class TestAirtableAdapterFetchRecords:
    """AirtableAdapter.fetch_records() reads all records via asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_fetch_records_returns_list_of_dicts(self):
        """fetch_records returns a list of Airtable record dicts."""
        from app.integrations.adapters.airtable import AirtableAdapter

        adapter = AirtableAdapter(api_key="test_key", base_id="appTEST")
        mock_table = MagicMock()
        mock_records = [
            {"id": "rec1", "fields": {"Nombre Completo": "Alice"}},
            {"id": "rec2", "fields": {"Nombre Completo": "Bob"}},
        ]
        mock_table.all.return_value = mock_records

        with patch.object(adapter, "_get_table", return_value=mock_table):
            with patch("asyncio.to_thread", new=AsyncMock(return_value=mock_records)):
                result = await adapter.fetch_records(table_id="tblTEST")

        assert result == mock_records
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_records_calls_to_thread_with_table_all(self):
        """fetch_records wraps Table.all() in asyncio.to_thread (non-blocking)."""
        from app.integrations.adapters.airtable import AirtableAdapter

        adapter = AirtableAdapter(api_key="test_key", base_id="appTEST")
        mock_table = MagicMock()
        mock_table.all.return_value = []

        with patch.object(adapter, "_get_table", return_value=mock_table) as mock_get:
            with patch("app.integrations.adapters.airtable.adapter.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
                mock_to_thread.return_value = []
                result = await adapter.fetch_records(table_id="tblTEST456")

        mock_get.assert_called_once_with("tblTEST456")
        mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_records_passes_filter_formula(self):
        """fetch_records passes filter_formula to Table.all() when provided."""
        from app.integrations.adapters.airtable import AirtableAdapter

        adapter = AirtableAdapter(api_key="test_key", base_id="appTEST")
        mock_table = MagicMock()

        with patch.object(adapter, "_get_table", return_value=mock_table):
            with patch(
                "app.integrations.adapters.airtable.adapter.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread:
                mock_to_thread.return_value = []
                await adapter.fetch_records(
                    table_id="tblTEST", filter_formula="{Status}='Nuevo!'"
                )

        # to_thread should be called with the filter formula
        call_kwargs = mock_to_thread.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_fetch_records_returns_empty_list_when_no_records(self):
        """fetch_records returns empty list when Airtable table has no records."""
        from app.integrations.adapters.airtable import AirtableAdapter

        adapter = AirtableAdapter(api_key="test_key", base_id="appTEST")
        mock_table = MagicMock()

        with patch.object(adapter, "_get_table", return_value=mock_table):
            with patch(
                "app.integrations.adapters.airtable.adapter.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value=[],
            ):
                result = await adapter.fetch_records(table_id="tblTEST")

        assert result == []


# ===========================================================================
# Task 3: crm_import_service.import_leads_from_crm()
# ===========================================================================


class TestImportLeadsFromCRM:
    """import_leads_from_crm() orchestrates Airtable → Qora import."""

    @pytest.mark.asyncio
    async def test_import_result_has_counts(self, tmp_path, monkeypatch):
        """import_leads_from_crm returns ImportResult with created/updated/skipped/errors."""
        from app.integrations import crm_import_service

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        crm_yaml = tmp_path / "test-client" / "crm.yaml"
        crm_yaml.parent.mkdir()
        crm_yaml.write_text(
            """
provider: airtable
base_id: appTEST
table_id: tblTEST
api_key_env: TEST_AIRTABLE_KEY
match_field: lead_id
field_mappings:
  - source: name
    target: "Nombre Completo"
    type: string
  - source: phone
    target: "Teléfono"
    type: phone
""",
            encoding="utf-8",
        )

        mock_records = [
            {
                "id": "recABC",
                "fields": {
                    "Nombre Completo": "New User",
                    "Teléfono": "+5491199998888",
                },
            }
        ]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        # Simulate: no existing lead by phone
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
        ) as mock_load, patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            from app.integrations.crm_config import CRMConfig, CRMFieldDef

            mock_config = MagicMock(spec=CRMConfig)
            mock_config.provider = "airtable"
            mock_config.base_id = "appTEST"
            mock_config.table_id = "tblTEST"
            mock_config.field_mappings = [
                CRMFieldDef(source="name", target="Nombre Completo", type="string"),
                CRMFieldDef(source="phone", target="Teléfono", type="phone"),
            ]
            mock_config.status_mapping = None
            mock_config.import_status_mapping = None
            mock_config.resolve_api_key.return_value = "pat_test"
            mock_load.return_value = mock_config

            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db, clients_root=tmp_path
            )

        assert hasattr(result, "created")
        assert hasattr(result, "updated")
        assert hasattr(result, "skipped")
        assert hasattr(result, "errors")

    @pytest.mark.asyncio
    async def test_import_creates_new_lead_when_phone_not_found(
        self, tmp_path, monkeypatch
    ):
        """import_leads_from_crm creates a lead when no phone match exists."""
        from app.integrations import crm_import_service

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        mock_records = [
            {
                "id": "recNEW",
                "fields": {
                    "Nombre Completo": "Brand New Lead",
                    "Teléfono": "+5491199997777",
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre Completo", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.created == 1
        assert result.updated == 0
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_updates_existing_lead_when_phone_found(
        self, tmp_path, monkeypatch
    ):
        """import_leads_from_crm updates lead when phone match exists."""
        from app.integrations import crm_import_service
        from app.leads.models import Lead, LeadStatus

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        existing_lead = Lead(
            id="existing-123",
            client_id="test-client",
            name="Old Name",
            phone="+5491199996666",
            status=LeadStatus.NEW.value,
        )

        mock_records = [
            {
                "id": "recEXIST",
                "fields": {
                    "Nombre Completo": "Updated Name",
                    "Teléfono": "+5491199996666",
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre Completo", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=existing_lead)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.updated == 1
        assert result.created == 0
        # Name should be updated
        assert existing_lead.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_import_advances_status_when_imported_is_ahead(
        self, tmp_path, monkeypatch
    ):
        """Existing lead status='new' receiving status='quoted' → updates forward."""
        from app.integrations import crm_import_service
        from app.leads.models import Lead, LeadStatus

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        existing_lead = Lead(
            id="ahead-1",
            client_id="test-client",
            name="Lead",
            phone="+5491100001111",
            status=LeadStatus.NEW.value,
        )

        mock_records = [
            {
                "id": "recAHEAD",
                "fields": {
                    "Teléfono": "+5491100001111",
                    "Status": "quoted",
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
            CRMFieldDef(source="status", target="Status", type="string"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=existing_lead)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.updated == 1
        assert existing_lead.status == LeadStatus.QUOTED.value

    @pytest.mark.asyncio
    async def test_import_does_not_regress_status_when_imported_is_behind(
        self, tmp_path, monkeypatch
    ):
        """Existing lead status='quoted' receiving status='new' → does NOT regress."""
        from app.integrations import crm_import_service
        from app.leads.models import Lead, LeadStatus

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        existing_lead = Lead(
            id="behind-1",
            client_id="test-client",
            name="Lead",
            phone="+5491100002222",
            status=LeadStatus.QUOTED.value,
        )

        mock_records = [
            {
                "id": "recBEHIND",
                "fields": {
                    "Teléfono": "+5491100002222",
                    "Status": "new",
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
            CRMFieldDef(source="status", target="Status", type="string"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=existing_lead)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.updated == 1
        # Status must remain quoted — never regress to new
        assert existing_lead.status == LeadStatus.QUOTED.value

    @pytest.mark.asyncio
    async def test_import_stores_external_crm_id(self, tmp_path, monkeypatch):
        """import_leads_from_crm stores Airtable record ID as external_crm_id."""
        from app.integrations import crm_import_service

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        mock_records = [
            {
                "id": "recSTORED999",
                "fields": {
                    "Nombre Completo": "Some Lead",
                    "Teléfono": "+5491155554444",
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.provider = "airtable"
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre Completo", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = mock_scalar
        mock_db.flush = AsyncMock()

        created_leads = []

        def capture_add(obj):
            created_leads.append(obj)

        mock_db.add = MagicMock(side_effect=capture_add)

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.created == 1
        assert len(created_leads) == 1
        # The lead must have the Airtable record ID stored
        assert created_leads[0].external_crm_id == "recSTORED999"

    @pytest.mark.asyncio
    async def test_import_returns_no_op_when_no_crm_config(self, tmp_path):
        """import_leads_from_crm returns empty ImportResult when no crm.yaml exists."""
        from app.integrations import crm_import_service

        mock_db = AsyncMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=None,
        ):
            result = await crm_import_service.import_leads_from_crm(
                "no-config-client", mock_db
            )

        assert result.created == 0
        assert result.updated == 0
        assert result.skipped == 0
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_import_skips_record_missing_phone(self, tmp_path, monkeypatch):
        """Records without a phone field are skipped (phone required for dedup)."""
        from app.integrations import crm_import_service

        monkeypatch.setenv("TEST_AIRTABLE_KEY", "pat_test")

        mock_records = [
            {
                "id": "recNOPHONE",
                "fields": {
                    "Nombre Completo": "No Phone User",
                    # Teléfono is absent
                },
            }
        ]

        from app.integrations.crm_config import CRMConfig, CRMFieldDef

        mock_config = MagicMock(spec=CRMConfig)
        mock_config.base_id = "appTEST"
        mock_config.table_id = "tblTEST"
        mock_config.field_mappings = [
            CRMFieldDef(source="name", target="Nombre Completo", type="string"),
            CRMFieldDef(source="phone", target="Teléfono", type="phone"),
        ]
        mock_config.status_mapping = None
        mock_config.import_status_mapping = None
        mock_config.resolve_api_key.return_value = "pat_test"

        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        with patch(
            "app.integrations.crm_import_service.CRMConfigLoader.load",
            return_value=mock_config,
        ), patch(
            "app.integrations.crm_import_service.AirtableAdapter"
        ) as MockAdapter:
            mock_adapter_instance = AsyncMock()
            mock_adapter_instance.fetch_records = AsyncMock(return_value=mock_records)
            MockAdapter.return_value = mock_adapter_instance

            result = await crm_import_service.import_leads_from_crm(
                "test-client", mock_db
            )

        assert result.skipped == 1
        assert result.created == 0
        mock_db.add.assert_not_called()


# ===========================================================================
# Task 4: Lead model has external_crm_id column
# ===========================================================================


class TestLeadModelExternalCrmId:
    """Lead model must have external_crm_id field for bidirectional sync."""

    def test_lead_has_external_crm_id_attribute(self):
        """Lead model has external_crm_id attribute (nullable string)."""
        from app.leads.models import Lead

        lead = Lead(
            id="test-id",
            client_id="test-client",
            name="Test",
            phone="+54911999",
            status="new",
        )
        # Should be settable without error
        lead.external_crm_id = "recSOMETHING"
        assert lead.external_crm_id == "recSOMETHING"

    def test_lead_external_crm_id_defaults_to_none(self):
        """external_crm_id is None by default (nullable)."""
        from app.leads.models import Lead

        lead = Lead(
            id="test-id",
            client_id="test-client",
            name="Test",
            phone="+54911999",
            status="new",
        )
        assert lead.external_crm_id is None


# ===========================================================================
# Task 5: CRMConfig supports import_status_mapping
# ===========================================================================


class TestCRMConfigImportStatusMapping:
    """CRMConfig must accept optional import_status_mapping field."""

    def test_crm_config_accepts_import_status_mapping(self, tmp_path):
        """crm.yaml with import_status_mapping is loaded without error."""
        crm_yaml = tmp_path / "test-client" / "crm.yaml"
        crm_yaml.parent.mkdir()
        crm_yaml.write_text(
            """
provider: airtable
base_id: appTEST
table_id: tblTEST
api_key_env: TEST_KEY
match_field: lead_id
status_mapping:
  new: "Nuevo!"
import_status_mapping:
  "Nuevo!": new
field_mappings:
  - source: name
    target: "Nombre Completo"
    type: string
""",
            encoding="utf-8",
        )
        from app.integrations.crm_config import CRMConfigLoader

        config = CRMConfigLoader.load("test-client", clients_root=tmp_path)
        assert config is not None
        assert config.import_status_mapping == {"Nuevo!": "new"}

    def test_crm_config_import_status_mapping_defaults_to_none(self, tmp_path):
        """crm.yaml without import_status_mapping defaults to None."""
        crm_yaml = tmp_path / "test-client2" / "crm.yaml"
        crm_yaml.parent.mkdir()
        crm_yaml.write_text(
            """
provider: airtable
base_id: appTEST
table_id: tblTEST
api_key_env: TEST_KEY
match_field: lead_id
field_mappings:
  - source: name
    target: "Nombre Completo"
    type: string
""",
            encoding="utf-8",
        )
        from app.integrations.crm_config import CRMConfigLoader

        config = CRMConfigLoader.load("test-client2", clients_root=tmp_path)
        assert config is not None
        assert config.import_status_mapping is None


# ===========================================================================
# Task 6: API endpoint POST /api/v1/clients/{client_id}/crm/import
# ===========================================================================


class TestCRMImportEndpoint:
    """POST /api/v1/clients/{client_id}/crm/import triggers import and returns summary."""

    @pytest.mark.asyncio
    async def test_import_endpoint_returns_200_with_summary(self):
        """Endpoint returns 200 with created/updated/skipped/errors counts."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.integrations.crm_import_service import ImportResult

        mock_result = ImportResult(created=3, updated=1, skipped=0, errors=[])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        with patch(
            "app.integrations.crm_router.import_leads_from_crm",
            new=AsyncMock(return_value=mock_result),
        ), patch(
            "app.integrations.crm_router.async_session_factory",
            mock_factory,
        ), patch(
            "app.core.database.async_session_factory",
            mock_factory,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/clients/quintana-seguros/crm/import"
                )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 3
        assert data["updated"] == 1
        assert data["skipped"] == 0
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_import_endpoint_returns_200_with_empty_result_when_no_config(self):
        """Endpoint returns 200 with empty counts when client has no crm.yaml."""
        from httpx import AsyncClient, ASGITransport
        from app.main import app
        from app.integrations.crm_import_service import ImportResult

        mock_result = ImportResult(created=0, updated=0, skipped=0, errors=[])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        with patch(
            "app.integrations.crm_router.import_leads_from_crm",
            new=AsyncMock(return_value=mock_result),
        ), patch(
            "app.integrations.crm_router.async_session_factory",
            mock_factory,
        ), patch(
            "app.core.database.async_session_factory",
            mock_factory,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/clients/no-config-client/crm/import"
                )

        # Returns 200 with empty result — endpoint itself doesn't fail
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 0
        assert data["errors"] == []
