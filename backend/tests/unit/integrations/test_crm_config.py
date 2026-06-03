"""Unit tests for CRM config loader — TDD RED phase.

Covers spec scenarios:
- FM-1: valid crm.yaml loads without error
- FM-2: all required fields validated at load time
- FM-3: credentials resolved from env var, never stored in config object
- FM-4: missing crm.yaml returns None (silent skip)
- FM-2/variant: missing match_field raises ConfigValidationError
- FM-3/variant: missing env var raises CredentialResolutionError

Test layer: Unit (tmp_path YAML fixtures, monkeypatch env — no IO to real FS).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helper to write a crm.yaml to a tmp client dir
# ---------------------------------------------------------------------------


def _write_crm_yaml(client_dir: Path, data: dict) -> None:
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "crm.yaml").write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# 1. Valid config loads without error (FM-1, FM-2, FM-3)
# ---------------------------------------------------------------------------


def test_load_valid_crm_config_returns_config(tmp_path: Path, monkeypatch):
    """A well-formed crm.yaml with all required fields loads successfully."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_secret")

    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXXXXXXXXXXXX",
            "table_id": "tblYYYYYYYYYYYYYY",
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [
                {"source": "name", "target": "Nombre", "type": "string", "required": True},
                {"source": "phone", "target": "Teléfono", "type": "phone", "required": True},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros", clients_root=tmp_path / "clients")

    assert config is not None
    assert config.provider == "airtable"
    assert config.base_id == "appXXXXXXXXXXXXXX"
    assert config.table_id == "tblYYYYYYYYYYYYYY"
    assert config.match_field == "phone"
    assert len(config.field_mappings) == 2
    assert config.field_mappings[0].source == "name"
    assert config.field_mappings[1].target == "Teléfono"


def test_api_key_resolved_from_env_not_stored_in_config(tmp_path: Path, monkeypatch):
    """FM-3: resolved API key is available via resolve_api_key() but NOT stored."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_secret")

    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXXXXXXXXXXXX",
            "table_id": "tblYYYYYYYYYYYYYY",
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros", clients_root=tmp_path / "clients")

    assert config is not None
    # api_key_env stores the KEY NAME, not the secret value
    assert config.api_key_env == "QUINTANA_AIRTABLE_API_KEY"
    # The resolved secret is accessible via helper — not a bare string attribute
    resolved = config.resolve_api_key()
    assert resolved == "pat_test_secret"
    # Confirm the raw secret is not in the model's dict representation
    config_dict = config.model_dump()
    assert "pat_test_secret" not in str(config_dict)


# ---------------------------------------------------------------------------
# 2. Missing crm.yaml returns None (FM-4 — silent skip)
# ---------------------------------------------------------------------------


def test_missing_crm_yaml_returns_none(tmp_path: Path):
    """FM-4: client with no crm.yaml returns None — sync should be skipped."""
    clients_root = tmp_path / "clients"
    clients_root.mkdir(parents=True)
    # No crm.yaml written — client dir doesn't even exist

    from app.integrations.crm_config import CRMConfigLoader

    result = CRMConfigLoader.load("no-crm-client", clients_root=clients_root)

    assert result is None


def test_crm_yaml_absent_from_existing_client_dir_returns_none(tmp_path: Path):
    """FM-4: client dir exists but crm.yaml not present → None."""
    client_dir = tmp_path / "clients" / "some-client"
    client_dir.mkdir(parents=True)
    # Directory exists but no crm.yaml

    from app.integrations.crm_config import CRMConfigLoader

    result = CRMConfigLoader.load("some-client", clients_root=tmp_path / "clients")

    assert result is None


# ---------------------------------------------------------------------------
# 3. Missing required field raises ConfigValidationError (FM-2)
# ---------------------------------------------------------------------------


def test_missing_match_field_raises_config_validation_error(tmp_path: Path, monkeypatch):
    """FM-2: crm.yaml without match_field raises ConfigValidationError."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")

    client_dir = tmp_path / "clients" / "bad-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            # match_field intentionally omitted
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("bad-client", clients_root=tmp_path / "clients")


def test_missing_base_id_raises_config_validation_error(tmp_path: Path, monkeypatch):
    """FM-2: crm.yaml without base_id raises ConfigValidationError."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")

    client_dir = tmp_path / "clients" / "bad-client-base"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            # base_id intentionally omitted
            "table_id": "tblYYYY",
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("bad-client-base", clients_root=tmp_path / "clients")


def test_spec_shaped_crm_yaml_aliases_load_successfully(tmp_path: Path, monkeypatch):
    """Spec compatibility: adapter/credentials_key aliases map to canonical fields."""
    monkeypatch.setenv("TEST_API_KEY", "test_secret")

    client_dir = tmp_path / "clients" / "spec-shaped-client"
    _write_crm_yaml(
        client_dir,
        {
            "adapter": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "credentials_key": "TEST_API_KEY",
            "match_field": "phone",
            "field_map": [
                {"source": "phone", "target": "Teléfono", "type": "phone", "required": True},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("spec-shaped-client", clients_root=tmp_path / "clients")

    assert config is not None
    assert config.provider == "airtable"
    assert config.api_key_env == "TEST_API_KEY"
    assert len(config.field_mappings) == 1
    assert config.field_mappings[0].source == "phone"
    assert config.resolve_api_key() == "test_secret"


def test_field_mapping_singular_alias_loads_successfully(tmp_path: Path, monkeypatch):
    """Backward compatibility: field_mapping singular alias maps to field_mappings."""
    monkeypatch.setenv("TEST_API_KEY", "test_secret")

    client_dir = tmp_path / "clients" / "singular-field-mapping-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "TEST_API_KEY",
            "match_field": "phone",
            "field_mapping": [
                {"source": "name", "target": "Nombre", "type": "string"},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load(
        "singular-field-mapping-client", clients_root=tmp_path / "clients"
    )

    assert config is not None
    assert len(config.field_mappings) == 1
    assert config.field_mappings[0].target == "Nombre"


def test_missing_api_key_env_field_raises_config_validation_error(tmp_path: Path):
    """FM-2: crm.yaml without api_key_env raises ConfigValidationError."""
    client_dir = tmp_path / "clients" / "bad-client2"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            # api_key_env intentionally omitted
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("bad-client2", clients_root=tmp_path / "clients")


def test_missing_table_id_raises_config_validation_error(tmp_path: Path, monkeypatch):
    """FM-2: crm.yaml without table_id raises ConfigValidationError."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")

    client_dir = tmp_path / "clients" / "bad-client3"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            # table_id omitted
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("bad-client3", clients_root=tmp_path / "clients")


