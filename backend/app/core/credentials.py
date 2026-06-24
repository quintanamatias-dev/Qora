"""Centralized credential validation for Qora per-client integrations.

This module owns startup validation of tenant integration credentials — the
CRM secrets that are referenced by env var name in each client's crm.yaml.

Design decisions:
  - Global Qora credentials (OPENAI_API_KEY, ELEVENLABS_API_KEY) are validated
    exclusively by Settings model_validator. They are NOT in scope here.
  - Per-client CRM credentials are validated here by scanning crm.yaml files.
  - The ALL_CAPS heuristic (already in CRMConfig.resolve_api_key) determines
    whether an api_key value is an env var reference or a literal value.
  - Literal (non-ALL_CAPS) api_key values are dev/test patterns — not looked up,
    not validated against the placeholder list (they are intentionally plain).
  - Secret values are NEVER logged or included in error messages.

Spec reference:
  openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md
  openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------

# Keep this set in sync with _WEAK_PLACEHOLDERS in config.py.
# Source of truth: openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
WEAK_PLACEHOLDERS: frozenset[str] = frozenset({
    "change-me-before-production",
    "your-key-here",
    "todo",
    "replace_me",
    "xxx",
    "test",
    "changeme",
})

# ALL_CAPS_UNDERSCORES env var name pattern (mirrors CRMConfig heuristic).
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


def is_weak_placeholder(value: str) -> bool:
    """Return True if the value matches a known weak placeholder pattern.

    Comparison is case-insensitive. An empty string is NOT considered a
    placeholder — use a separate presence check before calling this.

    Args:
        value: The secret value to evaluate. Never logged.

    Returns:
        True if the value is a known placeholder; False otherwise.
    """
    return value.strip().lower() in WEAK_PLACEHOLDERS


def _looks_like_env_var_name(value: str) -> bool:
    """Return True if value matches the ALL_CAPS_UNDERSCORES env var name pattern."""
    return bool(_ENV_VAR_NAME_PATTERN.match(value))


# ---------------------------------------------------------------------------
# Startup validator
# ---------------------------------------------------------------------------

_DEFAULT_CLIENTS_ROOT = Path(__file__).parent.parent.parent / "clients"


def validate_all_integration_credentials(
    clients_root: Path | None = None,
) -> None:
    """Scan all crm.yaml files and hard-fail if any active integration
    references an env var that is missing or is a weak placeholder.

    Only validates per-client integration credentials (e.g. QUINTANA_AIRTABLE_API_KEY).
    Global Qora credentials (OPENAI_API_KEY, ELEVENLABS_API_KEY) are NOT checked here.

    Clients without a crm.yaml are silently skipped.
    Integrations with ``enabled: false`` are silently skipped.
    Literal api_key values (non-ALL_CAPS) are used as-is without env lookup or validation.

    Args:
        clients_root: Path to the directory containing per-client subdirectories.
                      Defaults to ``backend/clients/``.

    Raises:
        SystemExit: With a clear error message naming the client and missing variable
                    if any active CRM integration references an unset or placeholder env var.
    """
    root = clients_root if clients_root is not None else _DEFAULT_CLIENTS_ROOT

    if not root.exists():
        logger.debug("credentials: clients_root does not exist, skipping validation", extra={"path": str(root)})
        return

    errors: list[str] = []

    for client_dir in sorted(root.iterdir()):
        if not client_dir.is_dir():
            continue

        client_id = client_dir.name
        crm_yaml_path = client_dir / "crm.yaml"

        if not crm_yaml_path.exists():
            logger.debug("credentials: no crm.yaml for client, skipping", extra={"client_id": client_id})
            continue

        try:
            raw = yaml.safe_load(crm_yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("credentials: malformed crm.yaml for client %s: %s", client_id, exc)
            continue

        if not isinstance(raw, dict):
            logger.warning("credentials: invalid crm.yaml for client %s: not a mapping", client_id)
            continue

        # Check enabled field — default True for backward compat (existing files work unchanged).
        enabled = raw.get("enabled", True)
        if not enabled:
            logger.debug("credentials: integration disabled for client %s, skipping", client_id)
            continue

        # Resolve the api_key field (supporting both api_key and legacy api_key_env).
        api_key_value: str | None = raw.get("api_key") or raw.get("api_key_env") or raw.get("credentials_key")

        if api_key_value is None:
            logger.debug("credentials: no api_key configured for client %s, skipping", client_id)
            continue

        # If the value looks like an env var name, validate the env var.
        if not _looks_like_env_var_name(api_key_value):
            # Literal dev/test value — not an env var reference; no env lookup needed.
            logger.debug(
                "credentials: client %s uses a literal api_key (dev/test), skipping env validation",
                client_id,
            )
            continue

        # It IS an env var reference — validate presence and placeholder.
        env_var_name = api_key_value
        env_value = os.environ.get(env_var_name)

        if env_value is None:
            errors.append(
                f"Client '{client_id}': CRM integration credential env var "
                f"'{env_var_name}' is not set. "
                f"Add {env_var_name} to your .env file."
            )
            logger.error(
                "credentials: missing CRM credential",
                extra={"client_id": client_id, "env_var": env_var_name},
            )
            continue

        if not env_value.strip():
            errors.append(
                f"Client '{client_id}': CRM integration credential env var "
                f"'{env_var_name}' is set but empty. "
                f"Set {env_var_name} to a valid non-empty value."
            )
            logger.error(
                "credentials: empty CRM credential",
                extra={"client_id": client_id, "env_var": env_var_name},
            )
            continue

        if is_weak_placeholder(env_value):
            errors.append(
                f"Client '{client_id}': CRM integration credential env var "
                f"'{env_var_name}' contains a known weak placeholder. "
                f"Replace it with a real credential before starting the application. "
                f"Secret values are never logged."
            )
            logger.error(
                "credentials: placeholder CRM credential",
                extra={"client_id": client_id, "env_var": env_var_name},
            )
            continue

        logger.debug(
            "credentials: OK for client %s env var %s",
            client_id,
            env_var_name,
        )

    if errors:
        error_message = (
            "Startup aborted — CRM integration credential(s) are missing or invalid:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )
        sys.exit(error_message)
