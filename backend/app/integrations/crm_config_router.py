"""CRM integration config API router — reads/writes client_integrations/client_secrets.

Provides:
- GET  /api/v1/clients/{client_id}/integrations
  Returns the client's configured integrations (currently Airtable if present).
  SECURITY: api_key_env is always a NAME (env var name or a canonical secret
  name), never the actual secret.

- GET  /api/v1/clients/{client_id}/integrations/available
  Returns all supported providers with their connection status.

- PUT  /api/v1/clients/{client_id}/integrations/{provider}
  Updates specific fields in the client_integrations row.
  Returns the updated config.

- POST /api/v1/clients/{client_id}/integrations/{provider}/connect
  Creates a new client_integrations row with default field/status mappings.
  Returns 409 if one already exists.

- POST /api/v1/clients/{client_id}/integrations/{provider}/test
  Attempts a 1-record read from the configured Airtable base.
  Returns { success, message, record_count? }.
  SECURITY: never includes the raw API key in the response.

- PUT  /api/v1/clients/{client_id}/integrations/{provider}/secret
  Write-only secret upload: body {value}, response {name, is_set, updated_at}.
  SECURITY: the submitted value is never echoed back. 503 when
  QORA_SECRETS_MASTER_KEY is not configured.

- GET  /api/v1/clients/{client_id}/integrations/{provider}/status
  Returns {status, status_reason, last_checked_at, secret_source}.

- POST /api/v1/clients/{client_id}/integrations/{provider}/secrets/import-from-env
  Superadmin-only: copies the integration's legacy env var value into
  client_secrets, encrypted.

- DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect
  Removes the client_integrations row (disconnects the integration).

Design decisions (client-integrations-secrets, design.md P3-D6/P3-D7):
- Uses existing CRMConfig model from crm_config.py (no new Pydantic shapes).
- A submitted api_key_env value that matches the ALL_CAPS env-var-name
  pattern is stored as-is (legacy env fallback, no secret write). Any other
  value is treated as a literal secret: encrypted into client_secrets under
  the integration's existing legacy_env_var_name, or the canonical name
  f"{provider}_api_key" when none is set yet — this is the single naming
  convention PUT .../secret and the import-from-env endpoint also use, so
  resolve_client_secret always finds whichever name is currently active.
- Every write calls IntegrationStore.invalidate(client_id) and recomputes
  the row's status via recompute_and_persist_status.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_client_access, require_superadmin
from app.core.auth import CallerIdentity, require_api_key
from app.core.crypto import get_secret_crypto
from app.integrations.crm_config import CRMConfig, ConfigValidationError
from app.integrations.integration_store import get_default_store, recompute_and_persist_status
from app.tenants.models import Client, ClientIntegration, ClientSecret

router = APIRouter(
    prefix="/clients",
    tags=["integrations"],
    dependencies=[Depends(require_client_access)],
)


# ---------------------------------------------------------------------------
# DB session dependency
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class IntegrationConfigResponse(BaseModel):
    """JSON-safe integration config — api_key_env is always a NAME."""

    provider: str
    base_id: str
    table_id: str
    api_key_env: str       # SECURITY: env var name or canonical secret name, never a secret value
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
    """Payload for POST /integrations/{provider}/connect — creates a new row."""

    base_id: str
    table_id: str
    api_key_env: str  # Env var name, or a literal secret value to encrypt


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


class PutSecretPayload(BaseModel):
    """Write-only payload for PUT /integrations/{provider}/secret."""

    value: str


class SecretResponse(BaseModel):
    """SECURITY: never includes the secret value — name, is_set, updated_at only."""

    name: str
    is_set: bool
    updated_at: datetime


class IntegrationStatusResponse(BaseModel):
    """Status without any secret value (client-integrations-secrets P3-D7)."""

    status: str
    status_reason: str | None = None
    last_checked_at: datetime | None = None
    secret_source: Literal["db", "env", "missing"]


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


def _sanitize_secret_text(text: str, api_key: str | None) -> str:
    """Strip known Airtable token shapes and the resolved secret from error text."""
    cleaned = _AIRTABLE_PAT_PATTERN.sub("[REDACTED]", text)
    if api_key:
        cleaned = cleaned.replace(api_key, "[REDACTED]")
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


async def _get_integration_row(
    session: AsyncSession, client_id: str, provider: str
) -> ClientIntegration | None:
    result = await session.execute(
        select(ClientIntegration).where(
            ClientIntegration.client_id == client_id,
            ClientIntegration.provider == provider,
        )
    )
    return result.scalar_one_or_none()


def _config_from_row(row: ClientIntegration) -> CRMConfig:
    payload = json.loads(row.config)
    payload.setdefault("provider", row.provider)
    payload.setdefault("enabled", row.enabled)
    return CRMConfig.model_validate(payload)


def _caller_label(caller: CallerIdentity) -> str:
    return caller.email or caller.api_key_hash


async def _upsert_secret_row(
    session: AsyncSession,
    client_id: str,
    name: str,
    plaintext: str,
    caller: CallerIdentity,
    crypto,
) -> ClientSecret:
    """Encrypt plaintext and UPSERT the (client_id, name) client_secrets row.

    SECURITY: plaintext is never logged and never returned — callers build
    the response from (name, True, row.updated_at) only.
    """
    result = await session.execute(
        select(ClientSecret).where(ClientSecret.client_id == client_id, ClientSecret.name == name)
    )
    row = result.scalar_one_or_none()
    ciphertext, key_id = crypto.encrypt(plaintext)
    updated_by = _caller_label(caller)

    if row is None:
        row = ClientSecret(
            client_id=client_id,
            name=name,
            ciphertext=ciphertext,
            key_id=key_id,
            created_by=updated_by,
            updated_by=updated_by,
        )
        session.add(row)
    else:
        row.ciphertext = ciphertext
        row.key_id = key_id
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = updated_by

    await session.flush()
    return row


async def _store_literal_secret_and_get_name(
    session: AsyncSession,
    client_id: str,
    provider: str,
    literal_value: str,
    existing_legacy_name: str | None,
    caller: CallerIdentity,
) -> str:
    """Encrypt a literal api_key submitted via the config PUT/connect payload.

    Returns the secret's name (to store as legacy_env_var_name). Raises 503
    when no master key is configured — nothing is ever stored unencrypted.
    """
    crypto = get_secret_crypto()
    if crypto is None:
        raise HTTPException(
            status_code=503,
            detail="QORA_SECRETS_MASTER_KEY is not configured; cannot store secret values.",
        )
    secret_name = existing_legacy_name or f"{provider}_api_key"
    await _upsert_secret_row(session, client_id, secret_name, literal_value, caller, crypto)
    return secret_name


def _upsert_integration_row(
    row: ClientIntegration | None,
    session: AsyncSession,
    client_id: str,
    provider: str,
    config_dict: dict[str, Any],
    caller: CallerIdentity,
) -> ClientIntegration:
    """Mutate an existing row in place, or create a new one. Caller commits."""
    updated_by = _caller_label(caller)
    config_json = json.dumps(config_dict)

    if row is None:
        row = ClientIntegration(
            client_id=client_id,
            provider=provider,
            enabled=True,
            config=config_json,
            status="ok",
            created_by=updated_by,
            updated_by=updated_by,
        )
        session.add(row)
    else:
        row.config = config_json
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = updated_by
    return row


def _config_to_response(config: CRMConfig, connected: bool) -> IntegrationConfigResponse:
    """Convert CRMConfig to IntegrationConfigResponse.

    SECURITY: api_key_env is always a NAME (legacy_env_var_name) — DB-backed
    configs never carry a literal api_key, so there is nothing to mask here.
    """
    return IntegrationConfigResponse(
        provider=config.provider,
        base_id=config.base_id,
        table_id=config.table_id,
        api_key_env=config.legacy_env_var_name or "",
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


def _test_airtable_connection(config: CRMConfig, api_key: str) -> dict[str, Any]:
    """Test Airtable connectivity with a minimal 1-record fetch.

    This function is a standalone helper so tests can monkeypatch it.

    SECURITY: NEVER includes the raw API key in the returned dict.
    """
    validation_error = _validate_airtable_ids(config.base_id, config.table_id)
    if validation_error:
        return {"success": False, "message": validation_error}

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
        error_str = _sanitize_secret_text(str(e), api_key)
        if "404" in error_str or "NOT_FOUND" in error_str.upper():
            error_str = (
                f"Airtable could not find base '{config.base_id}' and table '{config.table_id}'. "
                "Check that the Base ID starts with 'app', the Table ID starts with 'tbl' or is an exact table name, "
                "and the credential has access to that base."
            )
        return {"success": False, "message": f"Connection failed: {error_str}"}


def _list_airtable_fields(config: CRMConfig, api_key: str) -> list[dict[str, Any]]:
    """Fetch Airtable table fields via pyairtable schema APIs."""
    validation_error = _validate_airtable_ids(config.base_id, config.table_id)
    if validation_error:
        raise HTTPException(status_code=422, detail=validation_error)

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
        detail = _sanitize_secret_text(str(e), api_key)
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


async def _recompute_status_or_422(session: AsyncSession, client_id: str, provider: str) -> None:
    try:
        await recompute_and_persist_status(session, client_id, provider)
    except (ConfigValidationError, ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/integrations",
    response_model=list[IntegrationConfigResponse],
    summary="Get integration configs for a client",
    description=(
        "Returns the client's configured integrations as a list. "
        "Currently supports Airtable. Returns empty list if none configured. "
        "SECURITY: api_key_env returns a NAME, never the actual secret."
    ),
)
async def get_integrations(
    client_id: str, session: AsyncSession = Depends(get_db_session)
) -> list[IntegrationConfigResponse]:
    """GET /api/v1/clients/{client_id}/integrations"""
    result = await session.execute(
        select(ClientIntegration).where(ClientIntegration.client_id == client_id)
    )
    rows = result.scalars().all()
    responses: list[IntegrationConfigResponse] = []
    for row in rows:
        try:
            config = _config_from_row(row)
        except (ConfigValidationError, ValidationError, ValueError):
            continue
        responses.append(_config_to_response(config, row.status == "ok"))
    return responses


@router.get(
    "/{client_id}/integrations/available",
    response_model=list[AvailableIntegration],
    summary="Get available integrations for a client",
    description=(
        "Returns all supported integration providers with their connection status. "
        "Currently only Airtable is supported."
    ),
)
async def get_available_integrations(
    client_id: str, session: AsyncSession = Depends(get_db_session)
) -> list[AvailableIntegration]:
    """GET /api/v1/clients/{client_id}/integrations/available"""
    row = await _get_integration_row(session, client_id, "airtable")

    return [
        AvailableIntegration(
            provider="airtable",
            name="Airtable",
            description="Sync leads with your Airtable base",
            is_connected=row is not None,
            icon="/images/integrations/airtable-icon.webp",
        )
    ]


@router.put(
    "/{client_id}/integrations/{provider}",
    dependencies=[Depends(require_superadmin)],
    response_model=IntegrationConfigResponse,
    summary="Update integration config for a client",
    description=(
        "Updates specific fields in the client's client_integrations row. "
        "SECURITY: a literal api_key_env value is encrypted into client_secrets, "
        "never stored in the config column; an env-var-name value is stored as-is."
    ),
)
async def update_integration(
    client_id: str,
    provider: str,
    payload: UpdateIntegrationPayload,
    session: AsyncSession = Depends(get_db_session),
    caller: CallerIdentity = Depends(require_api_key),
) -> IntegrationConfigResponse:
    """PUT /api/v1/clients/{client_id}/integrations/{provider}"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    raw: dict = json.loads(row.config)

    update_data = payload.model_dump(exclude_none=True, exclude={"api_key_env"})
    next_base_id = update_data.get("base_id", raw.get("base_id", ""))
    next_table_id = update_data.get("table_id", raw.get("table_id", ""))
    if "base_id" in update_data or "table_id" in update_data:
        validation_error = _validate_airtable_ids(str(next_base_id), str(next_table_id))
        if validation_error:
            raise HTTPException(status_code=422, detail=validation_error)
    raw.update(update_data)

    if payload.api_key_env is not None:
        if _looks_like_env_var_name(payload.api_key_env):
            raw["legacy_env_var_name"] = payload.api_key_env
        else:
            raw["legacy_env_var_name"] = await _store_literal_secret_and_get_name(
                session, client_id, provider, payload.api_key_env, raw.get("legacy_env_var_name"), caller
            )

    row.config = json.dumps(raw)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = _caller_label(caller)

    get_default_store().invalidate(client_id)
    await _recompute_status_or_422(session, client_id, provider)
    await session.commit()

    config = _config_from_row(row)
    return _config_to_response(config, row.status == "ok")


