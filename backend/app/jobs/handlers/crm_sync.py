"""Durable CRM Sync Job Handler.

Wraps crm_sync_service.sync_lead() with error classification:
  - Transient errors (timeout, network, 5xx): raise plain Exception → executor retries
    up to max_attempts with exponential backoff.
  - Configuration errors (schema mismatch, auth failure, invalid mapping):
    raise ConfigurationError → executor dead-letters after 1 retry with
    operator_review=True in the error JSON.

Handler signature: async (payload: dict, db: AsyncSession) -> None

Payload keys:
  client_id (str): Client slug for CRM config lookup.
  lead_id   (str): UUID of the lead to sync.

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/durable-post-call-pipeline/spec.md
        Requirement: CRM Sync Is Durable With Error Classification
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import crm_sync_service
from app.jobs.registry import ConfigurationError

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Exception type names that indicate a configuration/mapping problem.
# When an adapter raises one of these, it is reclassified as ConfigurationError
# so the executor applies the 1-retry-then-dead policy instead of full backoff.
# ---------------------------------------------------------------------------
_CONFIG_ERROR_TYPE_NAMES: frozenset[str] = frozenset({
    "ConfigurationError",
    "AuthenticationError",
    "SchemaError",
    "MappingError",
    "ValidationError",
})

# HTTP status codes that indicate a permanent configuration failure.
# Used when the adapter attaches .status_code or .response.status_code.
#
# 400 Bad Request  — malformed request, often a schema/field mismatch.
# 401 Unauthorized — missing or invalid credentials (auth config error).
# 403 Forbidden    — valid credentials but insufficient permissions (config error).
# 404 Not Found    — target resource does not exist; usually a config/mapping error
#                    (e.g. wrong CRM object ID or endpoint URL in crm.yaml).
# 422 Unprocessable Entity — request well-formed but semantically invalid (field mapping).
#
# All of these are non-transient: retrying with the same payload will not fix them.
# The executor dead-letters after 1 retry and sets operator_review=True.
_CONFIG_ERROR_HTTP_STATUSES: frozenset[int] = frozenset({400, 401, 403, 404, 422})


async def crm_sync_handler(payload: dict, db: AsyncSession) -> None:
    """Execute CRM sync for a lead with error classification.

    Calls crm_sync_service.sync_lead(client_id, lead_id, db_session=db).

    Success: returns normally — executor marks job 'completed'.
    ConfigurationError: propagates — executor dead-letters after 1 retry with
        operator_review=True in background_jobs.error.
    Other exceptions: reclassified if type name is in _CONFIG_ERROR_TYPE_NAMES
        or HTTP status is in _CONFIG_ERROR_HTTP_STATUSES; otherwise propagated
        as-is so the executor applies full retry backoff.

    Args:
        payload: Must contain 'client_id' (str) and 'lead_id' (str).
        db:      Fresh AsyncSession provided by the executor for this attempt.

    Raises:
        ValueError: If required payload keys are missing.
        ConfigurationError: For auth failures, schema/mapping errors, invalid config.
        Exception: For transient errors (timeouts, 5xx, rate limits).

    Spec: Requirement: CRM Sync Is Durable With Error Classification
    """
    client_id = payload.get("client_id")
    lead_id = payload.get("lead_id")

    if not client_id or not lead_id:
        raise ValueError(
            "crm_sync_handler: payload must contain 'client_id' and 'lead_id'. "
            f"Got keys: {list(payload.keys())}"
        )

    logger.info("crm_sync_job_started", client_id=client_id, lead_id=lead_id)

    try:
        await crm_sync_service.sync_lead(
            client_id=client_id,
            lead_id=lead_id,
            db_session=db,
        )
    except ConfigurationError:
        # Already classified — propagate as-is for dead-letter policy.
        logger.warning(
            "crm_sync_config_error",
            client_id=client_id,
            lead_id=lead_id,
        )
        raise
    except Exception as exc:
        exc_type_name = type(exc).__name__

        # Reclassify by exception type name (covers MappingError, SchemaError, etc.)
        if exc_type_name in _CONFIG_ERROR_TYPE_NAMES:
            logger.warning(
                "crm_sync_config_error_reclassified",
                client_id=client_id,
                lead_id=lead_id,
                exc_type=exc_type_name,
            )
            raise ConfigurationError(str(exc)) from exc

        # Reclassify by HTTP status code (adapters that attach .status_code)
        status_code = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
        if status_code is not None and int(status_code) in _CONFIG_ERROR_HTTP_STATUSES:
            logger.warning(
                "crm_sync_config_error_http",
                client_id=client_id,
                lead_id=lead_id,
                status_code=status_code,
            )
            raise ConfigurationError(
                f"CRM sync rejected with HTTP {status_code}: {exc}"
            ) from exc

        # Transient error — propagate as-is for full retry backoff.
        logger.warning(
            "crm_sync_transient_error",
            client_id=client_id,
            lead_id=lead_id,
            exc_type=exc_type_name,
            error=str(exc),
        )
        raise

    logger.info("crm_sync_job_completed", client_id=client_id, lead_id=lead_id)
