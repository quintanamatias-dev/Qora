"""QORA Clients — Full CRUD router under /api/v1/clients.

Endpoints:
    POST   /api/v1/clients              — Create client (201 / 409 / 422)
    GET    /api/v1/clients              — List active clients (200)
    GET    /api/v1/clients/{client_id}  — Get single client (200 / 404)
    PATCH  /api/v1/clients/{client_id}  — Partial update (200 / 404)
    DELETE /api/v1/clients/{client_id}  — Soft delete (200 / 404)

Uses existing `tenants` SQLAlchemy models — no new DB models created.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.schemas import ClientCreate, ClientResponse, ClientUpdate
from app.core.auth import require_api_key
from app.tenants.models import Agent, Client
import app.tenants.service as tenant_service

router = APIRouter(
    prefix="/clients",
    tags=["clients"],
    dependencies=[Depends(require_api_key)],
)


# ---------------------------------------------------------------------------
# DB session dependency
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify_client_id(name: str) -> str:
    """Convert a display name to an ASCII URL slug.

    Examples:
        'Qora Demo' → 'qora-demo'
        'Acme Corp!' → 'acme-corp'
        '  Spaces  ' → 'spaces'
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "client"


def _client_to_response(client: Client, agent_count: int = 0) -> ClientResponse:
    """Map a Client ORM object to a ClientResponse schema."""
    return ClientResponse(
        client_id=client.id,
        name=client.name,
        agent_name=client.agent_name,
        voice_id=client.voice_id,
        is_active=client.is_active,
        created_at=client.created_at,
        agent_count=agent_count,
        scheduler_enabled=client.scheduler_enabled,
        scheduler_max_attempts=client.scheduler_max_attempts,
        scheduler_cooldown_minutes=client.scheduler_cooldown_minutes,
        scheduler_allowed_hours_start=client.scheduler_allowed_hours_start,
        scheduler_allowed_hours_end=client.scheduler_allowed_hours_end,
        scheduler_retry_on_outcomes=client.scheduler_retry_on_outcomes,
        scheduler_timezone=client.scheduler_timezone,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/clients
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=ClientResponse)
async def create_client(
    payload: ClientCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new client.

    Delegates to service.create_client() which automatically bootstraps a
    default Agent for the new client (regression fix — router MUST NOT
    construct Client() directly).

    When `client_id` is omitted, a URL-safe slug is auto-generated from
    `name`. Collisions are resolved by appending `-2`, `-3`, etc.

    Returns:
        201: ClientResponse with the created client.
        409: If explicit client_id already exists.
        422: If slug validation fails (handled by Pydantic).
    """
    # Resolve client_id: use explicit value or auto-generate from name
    if payload.client_id is not None:
        resolved_id = payload.client_id
        # Check for duplicate on explicit id
        existing = await session.get(Client, resolved_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={"error": "client already exists", "client_id": resolved_id},
            )
    else:
        # Auto-generate slug with collision dedup
        base_slug = _slugify_client_id(payload.name)
        resolved_id = base_slug
        suffix = 2
        while await session.get(Client, resolved_id) is not None:
            resolved_id = f"{base_slug}-{suffix}"
            suffix += 1

    try:
        client = await tenant_service.create_client(
            session,
            id=resolved_id,
            name=payload.name,
            agent_name=payload.agent_name,
            voice_id=payload.voice_id,
            system_prompt_override=payload.system_prompt_override,
            scheduler_enabled=payload.scheduler_enabled,
            scheduler_max_attempts=payload.scheduler_max_attempts,
            scheduler_cooldown_minutes=payload.scheduler_cooldown_minutes,
            scheduler_allowed_hours_start=payload.scheduler_allowed_hours_start,
            scheduler_allowed_hours_end=payload.scheduler_allowed_hours_end,
            scheduler_retry_on_outcomes=payload.scheduler_retry_on_outcomes,
            scheduler_timezone=payload.scheduler_timezone,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "client name already exists",
                "name": payload.name,
            },
        )
    await session.refresh(client)
    count_result = await session.execute(
        select(func.count(Agent.id)).where(
            Agent.client_id == client.id,
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent_count = count_result.scalar_one() or 0
    return _client_to_response(client, agent_count=agent_count)


# ---------------------------------------------------------------------------
# GET /api/v1/clients
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ClientResponse])
async def list_clients(
    session: AsyncSession = Depends(get_db_session),
):
    """Return all active clients.

    Returns:
        200: List of active ClientResponse objects.
    """
    result = await session.execute(select(Client).where(Client.is_active == True))  # noqa: E712
    clients = result.scalars().all()

    # Query active agent counts for all active clients in one round trip
    client_ids = [c.id for c in clients]
    counts_result = await session.execute(
        select(Agent.client_id, func.count(Agent.id).label("agent_count"))
        .where(
            Agent.client_id.in_(client_ids),
            Agent.is_active == True,  # noqa: E712
        )
        .group_by(Agent.client_id)
    )
    counts: dict[str, int] = {row.client_id: row.agent_count for row in counts_result}

    return [_client_to_response(c, agent_count=counts.get(c.id, 0)) for c in clients]


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Return a single client by id.

    Returns:
        200: ClientResponse.
        404: If client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )
    count_result = await session.execute(
        select(func.count(Agent.id)).where(
            Agent.client_id == client_id,
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent_count = count_result.scalar_one() or 0
    return _client_to_response(client, agent_count=agent_count)


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    payload: ClientUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Partially update a client. Only provided fields are updated.

    client_id is NOT updatable.

    Returns:
        200: Updated ClientResponse.
        404: If client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    update_data = payload.model_dump(exclude_unset=True)

    # Validate combined hour window: merge incoming PATCH values with current DB values
    # so partial updates like {"scheduler_allowed_hours_start": 22} are caught when
    # the stored end_hour would create an invalid window (start >= end).
    patch_start = update_data.get("scheduler_allowed_hours_start")
    patch_end = update_data.get("scheduler_allowed_hours_end")
    if patch_start is not None or patch_end is not None:
        effective_start = (
            patch_start
            if patch_start is not None
            else client.scheduler_allowed_hours_start
        )
        effective_end = (
            patch_end if patch_end is not None else client.scheduler_allowed_hours_end
        )
        if effective_start >= effective_end:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_hour_window",
                    "detail": (
                        f"scheduler_allowed_hours_start ({effective_start}) must be less than "
                        f"scheduler_allowed_hours_end ({effective_end})."
                    ),
                },
            )

    for field, value in update_data.items():
        if hasattr(client, field):
            setattr(client, field, value)

    await session.flush()
    await session.commit()
    await session.refresh(client)
    count_result = await session.execute(
        select(func.count(Agent.id)).where(
            Agent.client_id == client_id,
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent_count = count_result.scalar_one() or 0
    return _client_to_response(client, agent_count=agent_count)


# ---------------------------------------------------------------------------
# DELETE /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


@router.delete("/{client_id}", response_model=ClientResponse)
async def delete_client(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Soft-delete a client (sets is_active=False). Record is NOT removed.

    Returns:
        200: ClientResponse with is_active=False.
        404: If client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    client.is_active = False
    await session.flush()
    await session.commit()
    await session.refresh(client)
    count_result = await session.execute(
        select(func.count(Agent.id)).where(
            Agent.client_id == client_id,
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent_count = count_result.scalar_one() or 0
    return _client_to_response(client, agent_count=agent_count)