@router.post(
    "/{client_id}/integrations/{provider}/test",
    dependencies=[Depends(require_superadmin)],
    response_model=IntegrationTestResult,
    summary="Test integration connection for a client",
    description=(
        "Attempts to connect to the configured CRM (e.g. Airtable) "
        "by fetching a single record. "
        "SECURITY: never returns the raw API key value in any response."
    ),
)
async def test_integration(
    client_id: str,
    provider: str,
    session: AsyncSession = Depends(get_db_session),
) -> IntegrationTestResult:
    """POST /api/v1/clients/{client_id}/integrations/{provider}/test"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    config = _config_from_row(row)
    if config.provider != provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider}' not configured for client '{client_id}'",
        )

    try:
        api_key = await config.resolve_api_key_async(session, client_id)
    except Exception as e:
        return IntegrationTestResult(success=False, message=f"Credential error: {e}")

    if api_key is None:
        return IntegrationTestResult(
            success=False,
            message="Credential could not be resolved. Check the configured secret or environment variable.",
        )

    result = _test_airtable_connection(config, api_key)
    return IntegrationTestResult(**result)


@router.get(
    "/{client_id}/integrations/{provider}/fields",
    response_model=AirtableFieldsResponse,
    summary="List Airtable table fields for mapping",
)
async def get_integration_fields(
    client_id: str, provider: str, session: AsyncSession = Depends(get_db_session)
) -> AirtableFieldsResponse:
    """GET /api/v1/clients/{client_id}/integrations/{provider}/fields"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")
    config = _config_from_row(row)
    if config.provider != provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not configured for client '{client_id}'")

    try:
        api_key = await config.resolve_api_key_async(session, client_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Credential error: {e}") from e
    if api_key is None:
        raise HTTPException(status_code=400, detail="Credential could not be resolved.")

    return AirtableFieldsResponse(
        fields=[AirtableFieldResponse(**field) for field in _list_airtable_fields(config, api_key)]
    )


@router.put(
    "/{client_id}/integrations/{provider}/mappings",
    dependencies=[Depends(require_superadmin)],
    response_model=IntegrationConfigResponse,
    summary="Save Airtable field mappings for a client",
)
async def save_integration_mappings(
    client_id: str,
    provider: str,
    payload: SaveMappingsPayload,
    session: AsyncSession = Depends(get_db_session),
    caller: CallerIdentity = Depends(require_api_key),
) -> IntegrationConfigResponse:
    """PUT /api/v1/clients/{client_id}/integrations/{provider}/mappings"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

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

    raw: dict = json.loads(row.config)
    raw["field_mappings"] = payload.field_mappings
    raw["custom_fields"] = payload.field_definitions
    raw.pop("field_definitions", None)
    raw["quote_ready_fields"] = payload.quote_ready_fields

    row.config = json.dumps(raw)
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = _caller_label(caller)

    get_default_store().invalidate(client_id)
    await _recompute_status_or_422(session, client_id, provider)
    await session.commit()

    config = _config_from_row(row)
    return _config_to_response(config, row.status == "ok")


@router.post(
    "/{client_id}/integrations/{provider}/connect",
    dependencies=[Depends(require_superadmin)],
    response_model=IntegrationConfigResponse,
    status_code=201,
    summary="Connect a new integration for a client",
    description=(
        "Creates a new client_integrations row with default field and status mappings. "
        "Returns 404 if the client does not exist. "
        "Returns 409 if already configured (use PUT to update). "
        "SECURITY: a literal api_key_env value is encrypted into client_secrets, "
        "never stored in the config column."
    ),
)
async def connect_integration(
    client_id: str,
    provider: str,
    payload: ConnectIntegrationPayload,
    session: AsyncSession = Depends(get_db_session),
    caller: CallerIdentity = Depends(require_api_key),
) -> IntegrationConfigResponse:
    """POST /api/v1/clients/{client_id}/integrations/{provider}/connect"""
    client_result = await session.execute(select(Client).where(Client.id == client_id))
    if client_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    existing = await _get_integration_row(session, client_id, provider)
    if existing is not None:
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

    raw: dict = {
        "base_id": payload.base_id,
        "table_id": payload.table_id,
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

    if _looks_like_env_var_name(payload.api_key_env):
        raw["legacy_env_var_name"] = payload.api_key_env
    else:
        raw["legacy_env_var_name"] = await _store_literal_secret_and_get_name(
            session, client_id, provider, payload.api_key_env, None, caller
        )

    row = _upsert_integration_row(None, session, client_id, provider, raw, caller)
    await session.flush()

    get_default_store().invalidate(client_id)
    await _recompute_status_or_422(session, client_id, provider)
    await session.commit()

    config = _config_from_row(row)
    return _config_to_response(config, row.status == "ok")


@router.delete(
    "/{client_id}/integrations/{provider}/disconnect",
    dependencies=[Depends(require_superadmin)],
    summary="Disconnect an integration for a client",
    description=(
        "Deletes the client_integrations row, removing the integration configuration. "
        "Returns 404 if no integration is configured for the client."
    ),
)
async def disconnect_integration(
    client_id: str,
    provider: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    await session.delete(row)
    get_default_store().invalidate(client_id)
    await session.commit()
    return {"success": True, "message": "Integration disconnected"}


@router.put(
    "/{client_id}/integrations/{provider}/secret",
    dependencies=[Depends(require_superadmin)],
    response_model=SecretResponse,
    summary="Set a client's integration secret value (write-only)",
    description=(
        "Encrypts and stores the submitted value in client_secrets. "
        "SECURITY: the response never echoes the submitted value — only "
        "name, is_set, and updated_at. Returns 503 if QORA_SECRETS_MASTER_KEY "
        "is not configured."
    ),
)
async def put_integration_secret(
    client_id: str,
    provider: str,
    payload: PutSecretPayload,
    session: AsyncSession = Depends(get_db_session),
    caller: CallerIdentity = Depends(require_api_key),
) -> SecretResponse:
    """PUT /api/v1/clients/{client_id}/integrations/{provider}/secret"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    crypto = get_secret_crypto()
    if crypto is None:
        raise HTTPException(
            status_code=503,
            detail="QORA_SECRETS_MASTER_KEY is not configured; cannot store secret values.",
        )

    raw: dict = json.loads(row.config)
    secret_name = raw.get("legacy_env_var_name") or f"{provider}_api_key"
    secret_row = await _upsert_secret_row(session, client_id, secret_name, payload.value, caller, crypto)

    if raw.get("legacy_env_var_name") != secret_name:
        raw["legacy_env_var_name"] = secret_name
        row.config = json.dumps(raw)
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = _caller_label(caller)

    get_default_store().invalidate(client_id)
    await _recompute_status_or_422(session, client_id, provider)
    await session.commit()
    await session.refresh(secret_row)

    return SecretResponse(name=secret_name, is_set=True, updated_at=secret_row.updated_at)


@router.get(
    "/{client_id}/integrations/{provider}/status",
    response_model=IntegrationStatusResponse,
    summary="Get a client's integration status",
    description=(
        "Returns status, status_reason, last_checked_at, and secret_source "
        "(db|env|missing) — never a secret value."
    ),
)
async def get_integration_status(
    client_id: str,
    provider: str,
    session: AsyncSession = Depends(get_db_session),
) -> IntegrationStatusResponse:
    """GET /api/v1/clients/{client_id}/integrations/{provider}/status"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    raw: dict = json.loads(row.config)
    secret_name = raw.get("legacy_env_var_name")

    secret_source: Literal["db", "env", "missing"] = "missing"
    if secret_name and get_secret_crypto() is not None:
        secret_result = await session.execute(
            select(ClientSecret).where(ClientSecret.client_id == client_id, ClientSecret.name == secret_name)
        )
        if secret_result.scalar_one_or_none() is not None:
            secret_source = "db"
    if secret_source == "missing" and secret_name and _looks_like_env_var_name(secret_name):
        if os.environ.get(secret_name):
            secret_source = "env"

    return IntegrationStatusResponse(
        status=row.status,
        status_reason=row.status_reason,
        last_checked_at=row.last_checked_at,
        secret_source=secret_source,
    )


@router.post(
    "/{client_id}/integrations/{provider}/secrets/import-from-env",
    dependencies=[Depends(require_superadmin)],
    response_model=SecretResponse,
    summary="Import a legacy environment-variable secret into encrypted storage",
    description=(
        "Superadmin-only. Copies the integration's configured legacy environment "
        "variable's current value into client_secrets, encrypted. Returns 503 "
        "without a master key, 404 when no legacy env var is configured or set."
    ),
)
async def import_secret_from_env(
    client_id: str,
    provider: str,
    session: AsyncSession = Depends(get_db_session),
    caller: CallerIdentity = Depends(require_api_key),
) -> SecretResponse:
    """POST /api/v1/clients/{client_id}/integrations/{provider}/secrets/import-from-env"""
    row = await _get_integration_row(session, client_id, provider)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No integration config found for client '{client_id}'")

    raw: dict = json.loads(row.config)
    env_name = raw.get("legacy_env_var_name")
    if not env_name or not _looks_like_env_var_name(env_name):
        raise HTTPException(
            status_code=404,
            detail="No legacy environment variable is configured for this integration.",
        )

    crypto = get_secret_crypto()
    if crypto is None:
        raise HTTPException(
            status_code=503,
            detail="QORA_SECRETS_MASTER_KEY is not configured; cannot import secrets.",
        )

    value = os.environ.get(env_name)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Environment variable '{env_name}' is not set.")

    secret_row = await _upsert_secret_row(session, client_id, env_name, value, caller, crypto)
    get_default_store().invalidate(client_id)
    await _recompute_status_or_422(session, client_id, provider)
    await session.commit()
    await session.refresh(secret_row)

    return SecretResponse(name=env_name, is_set=True, updated_at=secret_row.updated_at)
