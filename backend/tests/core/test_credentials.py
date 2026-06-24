"""Tests for Phase B8 — Secrets Management: Centralized credential validation.

TDD RED phase (task 1.3): These tests define the expected behavior for the
credentials.py module that will be created in task 1.4 (GREEN).

Spec references:
  - openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md
  - openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
    (Requirement: Placeholder Value Rejection)

Covered scenarios:
  - is_weak_placeholder(): detects all known placeholder patterns (case-insensitive)
  - is_weak_placeholder(): does not flag real values
  - validate_all_integration_credentials(): active CRM with present key → no error
  - validate_all_integration_credentials(): active CRM with missing key → SystemExit
  - validate_all_integration_credentials(): active CRM with placeholder key → SystemExit
  - validate_all_integration_credentials(): disabled CRM (enabled: false) → skipped
  - validate_all_integration_credentials(): no crm.yaml → skipped, no error
  - validate_all_integration_credentials(): empty clients root → no error
  - validate_all_integration_credentials(): global Qora credentials NOT validated here
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_crm_yaml(client_dir: Path, data: dict) -> None:
    """Write a crm.yaml to a temporary client directory."""
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "crm.yaml").write_text(yaml.dump(data))


def _base_crm_data(api_key: str = "QUINTANA_AIRTABLE_API_KEY") -> dict:
    """Return a minimal valid crm.yaml data dict."""
    return {
        "provider": "airtable",
        "base_id": "appXXXXXXXX",
        "table_id": "tblYYYYYYYY",
        "api_key": api_key,
        "match_field": "phone",
        "field_mappings": [
            {"source": "name", "target": "Nombre", "type": "string", "required": False},
        ],
    }


# ---------------------------------------------------------------------------
# Task 1.3 — RED: is_weak_placeholder()
# ---------------------------------------------------------------------------


class TestIsWeakPlaceholder:
    """Unit tests for the placeholder detection utility function."""

    @pytest.mark.parametrize("value", [
        "change-me-before-production",
        "CHANGE-ME-BEFORE-PRODUCTION",  # case-insensitive
        "Change-Me-Before-Production",
        "your-key-here",
        "YOUR-KEY-HERE",
        "TODO",
        "todo",
        "REPLACE_ME",
        "replace_me",
        "xxx",
        "XXX",
        "test",
        "TEST",
        "changeme",
        "CHANGEME",
    ])
    def test_known_placeholders_are_detected(self, value):
        """Each known placeholder pattern must be detected (case-insensitive)."""
        from app.core.credentials import is_weak_placeholder
        assert is_weak_placeholder(value) is True

    @pytest.mark.parametrize("value", [
        "sk-proj-abcdefghijklmnopqrstuvwx",
        "pat_1234567890abcdef",
        "el-api-key-real",
        "qora-local-dev-key",          # not in the list
        "my-local-key",                # not in the list
        "strongpassword123",
        "el-prod-key-abc123",
    ])
    def test_real_values_are_not_flagged(self, value):
        """Non-placeholder values must return False."""
        from app.core.credentials import is_weak_placeholder
        assert is_weak_placeholder(value) is False

    def test_empty_string_not_flagged_as_placeholder(self):
        """Empty string is not a 'placeholder'; it's 'missing' — different check."""
        from app.core.credentials import is_weak_placeholder
        # Empty string is handled by the presence check, not placeholder check
        assert is_weak_placeholder("") is False


# ---------------------------------------------------------------------------
# Task 1.3 — RED: validate_all_integration_credentials()
# ---------------------------------------------------------------------------


