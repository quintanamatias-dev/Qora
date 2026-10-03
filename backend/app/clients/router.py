"""QORA Clients — Full CRUD router under /api/v1/clients.

Endpoints:
    POST   /api/v1/clients              — Create client (201 / 409 / 422)
    GET    /api/v1/clients              — List active clients the caller can access (200)
    GET    /api/v1/clients/{client_id}  — Get single client (200 / 404)
    PATCH  /api/v1/clients/{client_id}  — Partial update (200 / 404)
    DELETE /api/v1/clients/{client_id}  — Soft delete (200 / 404)

Uses existing `tenants` SQLAlchemy models — no new DB models created.
"""

from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.schemas import (
    AnalysisProfileResponse,
    ApplyAnalysisProfileTemplatePayload,
    ClientConfigRevisionResponse,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    PutAnalysisProfilePayload,
    RollbackAnalysisProfilePayload,
)
from app.core.access import require_client_access, require_superadmin
from app.core.auth import CallerIdentity, require_api_key
from app.elevenlabs.service import sync_to_elevenlabs
from app.tenants.client_config_schema import ClientConfigPatch, ClientConfigV1
from app.tenants.materialize import materialize_agent_config, snapshot_mirrored_fields
from app.tenants.models import Agent, Client, ClientAnalysisProfileRevision, ClientConfigRevision
import app.tenants.service as tenant_service
from app.tenants import revisions_service

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
        'Acme Widgets' → 'acme-widgets'
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
        scheduler_backoff_multiplier=client.scheduler_backoff_multiplier,
        next_action_max_attempts=client.next_action_max_attempts,
        next_action_min_interest_for_followup=client.next_action_min_interest_for_followup,
        next_action_close_on_hard_rejection=client.next_action_close_on_hard_rejection,
        analysis_language=client.analysis_language,
        plan=client.plan or "pilot",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/clients
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=ClientResponse, dependencies=[Depends(require_superadmin)])
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
            scheduler_backoff_multiplier=payload.scheduler_backoff_multiplier,
        )
        # agent-config-inheritance D11/D18: service.create_client() bootstraps
        # the client's initial empty config revision — every caller (seeders,
        # service, this router) gets it from one place.
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
    caller: CallerIdentity = Depends(require_api_key),
):
    """Return the active clients the caller can access.

    Superadmins see every client; tenant users see only their own, which lets
    the panel resolve "my client" through the same endpoint.

    Returns:
        200: List of active ClientResponse objects.
    """
    result = await session.execute(select(Client).where(Client.is_active == True))  # noqa: E712
    clients = [c for c in result.scalars().all() if caller.can_access(c.id)]

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


@router.get("/{client_id}", response_model=ClientResponse, dependencies=[Depends(require_client_access)])
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


@router.patch("/{client_id}", response_model=ClientResponse, dependencies=[Depends(require_superadmin)])
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


@router.delete("/{client_id}", response_model=ClientResponse, dependencies=[Depends(require_superadmin)])
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


# ---------------------------------------------------------------------------
# Client config revisions (agent-config-inheritance D11)
# ---------------------------------------------------------------------------


def _client_revision_to_response(
    revision: ClientConfigRevision,
) -> ClientConfigRevisionResponse:
    return ClientConfigRevisionResponse(
        id=revision.id,
        client_id=revision.client_id,
        revision_number=revision.revision_number,
        config=json.loads(revision.config),
        schema_version=revision.schema_version,
        source=revision.source,
        created_by=revision.created_by,
        created_at=revision.created_at,
        note=revision.note,
    )


async def _materialize_and_propagate(
    session: AsyncSession, request: Request, client_id: str
) -> None:
    """design.md D19/task 5.5: after a client config revision is activated,
    re-materialize every ACTIVE agent of that client and trigger the
    existing EL sync (fire-and-forget, same mechanism agents/router.py uses)
    for agents whose mirrored columns actually changed and that have an
    elevenlabs_agent_id. Agents with no column change are left alone — an
    unrelated client-level edit must not fan out a sync storm.
    """
    agents = await tenant_service.list_agents_for_client(session, client_id)
    agents_to_sync: list[str] = []
    for agent in agents:
        before = snapshot_mirrored_fields(agent)
        await materialize_agent_config(session, agent)
        after = snapshot_mirrored_fields(agent)
        changed = any(before[field] != after[field] for field in before)
        if changed and agent.elevenlabs_agent_id:
            agents_to_sync.append(agent.id)

    await session.commit()

    if agents_to_sync:
        settings = request.app.state.settings
        for agent_id in agents_to_sync:
            asyncio.create_task(sync_to_elevenlabs(agent_id=agent_id, settings=settings))


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}/config
# ---------------------------------------------------------------------------


