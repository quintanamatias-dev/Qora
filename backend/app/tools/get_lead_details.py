"""QORA Tools — get_lead_details handler.

Returns full lead details for the current call.
Increments call_count and sets last_called_at.

Covers: CAP-4 get_lead_details.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead


async def get_lead_details(
    session: AsyncSession,
    lead_id: str,
) -> dict:
    """Fetch full lead record and increment call counter.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to fetch.

    Returns:
        Dict with all lead fields, or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Increment call_count and update last_called_at
    lead.call_count = (lead.call_count or 0) + 1
    lead.last_called_at = datetime.now(timezone.utc)
    await session.flush()

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
