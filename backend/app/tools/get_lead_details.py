"""QORA Tools — get_lead_details handler.

Returns full lead details for the current call.
NOTE: call_count increment and last_called_at update were MOVED to initiation.py
(Task 1.6 — configurable-agent-tools). Initiation is the canonical "call started"
event. Side-effects in a query tool violate least-surprise.

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
) -> dict:
    """Fetch full lead record (read-only — no side effects).

    Returns the current lead data without modifying any fields.
    call_count increment and last_called_at are set in initiation.py.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to fetch.

    Returns:
        Dict with all lead fields, or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "name": lead.name,
        "phone": lead.phone,
        "car_make": lead.car_make,
        "car_model": lead.car_model,
        "car_year": lead.car_year,
        "current_insurance": lead.current_insurance,
        "status": lead.status,
        "notes": lead.notes,
        "call_count": lead.call_count,
        "last_called_at": lead.last_called_at.isoformat()
        if lead.last_called_at
        else None,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }
