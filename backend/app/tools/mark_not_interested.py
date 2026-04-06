"""QORA Tools — mark_not_interested handler.

Transitions a lead to 'not_interested' and saves the reason in notes.

Covers: CAP-4 mark_not_interested.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, transition_lead_status, InvalidTransitionError


async def mark_not_interested(
    session: AsyncSession,
    lead_id: str,
    reason: str,
) -> dict:
    """Mark a lead as not interested and record the reason.

    Lead is NEVER deleted — only status + notes updated.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.
        reason: Required — reason for rejection (free text).

    Returns:
        Updated lead dict, or {"error": ...}.
    """
    # Validate reason is not empty
    if not reason or not reason.strip():
        return {"error": "missing_field", "field": "reason"}

    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Transition to not_interested (enforces state machine)
    try:
        await transition_lead_status(session, lead_id, "not_interested")
    except InvalidTransitionError as e:
        return {"error": f"invalid_transition: {e.from_status} → {e.to_status}"}

    # Save reason in notes
    existing = lead.notes or ""
    rejection_note = f"No interesado: {reason}"
    lead.notes = f"{existing}\n{rejection_note}".strip() if existing else rejection_note

    lead.updated_at = datetime.now(timezone.utc)
    await session.flush()

    return {
        "id": lead.id,
        "status": lead.status,
        "notes": lead.notes,
        "updated_at": lead.updated_at.isoformat(),
    }
