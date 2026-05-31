"""Unit tests for CRM status mapping + zona/age field mapping.

Covers:
- Task 6: crm.yaml loads status_mapping section
- Task 7: CRM sync translates Qora status to CRM value when status_mapping present
- Task 8: crm.yaml field_mappings includes age + zona for quintana-seguros
- Task 9: _lead_to_dict includes zona and age
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _write_crm_yaml(client_dir: Path, data: dict) -> None:
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "crm.yaml").write_text(yaml.dump(data, allow_unicode=True))


# ---------------------------------------------------------------------------
# Task 6: status_mapping loaded from crm.yaml
# ---------------------------------------------------------------------------


def test_crm_config_loads_status_mapping(tmp_path: Path, monkeypatch):
    """CRMConfig must expose status_mapping dict when present in crm.yaml."""
    monkeypatch.setenv("TEST_KEY", "pat_secret")

    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "TEST_KEY",
            "match_field": "lead_id",
            "status_mapping": {
                "new": "Nuevo!",
                "called": "Contactado (en espera)",
                "quoted": "Cotizado",
                "interested": "COMPRÓ",
                "not_interested": "Perdido",
                "follow_up": "Recontactar",
            },
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros", clients_root=tmp_path / "clients")
    assert config is not None
    assert config.status_mapping is not None
    assert config.status_mapping["quoted"] == "Cotizado"
    assert config.status_mapping["new"] == "Nuevo!"
    assert config.status_mapping["interested"] == "COMPRÓ"


def test_crm_config_status_mapping_defaults_to_none(tmp_path: Path, monkeypatch):
    """When status_mapping is absent from crm.yaml, config.status_mapping is None."""
    monkeypatch.setenv("TEST_KEY", "pat_secret")

    client_dir = tmp_path / "clients" / "no-mapping-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "TEST_KEY",
            "match_field": "lead_id",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("no-mapping-client", clients_root=tmp_path / "clients")
    assert config is not None
    assert config.status_mapping is None


# ---------------------------------------------------------------------------
# Task 7: CRM sync payload applies status_mapping translation
# ---------------------------------------------------------------------------


def test_field_mapper_applies_status_mapping_for_status_field():
    """FieldMapper must translate the Qora status via status_mapping when provided."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [
        CRMFieldDef(source="name", target="Nombre", type="string"),
        CRMFieldDef(source="status", target="Status", type="string"),
    ]
    status_mapping = {
        "new": "Nuevo!",
        "called": "Contactado (en espera)",
        "quoted": "Cotizado",
        "interested": "COMPRÓ",
        "not_interested": "Perdido",
        "follow_up": "Recontactar",
    }
    mapper = FieldMapper(field_defs, status_mapping=status_mapping)
    payload = mapper.map({"name": "Ana García", "status": "quoted"})

    assert payload["Status"] == "Cotizado"
    assert payload["Nombre"] == "Ana García"


def test_field_mapper_no_status_mapping_passes_raw_status():
    """Without status_mapping, raw Qora status is used in the CRM payload."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="status", target="Status", type="string")]
    mapper = FieldMapper(field_defs)
    payload = mapper.map({"status": "quoted"})

    assert payload["Status"] == "quoted"


def test_field_mapper_unmapped_status_uses_raw_value():
    """If Qora status is not in status_mapping, use raw value (don't skip)."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="status", target="Status", type="string")]
    status_mapping = {"new": "Nuevo!"}  # only 'new' mapped
    mapper = FieldMapper(field_defs, status_mapping=status_mapping)
    payload = mapper.map({"status": "quoted"})

    # 'quoted' not in mapping → use raw value
    assert payload["Status"] == "quoted"


# ---------------------------------------------------------------------------
# Task 8: quintana-seguros crm.yaml has age + zona field mappings
# ---------------------------------------------------------------------------


def test_quintana_crm_yaml_has_age_field_mapping():
    """The real quintana-seguros crm.yaml must map 'age' → 'Edad'."""
    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros")
    assert config is not None, "quintana-seguros must have a crm.yaml"

    sources = {fm.source for fm in config.field_mappings}
    assert "age" in sources, "crm.yaml must include field mapping for 'age'"

    age_fm = next(fm for fm in config.field_mappings if fm.source == "age")
    assert age_fm.target == "Edad"
    assert age_fm.type == "integer"


def test_quintana_crm_yaml_has_zona_field_mapping():
    """The real quintana-seguros crm.yaml must map 'zona' → 'Zona'."""
    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros")
    assert config is not None, "quintana-seguros must have a crm.yaml"

    sources = {fm.source for fm in config.field_mappings}
    assert "zona" in sources, "crm.yaml must include field mapping for 'zona'"

    zona_fm = next(fm for fm in config.field_mappings if fm.source == "zona")
    assert zona_fm.target == "Zona"
    assert zona_fm.type == "string"


def test_quintana_crm_yaml_has_status_mapping():
    """The real quintana-seguros crm.yaml must have a status_mapping section."""
    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros")
    assert config is not None, "quintana-seguros must have a crm.yaml"
    assert config.status_mapping is not None, "quintana-seguros crm.yaml must have status_mapping"
    assert "quoted" in config.status_mapping
    assert config.status_mapping["quoted"] == "Cotizado"


# ---------------------------------------------------------------------------
# Task 9: _lead_to_dict includes zona and age
# ---------------------------------------------------------------------------


class _FakeLead:
    """Minimal Lead-like object for testing _lead_to_dict."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "lead-123")
        self.client_id = kwargs.get("client_id", "quintana-seguros")
        self.name = kwargs.get("name", "Test Lead")
        self.phone = kwargs.get("phone", "+5491100000000")
        self.status = kwargs.get("status", "new")
        self.notes = kwargs.get("notes")
        self.car_make = kwargs.get("car_make")
        self.car_model = kwargs.get("car_model")
        self.car_year = kwargs.get("car_year")
        self.current_insurance = kwargs.get("current_insurance")
        self.email = kwargs.get("email")
        self.age = kwargs.get("age")
        self.zona = kwargs.get("zona")
        self.summary_last_call = kwargs.get("summary_last_call")
        self.interest_level = kwargs.get("interest_level")
        self.do_not_call = kwargs.get("do_not_call", False)
        self.next_action = kwargs.get("next_action")
        self.call_count = kwargs.get("call_count", 0)


def test_lead_to_dict_includes_zona():
    """_lead_to_dict must include 'zona' key."""
    from app.integrations.crm_sync_service import _lead_to_dict

    lead = _FakeLead(zona="Palermo")
    result = _lead_to_dict(lead)
    assert "zona" in result
    assert result["zona"] == "Palermo"


def test_lead_to_dict_includes_zona_when_none():
    """_lead_to_dict must include 'zona' key even when value is None."""
    from app.integrations.crm_sync_service import _lead_to_dict

    lead = _FakeLead(zona=None)
    result = _lead_to_dict(lead)
    assert "zona" in result
    assert result["zona"] is None


def test_lead_to_dict_includes_age():
    """_lead_to_dict must include 'age' key."""
    from app.integrations.crm_sync_service import _lead_to_dict

    lead = _FakeLead(age=35)
    result = _lead_to_dict(lead)
    assert "age" in result
    assert result["age"] == 35
