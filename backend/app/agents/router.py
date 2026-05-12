"""QORA Agents — CRUD router nested under /api/v1/clients/{client_id}/agents/.

Endpoints:
    GET    /api/v1/clients/{client_id}/agents/                  — List agents (200 / 404)
    POST   /api/v1/clients/{client_id}/agents/                  — Create agent (201 / 404 / 409 / 422)
    GET    /api/v1/clients/{client_id}/agents/{agent_id}        — Get single agent (200 / 404)
    PATCH  /api/v1/clients/{client_id}/agents/{agent_id}        — Partial update (200 / 404)
    POST   /api/v1/clients/{client_id}/agents/{agent_id}/deactivate    — Soft delete (200 / 404 / 409)
    POST   /api/v1/clients/{client_id}/agents/{agent_id}/make-default  — Atomic default swap (200 / 404 / 409)
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import AgentCreate, AgentResponse, AgentUpdate
from app.tenants.models import Agent, Client
import app.tenants.service as tenant_service

router = APIRouter(
    prefix="/clients/{client_id}/agents",
    tags=["agents"],
    redirect_slashes=False,
)


# ---------------------------------------------------------------------------
# DB session dependency (shared pattern from clients/router.py)
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


def _deserialize_tools(tools_enabled: str | list | None) -> list[str]:
    """Deserialize tools_enabled from DB JSON string to list[str].

    The DB stores tools_enabled as a JSON string (e.g., '["get_lead_details"]').
    The API contract requires list[str] in responses.
    """
    if tools_enabled is None:
        return []
    if isinstance(tools_enabled, list):
        return tools_enabled
    try:
        parsed = json.loads(tools_enabled)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _tts_field(agent: Agent, field: str, default: float) -> float:
    """Return an agent TTS float column, falling back to *default* only when the
    column is None (missing / not-yet-migrated row).

    Using ``value or default`` is WRONG: it replaces the valid boundary value
    ``0.0`` with the default because ``0.0`` is falsy in Python.  An explicit
    ``None`` check is required.
    """
    value = getattr(agent, field, None)
    return default if value is None else value


def _agent_to_response(agent: Agent) -> AgentResponse:
    """Map an Agent ORM object to an AgentResponse schema."""
    has_prompt = bool(agent.system_prompt and agent.system_prompt.strip())
    has_el_id = bool(getattr(agent, "elevenlabs_agent_id", None))
    custom_llm_url = f"/api/v1/voice/{agent.client_id}/custom-llm/chat/completions"
    return AgentResponse(
        agent_id=agent.id,
        client_id=agent.client_id,
        slug=agent.slug,
        name=agent.name,
        voice_id=agent.voice_id,
        system_prompt=agent.system_prompt,
        knowledge_base=agent.knowledge_base,
        model=agent.model,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        tools_enabled=_deserialize_tools(agent.tools_enabled),
        is_active=agent.is_active,
        is_default=agent.is_default,
        created_at=agent.created_at,
        elevenlabs_agent_id=getattr(agent, "elevenlabs_agent_id", None),
        custom_llm_url=custom_llm_url,
        has_prompt=has_prompt,
        has_elevenlabs_agent_id=has_el_id,
        is_conversation_ready=has_prompt and has_el_id,
        tts_speed=_tts_field(agent, "tts_speed", 0.95),
        tts_stability=_tts_field(agent, "tts_stability", 0.4),
        tts_similarity_boost=_tts_field(agent, "tts_similarity_boost", 0.75),
    )


async def _require_client(session: AsyncSession, client_id: str) -> None:
    """Raise 404 if the client does not exist."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/agents/
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentResponse]:
    """Return all active agents for a client.

    Returns:
        200: List of AgentResponse objects.
        404: If client does not exist.
    """
    await _require_client(session, client_id)
    agents = await tenant_service.list_agents_for_client(session, client_id)
    return [_agent_to_response(a) for a in agents]


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(
    client_id: str,
    payload: AgentCreate,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Create a new agent for a client.

    Returns:
        201: AgentResponse with the created agent.
        404: If client does not exist.
        409: If slug already exists for this client.
        422: If tools_enabled or slug validation fails (Pydantic).
    """
    await _require_client(session, client_id)

    try:
        agent = await tenant_service.create_agent(
            session,
            client_id=client_id,
            slug=payload.slug,
            name=payload.name,
            voice_id=payload.voice_id,
            system_prompt=payload.system_prompt,
            knowledge_base=payload.knowledge_base,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            tools_enabled=json.dumps(payload.tools_enabled),
            is_active=True,
            is_default=payload.is_default,
            elevenlabs_agent_id=payload.elevenlabs_agent_id,
            tts_speed=payload.tts_speed,
            tts_stability=payload.tts_stability,
            tts_similarity_boost=payload.tts_similarity_boost,
        )
    except ValueError as exc:
        msg = str(exc)
        if "slug" in msg:
            raise HTTPException(
                status_code=409,
                detail={"error": "slug already exists", "detail": msg},
            ) from exc
        # is_default conflict
        raise HTTPException(
            status_code=409,
            detail={"error": "default agent conflict", "detail": msg},
        ) from exc

    await session.commit()
    await session.refresh(agent)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    client_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Return a single agent by id.

    Returns:
        200: AgentResponse.
        404: If client or agent does not exist.
    """
    await _require_client(session, client_id)

    agent = await tenant_service.get_agent(session, agent_id)
    if agent is None or agent.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    client_id: str,
    agent_id: str,
    payload: AgentUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Partially update an agent. Only provided fields are updated.

    Returns:
        200: Updated AgentResponse.
        404: If client or agent does not exist.
    """
    await _require_client(session, client_id)

    update_data = payload.model_dump(exclude_unset=True)
    # Serialize tools_enabled list to JSON string for DB storage
    if "tools_enabled" in update_data and isinstance(
        update_data["tools_enabled"], list
    ):
        update_data["tools_enabled"] = json.dumps(update_data["tools_enabled"])
    agent = await tenant_service.update_agent(
        session, agent_id, client_id, **update_data
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )

    await session.commit()
    await session.refresh(agent)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/{agent_id}/deactivate
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/deactivate", response_model=AgentResponse)
async def deactivate_agent(
    client_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Soft-delete an agent (sets is_active=False).

    Returns:
        200: AgentResponse with is_active=False.
        404: If agent does not exist.
        409: If agent is the sole active default (guard error).
    """
    await _require_client(session, client_id)

    # Explicit existence check so 404 is reserved for "not found" only
    _agent_check = await tenant_service.get_agent(session, agent_id)
    if _agent_check is None or _agent_check.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )

    try:
        agent = await tenant_service.deactivate_agent(session, agent_id, client_id)
    except ValueError as exc:
        msg = str(exc)
        if "cannot_deactivate_sole_default_agent" in msg:
            raise HTTPException(
                status_code=409,
                detail={"error": "cannot deactivate sole default agent", "detail": msg},
            ) from exc
        # Unexpected ValueError — return 500, not a misleading 404
        raise HTTPException(
            status_code=500,
            detail={"error": "internal error", "detail": msg},
        ) from exc

    await session.commit()
    await session.refresh(agent)
    return _agent_to_response(agent)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/{agent_id}/make-default
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/make-default", response_model=AgentResponse)
async def make_default_agent(
    client_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Atomically swap the default agent for a client.

    Returns:
        200: AgentResponse with is_default=True.
        404: If agent does not exist.
        409: If agent is inactive (cannot be made default).
    """
    await _require_client(session, client_id)

    # Explicit existence check so 404 is reserved for "not found" only
    _agent_check = await tenant_service.get_agent(session, agent_id)
    if _agent_check is None or _agent_check.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )

    try:
        agent = await tenant_service.set_default_agent(session, client_id, agent_id)
    except ValueError as exc:
        msg = str(exc)
        if "cannot_set_inactive_agent_as_default" in msg:
            raise HTTPException(
                status_code=409,
                detail={"error": "cannot set inactive agent as default", "detail": msg},
            ) from exc
        # Unexpected ValueError — return 500, not a misleading 404
        raise HTTPException(
            status_code=500,
            detail={"error": "internal error", "detail": msg},
        ) from exc

    await session.commit()
    await session.refresh(agent)
    return _agent_to_response(agent)