# ---------------------------------------------------------------------------
# 4. Missing env var raises CredentialResolutionError (FM-3)
# ---------------------------------------------------------------------------


def test_missing_env_var_raises_credential_resolution_error(tmp_path: Path, monkeypatch):
    """FM-3: credentials_key env var not set raises CredentialResolutionError."""
    # Ensure the env var is NOT set
    monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
            "match_field": "phone",
            "field_mappings": [],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, CredentialResolutionError

    config = CRMConfigLoader.load("quintana-seguros", clients_root=tmp_path / "clients")
    assert config is not None  # load succeeds; error deferred to resolve time

    with pytest.raises(CredentialResolutionError):
        config.resolve_api_key()


# ---------------------------------------------------------------------------
# 5. Field mappings validate correctly (FM-5, FM-6)
# ---------------------------------------------------------------------------


def test_field_mappings_loaded_with_all_types(tmp_path: Path, monkeypatch):
    """FM-6: arbitrary key-value field_map entries load without error."""
    monkeypatch.setenv("TEST_API_KEY", "test_secret")

    client_dir = tmp_path / "clients" / "full-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "TEST_API_KEY",
            "match_field": "phone",
            "field_mappings": [
                {"source": "name", "target": "Nombre", "type": "string", "required": True},
                {"source": "phone", "target": "Teléfono", "type": "phone", "required": True},
                {"source": "age", "target": "Edad", "type": "integer"},
                {"source": "summary_last_call", "target": "Resumen", "type": "string"},
                {"source": "interest_level", "target": "Interés", "type": "integer"},
                {"source": "status", "target": "Estado", "type": "string"},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("full-client", clients_root=tmp_path / "clients")

    assert config is not None
    assert len(config.field_mappings) == 6
    # Verify specific field def attributes
    phone_field = next(f for f in config.field_mappings if f.source == "phone")
    assert phone_field.target == "Teléfono"
    assert phone_field.type == "phone"
    assert phone_field.required is True

    age_field = next(f for f in config.field_mappings if f.source == "age")
    assert age_field.type == "integer"
    assert age_field.required is False  # default


# ---------------------------------------------------------------------------
# 6. Unknown field type rejected at validation time (no silent str() fallback)
# ---------------------------------------------------------------------------


def test_unknown_field_type_raises_config_validation_error(tmp_path: Path, monkeypatch):
    """An unsupported CRMFieldDef.type must fail validation, not silently fall back."""
    monkeypatch.setenv("TEST_API_KEY", "test_secret")

    client_dir = tmp_path / "clients" / "bad-type-client"
    _write_crm_yaml(
        client_dir,
        {
            "provider": "airtable",
            "base_id": "appXXXX",
            "table_id": "tblYYYY",
            "api_key_env": "TEST_API_KEY",
            "match_field": "phone",
            "field_mappings": [
                {"source": "name", "target": "Nombre", "type": "frobnicate"},
            ],
        },
    )

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("bad-type-client", clients_root=tmp_path / "clients")


def test_unknown_field_type_rejected_on_direct_model_construction():
    """CRMFieldDef rejects an unsupported type via Pydantic Literal validation."""
    from pydantic import ValidationError
    from app.integrations.crm_config import CRMFieldDef

    with pytest.raises(ValidationError):
        CRMFieldDef(source="name", target="Nombre", type="frobnicate")


# ---------------------------------------------------------------------------
# 7. Malformed YAML wrapped in ConfigValidationError (issue 6)
# ---------------------------------------------------------------------------


def test_malformed_yaml_raises_config_validation_error(tmp_path: Path):
    """A syntactically broken crm.yaml must raise ConfigValidationError, not a raw YAMLError."""
    client_dir = tmp_path / "clients" / "broken-yaml-client"
    client_dir.mkdir(parents=True)
    # Invalid YAML: unbalanced bracket / bad indentation
    (client_dir / "crm.yaml").write_text("provider: airtable\n  base_id: [unclosed\n")

    from app.integrations.crm_config import CRMConfigLoader, ConfigValidationError

    with pytest.raises(ConfigValidationError):
        CRMConfigLoader.load("broken-yaml-client", clients_root=tmp_path / "clients")
