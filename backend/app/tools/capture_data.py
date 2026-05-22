"""QORA Tools — capture_data handler.

Generic field-capture tool whose schema is stored per-agent in tool_config JSON.
Validates arguments against the agent's stored JSON Schema, then writes one
LeadProfileFact row per captured field using the key format `captured:{field_name}`.

Spec: Requirement: capture_data Handler Validates and Persists
AC-2: Missing required fields → error, no DB writes (atomic)
AC-3: Cross-tenant access → lead_not_found (no leakage)
AC-4: Each captured field → one active LeadProfileFact with key `captured:{name}`
AC-5: Never transitions lead status
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
) -> dict:
    """Validate captured fields against agent schema and write LeadProfileFact rows.

    The function validates that all required fields (from tool_config["capture_data"]
    ["required"], excluding "lead_id") are present in captured_fields. On success,
    it writes one LeadProfileFact row per captured field with key `captured:{field}`.
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

    # Extract required fields from schema (excluding lead_id — always implicit)
    schema_required: list[str] = list(capture_config.get("required", []))
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

    # Determine which fields to write: only fields that are present in captured_fields
    # (optional fields are skipped if not provided)
    fields_to_write = [
        (field_name, captured_fields[field_name])
        for field_name in captured_fields
        if field_name != "lead_id" and captured_fields[field_name] is not None
    ]

    now = _utcnow()

    # Upsert each captured field as a LeadProfileFact with "captured:" prefix
    for field_name, field_value in fields_to_write:
        fact_key = f"captured:{field_name}"
        fact_value = str(field_value)

        # Supersede any existing active row for this key
        existing_result = await session.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == lead_id,
                LeadProfileFact.fact_key == fact_key,
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        existing = existing_result.scalar_one_or_none()

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
