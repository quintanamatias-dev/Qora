"""CRM import service — orchestrates Airtable → Qora lead import (PULL direction).

Design decisions:
- import_leads_from_crm() is the single public entry point.
- Reads crm.yaml for the client (same config as push sync).
- Fetches all Airtable records via AirtableAdapter.fetch_records() (batch, not live).
- Reverse-maps Airtable fields → Qora fields using FieldMapper.reverse_map().
- Deduplicates by phone number (client-scoped): update if found, create if not.
- Stores the Airtable record ID as external_crm_id on the Lead (generic field).
- Returns an ImportResult with counts: created, updated, skipped, errors.
- Records missing a phone field are skipped (phone required for dedup).
- This is a batch operation — NOT called during live calls.
- Does not modify the push sync path (crm_sync_service.py).

Transaction atomicity:
- This function only stages changes (session.add / attribute mutation). It does
  NOT flush or commit per record. The caller (crm_router) owns the single
  transaction boundary: all staged records commit together, or none do if the
  caller's commit fails.
- Per-record errors that are caught here are recorded in ImportResult.errors and
  do NOT abort the batch. Only unexpected errors propagate to the caller and
  cause the whole transaction to roll back.

Error message hygiene:
- Error strings in ImportResult.errors reference the record identifier only and
  never embed raw exception text, to avoid leaking internal details.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.adapters.airtable import AirtableAdapter
from app.integrations.crm_config import (
    CRMConfigLoader,
    CredentialResolutionError,
    ConfigValidationError,
)
from app.integrations.field_mapping import FieldMapper
from app.leads import lead_custom_fields_service
from app.leads.models import Lead, LeadStatus


# ---------------------------------------------------------------------------
# Base Lead field set — used to classify import fields as base vs custom
# ---------------------------------------------------------------------------
#
# These are the columns that exist on the Lead ORM model itself.
# Any reverse-mapped field NOT in this set is a custom field and must be
# upserted to lead_custom_fields via the CRUD service (AC-8).
#
# Design (dynamic-lead-fields WU-2): during the transition period, custom
# fields are DUAL-WRITTEN — they go to both lead_custom_fields AND the
# legacy Lead ORM columns (backward compat for existing code paths).
# After WU-7, legacy column writes will be removed.
_BASE_LEAD_FIELDS: frozenset[str] = frozenset({
    "id",
    "client_id",
    "name",
    "phone",
    "email",
    "status",
    "notes",
    "external_lead_id",
    "external_crm_id",
    "call_count",
    "do_not_call",
    "summary_last_call",
    "interest_level",
    "objections_heard",
    "extracted_facts",
    "next_action",
    "next_action_at",
})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status progression ordering
# ---------------------------------------------------------------------------
#
# Leads can progress forward through the pipeline. On import we only apply an
# incoming status if it is "ahead" of the current Qora status — never regress a
# lead that has already progressed locally.
_STATUS_ORDER: dict[str, int] = {
    LeadStatus.NEW.value: 0,
    LeadStatus.CALLED.value: 1,
    LeadStatus.FOLLOW_UP.value: 2,
    LeadStatus.QUOTED.value: 3,
    LeadStatus.INTERESTED.value: 4,
    LeadStatus.NOT_INTERESTED.value: 5,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """Summary of a CRM import run.

    Attributes:
        created: Number of new leads created in Qora.
        updated: Number of existing leads updated with new data.
        skipped: Number of records skipped (e.g., missing required field).
        errors: List of error message strings for records that failed.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------


