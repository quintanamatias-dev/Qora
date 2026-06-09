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
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads import lead_custom_fields_service as cf_service
from app.leads.models import LeadStatus
from app.leads.service import (
    InvalidTransitionError,
    create_lead,
    get_active_profile_facts,
    get_interest_history,
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

    # Backward-compatible optional body field. New frontend calls scope by
    # `client_id` query param, matching list endpoints.
    client_id: str | None = None
    name: str
    phone: str
    notes: str | None = None
    # WU-6: optional custom fields written to lead_custom_fields table
    custom_fields: dict[str, str] | None = None

    model_config = ConfigDict(extra="forbid")


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


def _lead_to_dict(
    lead,
    *,
    next_scheduled_call_at: datetime | None = None,
    profile_facts: list | None = None,
    interest_history: list | None = None,
    custom_fields: dict[str, str] | None = None,
) -> dict:
    """Serialize a Lead ORM object to a response dict.

    Includes Phase 2 CRM fields (summary_last_call, interest_level, etc.),
    Phase 7 enrichment field (next_scheduled_call_at), Issue #36 additive
    fields (profile_facts, interest_history), and WU-6 custom_fields dict.
    All optional fields are null-safe — returned as null if not set.

    Args:
        lead: Lead ORM instance.
        next_scheduled_call_at: Optional datetime from batch enrichment query.
            Passed by list_leads(); other callers omit it (defaults to None).
        profile_facts: Pre-fetched list of active LeadProfileFact dicts (Issue #36).
            If None, defaults to empty dict in the response.
        interest_history: Pre-fetched list of LeadInterestHistory dicts (Issue #36).
            If None, defaults to empty list in the response.
        custom_fields: Pre-fetched {field_key: field_value} from lead_custom_fields (WU-6).
            If None, defaults to empty dict in the response.
    """
    # Group profile_facts by namespace prefix (strip trailing colon)
    grouped_profile_facts: dict = {}
    for row in profile_facts or []:
        fact_key = row.get("fact_key", "")
        # Extract namespace prefix (e.g. 'profile:married' → 'profile')
        if ":" in fact_key:
            namespace = fact_key.split(":")[0]
            value = row.get("fact_value") or fact_key[len(namespace) + 1 :]
            grouped_profile_facts.setdefault(namespace, []).append(value)

    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "name": lead.name,
        "phone": lead.phone,
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
        # Issue #36 additive fields — accumulated lead profile
        "profile_facts": grouped_profile_facts,
        "interest_history": [
            {
                "interest_level": row.get("interest_level"),
                "recorded_at": row.get("recorded_at"),
            }
            for row in (interest_history or [])
        ],
        # WU-6: dynamic custom fields from lead_custom_fields table
        "custom_fields": custom_fields if custom_fields is not None else {},
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
    leads = await list_leads_for_client(session, client_id.lower())
    if not leads:
        return []
    lead_ids = [lead.id for lead in leads]
    schedule_map = await _batch_next_scheduled_call_at(session, lead_ids)
    # WU-6: batch load custom fields for all leads in one query
    cf_map = await cf_service.batch_get(session, lead_ids, client_id.lower())
    return [
        _lead_to_dict(
            lead,
            next_scheduled_call_at=schedule_map.get(lead.id),
            custom_fields=cf_map.get(lead.id, {}),
        )
        for lead in leads
    ]


@router.get("/{lead_id}")
async def get_lead_by_id(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single lead by its UUID.

    Returns:
        Lead object with all fields including accumulated profile_facts and interest_history.

    Raises:
        404: If lead_id does not exist.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Issue #36: Fetch accumulated profile data from relational tables
    profile_facts = await get_active_profile_facts(session, lead_id)
    interest_history = await get_interest_history(session, lead_id)
    # WU-6: load custom fields scoped to this lead's client
    custom_fields = await cf_service.get_all(session, lead_id, lead.client_id)

    return _lead_to_dict(
        lead,
        profile_facts=profile_facts,
        interest_history=interest_history,
        custom_fields=custom_fields,
    )


@router.post("", status_code=201)
async def create_new_lead(
    body: CreateLeadRequest,
    client_id: str | None = Query(None, description="Tenant client ID to scope creation"),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new lead record.

    Returns:
        Created lead object (HTTP 201).
    """
    resolved_client_id = (client_id or body.client_id or "").lower()
    if not resolved_client_id:
        raise HTTPException(status_code=422, detail={"error": "client_id is required"})

    lead = await create_lead(
        session,
        client_id=resolved_client_id,
        name=body.name,
        phone=body.phone,
        notes=body.notes,
    )

    # WU-6: write custom_fields to lead_custom_fields table if provided
    if body.custom_fields:
        await cf_service.upsert_many(
            session,
            lead_id=lead.id,
            client_id=resolved_client_id,
            fields=body.custom_fields,
        )

    await session.commit()

    # Reload custom fields after commit so response reflects stored values
    custom_fields = await cf_service.get_all(session, lead.id, resolved_client_id)
    return _lead_to_dict(lead, custom_fields=custom_fields)


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
    # WU-6: include custom_fields in patch status response
    custom_fields = await cf_service.get_all(session, lead_id, lead.client_id)
    return _lead_to_dict(lead, custom_fields=custom_fields)


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
