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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.schemas import ClientCreate, ClientResponse, ClientUpdate
from app.tenants.models import Client

router = APIRouter(prefix="/clients", tags=["clients"])


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
# Helper
# ---------------------------------------------------------------------------


def _client_to_response(client: Client) -> ClientResponse:
    """Map a Client ORM object to a ClientResponse schema."""
    return ClientResponse(
        client_id=client.id,
        broker_name=client.broker_name,
        agent_name=client.agent_name,
        voice_id=client.voice_id,
        is_active=client.is_active,
        created_at=client.created_at,
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

    Returns:
        201: ClientResponse with the created client.
        409: If client_id already exists.
        422: If slug validation fails (handled by Pydantic).
    """
    # Check for duplicate
    existing = await session.get(Client, payload.client_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "client already exists", "client_id": payload.client_id},
        )

    client = Client(
        id=payload.client_id,
        # name must be unique — use broker_name as display name
        name=payload.broker_name,
        broker_name=payload.broker_name,
        agent_name=payload.agent_name,
        voice_id=payload.voice_id,
        system_prompt_override=payload.system_prompt_override,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    await session.commit()
    await session.refresh(client)
    return _client_to_response(client)


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
    return [_client_to_response(c) for c in clients]


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
    return _client_to_response(client)


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
        effective_start = patch_start if patch_start is not None else client.scheduler_allowed_hours_start
        effective_end = patch_end if patch_end is not None else client.scheduler_allowed_hours_end
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
    return _client_to_response(client)


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
    return _client_to_response(client)
