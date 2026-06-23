"""CRM configuration loader for per-client crm.yaml files.

Design decisions:
- Config lives at backend/clients/{client_id}/crm.yaml (filesystem, no DB)
- Missing file → returns None (silent skip per FM-4)
- Missing required fields → raises ConfigValidationError (fail-fast per FM-2)
- api_key stores either a literal value OR an env var name (resolved via heuristic):
  - Matches ^[A-Z][A-Z0-9_]+$ → os.environ lookup (backward-compat env var pattern)
  - Otherwise → literal value used directly (QR-4 dev/test pattern)
- Backward compat: api_key_env still accepted as field name; mapped to api_key at load
- FieldMapping validated as Pydantic model at load time (FM-5)
- Arbitrary field_map entries supported via list[CRMFieldDef] (FM-6)
- custom_fields: list[CustomFieldDef] — dynamic field definitions for lead data (QR-3)
- quote_ready_fields: list[str] — fields that must be present for "quoted" status (QR-3)
- Duplicate field_key in custom_fields rejected at load time
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

# Custom field keys should be snake_case — they become tool-schema property names
# and lead_custom_fields keys. Non-conforming keys are warned (not rejected) here
# to avoid breaking existing configs at load time; the save endpoint rejects them.
_SNAKE_CASE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Raised when crm.yaml is present but fails required-field validation."""


class CredentialResolutionError(Exception):
    """Raised when api_key is an env var name but the env var is not set."""


# ---------------------------------------------------------------------------
# Heuristic: env var name vs literal value
# ---------------------------------------------------------------------------

# ALL_CAPS_UNDERSCORES pattern: ^[A-Z][A-Z0-9_]+$
# e.g. QUINTANA_AIRTABLE_API_KEY → env var lookup
# e.g. pat.abcdefghijklmnop → literal
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


def _looks_like_env_var_name(value: str) -> bool:
    """Return True if the value matches the ALL_CAPS_UNDERSCORE env var name pattern."""
    return bool(_ENV_VAR_NAME_PATTERN.match(value))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CRMFieldDef(BaseModel):
    """Defines a single field mapping from a Qora lead field to a CRM field."""

    source: str          # Qora lead field name (e.g. "name", "phone")
    target: str          # CRM column/field name (e.g. "Nombre", "Teléfono")
    type: Literal["string", "integer", "boolean", "date", "phone"] = "string"
    required: bool = False

    model_config = {"extra": "forbid"}


class CustomFieldDef(BaseModel):
    """Defines a single custom field for client-specific lead data.

    Used to generate capture_data tool schema and validate field types at write time.
    Spec: dynamic-lead-fields QR-3
    """

    field_key: str       # Key used in lead_custom_fields table (e.g. "car_make")
    field_type: Literal["string", "integer", "boolean", "date", "phone"] = "string"
    label: str           # Human-readable label for tool descriptions
    required: bool = False

    model_config = {"extra": "forbid"}


