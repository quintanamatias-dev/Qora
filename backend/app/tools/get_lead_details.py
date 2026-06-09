"""QORA Tools — get_lead_details handler.

Returns full lead details for the current call.
NOTE: call_count increment and last_called_at update were MOVED to initiation.py
(Task 1.6 — configurable-agent-tools). Initiation is the canonical "call started"
event. Side-effects in a query tool violate least-surprise.

dynamic-lead-fields WU-7: includes custom_fields loaded from lead_custom_fields table.
Legacy Lead ORM columns (car_make, car_model, etc.) are still returned for backward
compat during transition, but custom_fields is the authoritative source for business data.

Covers: CAP-4 get_lead_details.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_lead_details",
        "description": "Obtenés los datos completos del lead del CRM",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "ID del lead"}
            },
            "required": ["lead_id"],
        },
    },
}


async def get_lead_details(
    session: AsyncSession,
    lead_id: str,
    client_id: str | None = None,
) -> dict:
    """Fetch full lead record (read-only — no side effects).

    Returns the current lead data without modifying any fields.
    call_count increment and last_called_at are set in initiation.py.

    dynamic-lead-fields WU-7: also loads custom_fields from lead_custom_fields
    when client_id is provided. Without client_id, custom_fields is empty (isolation).

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to fetch.
        client_id: Optional client slug for custom field isolation. When provided,
            custom_fields is populated from lead_custom_fields. When absent, returns {}.

    Returns:
        Dict with all lead fields plus custom_fields, or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Load custom fields when client_id is available (AC-1: primary read path)
    custom_fields: dict[str, str] = {}
    if client_id:
        try:
            from app.leads.lead_custom_fields_service import get_all as _get_all_cf

            custom_fields = await _get_all_cf(session, lead_id, client_id)
        except Exception:
            pass  # best-effort — degrade gracefully to empty custom_fields

    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "name": lead.name,
        "phone": lead.phone,
        "status": lead.status,
        "notes": lead.notes,
        "call_count": lead.call_count,
        "last_called_at": lead.last_called_at.isoformat()
        if lead.last_called_at
        else None,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        # dynamic-lead-fields WU-7: authoritative business data from lead_custom_fields
        "custom_fields": custom_fields,
    }
