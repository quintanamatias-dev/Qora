"""CRM configuration loader for per-client crm.yaml files.

Design decisions:
- Config lives at backend/clients/{client_id}/crm.yaml (filesystem, no DB)
- Missing file → returns None (silent skip per FM-4)
- Missing required fields → raises ConfigValidationError (fail-fast per FM-2)
- Credentials stored as env var NAME only; resolved lazily via resolve_api_key()
  → secret NEVER appears in config object or logs (FM-3)
- FieldMapping validated as Pydantic model at load time (FM-5)
- Arbitrary field_map entries supported via list[CRMFieldDef] (FM-6)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Raised when crm.yaml is present but fails required-field validation."""


class CredentialResolutionError(Exception):
    """Raised when the env var named by api_key_env is not set."""


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


class CRMConfig(BaseModel):
    """Validated CRM configuration loaded from a client's crm.yaml.

    Security: api_key_env stores only the ENV VAR NAME — never the secret value.
    Call resolve_api_key() to retrieve the actual credential at runtime.
    """

    provider: Literal["airtable"]
    base_id: str
    table_id: str
    api_key_env: str       # env var NAME (e.g. "QUINTANA_AIRTABLE_API_KEY")
    match_field: str
    field_mappings: list[CRMFieldDef] = Field(default_factory=list)
    # Optional status translation map: Qora status → CRM singleSelect label.
    # When present and the source field is "status", the mapper translates the value.
    # If a Qora status is absent from this map, the raw value is used as fallback.
    status_mapping: dict[str, str] | None = None

    model_config = {"extra": "ignore"}

    def resolve_api_key(self) -> str:
        """Resolve the API key from the environment at call time.

        Raises:
            CredentialResolutionError: if the named env var is not set.
        """
        value = os.environ.get(self.api_key_env)
        if value is None:
            raise CredentialResolutionError(
                f"CRM credential env var '{self.api_key_env}' is not set. "
                "Configure it in your .env file or deployment environment."
            )
        return value


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

        # Accept the original spec names while keeping the implementation model
        # explicit: provider/api_key_env are the internal canonical names.
        if "provider" not in raw and "adapter" in raw:
            raw["provider"] = raw["adapter"]
        if "api_key_env" not in raw and "credentials_key" in raw:
            raw["api_key_env"] = raw["credentials_key"]
        if "field_mappings" not in raw:
            if "field_map" in raw:
                raw["field_mappings"] = raw["field_map"]
            elif "field_mapping" in raw:
                raw["field_mappings"] = raw["field_mapping"]

        try:
            return CRMConfig.model_validate(raw)
        except ValidationError as exc:
            raise ConfigValidationError(
                f"Invalid crm.yaml for client '{client_id}': {exc}"
            ) from exc