async def import_leads_from_crm(
    client_id: str,
    db_session: AsyncSession,
    *,
    clients_root: Path | None = None,
) -> ImportResult:
    """Import leads from the configured external CRM into Qora's DB.

    Algorithm:
    1. Load CRMConfig from crm.yaml; return empty ImportResult if missing.
    2. Resolve API key from env var; return empty result with error on failure.
    3. Fetch all records from Airtable via AirtableAdapter.fetch_records().
    4. For each record:
       a. Reverse-map Airtable fields → Qora field names.
       b. Skip if phone is missing (required for dedup).
       c. Look up lead by (client_id, phone).
       d. If found: update name and other mappable fields + external_crm_id,
          and advance status only if the imported status is ahead.
       e. If not found: create new lead with status="new" + external_crm_id.
    5. Return ImportResult with counts.

    Persistence is staged but not committed here — the caller owns the single
    transaction boundary (all-or-nothing). See module docstring.

    Args:
        client_id: Client slug (matches directory under clients/).
        db_session: Active async SQLAlchemy session.
        clients_root: Override clients root path (used in tests).

    Returns:
        ImportResult with created/updated/skipped/errors counts.
    """
    result = ImportResult()

    # 1. Load CRM config
    try:
        load_kwargs: dict[str, Any] = {}
        if clients_root is not None:
            load_kwargs["clients_root"] = clients_root

        config = CRMConfigLoader.load(client_id, **load_kwargs)
    except ConfigValidationError as exc:
        logger.error(
            "crm_import_skipped: invalid crm.yaml",
            extra={"client_id": client_id, "error": str(exc)},
        )
        result.errors.append(f"Config error: {exc}")
        return result

    if config is None:
        logger.info(
            "crm_import_skipped: no crm.yaml for client",
            extra={"client_id": client_id},
        )
        return result

    # 2. Resolve credentials
    try:
        api_key = config.resolve_api_key()
    except CredentialResolutionError as exc:
        logger.error(
            "crm_import_skipped: credential resolution failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        result.errors.append(f"Credential error: {exc}")
        return result

    # 3. Fetch records from Airtable
    adapter = AirtableAdapter(api_key=api_key, base_id=config.base_id)
    try:
        records = await adapter.fetch_records(table_id=config.table_id)
    except Exception as exc:
        logger.error(
            "crm_import_failed: could not fetch records",
            extra={"client_id": client_id, "error": str(exc)},
        )
        result.errors.append(f"Fetch error: {exc}")
        return result

    # Build reverse mapper
    import_status_mapping = getattr(config, "import_status_mapping", None)
    mapper = FieldMapper(
        config.field_mappings,
        import_status_mapping=import_status_mapping,
    )

    # Build field_types lookup from custom_fields config for type-aware upserts (AC-8)
    # {field_key: field_type} — used when upserting to lead_custom_fields
    _custom_field_types: dict[str, str] = {
        cf.field_key: cf.field_type
        for cf in getattr(config, "custom_fields", [])
    }

    # 4. Process each record
    for record in records:
        airtable_id = record.get("id", "")
        airtable_fields = record.get("fields", {})

        try:
            qora_data = mapper.reverse_map(airtable_fields)
        except Exception as exc:
            logger.warning(
                "crm_import_record_mapping_failed",
                extra={"airtable_id": airtable_id, "error": str(exc)},
            )
            result.skipped += 1
            result.errors.append(f"Mapping error for record {airtable_id}")
            continue

        phone = qora_data.get("phone")
        if not phone:
            logger.debug(
                "crm_import_record_skipped: missing phone",
                extra={"airtable_id": airtable_id},
            )
            result.skipped += 1
            continue

        # 4c. Look up lead by (client_id, phone)
        try:
            existing = await _find_lead_by_phone(db_session, client_id, phone)
        except Exception as exc:
            logger.error(
                "crm_import_db_lookup_failed",
                extra={"airtable_id": airtable_id, "phone": phone, "error": str(exc)},
            )
            result.errors.append(f"DB lookup error for record {airtable_id}")
            result.skipped += 1
            continue

        # Wrap the entire per-record persist block in a savepoint.
        # If _update_lead_from_qora_data mutates the Lead ORM and then
        # upsert_many fails, the savepoint rollback reverts BOTH the Lead
        # mutations and any custom-field writes staged within this record.
        # The outer transaction is preserved for all other records.
        #
        # Note: `await db_session.begin_nested()` is used instead of the
        # bare `db_session.begin_nested()` form — this is compatible with
        # both real AsyncSession (AsyncSessionTransaction is awaitable) and
        # AsyncMock-based unit tests (which require await to get the cm).
        try:
            async with await db_session.begin_nested() as savepoint:
                if existing is not None:
                    # 4d. Update existing lead — check for duplicate external_lead_id
                    eid_holder_id: str | None = None
                    incoming_eid = qora_data.get("external_lead_id")
                    if incoming_eid is not None:
                        eid_holder = await _find_lead_by_external_lead_id(
                            db_session, client_id, incoming_eid
                        )
                        if eid_holder is not None and eid_holder.id != existing.id:
                            eid_holder_id = eid_holder.id

                    # Returns pending_custom_fields dict (AC-8)
                    pending_custom_fields = _update_lead_from_qora_data(
                        existing,
                        qora_data,
                        airtable_id,
                        existing_external_lead_id_holder=eid_holder_id,
                    )
                    # Upsert non-base fields to lead_custom_fields (AC-8)
                    if pending_custom_fields:
                        await lead_custom_fields_service.upsert_many(
                            db_session,
                            lead_id=existing.id,
                            client_id=client_id,
                            fields=pending_custom_fields,
                            field_types=_custom_field_types if _custom_field_types else None,
                        )
                    result.updated += 1
                    logger.info(
                        "crm_import_lead_updated",
                        extra={"lead_id": existing.id, "airtable_id": airtable_id},
                    )
                else:
                    # 4e. Create new lead — returns (Lead, pending_custom_fields) (AC-8)
                    lead, pending_custom_fields = _create_lead_from_qora_data(
                        client_id=client_id,
                        qora_data=qora_data,
                        airtable_id=airtable_id,
                    )
                    db_session.add(lead)
                    await db_session.flush()
                    # Upsert non-base fields to lead_custom_fields (AC-8)
                    if pending_custom_fields:
                        await lead_custom_fields_service.upsert_many(
                            db_session,
                            lead_id=lead.id,
                            client_id=client_id,
                            fields=pending_custom_fields,
                            field_types=_custom_field_types if _custom_field_types else None,
                        )
                    result.created += 1
                    logger.info(
                        "crm_import_lead_created",
                        extra={"lead_id": lead.id, "airtable_id": airtable_id},
                    )
        except Exception as exc:
            # Savepoint was rolled back automatically by the context manager on exception.
            # Lead mutations and custom-field writes for this record are fully reverted.
            logger.error(
                "crm_import_record_persist_failed",
                extra={"airtable_id": airtable_id, "error": str(exc)},
            )
            result.errors.append(f"Persist error for record {airtable_id}")
            result.skipped += 1

    logger.info(
        "crm_import_complete",
        extra={
            "client_id": client_id,
            "created": result.created,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": len(result.errors),
        },
    )
    return result


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


async def _find_lead_by_phone(
    db_session: AsyncSession,
    client_id: str,
    phone: str,
) -> Lead | None:
    """Look up a lead by (client_id, phone) — returns first match or None."""
    result = await db_session.execute(
        select(Lead).where(
            Lead.client_id == client_id,
            Lead.phone == phone,
        )
    )
    return result.scalar_one_or_none()


async def _find_lead_by_external_lead_id(
    db_session: AsyncSession,
    client_id: str,
    external_lead_id: int,
) -> Lead | None:
    """Look up a lead by (client_id, external_lead_id) — returns first match or None.

    Used to detect duplicate external_lead_id during import.
    """
    result = await db_session.execute(
        select(Lead).where(
            Lead.client_id == client_id,
            Lead.external_lead_id == external_lead_id,
        )
    )
    return result.scalar_one_or_none()


def _update_lead_from_qora_data(
    lead: Lead,
    qora_data: dict[str, Any],
    airtable_id: str,
    existing_external_lead_id_holder: str | None = None,
) -> dict[str, Any]:
    """Update mutable fields on an existing Lead from imported Qora data dict.

    Only updates fields that are present in qora_data (reverse-mapped from Airtable).
    Always updates external_crm_id to keep the reference current.
    Does NOT update phone (that's the dedup key).

    Status handling: applies the imported status only when it is *ahead* of the
    current Qora status per _STATUS_ORDER (forward-only). If the current status
    is equal or already ahead, the status is left unchanged to avoid regressing
    leads that have progressed in Qora.

    Design (dynamic-lead-fields WU-2, AC-8):
    - Base fields (name, email, status, external_lead_id) are written to Lead ORM columns.
    - Non-base fields (car_make, car_model, car_year, current_insurance, age, zona, and
      future custom fields) are collected and returned as pending_custom_fields.
    - DUAL-WRITE: non-base fields are ALSO written to legacy Lead ORM columns (backward
      compat during transition; removed in WU-7).

    Args:
        lead: The Lead ORM object to update.
        qora_data: Reverse-mapped fields from the Airtable record.
        airtable_id: Airtable record ID (stored as external_crm_id).
        existing_external_lead_id_holder: If another lead already holds the
            same external_lead_id value from qora_data, pass that lead's ID
            here so a warning is logged. The update still proceeds.

    Returns:
        pending_custom_fields: {field_key: value} for all non-base fields found
        in qora_data. The caller is responsible for upsetting these to
        lead_custom_fields via lead_custom_fields_service.upsert_many().
    """
    pending_custom_fields: dict[str, Any] = {}

    # --- Base fields: write directly to Lead ORM ---
    if "name" in qora_data:
        lead.name = qora_data["name"]
    if "email" in qora_data:
        lead.email = qora_data["email"]
    if "status" in qora_data:
        _apply_status_if_ahead(lead, qora_data["status"])
    if "external_lead_id" in qora_data:
        incoming_eid = qora_data["external_lead_id"]
        if (
            incoming_eid is not None
            and existing_external_lead_id_holder is not None
            and existing_external_lead_id_holder != lead.id
        ):
            logger.warning(
                "crm_import_duplicate_external_lead_id: two leads share the same "
                "external_lead_id; proceeding with update but data may be ambiguous",
                extra={
                    "external_lead_id": incoming_eid,
                    "target_lead_id": lead.id,
                    "conflicting_lead_id": existing_external_lead_id_holder,
                    "airtable_id": airtable_id,
                },
            )
        lead.external_lead_id = incoming_eid

    # Always store the Airtable record ID
    lead.external_crm_id = airtable_id

    # --- Non-base fields: classify as custom + DUAL-WRITE to legacy columns ---
    for key, value in qora_data.items():
        if key in _BASE_LEAD_FIELDS:
            continue
        # Collect for upsert to lead_custom_fields
        pending_custom_fields[key] = value
        # DUAL-WRITE: also write to legacy Lead column if it exists (backward compat)
        # This keeps existing code paths working until WU-7 removes the legacy columns.
        if hasattr(lead, key):
            setattr(lead, key, value)

    return pending_custom_fields


def _apply_status_if_ahead(lead: Lead, imported_status_raw: Any) -> None:
    """Advance lead.status to imported status only if it is strictly ahead.

    Uses _STATUS_ORDER for the simple forward ordering:
    new < called < follow_up < quoted < interested < not_interested.

    Unknown/unmappable imported statuses are ignored (no change). Likewise, an
    imported status that is equal to or behind the current status is ignored so
    leads never regress.
    """
    # Validate the imported status against the known enum; ignore if unknown.
    try:
        imported_status = LeadStatus(imported_status_raw).value
    except ValueError:
        return

    current_rank = _STATUS_ORDER.get(lead.status)
    imported_rank = _STATUS_ORDER.get(imported_status)
    if current_rank is None or imported_rank is None:
        return

    if imported_rank > current_rank:
        lead.status = imported_status


def _create_lead_from_qora_data(
    client_id: str,
    qora_data: dict[str, Any],
    airtable_id: str,
) -> tuple[Lead, dict[str, Any]]:
    """Create a new Lead instance from reverse-mapped Qora data.

    New leads from Airtable import always start with status="new" unless
    a status mapping produced a known Qora status.

    Design (dynamic-lead-fields WU-2, AC-8):
    - Base fields are set directly on the Lead ORM object.
    - Non-base fields are collected as pending_custom_fields.
    - DUAL-WRITE: non-base fields are ALSO set on legacy Lead ORM columns (backward compat).

    Returns:
        (lead, pending_custom_fields): The new Lead instance and a dict of non-base
        fields that must be upserted to lead_custom_fields by the caller.
    """
    status_raw = qora_data.get("status", LeadStatus.NEW.value)
    # Validate status value; fall back to "new" if unknown
    try:
        status = LeadStatus(status_raw).value
    except ValueError:
        status = LeadStatus.NEW.value

    # Collect non-base fields as pending custom fields
    pending_custom_fields: dict[str, Any] = {
        key: value
        for key, value in qora_data.items()
        if key not in _BASE_LEAD_FIELDS and key != "phone" and key != "status"
    }

    # DUAL-WRITE: also populate legacy Lead columns for backward compat.
    # The Lead constructor accepts them directly; during transition these columns
    # still exist in the DB and may be read by code not yet migrated to WU-2+.
    lead = Lead(
        id=str(uuid.uuid4()),
        client_id=client_id,
        name=qora_data.get("name", ""),
        phone=qora_data["phone"],
        email=qora_data.get("email"),
        # Legacy columns (DUAL-WRITE — backward compat until WU-7)
        current_insurance=qora_data.get("current_insurance"),
        zona=qora_data.get("zona"),
        age=qora_data.get("age"),
        car_make=qora_data.get("car_make"),
        car_model=qora_data.get("car_model"),
        car_year=qora_data.get("car_year"),
        status=status,
        external_crm_id=airtable_id,
        external_lead_id=qora_data.get("external_lead_id"),
    )

    return lead, pending_custom_fields
