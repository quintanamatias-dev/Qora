"""QORA Tools — get_lead_history handler (Issue #36).

Returns LeadInterestHistory rows (newest first, capped at 10) for a lead,
formatted as plain Spanish timeline text. Voice-first format (AD-4).

Covers: Issue #36 agent-lead-query-tools.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, get_interest_history


async def get_lead_history(
    session: AsyncSession,
    lead_id: str,
) -> dict:
    """Fetch interest history timeline for a lead.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to fetch history for.

    Returns:
        {"result": "<Spanish timeline text>"} or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    rows = await get_interest_history(session, lead_id, limit=10)

    if not rows:
        return {"result": f"No hay historial de interés para el lead {lead.name}."}

    # Format as timeline: newest first
    lines = [f"Historial de interés de {lead.name} (más reciente primero):"]
    for row in rows:
        recorded_at = row.get("recorded_at", "")
        # Shorten ISO datetime to date only for voice readability
        date_str = recorded_at[:10] if recorded_at else "fecha desconocida"
        lines.append(f"- {date_str}: nivel {row['interest_level']}/100")

    return {"result": "\n".join(lines)}
