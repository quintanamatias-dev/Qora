"""QORA Scheduler — REST API router for ScheduledCall CRUD (Phase 6).

Endpoints under /api/v1/scheduler/{client_id}/queue:
    POST   /                     — Create manual ScheduledCall
    GET    /                     — List queue (with optional status/lead filters)
    GET    /{id}                 — Get single ScheduledCall
    POST   /{id}/cancel          — Cancel (pending → cancelled)
    PATCH  /{id}                 — Reschedule (update scheduled_at, pending only)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key

from app.scheduler.schemas import (
    ScheduledCallCreate,
    ScheduledCallReschedule,
    ScheduledCallResponse,
)
from app.scheduler.service import (
    cancel_scheduled_call,
    complete_scheduled_call,
    create_scheduled_call,
    get_active_scheduled_call_for_lead,
    get_scheduled_call,
    list_queue,
    reschedule_call,
)

router = APIRouter(
    tags=["scheduler"],
    dependencies=[Depends(require_api_key)],
)
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# DB session dependency (reuses pattern from clients/router.py)
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# POST /api/v1/scheduler/{client_id}/queue
# ---------------------------------------------------------------------------


@router.post(
    "/scheduler/{client_id}/queue",
    status_code=201,
    response_model=ScheduledCallResponse,
)
@router.post(
    "/clients/{client_id}/scheduled-calls",
    status_code=201,
    response_model=ScheduledCallResponse,
)
async def create_manual_scheduled_call(
    client_id: str,
    payload: ScheduledCallCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a manual ScheduledCall for a client's lead.

    Returns:
        201: ScheduledCallResponse with the created record.
        404: If client or lead does not exist.
        403: If lead belongs to a different tenant.
        422: If scheduled_at is outside the client's allowed hours.
    """
    from app.tenants.models import Client
    from app.leads.models import Lead
    from zoneinfo import ZoneInfo

    # Load and validate client
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    # Issue 1: Validate lead ownership (multi-tenant isolation)
    lead = await session.get(Lead, payload.lead_id)
    if lead is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "lead not found", "lead_id": payload.lead_id},
        )
    if lead.client_id != client_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "lead does not belong to this client",
                "lead_id": payload.lead_id,
            },
        )

    # Issue 2: Validate scheduled_at against allowed hours
    tz = ZoneInfo(client.scheduler_timezone)
    local_dt = payload.scheduled_at.astimezone(tz)
    if not (
        client.scheduler_allowed_hours_start
        <= local_dt.hour
        < client.scheduler_allowed_hours_end
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"scheduled_at ({local_dt.strftime('%H:%M')} local) "
                    f"is outside allowed hours "
                    f"[{client.scheduler_allowed_hours_start}–{client.scheduler_allowed_hours_end})."
                )
            },
        )

    duplicate = await get_active_scheduled_call_for_lead(
        session,
        client_id=client_id,
        lead_id=payload.lead_id,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "scheduled call already exists",
                "scheduled_call_id": duplicate.id,
            },
        )

    # Resolve agent_id: use the client's default agent (manual calls have no source session)
    from app.tenants.service import get_default_agent

    default_agent = await get_default_agent(session, client_id)
    if default_agent is None:
        logger.warning(
            "manual_scheduled_call_no_default_agent",
            client_id=client_id,
        )
    resolved_agent_id = default_agent.id if default_agent is not None else None

    sc = await create_scheduled_call(
        session,
        client_id=client_id,
        lead_id=payload.lead_id,
        scheduled_at=payload.scheduled_at,
        trigger_reason="manual",
        source_session_id=None,
        attempt_number=1,
        max_attempts=client.scheduler_max_attempts,
        notes=payload.notes,
        agent_id=resolved_agent_id,
    )
    await session.commit()
    await session.refresh(sc)
    return ScheduledCallResponse.model_validate(sc)


# ---------------------------------------------------------------------------
# GET /api/v1/scheduler/{client_id}/queue
# ---------------------------------------------------------------------------


