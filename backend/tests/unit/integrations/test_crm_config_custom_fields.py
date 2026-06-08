"""Tests for CRM config custom_fields, quote_ready_fields, and api_key heuristic.

Spec: dynamic-lead-fields WU-1 task 1.3
Requirements: QR-3, QR-4, duplicate field rejection

TDD RED phase:
- CustomFieldDef model validation
- custom_fields and quote_ready_fields loaded from crm.yaml
- api_key field (new) with resolve_api_key() heuristic
- api_key_env backward compatibility
- Duplicate field_key in custom_fields rejected at load time
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
    (client_dir / "crm.yaml").write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# QR-3: field_definitions (custom fields) loaded from crm.yaml
# ---------------------------------------------------------------------------


def test_crm_config_loads_custom_field_definitions(tmp_path: Path, monkeypatch):
    """QR-3: CRMConfig loads field_definitions as list[CustomFieldDef].

    GIVEN crm.yaml with field_definitions entries
    WHEN CRMConfigLoader.load() is called
    THEN config.custom_fields contains CustomFieldDef objects with field_key/field_type/label
    """
    monkeypatch.setenv("TEST_KEY", "literal-value")

    client_dir = tmp_path / "clients" / "test-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "TEST_KEY",
            "match_field": "phone",
            "field_mappings": [],
            "field_definitions": [
                {"field_key": "car_make", "field_type": "string", "label": "Car Make"},
                {"field_key": "car_year", "field_type": "integer", "label": "Car Year"},
                {"field_key": "age", "field_type": "integer", "label": "Age"},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("test-client", clients_root=tmp_path / "clients")

    assert config is not None
    assert len(config.custom_fields) == 3

    car_make = next(f for f in config.custom_fields if f.field_key == "car_make")
    assert car_make.field_type == "string"
    assert car_make.label == "Car Make"

    car_year = next(f for f in config.custom_fields if f.field_key == "car_year")
    assert car_year.field_type == "integer"


def test_crm_config_custom_fields_default_to_empty_list(tmp_path: Path, monkeypatch):
    """QR-3: CRMConfig.custom_fields defaults to [] when field_definitions is absent."""
    monkeypatch.setenv("TEST_KEY", "pat-abc123")

    client_dir = tmp_path / "clients" / "no-custom-fields"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "TEST_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("no-custom-fields", clients_root=tmp_path / "clients")

    assert config is not None
    assert config.custom_fields == []


def test_custom_field_def_accepts_all_valid_types():
    """QR-3: CustomFieldDef validates field_type against the allowed enum."""
    from app.integrations.crm_config import CustomFieldDef

    for field_type in ["string", "integer", "boolean", "date", "phone"]:
        field = CustomFieldDef(field_key="test_key", field_type=field_type, label="Test")
        assert field.field_type == field_type


def test_custom_field_def_rejects_unknown_type():
    """QR-3: CustomFieldDef rejects unknown field_type via Pydantic Literal."""
    from pydantic import ValidationError
    from app.integrations.crm_config import CustomFieldDef

    with pytest.raises(ValidationError):
        CustomFieldDef(field_key="test_key", field_type="frobnicate", label="Test")


# ---------------------------------------------------------------------------
# QR-3 extension: quote_ready_fields
# ---------------------------------------------------------------------------


def test_crm_config_loads_quote_ready_fields(tmp_path: Path, monkeypatch):
    """QR-3: CRMConfig loads quote_ready_fields as list[str].

    GIVEN crm.yaml with quote_ready_fields: [car_make, car_year, age]
    WHEN CRMConfigLoader.load() is called
    THEN config.quote_ready_fields == ['car_make', 'car_year', 'age']
    """
    monkeypatch.setenv("TEST_KEY", "pat-abc123")

    client_dir = tmp_path / "clients" / "qrf-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "TEST_KEY",
            "match_field": "phone",
            "field_mappings": [],
            "quote_ready_fields": ["car_make", "car_year", "age"],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("qrf-client", clients_root=tmp_path / "clients")

    assert config is not None
    assert config.quote_ready_fields == ["car_make", "car_year", "age"]


def test_crm_config_quote_ready_fields_default_to_empty_list(tmp_path: Path, monkeypatch):
    """QR-3: quote_ready_fields defaults to [] when absent from crm.yaml."""
    monkeypatch.setenv("TEST_KEY", "pat-abc123")

    client_dir = tmp_path / "clients" / "no-qrf"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "TEST_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("no-qrf", clients_root=tmp_path / "clients")

    assert config is not None
    assert config.quote_ready_fields == []


# ---------------------------------------------------------------------------
# QR-4: api_key field with resolve_api_key() heuristic
# ---------------------------------------------------------------------------


def test_resolve_api_key_env_var_name_looks_up_env(tmp_path: Path, monkeypatch):
    """QR-4: api_key value matching ^[A-Z][A-Z0-9_]+$ → env var lookup.

    GIVEN api_key='QUINTANA_AIRTABLE_API_KEY' (ALL_CAPS_UNDERSCORE)
    AND env var QUINTANA_AIRTABLE_API_KEY='pat_secret_token'
    WHEN resolve_api_key() is called
    THEN it returns 'pat_secret_token' (env var value)
    """
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_secret_token")

    client_dir = tmp_path / "clients" / "env-lookup"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("env-lookup", clients_root=tmp_path / "clients")
    assert config is not None
    assert config.resolve_api_key() == "pat_secret_token"


def test_resolve_api_key_literal_value_returned_directly(tmp_path: Path):
    """QR-4: api_key value NOT matching ^[A-Z][A-Z0-9_]+$ → literal value.

    GIVEN api_key='pat.abcdefghijklmnop' (Airtable PAT format — not ALL_CAPS)
    WHEN resolve_api_key() is called
    THEN it returns the value directly without env lookup
    """
    client_dir = tmp_path / "clients" / "literal-key"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "pat.abcdefghijklmnop",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("literal-key", clients_root=tmp_path / "clients")
    assert config is not None
    assert config.resolve_api_key() == "pat.abcdefghijklmnop"


def test_resolve_api_key_lowercase_env_name_returns_literal(tmp_path: Path):
    """QR-4: api_key 'mykey_abc' (lowercase) → treated as literal (not env var name)."""
    client_dir = tmp_path / "clients" / "lower-key"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "my_literal_token",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("lower-key", clients_root=tmp_path / "clients")
    assert config is not None
    # lowercase → not an env var name → literal
    assert config.resolve_api_key() == "my_literal_token"


def test_resolve_api_key_env_var_not_set_raises(tmp_path: Path, monkeypatch):
    """QR-4: api_key looks like env var name but env var is unset → CredentialResolutionError."""
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    client_dir = tmp_path / "clients" / "missing-env"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "MISSING_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, CredentialResolutionError

    config = CRMConfigLoader.load("missing-env", clients_root=tmp_path / "clients")
    assert config is not None

    with pytest.raises(CredentialResolutionError):
        config.resolve_api_key()


# ---------------------------------------------------------------------------
# QR-4: api_key_env backward compat — both field names accepted
# ---------------------------------------------------------------------------


def test_api_key_env_old_field_name_still_works(tmp_path: Path, monkeypatch):
    """QR-4 backward compat: api_key_env still accepted as field name in crm.yaml.

    GIVEN crm.yaml uses old api_key_env field name
    WHEN CRMConfigLoader.load() is called
    THEN config.api_key is populated and resolve_api_key() works as expected
    """
    monkeypatch.setenv("OLD_ENV_KEY", "old-secret-value")

    client_dir = tmp_path / "clients" / "old-format"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "OLD_ENV_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("old-format", clients_root=tmp_path / "clients")
    assert config is not None
    # Old api_key_env must still resolve correctly
    assert config.resolve_api_key() == "old-secret-value"


# ---------------------------------------------------------------------------
# Duplicate field_key rejection
# ---------------------------------------------------------------------------


def test_duplicate_field_key_in_custom_fields_raises_at_load(tmp_path: Path, monkeypatch):
    """Duplicate field_key in field_definitions must be rejected at load time.

    GIVEN crm.yaml has two entries with the same field_key='car_make'
    WHEN CRMConfigLoader.load() is called
    THEN ConfigValidationError is raised
    """
    monkeypatch.setenv("TEST_KEY", "literal-value")

    client_dir = tmp_path / "clients" / "dup-fields"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key": "TEST_KEY",
            "match_field": "phone",
            "field_mappings": [],
            "field_definitions": [
                {"field_key": "car_make", "field_type": "string", "label": "Car Make"},
                {"field_key": "car_make", "field_type": "string", "label": "Duplicate"},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("dup-fields", clients_root=tmp_path / "clients")


# ---------------------------------------------------------------------------
# CustomFieldDef model direct tests
# ---------------------------------------------------------------------------


def test_custom_field_def_has_required_fields():
    """CustomFieldDef requires field_key, field_type, label."""
    from app.integrations.crm_config import CustomFieldDef

    field = CustomFieldDef(field_key="car_year", field_type="integer", label="Car Year")
    assert field.field_key == "car_year"
    assert field.field_type == "integer"
    assert field.label == "Car Year"
    assert field.required is False  # default


def test_custom_field_def_required_flag():
    """CustomFieldDef.required can be set to True."""
    from app.integrations.crm_config import CustomFieldDef

    field = CustomFieldDef(field_key="age", field_type="integer", label="Age", required=True)
    assert field.required is True
