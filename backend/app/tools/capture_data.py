"""QORA Tools — capture_data handler.

Generic field-capture tool whose schema is stored per-agent in tool_config JSON.
Validates arguments against the agent's stored JSON Schema, then:
1. Writes one lead_custom_fields row per captured field (primary storage — WU-5)
2. Dual-writes one LeadProfileFact row per field with key `captured:{field_name}`
   for backward compatibility with the intelligence pipeline.

Spec: Requirement: capture_data Handler Validates and Persists
AC-2: Missing required fields → error, no DB writes (atomic)
AC-3: Cross-tenant access → lead_not_found (no leakage)
AC-4: Each captured field → one active LeadProfileFact with key `captured:{name}`
AC-5: Never transitions lead status
dynamic-lead-fields WU-5: business data written to lead_custom_fields (dual-write)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import LeadProfileFact
from app.leads.service import get_lead


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


async def capture_data(
    session: AsyncSession,
    lead_id: str,
    tool_config: dict,
    captured_fields: dict,
    client_id: str,
    source_call_id: str | None = None,
    field_type_map: dict[str, str] | None = None,
) -> dict:
    """Validate captured fields against agent schema and write to storage.

    The function validates that all required fields (from tool_config["capture_data"]
    ["required"], excluding "lead_id") are present in captured_fields. On success:
    1. Upserts each captured field to lead_custom_fields (primary storage, WU-5)
    2. Dual-writes a LeadProfileFact row with key `captured:{field}` for backward
       compat with the intelligence/summarizer pipeline.

    On failure (missing fields, lead not found, wrong client), it returns an error
    dict and writes nothing.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to update.
        tool_config: Agent's tool_config dict. Must contain "capture_data" key with
            a JSON Schema parameters block.
        captured_fields: Dict of field_name → value provided by the LLM.
        client_id: Tenant client ID — used to enforce cross-tenant isolation.
        source_call_id: Optional call session ID for fact provenance.
        field_type_map: Optional dict of field_name → field_type for lead_custom_fields
            coercion (e.g. {"car_year": "integer"}). Defaults to "string" for unknown fields.

    Returns:
        On success: {"status": "captured", "fields": [list of captured field names]}
        On missing fields: {"error": "missing_required_fields", "missing": [...]}
        On lead not found or wrong tenant: {"error": "lead_not_found"}
        On missing tool_config: {"error": "missing_tool_config"}
    """
    # Validate tool_config
    if not tool_config or "capture_data" not in tool_config:
        return {"error": "missing_tool_config"}

    capture_config = tool_config["capture_data"]

    # Normalize schema location: support both nested {"parameters": {...}} and flat format.
    # Resolve a single source block to avoid split-source bugs where required and
    # properties come from different dicts when a malformed config has both nested
    # and flat keys.  Use ``is not None`` checks so valid empty values (e.g. [])
    # are not skipped by truthiness.
    _params_block = capture_config.get("parameters") if isinstance(capture_config.get("parameters"), dict) else None
    _source = _params_block if _params_block is not None else capture_config

    _raw_required = _source.get("required")
    schema_required: list[str] = list(_raw_required) if _raw_required is not None else []

    _raw_properties = _source.get("properties")
    schema_properties: dict = dict(_raw_properties) if _raw_properties is not None else {}

    # Extract required fields from schema (excluding lead_id — always implicit)
    required_data_fields = [f for f in schema_required if f != "lead_id"]

    # Validate: all required data fields must be present and non-None
    missing = [f for f in required_data_fields if f not in captured_fields or captured_fields[f] is None]
    if missing:
        return {"error": "missing_required_fields", "missing": missing}

    # Load lead with cross-tenant isolation
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}
    if lead.client_id != client_id:
        # Same response as not found — no information leakage
        return {"error": "lead_not_found"}

    # Determine which fields to write: only fields present in captured_fields
    # AND declared in the schema properties. Hallucinated fields from the LLM
    # (not in schema) are silently dropped to avoid polluting LeadProfileFact.
    fields_to_write = [
        (field_name, captured_fields[field_name])
        for field_name in captured_fields
        if field_name != "lead_id"
        and captured_fields[field_name] is not None
        and field_name in schema_properties
    ]

    now = _utcnow()
    _effective_field_type_map: dict[str, str] = field_type_map or {}

    # --- WU-5: Primary storage — upsert to lead_custom_fields ---
    # Each captured field is written to the lead_custom_fields table using the
    # field_type_map to resolve the appropriate field_type for coercion.
    from app.leads import lead_custom_fields_service as _lcf_service

    for field_name, field_value in fields_to_write:
        field_type = _effective_field_type_map.get(field_name, "string")
        try:
            await _lcf_service.upsert(
                session,
                lead_id=lead_id,
                client_id=client_id,
                field_key=field_name,
                field_value=field_value,
                field_type=field_type,
            )
        except Exception:
            # Custom-field write failure is fatal — abort and surface the error.
            # LeadProfileFact is dual-write / backward-compat data; it must NOT
            # be written when the primary storage write fails (would give a false
            # "captured" status while business data is missing).
            import logging as _logging
            _logging.getLogger(__name__).error(
                "capture_data: failed to upsert %s to lead_custom_fields; aborting",
                field_name,
                exc_info=True,
            )
            return {
                "error": "custom_field_write_failed",
                "field": field_name,
            }

    # --- Backward compat: dual-write to LeadProfileFact (captured: namespace) ---
    # The intelligence/summarizer pipeline reads from captured: facts during WU-5.
    # This write is kept for backward compat until WU-7 removes it.

    # Batch-load all existing active captured: facts for this lead in one query
    # to avoid N+1 selects (one per field).
    _existing_result = await session.execute(
        select(LeadProfileFact).where(
            LeadProfileFact.lead_id == lead_id,
            LeadProfileFact.fact_key.startswith("captured:"),
            LeadProfileFact.superseded_at == None,  # noqa: E711
        )
    )
    _existing_facts: dict[str, LeadProfileFact] = {
        fact.fact_key: fact for fact in _existing_result.scalars().all()
    }

    # Upsert each captured field as a LeadProfileFact with "captured:" prefix
    for field_name, field_value in fields_to_write:
        fact_key = f"captured:{field_name}"
        fact_value = str(field_value)

        existing = _existing_facts.get(fact_key)

        if existing is not None:
            if existing.fact_value == fact_value:
                continue  # Same value — skip to avoid unnecessary rows
            existing.superseded_at = now

        session.add(
            LeadProfileFact(
                id=_new_uuid(),
                lead_id=lead_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_call_id=source_call_id,
                recorded_at=now,
            )
        )

    captured_names = [name for name, _ in fields_to_write]
    return {"status": "captured", "fields": captured_names}