@router.patch(
    "/{client_id}/config",
    response_model=ClientConfigRevisionResponse,
    dependencies=[Depends(require_superadmin)],
)
async def patch_client_config(
    client_id: str,
    payload: ClientConfigPatch,
    request: Request,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> ClientConfigRevisionResponse:
    """Partial config update merged over the active sparse revision, then
    validated as ClientConfigV1 before a new revision is created and activated.

    A field explicitly set to null removes that override (inherit from the
    standard/agent again).

    Returns:
        200: The newly-activated ClientConfigRevisionResponse.
        404: If the client does not exist.
        422: If the merged config fails ClientConfigV1 validation (locked or
             agent_required field present, or a value out of range).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    active = await revisions_service.get_active_client_revision(session, client_id)
    base_config = json.loads(active.config) if active is not None else {}
    base_config.pop("schema_version", None)

    patch_data = payload.model_dump(exclude_unset=True, exclude={"note"})
    merged = {**base_config, **patch_data}
    # A field explicitly set to null removes the override entirely.
    merged = {k: v for k, v in merged.items() if v is not None}

    try:
        validated = ClientConfigV1(**merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_config", "detail": str(exc)},
        ) from exc

    revision = await revisions_service.create_client_revision(
        session,
        client=client,
        config=validated,
        source="api",
        created_by=caller.email or "api",
        note=payload.note,
    )

    await session.commit()
    await session.refresh(revision)

    await _materialize_and_propagate(session, request, client_id)

    return _client_revision_to_response(revision)


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/revisions
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/revisions", response_model=list[ClientConfigRevisionResponse]
)
async def list_client_config_revisions(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[ClientConfigRevisionResponse]:
    """Return every config revision for a client, newest first.

    Returns:
        200: List of ClientConfigRevisionResponse.
        404: If the client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    revisions = await revisions_service.list_client_revisions(session, client_id)
    return [_client_revision_to_response(r) for r in revisions]


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/revisions/{revision_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/revisions/{revision_id}",
    response_model=ClientConfigRevisionResponse,
)
async def get_client_config_revision(
    client_id: str,
    revision_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ClientConfigRevisionResponse:
    """Return a single config revision by id, scoped to this client.

    Returns:
        200: ClientConfigRevisionResponse.
        404: If the client or revision does not exist (or the revision
             belongs to another client — identical response, no probing signal).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    revision = await revisions_service.get_client_revision(
        session, client_id, revision_id
    )
    if revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_id": revision_id},
        )
    return _client_revision_to_response(revision)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/revisions/{revision_id}/rollback
# ---------------------------------------------------------------------------


@router.post(
    "/{client_id}/revisions/{revision_id}/rollback",
    response_model=ClientConfigRevisionResponse,
    dependencies=[Depends(require_superadmin)],
)
async def rollback_client_config(
    client_id: str,
    revision_id: str,
    request: Request,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> ClientConfigRevisionResponse:
    """Roll back to a prior client config revision: creates a NEW revision
    (source="rollback") copying the target's sparse config, then activates it.
    The target row is never reactivated or mutated.

    Returns:
        200: The newly-created rollback ClientConfigRevisionResponse.
        404: If the client or target revision does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    new_revision = await revisions_service.rollback_client_revision(
        session, client_id, revision_id, created_by=caller.email or "api"
    )
    if new_revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_id": revision_id},
        )

    await session.commit()
    await session.refresh(new_revision)

    await _materialize_and_propagate(session, request, client_id)

    return _client_revision_to_response(new_revision)


# ---------------------------------------------------------------------------
# Analysis profile revisions (analysis-profiles, design.md P5-D7)
# ---------------------------------------------------------------------------


def _analysis_profile_revision_to_response(
    revision: ClientAnalysisProfileRevision,
) -> AnalysisProfileResponse:
    from app.analysis.profiles.schema import AnalysisProfileConfigV1

    config = AnalysisProfileConfigV1.model_validate_json(revision.config)
    return AnalysisProfileResponse(
        id=revision.id,
        client_id=revision.client_id,
        revision_number=revision.revision_number,
        vertical=config.vertical,
        products=config.products,
        need_tags=config.need_tags,
        source=revision.source,
        created_by=revision.created_by,
        created_at=revision.created_at,
        note=revision.note,
    )


@router.get(
    "/{client_id}/analysis-profile",
    response_model=AnalysisProfileResponse,
)
async def get_analysis_profile(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisProfileResponse:
    """Returns the client's active analysis profile revision.

    Returns:
        200: AnalysisProfileResponse.
        404: If the client does not exist, or has no active revision.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )
    revision = await revisions_service.get_active_analysis_profile_revision(session, client_id)
    if revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no active analysis profile", "client_id": client_id},
        )
    return _analysis_profile_revision_to_response(revision)


@router.put(
    "/{client_id}/analysis-profile",
    response_model=AnalysisProfileResponse,
    dependencies=[Depends(require_superadmin)],
)
async def put_analysis_profile(
    client_id: str,
    payload: PutAnalysisProfilePayload,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisProfileResponse:
    """Creates and activates a new analysis profile revision.

    Validates: product ids unique within the submitted list, need-tag ids
    unique within the submitted list, every label_es/label_en non-empty
    (enforced by ProductEntry/NeedTagEntry) — 422 on any violation.

    Returns:
        200: The newly-created AnalysisProfileResponse.
        404: If the client does not exist.
        422: If the payload fails validation.
    """
    from app.analysis.profiles.schema import AnalysisProfileConfigV1

    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    config = AnalysisProfileConfigV1(
        vertical=payload.vertical,
        products=payload.products,
        need_tags=payload.need_tags,
    )
    revision = await revisions_service.create_analysis_profile_revision(
        session,
        client=client,
        config=config,
        source="api",
        created_by=caller.email or "api",
        note=payload.note,
    )
    await session.commit()
    await session.refresh(revision)
    return _analysis_profile_revision_to_response(revision)


@router.get(
    "/{client_id}/analysis-profile/revisions",
    response_model=list[AnalysisProfileResponse],
)
async def list_analysis_profile_revisions(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[AnalysisProfileResponse]:
    """Returns every analysis profile revision for a client, newest first.

    Returns:
        200: List of AnalysisProfileResponse.
        404: If the client does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )
    revisions = await revisions_service.list_analysis_profile_revisions(session, client_id)
    return [_analysis_profile_revision_to_response(r) for r in revisions]


@router.post(
    "/{client_id}/analysis-profile/rollback",
    response_model=AnalysisProfileResponse,
    dependencies=[Depends(require_superadmin)],
)
async def rollback_analysis_profile(
    client_id: str,
    payload: RollbackAnalysisProfilePayload,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisProfileResponse:
    """Rolls back to a prior revision: creates a NEW revision (source=
    "rollback") copying the target's config, then activates it. The target
    row is never reactivated or mutated.

    Returns:
        200: The newly-created rollback AnalysisProfileResponse.
        404: If the client or target revision does not exist (or the
             revision belongs to another client — identical response, no
             probing signal, same tenant-scoping precedent as every prior
             revisions router).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    new_revision = await revisions_service.rollback_analysis_profile_revision(
        session,
        client_id=client_id,
        target_revision_id=payload.target_revision_id,
        created_by=caller.email or "api",
    )
    if new_revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_id": payload.target_revision_id},
        )

    await session.commit()
    await session.refresh(new_revision)
    return _analysis_profile_revision_to_response(new_revision)


@router.post(
    "/{client_id}/analysis-profile/apply-template",
    response_model=AnalysisProfileResponse,
    dependencies=[Depends(require_superadmin)],
)
async def apply_analysis_profile_template(
    client_id: str,
    payload: ApplyAnalysisProfileTemplatePayload,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisProfileResponse:
    """Creates a new revision from a code-defined template's current data
    (design.md P5-D3) — an explicit, auditable action, never an implicit
    side effect.

    Returns:
        200: The newly-created AnalysisProfileResponse.
        404: If the client does not exist.
        422: If `vertical` is not a known template name.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )

    revision = await revisions_service.apply_analysis_profile_template(
        session,
        client=client,
        vertical=payload.vertical,
        created_by=caller.email or "api",
    )
    await session.commit()
    await session.refresh(revision)
    return _analysis_profile_revision_to_response(revision)