class TestValidateAllIntegrationCredentials:
    """Unit tests for the startup CRM credential validator."""

    def test_active_crm_with_valid_key_does_not_raise(self, tmp_path, monkeypatch):
        """Active CRM integration with a present, valid env var → no error."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-real-key-abc123")

        clients_root = tmp_path / "clients"
        client_dir = clients_root / "quintana-seguros"
        _write_crm_yaml(client_dir, _base_crm_data("QUINTANA_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        # Must complete without raising
        validate_all_integration_credentials(clients_root=clients_root)

    def test_active_crm_with_missing_key_raises_system_exit(self, tmp_path, monkeypatch):
        """Active CRM integration with a missing env var → SystemExit naming the client and var."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        clients_root = tmp_path / "clients"
        client_dir = clients_root / "quintana-seguros"
        _write_crm_yaml(client_dir, _base_crm_data("QUINTANA_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        with pytest.raises(SystemExit) as exc_info:
            validate_all_integration_credentials(clients_root=clients_root)

        message = str(exc_info.value).upper()
        assert "QUINTANA_AIRTABLE_API_KEY" in message or "QUINTANA" in message

    def test_active_crm_with_placeholder_key_raises_system_exit(self, tmp_path, monkeypatch):
        """Active CRM integration with a placeholder credential → SystemExit."""
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "change-me-before-production")

        clients_root = tmp_path / "clients"
        client_dir = clients_root / "quintana-seguros"
        _write_crm_yaml(client_dir, _base_crm_data("QUINTANA_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        with pytest.raises(SystemExit):
            validate_all_integration_credentials(clients_root=clients_root)

    def test_disabled_crm_integration_is_skipped(self, tmp_path, monkeypatch):
        """CRM with enabled: false is skipped — no credential validation performed."""
        monkeypatch.delenv("QUINTANA_AIRTABLE_API_KEY", raising=False)

        clients_root = tmp_path / "clients"
        client_dir = clients_root / "quintana-seguros"
        data = _base_crm_data("QUINTANA_AIRTABLE_API_KEY")
        data["enabled"] = False
        _write_crm_yaml(client_dir, data)

        from app.core.credentials import validate_all_integration_credentials
        # Disabled integration → must NOT raise even with missing key
        validate_all_integration_credentials(clients_root=clients_root)

    def test_client_without_crm_yaml_is_skipped(self, tmp_path):
        """Client directory without crm.yaml → no credential check, no error."""
        clients_root = tmp_path / "clients"
        # Create client dir but no crm.yaml
        (clients_root / "no-crm-client").mkdir(parents=True)

        from app.core.credentials import validate_all_integration_credentials
        validate_all_integration_credentials(clients_root=clients_root)

    def test_empty_clients_root_does_not_raise(self, tmp_path):
        """Empty clients root directory → nothing to validate, no error."""
        clients_root = tmp_path / "clients"
        clients_root.mkdir(parents=True)

        from app.core.credentials import validate_all_integration_credentials
        validate_all_integration_credentials(clients_root=clients_root)

    def test_nonexistent_clients_root_does_not_raise(self, tmp_path):
        """If the clients root path does not exist, validation is skipped gracefully."""
        clients_root = tmp_path / "does-not-exist"

        from app.core.credentials import validate_all_integration_credentials
        validate_all_integration_credentials(clients_root=clients_root)

    def test_global_qora_credentials_not_validated_by_crm_validator(self, tmp_path, monkeypatch):
        """The CRM validator must NOT look up OPENAI_API_KEY or ELEVENLABS_API_KEY.

        Those are managed by Settings. The CRM validator only validates per-client
        integration env var references found in crm.yaml files.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat-real-key")

        clients_root = tmp_path / "clients"
        client_dir = clients_root / "quintana-seguros"
        _write_crm_yaml(client_dir, _base_crm_data("QUINTANA_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        # Must NOT raise just because OPENAI/EL keys are missing
        validate_all_integration_credentials(clients_root=clients_root)

    def test_multiple_clients_all_valid(self, tmp_path, monkeypatch):
        """Multiple clients with valid credentials → all pass without error."""
        monkeypatch.setenv("CLIENT_A_AIRTABLE_API_KEY", "pat-client-a-key")
        monkeypatch.setenv("CLIENT_B_AIRTABLE_API_KEY", "pat-client-b-key")

        clients_root = tmp_path / "clients"
        _write_crm_yaml(clients_root / "client-a", _base_crm_data("CLIENT_A_AIRTABLE_API_KEY"))
        _write_crm_yaml(clients_root / "client-b", _base_crm_data("CLIENT_B_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        validate_all_integration_credentials(clients_root=clients_root)

    def test_one_of_multiple_clients_missing_key_raises(self, tmp_path, monkeypatch):
        """When one of multiple clients has a missing credential → SystemExit."""
        monkeypatch.setenv("CLIENT_A_AIRTABLE_API_KEY", "pat-client-a-key")
        monkeypatch.delenv("CLIENT_B_AIRTABLE_API_KEY", raising=False)

        clients_root = tmp_path / "clients"
        _write_crm_yaml(clients_root / "client-a", _base_crm_data("CLIENT_A_AIRTABLE_API_KEY"))
        _write_crm_yaml(clients_root / "client-b", _base_crm_data("CLIENT_B_AIRTABLE_API_KEY"))

        from app.core.credentials import validate_all_integration_credentials
        with pytest.raises(SystemExit):
            validate_all_integration_credentials(clients_root=clients_root)

    def test_literal_api_key_in_crm_yaml_not_treated_as_env_var(self, tmp_path, monkeypatch):
        """A literal (non-ALL_CAPS) api_key in crm.yaml is used directly, not as env var name."""
        # The env var is NOT set — but the api_key is a literal value, not an env var name
        monkeypatch.delenv("mytestapikey123", raising=False)

        clients_root = tmp_path / "clients"
        _write_crm_yaml(clients_root / "dev-client", _base_crm_data("mytestapikey123"))

        from app.core.credentials import validate_all_integration_credentials
        # Literal key → no env var lookup → should not raise
        validate_all_integration_credentials(clients_root=clients_root)
