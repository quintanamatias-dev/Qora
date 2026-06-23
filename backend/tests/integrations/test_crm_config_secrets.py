"""Tests for Phase B8 — Secrets Management: CRMConfig enabled field and credential handling.

TDD RED phase (task 1.5): Defines expected behavior for changes to CRMConfig
that will be implemented in task 1.6 (GREEN).

Spec reference:
  openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md

Covered scenarios:
  - CRMConfig.enabled defaults to True for backward compat (existing crm.yaml unchanged)
  - CRMConfig.enabled=false is loaded correctly
  - CRMConfig.enabled=true is explicit and loads correctly
  - CRMConfig.resolve_api_key() rejects placeholder values via CredentialResolutionError
  - CRMConfig.resolve_api_key() resolves valid env var correctly
  - CRMConfig.resolve_api_key() returns literal values (non-ALL_CAPS) directly
  - Existing quintana crm.yaml loads with enabled defaulting to True
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_crm_yaml(client_dir: Path, data: dict) -> None:
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "crm.yaml").write_text(yaml.dump(data))


def _base_crm_data(api_key: str = "QUINTANA_AIRTABLE_API_KEY") -> dict:
    return {
        "provider": "airtable",
        "base_id": "appXXXXXXXX",
        "table_id": "tblYYYYYYYY",
        "api_key": api_key,
        "match_field": "phone",
        "field_mappings": [],
    }


# ---------------------------------------------------------------------------
# Task 1.5 — RED: enabled field on CRMConfig
# ---------------------------------------------------------------------------


class TestCRMConfigEnabledField:
    """CRMConfig must support an enabled field defaulting to True."""

    def test_enabled_defaults_to_true_when_not_in_yaml(self, tmp_path, monkeypatch):
        """crm.yaml without 'enabled' key → enabled defaults to True (backward compat)."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-test-key")

        client_dir = tmp_path / "clients" / "quintana-seguros"
        data = _base_crm_data("QUINTANA_AIRTABLE_API_KEY")
        # Explicitly ensure 'enabled' is NOT in the YAML
        assert "enabled" not in data
        _write_crm_yaml(client_dir, data)

        from app.integrations.crm_config import CRMConfigLoader
        config = CRMConfigLoader.load(
            "quintana-seguros", clients_root=tmp_path / "clients"
        )
        assert config is not None
        # The new enabled field must default to True
        assert config.enabled is True

    def test_enabled_false_loads_correctly(self, tmp_path, monkeypatch):
        """crm.yaml with enabled: false → CRMConfig.enabled is False."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-test-key")

        client_dir = tmp_path / "clients" / "quintana-seguros"
        data = _base_crm_data("QUINTANA_AIRTABLE_API_KEY")
        data["enabled"] = False
        _write_crm_yaml(client_dir, data)

        from app.integrations.crm_config import CRMConfigLoader
        config = CRMConfigLoader.load(
            "quintana-seguros", clients_root=tmp_path / "clients"
        )
        assert config is not None
        assert config.enabled is False

    def test_enabled_true_explicit_loads_correctly(self, tmp_path, monkeypatch):
        """crm.yaml with explicit enabled: true → CRMConfig.enabled is True."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-test-key")

        client_dir = tmp_path / "clients" / "quintana-seguros"
        data = _base_crm_data("QUINTANA_AIRTABLE_API_KEY")
        data["enabled"] = True
        _write_crm_yaml(client_dir, data)

        from app.integrations.crm_config import CRMConfigLoader
        config = CRMConfigLoader.load(
            "quintana-seguros", clients_root=tmp_path / "clients"
        )
        assert config is not None
        assert config.enabled is True

    def test_real_quintana_crm_yaml_loads_with_enabled_true(self, monkeypatch):
        """The real production quintana crm.yaml loads with enabled defaulting to True.

        This verifies backward compat: existing files without the field work correctly.
        """
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-test-real-key")

        from app.integrations.crm_config import CRMConfigLoader
        # Uses the real file at backend/clients/quintana-seguros/crm.yaml
        config = CRMConfigLoader.load("quintana-seguros")
        assert config is not None
        # Must default to True even though the real file has no 'enabled' key
        assert config.enabled is True


# ---------------------------------------------------------------------------
# Task 1.5 — RED: resolve_api_key() placeholder rejection
# ---------------------------------------------------------------------------


class TestCRMConfigResolveApiKeyPlaceholder:
    """resolve_api_key() must reject placeholder env var values."""

    @pytest.mark.parametrize("placeholder", [
        "change-me-before-production",
        "your-key-here",
        "TODO",
        "REPLACE_ME",
        "xxx",
        "changeme",
    ])
    def test_placeholder_env_value_raises_credential_resolution_error(
        self, tmp_path, monkeypatch, placeholder
    ):
        """When the env var for an ALL_CAPS api_key contains a placeholder → error raised."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", placeholder)

        from app.integrations.crm_config import CRMConfig, CredentialResolutionError

        # Build a CRMConfig directly with an ALL_CAPS api_key
        config = CRMConfig(
            provider="airtable",
            base_id="appXXX",
            table_id="tblXXX",
            api_key="QUINTANA_AIRTABLE_API_KEY",
            match_field="phone",
        )
        with pytest.raises(CredentialResolutionError) as exc_info:
            config.resolve_api_key()

        # Error message must name the variable (not the value)
        assert "QUINTANA_AIRTABLE_API_KEY" in str(exc_info.value)

    def test_valid_env_value_resolves_correctly(self, monkeypatch):
        """A valid, non-placeholder env var value is returned correctly."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-real-production-key")

        from app.integrations.crm_config import CRMConfig

        config = CRMConfig(
            provider="airtable",
            base_id="appXXX",
            table_id="tblXXX",
            api_key="QUINTANA_AIRTABLE_API_KEY",
            match_field="phone",
        )
        result = config.resolve_api_key()
        assert result == "pat-real-production-key"

    def test_literal_api_key_returned_directly(self, monkeypatch):
        """A non-ALL_CAPS literal api_key is returned as-is without env lookup."""
        from app.integrations.crm_config import CRMConfig

        config = CRMConfig(
            provider="airtable",
            base_id="appXXX",
            table_id="tblXXX",
            api_key="mydevkey",  # Not ALL_CAPS → literal
            match_field="phone",
        )
        result = config.resolve_api_key()
        assert result == "mydevkey"

    def test_missing_env_var_still_raises_credential_resolution_error(self, monkeypatch):
        """ALL_CAPS api_key with missing env var → CredentialResolutionError (unchanged from before)."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        from app.integrations.crm_config import CRMConfig, CredentialResolutionError

        config = CRMConfig(
            provider="airtable",
            base_id="appXXX",
            table_id="tblXXX",
            api_key="QUINTANA_AIRTABLE_API_KEY",
            match_field="phone",
        )
        with pytest.raises(CredentialResolutionError):
            config.resolve_api_key()
