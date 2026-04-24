"""QORA Leads — Admin/debug router for lead management.

Provides endpoints for:
- GET /api/v1/leads?client_id={id} — list leads for a client
- GET /api/v1/leads/{id} — get single lead
- POST /api/v1/leads — create lead
- PATCH /api/v1/leads/{id}/status — transition status
- GET /api/v1/leads/{id}/history — call history for lead

Covers: T2.4 — GET/PATCH endpoints scope queries by client_id.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import LeadStatus
from app.leads.service import (
    InvalidTransitionError,
    create_lead,
    get_lead,
    list_leads_for_client,
    transition_lead_status,
)
from app.scheduler.models import ScheduledCall

router = APIRouter(prefix="/leads", tags=["leads"])


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------


async def get_db_session():
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class CreateLeadRequest(BaseModel):
    """Request body for creating a new lead."""

    client_id: str
    name: str
    phone: str
    car_make: str | None = None
    car_model: str | None = None
    car_year: int | None = None
    current_insurance: str | None = None
    notes: str | None = None


class PatchStatusRequest(BaseModel):
    """Request body for transitioning lead status."""

    status: LeadStatus


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------


async def _batch_next_scheduled_call_at(
    session: AsyncSession, lead_ids: list[str]
) -> dict[str, datetime]:
    """Return {lead_id: earliest_pending_scheduled_at} for the given lead IDs.

    Issues ONE query using MIN(scheduled_at) GROUP BY lead_id, filtered to
    status IN ('pending', 'in_progress'). Uses the composite index
    ix_scheduled_calls_lead_status for efficiency.

    Returns an empty dict when lead_ids is empty (avoids unnecessary query).
    """
    if not lead_ids:
        return {}

    stmt = (
        select(
            ScheduledCall.lead_id,
            func.min(ScheduledCall.scheduled_at).label("earliest"),
        )
        .where(
            ScheduledCall.lead_id.in_(lead_ids),
            ScheduledCall.status.in_(["pending", "in_progress"]),
        )
        .group_by(ScheduledCall.lead_id)
    )
    result = await session.execute(stmt)
    return {row.lead_id: row.earliest for row in result}


def _lead_to_dict(lead, *, next_scheduled_call_at: datetime | None = None) -> dict:
    """Serialize a Lead ORM object to a response dict.

    Includes Phase 2 CRM fields (summary_last_call, interest_level, etc.) and
    Phase 7 enrichment field (next_scheduled_call_at).
    All optional fields are null-safe — returned as null if not set.

    Args:
        lead: Lead ORM instance.
        next_scheduled_call_at: Optional datetime from batch enrichment query.
            Passed by list_leads(); other callers omit it (defaults to None).
    """
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
        "last_called_at": (
            lead.last_called_at.isoformat() if lead.last_called_at else None
        ),
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        # Phase 2 CRM fields — null-safe
        "summary_last_call": lead.summary_last_call,
        "objections_heard": lead.objections_heard,
        "interest_level": lead.interest_level,
        "extracted_facts": lead.extracted_facts,
        "do_not_call": lead.do_not_call,
        "next_action": lead.next_action,
        "next_action_at": (
            lead.next_action_at.isoformat() if lead.next_action_at else None
        ),
        # Phase 7 enrichment — earliest pending/in_progress scheduled call
        "next_scheduled_call_at": (
            next_scheduled_call_at.isoformat() if next_scheduled_call_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_leads(
    client_id: str = Query(..., description="Tenant client ID to scope results"),
    session: AsyncSession = Depends(get_db_session),
):
    """List all leads for a given client.

    Returns each lead enriched with next_scheduled_call_at (Phase 7):
    the earliest pending/in_progress scheduled call time, or null if none.
    Uses a single batch MIN() query — no N+1.

    Returns:
        List of lead objects for the specified client_id.

    Raises:
        422: If client_id query parameter is missing.
    """
    leads = await list_leads_for_client(session, client_id)
    if not leads:
        return []
    lead_ids = [lead.id for lead in leads]
    schedule_map = await _batch_next_scheduled_call_at(session, lead_ids)
    return [
        _lead_to_dict(lead, next_scheduled_call_at=schedule_map.get(lead.id))
        for lead in leads
    ]


@router.get("/{lead_id}")
async def get_lead_by_id(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single lead by its UUID.

    Returns:
        Lead object with all fields.

    Raises:
        404: If lead_id does not exist.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})
    return _lead_to_dict(lead)


@router.post("", status_code=201)
async def create_new_lead(
    body: CreateLeadRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new lead record.

    Returns:
        Created lead object (HTTP 201).
    """
    lead = await create_lead(
        session,
        client_id=body.client_id,
        name=body.name,
        phone=body.phone,
        car_make=body.car_make,
        car_model=body.car_model,
        car_year=body.car_year,
        current_insurance=body.current_insurance,
        notes=body.notes,
    )
    await session.commit()
    return _lead_to_dict(lead)


@router.patch("/{lead_id}/status")
async def patch_lead_status(
    lead_id: str,
    body: PatchStatusRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Transition a lead's status via the state machine.

    Returns:
        Updated lead object.

    Raises:
        404: If lead_id does not exist.
        409: If the transition is not allowed by the state machine.
        422: If status field is missing from request body.
    """
    try:
        lead = await transition_lead_status(session, lead_id, body.status)
    except ValueError:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})
    except InvalidTransitionError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "from": e.from_status,
                "to": e.to_status,
            },
        )

    await session.commit()
    return _lead_to_dict(lead)


@router.get("/{lead_id}/history")
async def get_lead_history(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get call session history for a lead.

    Returns:
        Dict with lead_id and list of call sessions.

    Raises:
        404: If lead_id does not exist.
    """
    from sqlalchemy import select
    from app.calls.models import CallSession

    # Verify lead exists
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Fetch all call sessions for this lead
    result = await session.execute(
        select(CallSession)
        .where(CallSession.lead_id == lead_id)
        .order_by(CallSession.started_at)
    )
    sessions = list(result.scalars().all())

    return {
        "lead_id": lead_id,
        "sessions": [
            {
                "id": cs.id,
                "client_id": cs.client_id,
                "status": cs.status,
                "outcome": cs.outcome,
                "started_at": cs.started_at.isoformat() if cs.started_at else None,
                "ended_at": cs.ended_at.isoformat() if cs.ended_at else None,
                "duration_seconds": cs.duration_seconds,
                "billable_minutes": cs.billable_minutes,
            }
            for cs in sessions
        ],
    }
