"""QORA Leads — Service layer for lead CRUD, state machine, and seed data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import Lead, LeadStatus, is_valid_transition


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """Raised when a requested state transition is not allowed."""

    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status!r} → {to_status!r}")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def get_lead(session: AsyncSession, lead_id: str) -> Lead | None:
    """Fetch a Lead by its UUID id.

    Returns:
        Lead instance or None if not found.
    """
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def list_leads_for_client(session: AsyncSession, client_id: str) -> list[Lead]:
    """Return all leads scoped to a specific client.

    Never returns leads from another tenant.
    """
    result = await session.execute(select(Lead).where(Lead.client_id == client_id))
    return list(result.scalars().all())


async def create_lead(
    session: AsyncSession,
    *,
    client_id: str,
    name: str,
    phone: str,
    car_make: str | None = None,
    car_model: str | None = None,
    car_year: int | None = None,
    current_insurance: str | None = None,
    status: str = LeadStatus.NEW.value,
    notes: str | None = None,
    lead_id: str | None = None,
) -> Lead:
    """Create and persist a new Lead record."""
    lead = Lead(
        id=lead_id or str(uuid.uuid4()),
        client_id=client_id,
        name=name,
        phone=phone,
        car_make=car_make,
        car_model=car_model,
        car_year=car_year,
        current_insurance=current_insurance,
        status=status,
        notes=notes,
    )
    session.add(lead)
    await session.flush()
    return lead


async def transition_lead_status(
    session: AsyncSession,
    lead_id: str,
    to_status: str,
) -> Lead:
    """Transition a lead's status to a new value, enforcing the state machine.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to transition.
        to_status: Target status string (e.g., "called", "interested").

    Returns:
        Updated Lead instance.

    Raises:
        ValueError: If lead_id does not exist.
        InvalidTransitionError: If the transition is not allowed.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise ValueError(f"Lead not found: {lead_id!r}")

    if not is_valid_transition(lead.status, to_status):
        raise InvalidTransitionError(lead.status, to_status)

    lead.status = to_status
    lead.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return lead


# ---------------------------------------------------------------------------
# Seed data — 5 Quintana Seguros test leads
# ---------------------------------------------------------------------------

_SEED_LEADS = [
    {
        "id": "lead-quintana-001",
        "name": "Carlos Méndez",
        "phone": "+5411155501",
        "car_make": "Toyota",
        "car_model": "Corolla",
        "car_year": 2021,
        "current_insurance": None,
        "status": LeadStatus.NEW.value,
        "notes": "Pidió cotización por web",
    },
    {
        "id": "lead-quintana-002",
        "name": "María López",
        "phone": "+5411155502",
        "car_make": "VW",
        "car_model": "Golf",
        "car_year": 2019,
        "current_insurance": None,
        "status": LeadStatus.NEW.value,
        "notes": "Referida por cliente existente",
    },
    {
        "id": "lead-quintana-003",
        "name": "Juan Pérez",
        "phone": "+5411155503",
        "car_make": "Ford",
        "car_model": "Ranger",
        "car_year": 2022,
        "current_insurance": None,
        "status": LeadStatus.CALLED.value,
        "notes": "Llamado una vez, no atendió",
    },
    {
        "id": "lead-quintana-004",
        "name": "Ana García",
        "phone": "+5411155504",
        "car_make": "Fiat",
        "car_model": "Cronos",
        "car_year": 2023,
        "current_insurance": None,
        "status": LeadStatus.INTERESTED.value,
        "notes": "Quiere todo riesgo",
    },
    {
        "id": "lead-quintana-005",
        "name": "Roberto Silva",
        "phone": "+5411155505",
        "car_make": "Chevrolet",
        "car_model": "Cruze",
        "car_year": 2020,
        "current_insurance": "La Caja",
        "status": LeadStatus.NOT_INTERESTED.value,
        "notes": "Tiene seguro reciente",
    },
]


async def seed_leads(session: AsyncSession) -> None:
    """Seed 5 test leads for quintana-seguros if none exist.

    Idempotent: skips if any leads already exist for the client.
    """
    existing = await list_leads_for_client(session, "quintana-seguros")
    if existing:
        return  # Already seeded — skip

    for data in _SEED_LEADS:
        lead = Lead(
            id=data["id"],
            client_id="quintana-seguros",
            name=data["name"],
            phone=data["phone"],
            car_make=data.get("car_make"),
            car_model=data.get("car_model"),
            car_year=data.get("car_year"),
            current_insurance=data.get("current_insurance"),
            status=data["status"],
            notes=data.get("notes"),
        )
        session.add(lead)

    await session.flush()
