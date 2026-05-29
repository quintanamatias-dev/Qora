"""CRM sync service — orchestrates post-call lead push to external CRM.

Design decisions (design.md):
- sync_lead() is the single public entry point; called via asyncio.create_task (Phase 3)
- Reads lead from SQLite (authoritative source) — no Airtable reads in call path (CS-7)
- Loads CRMConfig via CRMConfigLoader; returns silently if no crm.yaml (FM-4)
- Resolves API key at call time via config.resolve_api_key() (FM-3)
- Maps lead fields using FieldMapper from field_mapping.py (FM-5/FM-6)
- Delegates upsert to adapter via CRMPort interface (CS-3/CS-6)
- All CRM failures are swallowed after logging — call analysis unaffected (CS-5)
- Adapter factory is limited to app/integrations/adapters/ (CS-9)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.adapters.airtable import AirtableUpsertError, make_adapter
from app.integrations.crm_config import (
    CRMConfigLoader,
    CredentialResolutionError,
    ConfigValidationError,
)
from app.integrations.field_mapping import FieldMapper, MappingError
from app.leads.service import get_lead

logger = logging.getLogger(__name__)


async def sync_lead(
    client_id: str,
    lead_id: str,
    db_session: AsyncSession,
) -> None:
    """Push a lead's current data to the external CRM configured for the client.

    This function is intended to be called via asyncio.create_task() after the
    summarizer savepoint commits (Phase 3). It is fully fire-and-forget — any
    exception is logged and swallowed; the call analysis result is never affected.

    Algorithm:
    1. Load CRMConfig from crm.yaml; return if missing (FM-4)
    2. Resolve API key from env var (FM-3); log and return on failure
    3. Fetch lead from SQLite; return if not found (defensive)
    4. Map lead fields to CRM payload via FieldMapper (FM-5/FM-6)
    5. Construct adapter via factory (CS-9 — adapters/ only)
    6. Call adapter.upsert_record() (CS-3/CS-6)
    7. Catch and log any CRM error — never re-raise (CS-5)

    Args:
        client_id: Client slug (used to locate crm.yaml and scope the lead read)
        lead_id: UUID of the lead to sync
        db_session: Active async session for reading the lead from SQLite
    """
    # Outer safety net: CRM is a downstream mirror only. ANY failure in the
    # loader, credential resolver, lead fetch, field mapper construction,
    # adapter factory, or upsert must be isolated and logged — never propagated
    # to the caller (the post-call analysis path). The inner handlers below add
    # structured logging for the expected/known failure modes; this outer guard
    # catches everything else (CS-5).
    try:
        # 1. Load config — None means no crm.yaml → silent no-op (FM-4)
        try:
            config = CRMConfigLoader.load(client_id)
        except ConfigValidationError as exc:
            logger.error(
                "CRM sync skipped: invalid crm.yaml",
                extra={"client_id": client_id, "lead_id": lead_id, "error": str(exc)},
            )
            return

        if config is None:
            # No crm.yaml for this client — normal; no log needed
            return

        # 2. Resolve credentials — fail fast if env var missing (FM-3)
        try:
            api_key = config.resolve_api_key()
        except CredentialResolutionError as exc:
            logger.error(
                "CRM sync skipped: credential resolution failed",
                extra={"client_id": client_id, "lead_id": lead_id, "error": str(exc)},
            )
            return

        # 3. Fetch lead from SQLite (authoritative source — CS-7: no Airtable reads)
        lead = await get_lead(db_session, lead_id)
        if lead is None:
            logger.warning(
                "CRM sync skipped: lead not found in DB",
                extra={"client_id": client_id, "lead_id": lead_id},
            )
            return

        # 3b. Tenant guard: never sync a lead that belongs to a different client.
        # get_lead() looks up by id only, so we must verify ownership here to
        # prevent cross-tenant leakage into the wrong CRM base.
        if lead.client_id != client_id:
            logger.warning(
                "CRM sync skipped: lead belongs to a different client",
                extra={
                    "client_id": client_id,
                    "lead_id": lead_id,
                    "lead_client_id": lead.client_id,
                },
            )
            return

        # 4. Map lead fields → CRM payload (pure; no IO)
        lead_data = _lead_to_dict(lead)
        mapper = FieldMapper(config.field_mappings)
        try:
            payload = mapper.map(lead_data)
        except MappingError as exc:
            logger.error(
                "CRM sync skipped: field mapping failed",
                extra={"client_id": client_id, "lead_id": lead_id, "error": str(exc)},
            )
            return

        # 5. Construct adapter (CS-9: factory lives in adapters/ only)
        adapter = make_adapter(config.provider, api_key=api_key, base_id=config.base_id)

        # 6/7. Perform upsert; catch and log all failures (CS-5)
        try:
            record_id = await adapter.upsert_record(
                table_id=config.table_id,
                payload=payload,
                match_field=config.match_field,
            )
            logger.info(
                "CRM sync succeeded",
                extra={
                    "client_id": client_id,
                    "lead_id": lead_id,
                    "crm_record_id": record_id,
                },
            )
        except AirtableUpsertError as exc:
            logger.error(
                "CRM sync failed after retries",
                extra={"client_id": client_id, "lead_id": lead_id, "error": str(exc)},
            )
            # Do NOT re-raise — call analysis result must not be affected (CS-5)

    except Exception as exc:
        # Catch-all for unexpected loader/factory/pre-upsert/upsert failures.
        # Swallow all exceptions — CRM is a downstream mirror only (CS-5).
        logger.error(
            "CRM sync unexpected error",
            extra={"client_id": client_id, "lead_id": lead_id, "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Pure helper — Lead ORM → flat dict for FieldMapper
# ---------------------------------------------------------------------------


def _lead_to_dict(lead: Any) -> dict[str, Any]:
    """Convert a Lead ORM object to a flat dict for FieldMapper.map().

    Includes all mappable fields from the Lead model. None values are included
    so that FieldMapper can decide whether to omit optional fields or raise on
    required missing fields.

    This is a pure function: same lead → same dict.
    """
    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "name": lead.name,
        "phone": lead.phone,
        "status": lead.status,
        "notes": lead.notes,
        "car_make": lead.car_make,
        "car_model": lead.car_model,
        "car_year": lead.car_year,
        "current_insurance": lead.current_insurance,
        "email": lead.email,
        "age": lead.age,
        "summary_last_call": lead.summary_last_call,
        "interest_level": lead.interest_level,
        "do_not_call": lead.do_not_call,
        "next_action": lead.next_action,
        "call_count": lead.call_count,
    }
