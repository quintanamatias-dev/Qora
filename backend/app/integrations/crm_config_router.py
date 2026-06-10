"""CRM integration config API router — reads/writes crm.yaml per client.

Provides:
- GET  /api/v1/clients/{client_id}/integrations
  Returns the client's configured integrations (currently Airtable if present).
  SECURITY: api_key_env is always the env var NAME, never the actual secret.

- GET  /api/v1/clients/{client_id}/integrations/available
  Returns all supported providers with their connection status.

- PUT  /api/v1/clients/{client_id}/integrations/{provider}
  Updates specific fields in crm.yaml (base_id, table_id, api_key_env, match_field).
  Returns the updated config.

- POST /api/v1/clients/{client_id}/integrations/{provider}/connect
  Creates a new crm.yaml for the client with default field/status mappings.
  Returns 409 if crm.yaml already exists.

- POST /api/v1/clients/{client_id}/integrations/{provider}/test
  Attempts a 1-record read from the configured Airtable base.
  Returns { success, message, record_count? }.
  SECURITY: never includes the raw API key in the response.

- DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect
  Removes crm.yaml for the client (disconnects the integration).

Design decisions:
- Uses existing CRMConfig model from crm_config.py (no schema migration).
- CLIENTS_ROOT can be patched in tests for isolation.
- _test_airtable_connection is a separate function for testability via monkeypatching.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.integrations.crm_config import CRMConfig, CRMConfigLoader, ConfigValidationError

# ---------------------------------------------------------------------------
# Configuration — clients root (patchable for tests)
# ---------------------------------------------------------------------------

# Default: backend/clients/ relative to this file's location
CLIENTS_ROOT: Path = Path(__file__).resolve().parent.parent.parent / "clients"

router = APIRouter(prefix="/clients", tags=["integrations"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class IntegrationConfigResponse(BaseModel):
    """JSON-safe integration config — api_key_env is always the env var NAME."""

    provider: str
    base_id: str
    table_id: str
    api_key_env: str       # SECURITY: env var name or masked literal credential
    match_field: str
    field_count: int
    connected: bool
    status_mapping: dict[str, str] | None = None
    import_status_mapping: dict[str, str] | None = None
    field_mappings: list[dict[str, Any]] = Field(default_factory=list)
    field_definitions: list[dict[str, Any]] = Field(default_factory=list)
    quote_ready_fields: list[str] = Field(default_factory=list)


class UpdateIntegrationPayload(BaseModel):
    """Partial update payload for PUT /integrations/{provider}."""

    base_id: str | None = None
    table_id: str | None = None
    api_key_env: str | None = None
    match_field: str | None = None
    status_mapping: dict[str, str] | None = None
    import_status_mapping: dict[str, str] | None = None


class ConnectIntegrationPayload(BaseModel):
    """Payload for POST /integrations/{provider}/connect — creates a new crm.yaml."""

    base_id: str
    table_id: str
    api_key_env: str  # Name of the env var (e.g., "QORA_DEMO_AIRTABLE_API_KEY")


class AirtableFieldResponse(BaseModel):
    """Airtable table field metadata used by the admin mapping UI."""

    id: str | None = None
    name: str
    type: str | None = None


class AirtableFieldsResponse(BaseModel):
    """Response for GET /integrations/{provider}/fields."""

    fields: list[AirtableFieldResponse]


class SaveMappingsPayload(BaseModel):
    """Payload for saving admin-managed field mapping configuration."""

    field_mappings: list[dict[str, Any]] = Field(default_factory=list)
    field_definitions: list[dict[str, Any]] = Field(default_factory=list)
    quote_ready_fields: list[str] = Field(default_factory=list)


class IntegrationTestResult(BaseModel):
    """Result of POST /integrations/{provider}/test."""

    success: bool
    message: str
    record_count: int | None = None


class AvailableIntegration(BaseModel):
    """A supported integration provider with its connection status."""

    provider: str
    name: str
    description: str
    is_connected: bool
    icon: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")
_AIRTABLE_PAT_PATTERN = re.compile(r"\b(?:pat|key)[A-Za-z0-9._-]{12,}\b")
_REQUIRED_CORE_MAPPINGS = ("external_lead_id", "name", "phone", "email")
# Custom field keys must be snake_case: they become tool-schema property names
# and lead_custom_fields keys. Hyphens/uppercase break downstream lookups.
_SNAKE_CASE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _invalid_custom_field_keys(field_definitions: list[dict[str, Any]]) -> list[str]:
    """Return custom field keys that are not snake_case (e.g. 'test-field')."""
    invalid: list[str] = []
    for definition in field_definitions:
        key = str(definition.get("field_key", ""))
        if key and not _SNAKE_CASE_KEY_PATTERN.match(key):
            invalid.append(key)
    return invalid


def _looks_like_env_var_name(value: str) -> bool:
    return bool(_ENV_VAR_NAME_PATTERN.match(value))


def _safe_credential_label(value: str) -> str:
    """Return a display-safe credential label without exposing literal tokens."""
    if _looks_like_env_var_name(value):
        return value
    return "Stored credential (masked)"


def _sanitize_secret_text(text: str, config: CRMConfig) -> str:
    """Strip known Airtable token shapes from user-facing error text."""
    cleaned = _AIRTABLE_PAT_PATTERN.sub("[REDACTED]", text)
    if config.api_key and not _looks_like_env_var_name(config.api_key):
        cleaned = cleaned.replace(config.api_key, "[REDACTED]")
    try:
        actual_key = os.environ.get(config.api_key_env, "")
        if actual_key:
            cleaned = cleaned.replace(actual_key, "[REDACTED]")
    except Exception:
        pass
    return cleaned


def _validate_airtable_ids(base_id: str, table_id: str) -> str | None:
    """Return a helpful validation error, or None when IDs are usable."""
    if not base_id.startswith("app"):
        return (
            "Airtable Base ID must start with 'app'. Paste the full Base ID from Airtable, "
            "not the shortened value from a URL."
        )
    if not table_id:
        return "Airtable Table ID or table name is required."
    if table_id.startswith("tbl") or not re.fullmatch(r"[A-Za-z0-9]{8,}", table_id):
        return None
    return (
        "Airtable Table ID should usually start with 'tbl'. If using a table name, include the "
        "actual readable table name instead of a shortened URL fragment."
    )


def _load_config_or_none(client_id: str) -> CRMConfig | None:
    """Load crm.yaml for client_id, returning None if not found or invalid."""
    try:
        return CRMConfigLoader.load(client_id, clients_root=CLIENTS_ROOT)
    except ConfigValidationError:
        return None


def _config_to_response(config: CRMConfig) -> IntegrationConfigResponse:
    """Convert CRMConfig to IntegrationConfigResponse.

    SECURITY: api_key_env is the env var NAME. resolve_api_key() is NOT called.
    The 'connected' field checks whether the env var is set (not that the key is valid).
    """
    env_var_name = config.api_key_env
    connected = (
        bool(env_var_name)
        if not _looks_like_env_var_name(env_var_name)
        else bool(os.environ.get(env_var_name))
    )

    return IntegrationConfigResponse(
        provider=config.provider,
        base_id=config.base_id,
        table_id=config.table_id,
        api_key_env=_safe_credential_label(env_var_name),
        match_field=config.match_field,
        field_count=len(config.field_mappings),
        connected=connected,
        status_mapping=dict(config.status_mapping) if config.status_mapping else None,
        import_status_mapping=(
            dict(config.import_status_mapping) if config.import_status_mapping else None
        ),
        field_mappings=[field.model_dump() for field in config.field_mappings],
        field_definitions=[field.model_dump() for field in config.custom_fields],
        quote_ready_fields=list(config.quote_ready_fields),
    )


def _test_airtable_connection(config: CRMConfig) -> dict[str, Any]:
    """Test Airtable connectivity with a minimal 1-record fetch.

    This function is a standalone helper so tests can monkeypatch it.

    SECURITY: NEVER includes the raw API key in the returned dict.
    """
    validation_error = _validate_airtable_ids(config.base_id, config.table_id)
    if validation_error:
        return {"success": False, "message": validation_error}

    try:
        api_key = config.resolve_api_key()
    except Exception as e:
        return {"success": False, "message": f"Credential error: {e}"}

    try:
        # Import pyairtable lazily — only needed for this function
        from pyairtable import Api  # type: ignore[import-untyped]

        api = Api(api_key)
        table = api.table(config.base_id, config.table_id)
        records = table.all(max_records=1)
        record_count = len(records)
        return {
            "success": True,
            "message": f"Connected. Retrieved {record_count} record(s) successfully.",
            "record_count": record_count,
        }
    except ImportError:
        return {
            "success": False,
            "message": "pyairtable is not installed. Cannot test connection.",
        }
    except Exception as e:
        error_str = _sanitize_secret_text(str(e), config)
        if "404" in error_str or "NOT_FOUND" in error_str.upper():
            error_str = (
                f"Airtable could not find base '{config.base_id}' and table '{config.table_id}'. "
                "Check that the Base ID starts with 'app', the Table ID starts with 'tbl' or is an exact table name, "
                "and the credential has access to that base."
            )
        return {"success": False, "message": f"Connection failed: {error_str}"}


def _list_airtable_fields(config: CRMConfig) -> list[dict[str, Any]]:
    """Fetch Airtable table fields via pyairtable schema APIs."""
    validation_error = _validate_airtable_ids(config.base_id, config.table_id)
    if validation_error:
        raise HTTPException(status_code=422, detail=validation_error)

    try:
        api_key = config.resolve_api_key()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Credential error: {e}") from e

    try:
        from pyairtable import Api  # type: ignore[import-untyped]

        schema = Api(api_key).base(config.base_id).schema()
        tables = getattr(schema, "tables", [])
        for table in tables:
            table_id = getattr(table, "id", None) or (table.get("id") if isinstance(table, dict) else None)
            table_name = getattr(table, "name", None) or (table.get("name") if isinstance(table, dict) else None)
            if config.table_id not in {table_id, table_name}:
                continue
            raw_fields = getattr(table, "fields", None) or (table.get("fields") if isinstance(table, dict) else [])
            return [
                {
                    "id": getattr(field, "id", None) or (field.get("id") if isinstance(field, dict) else None),
                    "name": getattr(field, "name", None) or (field.get("name") if isinstance(field, dict) else ""),
                    "type": getattr(field, "type", None) or (field.get("type") if isinstance(field, dict) else None),
                }
                for field in raw_fields
                if getattr(field, "name", None) or (field.get("name") if isinstance(field, dict) else None)
            ]
    except ImportError as e:
        raise HTTPException(status_code=500, detail="pyairtable is not installed. Cannot list Airtable fields.") from e
    except HTTPException:
        raise
    except Exception as e:
        detail = _sanitize_secret_text(str(e), config)
        raise HTTPException(status_code=502, detail=f"Unable to fetch Airtable fields: {detail}") from e

    raise HTTPException(
        status_code=404,
        detail=(
            f"Airtable table '{config.table_id}' was not found in base '{config.base_id}'. "
            "Use a Table ID that starts with 'tbl' or the exact table name."
        ),
    )


def _missing_required_core_mappings(field_mappings: list[dict[str, Any]]) -> list[str]:
    mapped_sources = {
        str(mapping.get("source", "")): str(mapping.get("target", "")).strip()
        for mapping in field_mappings
    }
    return [field for field in _REQUIRED_CORE_MAPPINGS if not mapped_sources.get(field)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/integrations",
    response_model=list[IntegrationConfigResponse],
    summary="Get integration configs for a client",
    description=(
        "Returns the client's configured integrations as a list. "
        "Currently supports Airtable (crm.yaml). "
        "Returns empty list if no crm.yaml is found. "
        "SECURITY: api_key_env returns the env var NAME, never the actual secret."
    ),
)
async def get_integrations(client_id: str) -> list[IntegrationConfigResponse]:
    """GET /api/v1/clients/{client_id}/integrations"""
    config = _load_config_or_none(client_id)
    if config is None:
        return []
    return [_config_to_response(config)]


@router.get(
    "/{client_id}/integrations/available",
    response_model=list[AvailableIntegration],
    summary="Get available integrations for a client",
    description=(
        "Returns all supported integration providers with their connection status. "
        "Currently only Airtable is supported. "
        "is_connected=true when crm.yaml exists with provider=airtable."
    ),
)
async def get_available_integrations(client_id: str) -> list[AvailableIntegration]:
    """GET /api/v1/clients/{client_id}/integrations/available"""
    crm_path = CLIENTS_ROOT / client_id / "crm.yaml"
    is_connected = False
    if crm_path.exists():
        try:
            raw = yaml.safe_load(crm_path.read_text()) or {}
            is_connected = raw.get("provider") == "airtable"
        except Exception:
            is_connected = False

    return [
        AvailableIntegration(
            provider="airtable",
            name="Airtable",
            description="Sync leads with your Airtable base",
            is_connected=is_connected,
            icon="/images/integrations/airtable-icon.webp",
        )
    ]


@router.put(
    "/{client_id}/integrations/{provider}",
    response_model=IntegrationConfigResponse,
    summary="Update integration config for a client",
    description=(
        "Updates specific fields in the client's crm.yaml. "
        "Returns the updated config. "
        "SECURITY: api_key_env always stores the env var NAME, never the secret."
    ),
)
async def update_integration(
    client_id: str,
    provider: str,
    payload: UpdateIntegrationPayload,
) -> IntegrationConfigResponse:
    """PUT /api/v1/clients/{client_id}/integrations/{provider}"""
    crm_path = CLIENTS_ROOT / client_id / "crm.yaml"

    if not crm_path.exists():
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    # Load the raw YAML dict (preserve all fields, including field_mappings)
    raw: dict = yaml.safe_load(crm_path.read_text()) or {}

    # Apply partial updates
    update_data = payload.model_dump(exclude_none=True)
    next_base_id = update_data.get("base_id", raw.get("base_id", ""))
    next_table_id = update_data.get("table_id", raw.get("table_id", ""))
    if "base_id" in update_data or "table_id" in update_data:
        validation_error = _validate_airtable_ids(str(next_base_id), str(next_table_id))
        if validation_error:
            raise HTTPException(status_code=422, detail=validation_error)
    raw.update(update_data)

    # Write back to YAML
    crm_path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False))

    # Reload and validate the config
    try:
        config = CRMConfigLoader.load(client_id, clients_root=CLIENTS_ROOT)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if config is None:
        raise HTTPException(status_code=500, detail="Failed to reload integration config after update")

    return _config_to_response(config)


@router.post(
    "/{client_id}/integrations/{provider}/test",
    response_model=IntegrationTestResult,
    summary="Test integration connection for a client",
    description=(
        "Attempts to connect to the configured CRM (e.g. Airtable) "
        "by fetching a single record. "
        "Returns success/failure with a user-safe message and optional record_count. "
        "SECURITY: never returns the raw API key value in any response."
    ),
)
async def test_integration(
    client_id: str,
    provider: str,
) -> IntegrationTestResult:
    """POST /api/v1/clients/{client_id}/integrations/{provider}/test"""
    config = _load_config_or_none(client_id)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"No integration config found for client '{client_id}'",
        )

    if config.provider != provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not configured for client '{client_id}'",
        )

    result = _test_airtable_connection(config)
    return IntegrationTestResult(**result)


@router.get(
    "/{client_id}/integrations/{provider}/fields",
    response_model=AirtableFieldsResponse,
    summary="List Airtable table fields for mapping",
)
async def get_integration_fields(client_id: str, provider: str) -> AirtableFieldsResponse:
    """GET /api/v1/clients/{client_id}/integrations/{provider}/fields"""
    config = _load_config_or_none(client_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")
    if config.provider != provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured for client '{client_id}'")
    return AirtableFieldsResponse(fields=[AirtableFieldResponse(**field) for field in _list_airtable_fields(config)])


@router.put(
    "/{client_id}/integrations/{provider}/mappings",
    response_model=IntegrationConfigResponse,
    summary="Save Airtable field mappings for a client",
)
async def save_integration_mappings(
    client_id: str,
    provider: str,
    payload: SaveMappingsPayload,
) -> IntegrationConfigResponse:
    """PUT /api/v1/clients/{client_id}/integrations/{provider}/mappings"""
    crm_path = CLIENTS_ROOT / client_id / "crm.yaml"
    if not crm_path.exists():
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    raw: dict = yaml.safe_load(crm_path.read_text()) or {}
    if raw.get("provider") != provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured for client '{client_id}'")

    missing_required = _missing_required_core_mappings(payload.field_mappings)
    if missing_required:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required Airtable mappings: {', '.join(missing_required)}.",
        )

    invalid_keys = _invalid_custom_field_keys(payload.field_definitions)
    if invalid_keys:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid custom field keys: {', '.join(invalid_keys)}. "
                "Keys must be snake_case (lowercase letters, digits, underscores; "
                "e.g. 'car_make')."
            ),
        )

    raw["field_mappings"] = payload.field_mappings
    raw["custom_fields"] = payload.field_definitions
    raw.pop("field_definitions", None)
    raw["quote_ready_fields"] = payload.quote_ready_fields
    crm_path.write_text(yaml.dump(raw, allow_unicode=True, default_flow_style=False))

    try:
        config = CRMConfigLoader.load(client_id, clients_root=CLIENTS_ROOT)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if config is None:
        raise HTTPException(status_code=500, detail="Failed to reload integration config after mapping update")
    return _config_to_response(config)


@router.post(
    "/{client_id}/integrations/{provider}/connect",
    response_model=IntegrationConfigResponse,
    status_code=201,
    summary="Connect a new integration for a client",
    description=(
        "Creates a new crm.yaml for the client with default field and status mappings. "
        "Returns 404 if the client directory does not exist. "
        "Returns 409 if crm.yaml already exists (use PUT to update). "
        "SECURITY: api_key_env stores only the env var NAME, never the secret."
    ),
)
async def connect_integration(
    client_id: str,
    provider: str,
    payload: ConnectIntegrationPayload,
) -> IntegrationConfigResponse:
    """POST /api/v1/clients/{client_id}/integrations/{provider}/connect"""
    client_dir = CLIENTS_ROOT / client_id
    if not client_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Client directory not found for client '{client_id}'",
        )

    crm_path = client_dir / "crm.yaml"
    if crm_path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Integration already configured for client '{client_id}'. "
                "Use PUT to update the existing configuration."
            ),
        )

    validation_error = _validate_airtable_ids(payload.base_id, payload.table_id)
    if validation_error:
        raise HTTPException(status_code=422, detail=validation_error)

    crm_data: dict = {
        "provider": "airtable",
        "base_id": payload.base_id,
        "table_id": payload.table_id,
        "api_key_env": payload.api_key_env,
        "match_field": "lead_id",
        "field_mappings": [
            {"source": "external_lead_id", "target": "lead_id", "type": "integer"},
            {"source": "name", "target": "Name", "type": "string"},
            {"source": "phone", "target": "Phone", "type": "phone"},
            {"source": "email", "target": "Email", "type": "string"},
            {"source": "status", "target": "Status", "type": "string"},
        ],
        "status_mapping": {
            "new": "New",
            "called": "Called",
            "quoted": "Quoted",
            "interested": "Interested",
            "not_interested": "Not Interested",
            "follow_up": "Follow Up",
        },
        "import_status_mapping": {
            "New": "new",
            "Called": "called",
            "Quoted": "quoted",
            "Interested": "interested",
            "Not Interested": "not_interested",
            "Follow Up": "follow_up",
        },
    }

    crm_path.write_text(yaml.dump(crm_data, allow_unicode=True, default_flow_style=False))

    try:
        config = CRMConfigLoader.load(client_id, clients_root=CLIENTS_ROOT)
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if config is None:
        raise HTTPException(status_code=500, detail="Failed to load integration config after creation")

    return _config_to_response(config)


@router.delete(
    "/{client_id}/integrations/{provider}/disconnect",
    summary="Disconnect an integration for a client",
    description=(
        "Deletes the crm.yaml for the client, removing the integration configuration. "
        "Returns 404 if no integration is configured for the client."
    ),
)
async def disconnect_integration(
    client_id: str,
    provider: str,
) -> dict[str, Any]:
    """DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect"""
    crm_path = CLIENTS_ROOT / client_id / "crm.yaml"

    if not crm_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No integration config found for client '{client_id}'",
        )

    crm_path.unlink()
    return {"success": True, "message": "Integration disconnected"}