class CRMConfig(BaseModel):
    """Validated CRM configuration loaded from a client's crm.yaml.

    api_key heuristic (QR-4):
    - Matches ^[A-Z][A-Z0-9_]+$ → treated as env var name → os.environ lookup
    - Otherwise → treated as literal value (suitable for dev/test)

    Backward compat: api_key_env is still accepted and mapped to api_key at load time.

    enabled field (B8):
    - Default True preserves backward compat — existing crm.yaml files without this
      field are treated as enabled. Set enabled: false to disable without deleting the file.
    """

    enabled: bool = True  # B8: integration on/off switch; default True for backward compat
    provider: Literal["airtable"]
    base_id: str
    table_id: str
    api_key: str           # Renamed from api_key_env; see heuristic above (QR-4)
    match_field: str
    field_mappings: list[CRMFieldDef] = Field(default_factory=list)
    # Optional status translation map: Qora status → CRM singleSelect label.
    status_mapping: dict[str, str] | None = None
    # Optional reverse status map: CRM singleSelect label → Qora internal status.
    import_status_mapping: dict[str, str] | None = None
    # Custom field definitions — drives capture_data schema and field type validation
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)
    # Fields that must be present (non-null, non-empty) for a lead to be "quoted"
    quote_ready_fields: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def _validate_no_duplicate_custom_field_keys(self) -> "CRMConfig":
        """Reject duplicate field_key values in custom_fields list."""
        seen: set[str] = set()
        for fd in self.custom_fields:
            if fd.field_key in seen:
                raise ValueError(
                    f"Duplicate field_key {fd.field_key!r} in field_definitions. "
                    "Each field_key must be unique."
                )
            seen.add(fd.field_key)
        return self

    @model_validator(mode="after")
    def _warn_non_snake_case_custom_field_keys(self) -> "CRMConfig":
        """Warn (non-fatal) for custom field keys that are not snake_case."""
        for fd in self.custom_fields:
            if not _SNAKE_CASE_KEY_PATTERN.match(fd.field_key):
                logger.warning(
                    "Custom field key %r is not snake_case; it may break tool-schema "
                    "property names and lead_custom_fields lookups. Use lowercase "
                    "letters, digits, and underscores (e.g. 'car_make').",
                    fd.field_key,
                )
        return self

    def resolve_api_key(self) -> str:
        """Resolve the API key using the heuristic:

        - If api_key matches ^[A-Z][A-Z0-9_]+$ → look up in os.environ
        - Otherwise → return api_key literal

        B8 addition: when the env var value is set but contains a known weak
        placeholder, a CredentialResolutionError is raised identifying the env
        var name. The secret value is NEVER included in the error message.

        Raises:
            CredentialResolutionError: if the env var lookup fails or the
                resolved value is a known weak placeholder.
        """
        if _looks_like_env_var_name(self.api_key):
            # Treat as env var name → look up the actual credential
            value = os.environ.get(self.api_key)
            if value is None:
                raise CredentialResolutionError(
                    f"CRM credential env var '{self.api_key}' is not set. "
                    "Configure it in your .env file or deployment environment."
                )

            # B8: Reject weak placeholder values for CRM credentials.
            # Import here to avoid circular dependency (credentials imports crm_config).
            from app.core.credentials import is_weak_placeholder  # noqa: PLC0415
            if is_weak_placeholder(value):
                raise CredentialResolutionError(
                    f"CRM credential env var '{self.api_key}' contains a known weak placeholder. "
                    "Replace it with a real credential before starting the application. "
                    "Secret values are never logged."
                )

            return value

        # Treat as literal value (dev/test pattern)
        return self.api_key

    # ---------------------------------------------------------------------------
    # Backward compat: expose api_key_env as an alias for existing code
    # ---------------------------------------------------------------------------

    @property
    def api_key_env(self) -> str:
        """Backward-compat alias for api_key — used by existing code that reads api_key_env."""
        return self.api_key


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CLIENTS_ROOT = Path(__file__).parent.parent.parent / "clients"


class CRMConfigLoader:
    """Loads and validates per-client CRM configuration from crm.yaml."""

    @staticmethod
    def load(
        client_id: str,
        *,
        clients_root: Path | None = None,
    ) -> CRMConfig | None:
        """Load and validate the CRM config for a given client.

        Args:
            client_id: The client slug (matches the directory name under clients/).
            clients_root: Override the clients root path (used in tests via tmp_path).

        Returns:
            CRMConfig if crm.yaml exists and is valid, None if file is missing.

        Raises:
            ConfigValidationError: if the file exists but fails Pydantic validation.
        """
        root = clients_root if clients_root is not None else _DEFAULT_CLIENTS_ROOT
        crm_yaml_path = root / client_id / "crm.yaml"

        if not crm_yaml_path.exists():
            return None

        try:
            raw = yaml.safe_load(crm_yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigValidationError(
                f"Malformed crm.yaml for client '{client_id}': {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise ConfigValidationError(
                f"Invalid crm.yaml for client '{client_id}': expected a mapping/object"
            )

        # --- Alias normalization ---
        # provider/adapter
        if "provider" not in raw and "adapter" in raw:
            raw["provider"] = raw["adapter"]

        # api_key / api_key_env backward compat:
        # Accept both field names; prefer the new 'api_key' name.
        if "api_key" not in raw and "api_key_env" in raw:
            raw["api_key"] = raw["api_key_env"]
        elif "api_key_env" not in raw and "credentials_key" in raw:
            raw["api_key"] = raw["credentials_key"]

        # field_mappings aliases
        if "field_mappings" not in raw:
            if "field_map" in raw:
                raw["field_mappings"] = raw["field_map"]
            elif "field_mapping" in raw:
                raw["field_mappings"] = raw["field_mapping"]

        # field_definitions → custom_fields (spec uses both names)
        if "custom_fields" not in raw and "field_definitions" in raw:
            raw["custom_fields"] = raw["field_definitions"]

        try:
            return CRMConfig.model_validate(raw)
        except (ValidationError, ValueError) as exc:
            raise ConfigValidationError(
                f"Invalid crm.yaml for client '{client_id}': {exc}"
            ) from exc
