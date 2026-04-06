"""QORA Tools — register_interest handler.

Transitions a lead to 'interested' and saves collected car data.

Covers: CAP-4 register_interest.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, transition_lead_status, InvalidTransitionError


async def register_interest(
    session: AsyncSession,
    lead_id: str,
    car_make: str | None,
    car_model: str | None,
    car_year: int | None,
    current_insurance: str | None = None,
    notes: str | None = None,
) -> dict:
    """Register a lead's interest and transition to 'interested'.

    Required fields: car_make, car_model, car_year.
    Returns error dict if any required field is missing or transition fails.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.
        car_make: Required — car brand.
        car_model: Required — car model.
        car_year: Required — car year.
        current_insurance: Optional — current insurance provider.
        notes: Optional — agent notes.

    Returns:
        Updated lead dict, or {"error": ..., "field": ...}.
    """
    # Validate required fields
    if not car_make:
        return {"error": "missing_field", "field": "car_make"}
    if not car_model:
        return {"error": "missing_field", "field": "car_model"}
    if car_year is None:
        return {"error": "missing_field", "field": "car_year"}

    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Transition to interested (enforces state machine)
    try:
        await transition_lead_status(session, lead_id, "interested")
    except InvalidTransitionError as e:
        return {"error": f"invalid_transition: {e.from_status} → {e.to_status}"}

    # Update car details
    lead.car_make = car_make
    lead.car_model = car_model
    lead.car_year = car_year
    if current_insurance is not None:
        lead.current_insurance = current_insurance

    # Append notes
    if notes:
        existing = lead.notes or ""
        lead.notes = f"{existing}\n{notes}".strip() if existing else notes

    lead.updated_at = datetime.now(timezone.utc)
    await session.flush()

    return {
        "id": lead.id,
        "status": lead.status,
        "car_make": lead.car_make,
        "car_model": lead.car_model,
        "car_year": lead.car_year,
        "current_insurance": lead.current_insurance,
        "notes": lead.notes,
        "updated_at": lead.updated_at.isoformat(),
    }
