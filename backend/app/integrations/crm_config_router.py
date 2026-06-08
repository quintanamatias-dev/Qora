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
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    api_key_env: str       # SECURITY: env var NAME only, never the actual secret
    match_field: str
    field_count: int
    connected: bool
    status_mapping: dict[str, str] | None = None
    import_status_mapping: dict[str, str] | None = None


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
    connected = bool(os.environ.get(env_var_name))

    return IntegrationConfigResponse(
        provider=config.provider,
        base_id=config.base_id,
        table_id=config.table_id,
        api_key_env=env_var_name,
        match_field=config.match_field,
        field_count=len(config.field_mappings),
        connected=connected,
        status_mapping=dict(config.status_mapping) if config.status_mapping else None,
        import_status_mapping=(
            dict(config.import_status_mapping) if config.import_status_mapping else None
        ),
    )


def _test_airtable_connection(config: CRMConfig) -> dict[str, Any]:
    """Test Airtable connectivity with a minimal 1-record fetch.

    This function is a standalone helper so tests can monkeypatch it.

    SECURITY: NEVER includes the raw API key in the returned dict.
    """
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
        # Sanitize error message — do NOT include the api_key value
        error_str = str(e)
        # Extra safety: strip the actual secret from any error message
        try:
            actual_key = os.environ.get(config.api_key_env, "")
            if actual_key:
                error_str = error_str.replace(actual_key, "[REDACTED]")
        except Exception:
            pass
        return {"success": False, "message": f"Connection failed: {error_str}"}


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
