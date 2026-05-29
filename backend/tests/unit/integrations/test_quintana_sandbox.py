"""Quintana sandbox crm.yaml structural tests — TDD RED/GREEN phase 3.3.

Spec: Quintana sandbox deployment scenario (spec.md — crm-sync Specification):
  GIVEN backend/clients/quintana-seguros/crm.yaml exists with valid config
  WHEN a Quintana call completes
  THEN the sync uses only the field mapping and credentials defined in that config
  AND no Quintana-specific logic is hardcoded in app/integrations/

Test layer: Unit — pure filesystem + env-var monkeypatch; no live Airtable calls.

All credential references use env var NAMES only; no real secrets are present.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path to the real Quintana sandbox crm.yaml
# ---------------------------------------------------------------------------

_BACKEND_ROOT = Path(__file__).parent.parent.parent.parent  # backend/
_QUINTANA_CRM_YAML = _BACKEND_ROOT / "clients" / "quintana-seguros" / "crm.yaml"


# ---------------------------------------------------------------------------
# 1. crm.yaml file exists on the filesystem (structural guard)
# ---------------------------------------------------------------------------


def test_quintana_crm_yaml_exists():
    """backend/clients/quintana-seguros/crm.yaml must exist on the filesystem.

    This test FAILS (RED) until the file is created.
    It is the gating check for the entire Quintana sandbox spec scenario.
    """
    assert _QUINTANA_CRM_YAML.exists(), (
        f"Quintana crm.yaml not found at {_QUINTANA_CRM_YAML}. "
        "Create backend/clients/quintana-seguros/crm.yaml to satisfy spec FM-1."
    )


# ---------------------------------------------------------------------------
# 2. crm.yaml loads via CRMConfigLoader without error (FM-1, FM-2)
# ---------------------------------------------------------------------------


def test_quintana_crm_yaml_loads_valid_config(monkeypatch):
    """CRMConfigLoader.load('quintana-seguros') returns a valid CRMConfig.

    Spec FM-1: crm.yaml must load at startup or first sync.
    Spec FM-2: all required fields must be validated at load time.

    The env var is monkeypatched so no real secret is needed in CI.
    """
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_sandbox_key")

    from app.integrations.crm_config import CRMConfigLoader, CRMConfig

    config = CRMConfigLoader.load("quintana-seguros")

    assert config is not None, (
        "CRMConfigLoader.load('quintana-seguros') must return a CRMConfig, not None. "
        "Ensure crm.yaml has all required fields."
    )
    assert isinstance(config, CRMConfig), (
        f"Expected CRMConfig instance, got {type(config)}"
    )


# ---------------------------------------------------------------------------
# 3. Required fields are present and well-formed (FM-2)
# ---------------------------------------------------------------------------


def test_quintana_crm_config_required_fields(monkeypatch):
    """All required CRMConfig fields are present in the Quintana crm.yaml.

    Spec FM-2: adapter, base_id, table_id, match_field, credentials_key all required.
    Triangulation: tests each field independently for a real assertion.
    """
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_sandbox_key")

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros")
    assert config is not None

    assert config.provider == "airtable", (
        f"provider must be 'airtable', got {config.provider!r}"
    )
    assert config.base_id and config.base_id.startswith("app"), (
        f"base_id must start with 'app', got {config.base_id!r}"
    )
    assert config.table_id and config.table_id.startswith("tbl"), (
        f"table_id must start with 'tbl', got {config.table_id!r}"
    )
    assert config.match_field == "phone", (
        f"match_field must be 'phone' for Quintana, got {config.match_field!r}"
    )
    assert config.api_key_env == "QUINTANA_AIRTABLE_API_KEY", (
        f"api_key_env must be 'QUINTANA_AIRTABLE_API_KEY', got {config.api_key_env!r}"
    )
    assert len(config.field_mappings) >= 1, (
        "field_mappings must have at least one entry"
    )


# ---------------------------------------------------------------------------
# 4. crm.yaml contains no hardcoded secrets — only env var names (FM-3)
# ---------------------------------------------------------------------------


def test_quintana_crm_yaml_contains_no_hardcoded_secrets():
    """crm.yaml must reference credentials by env var NAME only — no secret values.

    Spec FM-3: resolved secret MUST NOT be stored in any config object or file.
    We grep the raw YAML for patterns that look like real Airtable API keys.
    """
    if not _QUINTANA_CRM_YAML.exists():
        pytest.skip("crm.yaml not yet created — skipped until test_quintana_crm_yaml_exists passes")

    raw = _QUINTANA_CRM_YAML.read_text()

    # Real Airtable PATs start with 'pat' followed by a dot and long token string
    # Real Airtable legacy keys start with 'key' followed by alphanumeric
    import re

    # Airtable PAT pattern: pat<base62>.xxxxx
    pat_pattern = re.compile(r"\bpat[A-Za-z0-9]{10,}\b")
    # Legacy key pattern: keyXXXXXXXXXX
    key_pattern = re.compile(r"\bkey[A-Za-z0-9]{8,}\b")

    assert not pat_pattern.search(raw), (
        "crm.yaml must NOT contain a real Airtable PAT token (starts with 'pat...'). "
        "Use api_key_env: ENV_VAR_NAME instead."
    )
    assert not key_pattern.search(raw), (
        "crm.yaml must NOT contain a real Airtable legacy API key (starts with 'key...'). "
        "Use api_key_env: ENV_VAR_NAME instead."
    )


# ---------------------------------------------------------------------------
# 5. No Quintana-specific logic exists in app/integrations/ source files
# ---------------------------------------------------------------------------


def test_no_quintana_specific_logic_in_integrations_package():
    """app/integrations/ must contain zero references to 'quintana'.

    Spec: no Quintana-specific logic is hardcoded in app/integrations/.
    Adding a new CRM adapter must require zero changes outside adapters/ (CS-9).

    This test scans the integrations package source files for any hardcoded
    'quintana' strings — which would indicate a config-driven concern has
    leaked into the generic adapter/service layer.
    """
    integrations_root = (
        Path(__file__).parent.parent.parent  # backend/
        / "app"
        / "integrations"
    )

    quintana_mentions: list[str] = []

    for py_file in sorted(integrations_root.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8").lower()
        if "quintana" in content:
            quintana_mentions.append(str(py_file.relative_to(integrations_root.parent.parent)))

    assert quintana_mentions == [], (
        "Quintana-specific logic found in app/integrations/ source files — "
        "this violates CS-9 (adapter must be generic). Affected files:\n"
        + "\n".join(f"  {f}" for f in quintana_mentions)
    )


# ---------------------------------------------------------------------------
# 6. Credential resolution uses env var at runtime — not baked-in value (FM-3)
# ---------------------------------------------------------------------------


def test_quintana_crm_config_credential_key_is_env_var_name(monkeypatch):
    """api_key_env stores an env var NAME, not the secret value itself.

    Spec FM-3: credentials resolved from env vars; the resolved secret must
    NOT be stored in the config object.

    Triangulation case: api_key_env value must be a valid env var name (all
    uppercase letters, digits, underscores) — not a real key.
    """
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_sandbox_key")

    from app.integrations.crm_config import CRMConfigLoader

    config = CRMConfigLoader.load("quintana-seguros")
    assert config is not None

    import re

    env_var_pattern = re.compile(r"^[A-Z][A-Z0-9_]+$")
    assert env_var_pattern.match(config.api_key_env), (
        f"api_key_env must be an env var name (e.g. QUINTANA_AIRTABLE_API_KEY), "
        f"got {config.api_key_env!r}"
    )

    # The config object itself must not store the resolved secret value
    config_dict = config.model_dump()
    for key, value in config_dict.items():
        if isinstance(value, str) and "pat_test_sandbox_key" in value:
            pytest.fail(
                f"Resolved secret found in config field '{key}' — "
                "CRMConfig must store only the env var NAME, not the secret value."
            )