@router.get(
    "/scheduler/{client_id}/queue",
    response_model=list[ScheduledCallResponse],
)
@router.get(
    "/clients/{client_id}/scheduled-calls",
    response_model=list[ScheduledCallResponse],
)
async def list_scheduled_calls(
    client_id: str,
    status: str | None = None,
    lead_id: str | None = None,
    scheduled_from: Optional[datetime] = Query(default=None),
    scheduled_to: Optional[datetime] = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    """List ScheduledCalls for a client with optional filters.

    Query params:
        status: Comma-separated list of statuses to filter by.
        lead_id: Filter by specific lead.
        scheduled_from: ISO 8601 datetime lower bound (inclusive).
        scheduled_to: ISO 8601 datetime upper bound (inclusive).

    Returns:
        200: List of ScheduledCallResponse objects.
        422: If date filters are not valid ISO 8601 datetimes.
    """
    status_filter = status.split(",") if status else None
    calls = await list_queue(
        session,
        client_id=client_id,
        status_filter=status_filter,
        lead_id=lead_id,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
    )
    return [ScheduledCallResponse.model_validate(sc) for sc in calls]


# ---------------------------------------------------------------------------
# GET /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}
# ---------------------------------------------------------------------------


@router.get(
    "/scheduler/{client_id}/queue/{scheduled_call_id}",
    response_model=ScheduledCallResponse,
)
@router.get(
    "/clients/{client_id}/scheduled-calls/{scheduled_call_id}",
    response_model=ScheduledCallResponse,
)
async def get_single_scheduled_call(
    client_id: str,
    scheduled_call_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single ScheduledCall.

    Returns:
        200: ScheduledCallResponse.
        404: If not found or belongs to a different client.
    """
    sc = await get_scheduled_call(session, scheduled_call_id)
    if sc is None or sc.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "scheduled call not found", "id": scheduled_call_id},
        )
    return ScheduledCallResponse.model_validate(sc)


# ---------------------------------------------------------------------------
# POST /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/scheduler/{client_id}/queue/{scheduled_call_id}/cancel",
    response_model=ScheduledCallResponse,
)
@router.patch(
    "/clients/{client_id}/scheduled-calls/{scheduled_call_id}/cancel",
    response_model=ScheduledCallResponse,
)
async def cancel_call(
    client_id: str,
    scheduled_call_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Cancel a pending or in_progress ScheduledCall.

    Returns:
        200: ScheduledCallResponse with status=cancelled.
        404: If not found or belongs to a different client.
        409: If the call is in a non-cancellable state.
    """
    sc = await get_scheduled_call(session, scheduled_call_id)
    if sc is None or sc.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "scheduled call not found", "id": scheduled_call_id},
        )

    try:
        cancelled = await cancel_scheduled_call(session, scheduled_call_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)})

    await session.commit()
    await session.refresh(cancelled)
    return ScheduledCallResponse.model_validate(cancelled)


# ---------------------------------------------------------------------------
# PATCH /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/scheduler/{client_id}/queue/{scheduled_call_id}",
    response_model=ScheduledCallResponse,
)
@router.patch(
    "/clients/{client_id}/scheduled-calls/{scheduled_call_id}/reschedule",
    response_model=ScheduledCallResponse,
)
async def reschedule_scheduled_call(
    client_id: str,
    scheduled_call_id: str,
    payload: ScheduledCallReschedule,
    session: AsyncSession = Depends(get_db_session),
):
    """Reschedule a pending ScheduledCall to a new datetime.

    New datetime must be within the client's allowed hours.

    Returns:
        200: ScheduledCallResponse with updated scheduled_at.
        404: If not found or belongs to a different client.
        422: If new_scheduled_at is outside allowed hours or call is not pending.
    """
    sc = await get_scheduled_call(session, scheduled_call_id)
    if sc is None or sc.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "scheduled call not found", "id": scheduled_call_id},
        )

    # Load client for allowed hours config
    from app.tenants.models import Client

    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    try:
        rescheduled = await reschedule_call(
            session,
            scheduled_call_id,
            new_scheduled_at=payload.scheduled_at,
            client_allowed_hours_start=client.scheduler_allowed_hours_start,
            client_allowed_hours_end=client.scheduler_allowed_hours_end,
            client_timezone=client.scheduler_timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)})

    await session.commit()
    await session.refresh(rescheduled)
    return ScheduledCallResponse.model_validate(rescheduled)


@router.patch(
    "/clients/{client_id}/scheduled-calls/{scheduled_call_id}/complete",
    response_model=ScheduledCallResponse,
)
async def complete_call(
    client_id: str,
    scheduled_call_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Mark a scheduled call completed using the spec-compliant Phase 6 endpoint."""
    sc = await get_scheduled_call(session, scheduled_call_id)
    if sc is None or sc.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "scheduled call not found", "id": scheduled_call_id},
        )

    try:
        completed = await complete_scheduled_call(session, scheduled_call_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": str(exc)})

    await session.commit()
    await session.refresh(completed)
    return ScheduledCallResponse.model_validate(completed)
