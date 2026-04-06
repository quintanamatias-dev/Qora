"""QORA Tools — schedule_followup handler.

Transitions a lead to 'follow_up' and stores the scheduled date in notes.

Covers: CAP-4 schedule_followup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, transition_lead_status, InvalidTransitionError


async def schedule_followup(
    session: AsyncSession,
    lead_id: str,
    followup_date: str,
    note: str | None = None,
) -> dict:
    """Schedule a follow-up call for a lead on a specific date.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.
        followup_date: ISO 8601 date string (e.g., "2026-05-01").
        note: Optional — additional note for the follow-up.

    Returns:
        Updated lead dict, or {"error": ...}.
    """
    # Validate followup_date
    if not followup_date or not followup_date.strip():
        return {"error": "missing_field", "field": "followup_date"}

    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Transition to follow_up (enforces state machine)
    try:
        await transition_lead_status(session, lead_id, "follow_up")
    except InvalidTransitionError as e:
        return {"error": f"invalid_transition: {e.from_status} → {e.to_status}"}

    # Persist followup date + note
    followup_entry = f"Seguimiento agendado: {followup_date}"
    if note:
        followup_entry += f" — {note}"

    existing = lead.notes or ""
    lead.notes = f"{existing}\n{followup_entry}".strip() if existing else followup_entry

    lead.updated_at = datetime.now(timezone.utc)
    await session.flush()

    return {
        "id": lead.id,
        "status": lead.status,
        "followup_date": followup_date,
        "notes": lead.notes,
        "updated_at": lead.updated_at.isoformat(),
    }
