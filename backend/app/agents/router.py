"""QORA Agents — CRUD router nested under /api/v1/clients/{client_id}/agents/.

Endpoints:
    GET    /api/v1/clients/{client_id}/agents/                              — List agents (200 / 404)
    POST   /api/v1/clients/{client_id}/agents/                              — Create agent (201 / 404 / 409 / 422)
    GET    /api/v1/clients/{client_id}/agents/{agent_id}                    — Get single agent (200 / 404)
    PATCH  /api/v1/clients/{client_id}/agents/{agent_id}                    — Partial update (200 / 404)
    POST   /api/v1/clients/{client_id}/agents/{agent_id}/deactivate         — Soft delete (200 / 404 / 409)
    POST   /api/v1/clients/{client_id}/agents/{agent_id}/sync-elevenlabs    — Manual EL re-sync (200 / 404)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import (
    AgentConfigRevisionResponse,
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    SyncStatusResponse,
)
from app.core.access import require_client_access, require_superadmin
from app.core.auth import CallerIdentity
from app.elevenlabs.service import ElevenLabsService, sync_to_elevenlabs
from app.tenants.agent_config_schema import (
    ALLOWED_AGENT_OVERRIDE_FIELDS,
    AgentConfigV1,
    AgentConfigV2Patch,
)
from app.tenants.config_resolver import EffectiveConfig, resolve_effective_config
from app.tenants.config_standard import AgentConfigStandard
from app.tenants.field_policy import AGENT_REQUIRED_FIELDS
from app.tenants.models import Agent, AgentConfigRevision, Client
import app.tenants.service as tenant_service
from app.tenants import revisions_service

router = APIRouter(
    prefix="/clients/{client_id}/agents",
    tags=["agents"],
    redirect_slashes=False,
    dependencies=[Depends(require_client_access)],
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


def _deserialize_tool_config(raw: str | dict | None) -> dict | None:
    """Deserialize tool_config from DB JSON string to dict.

    The DB stores tool_config as a JSON string (TEXT column, nullable).
    The API contract returns it as dict | None.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _tts_field(agent: Agent, field: str, default: float) -> float:
    """Return an agent TTS float column, falling back to *default* only when the
    column is None (missing / not-yet-migrated row).

    Using ``value or default`` is WRONG: it replaces the valid boundary value
    ``0.0`` with the default because ``0.0`` is falsy in Python.  An explicit
    ``None`` check is required.
    """
    value = getattr(agent, field, None)
    return default if value is None else value


def _agent_to_response(
    agent: Agent,
    *,
    config_incomplete: bool = False,
    missing_required_fields: list[str] | None = None,
) -> AgentResponse:
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
        elevenlabs_phone_number_id=getattr(agent, "elevenlabs_phone_number_id", None),
        custom_llm_url=custom_llm_url,
        has_prompt=has_prompt,
        has_elevenlabs_agent_id=has_el_id,
        is_conversation_ready=has_prompt and has_el_id,
        tts_speed=_tts_field(agent, "tts_speed", 0.95),
        tts_stability=_tts_field(agent, "tts_stability", 0.4),
        tts_similarity_boost=_tts_field(agent, "tts_similarity_boost", 0.75),
        tts_model=getattr(agent, "tts_model", "eleven_flash_v2_5") or "eleven_flash_v2_5",
        tool_config=_deserialize_tool_config(getattr(agent, "tool_config", None)),
        # ElevenLabs soft timeout + sync status (sdd/elevenlabs-provisioning)
        soft_timeout_seconds=getattr(agent, "soft_timeout_seconds", None),
        soft_timeout_message=getattr(agent, "soft_timeout_message", None),
        soft_timeout_use_llm=getattr(agent, "soft_timeout_use_llm", None),
        elevenlabs_sync_status=getattr(agent, "elevenlabs_sync_status", None),
        elevenlabs_last_synced_at=getattr(agent, "elevenlabs_last_synced_at", None),
        # ElevenLabs agent config sync (sdd/elevenlabs-config)
        voicemail_detection_enabled=getattr(agent, "voicemail_detection_enabled", None),
        max_call_duration_seconds=getattr(agent, "max_call_duration_seconds", None),
        config_incomplete=config_incomplete,
        missing_required_fields=missing_required_fields or [],
    )


_SYNC_FIELDS = frozenset({
    # Soft timeout config (sdd/elevenlabs-provisioning)
    "soft_timeout_seconds",
    "soft_timeout_message",
    "soft_timeout_use_llm",
    # Agent config sync — new fields (sdd/elevenlabs-config)
    "voicemail_detection_enabled",
    "max_call_duration_seconds",
    # TTS / voice config — phone calls never received these without a sync trigger
    "voice_id",
    "tts_model",
    "tts_speed",
    "tts_stability",
    "tts_similarity_boost",
})


def _should_trigger_sync(agent: Agent, changed_fields: set[str] | None = None) -> bool:
    """Return True if an ElevenLabs sync should be triggered.

    Conditions (both must be true):
    1. Agent has elevenlabs_agent_id bound
    2. At least one EL config field is set (not all None), OR changed_fields
       includes a sync-triggering field (for update path)

    Spec: sdd/elevenlabs-config — Requirement: Background Sync Upgrade
    """
    if not getattr(agent, "elevenlabs_agent_id", None):
        return False

    if changed_fields is not None:
        # Update path: only trigger if a sync field was actually changed
        return bool(changed_fields & _SYNC_FIELDS)

    # Create path: trigger if any EL config field is non-None. Agents always have
    # a voice_id, so in practice any agent with an elevenlabs_agent_id syncs on
    # create — that is intended (voice/TTS must reach ElevenLabs immediately).
    return (
        agent.soft_timeout_seconds is not None
        or agent.soft_timeout_message is not None
        or agent.soft_timeout_use_llm is not None
        or agent.voicemail_detection_enabled is not None
        or agent.max_call_duration_seconds is not None
        or agent.voice_id is not None
        or agent.tts_model is not None
        or agent.tts_speed is not None
        or agent.tts_stability is not None
        or agent.tts_similarity_boost is not None
    )


async def _require_client(session: AsyncSession, client_id: str) -> None:
    """Raise 404 if the client does not exist."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "client not found", "client_id": client_id},
        )


async def _require_agent(session: AsyncSession, client_id: str, agent_id: str) -> Agent:
    """Fetch an agent scoped to client_id, or raise 404."""
    agent = await tenant_service.get_agent(session, agent_id)
    if agent is None or agent.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )
    return agent


def _agent_config_snapshot(agent: Agent) -> AgentConfigV1:
    """Build a validated AgentConfigV1 from an Agent's current columns.

    Used as the merge base when no active revision exists yet, and to build
    the config mirrored into a new revision after the legacy PATCH updates
    Agent.* columns directly. system_prompt is coerced to "" when NULL —
    AgentConfigV1 requires a str, but legacy agents may not have one set yet.
    """
    snapshot = tenant_service.build_agent_config_v1_snapshot(agent, agent.system_prompt)
    snapshot["system_prompt"] = snapshot["system_prompt"] or ""
    return AgentConfigV1(**snapshot)


def _mirror_config_to_agent(agent: Agent, config: AgentConfigV1) -> None:
    """Write an activated revision's config onto the legacy Agent.* columns.

    TRANSITIONAL (design.md D6/D7): runtime still reads Agent.* columns until
    the Phase 3/4 cutover moves it to read the active revision directly.
    Fields with no Agent column (goal, first_message, language, turn_eagerness)
    are not mirrored — they have nowhere to live until Phase 1b/3.
    """
    agent.system_prompt = config.system_prompt
    agent.voice_id = config.voice_id
    agent.tts_model = config.tts_model
    agent.tts_speed = config.tts_speed
    agent.tts_stability = config.tts_stability
    agent.tts_similarity_boost = config.tts_similarity_boost
    agent.model = config.model
    agent.temperature = config.temperature
    agent.max_tokens = config.max_tokens
    agent.tools_enabled = json.dumps(config.tools_enabled)
    agent.soft_timeout_seconds = config.soft_timeout_seconds
    agent.soft_timeout_message = config.soft_timeout_message
    agent.soft_timeout_use_llm = config.soft_timeout_use_llm
    agent.voicemail_detection_enabled = config.voicemail_detection_enabled
    agent.max_call_duration_seconds = config.max_call_duration_seconds


async def _agent_completeness(
    session: AsyncSession, agent: Agent
) -> tuple[bool, list[str]]:
    """design.md D18/task 4.4: grandfathering visibility — computed purely from
    the agent's CURRENT active revision, with no distinction between a
    legacy-grandfathered agent and a newly-bootstrapped one that has not yet
    been configured.
    """
    active = await revisions_service.get_active_revision(
        session, agent.client_id, agent.id
    )
    overrides: dict = {}
    if active is not None:
        overrides = json.loads(active.config)
    missing = sorted(f for f in AGENT_REQUIRED_FIELDS if overrides.get(f) is None)
    return (len(missing) > 0, missing)


async def _resolve_effective_for_agent(
    session: AsyncSession, agent: Agent
) -> EffectiveConfig:
    """design.md D13/D18: resolve the agent's effective config through the
    same standard → client → agent chain used everywhere else, treating a
    legacy V1 full-snapshot revision's present fields as agent-provenance
    overrides (spec.md's "pre-existing V1 revision resolves without migration").
    """
    client_overrides: dict = {}
    client_revision = await revisions_service.get_active_client_revision(
        session, agent.client_id
    )
    if client_revision is not None:
        client_overrides = json.loads(client_revision.config)
        client_overrides.pop("schema_version", None)

    agent_overrides: dict = {}
    active = await revisions_service.get_active_revision(
        session, agent.client_id, agent.id
    )
    if active is not None:
        agent_overrides = json.loads(active.config)
        agent_overrides.pop("schema_version", None)

    return resolve_effective_config(AgentConfigStandard, client_overrides, agent_overrides)


def _mirror_effective_config_to_agent(agent: Agent, effective: EffectiveConfig) -> None:
    """TRANSITIONAL (design.md D18's decision #4): every agent revision write
    still mirrors the EFFECTIVE values into the legacy Agent.* columns, so the
    runtime (still reading columns until the Phase 5 cutover) behaves
    identically regardless of which level a field's value came from.
    """
    fields = effective.fields
    agent.system_prompt = fields["system_prompt"].value or ""
    agent.voice_id = fields["voice_id"].value
    agent.tts_model = fields["tts_model"].value
    agent.tts_speed = fields["tts_speed"].value
    agent.tts_stability = fields["tts_stability"].value
    agent.tts_similarity_boost = fields["tts_similarity_boost"].value
    agent.model = fields["model"].value
    agent.temperature = fields["temperature"].value
    agent.max_tokens = fields["max_tokens"].value
    agent.tools_enabled = json.dumps(fields["tools_enabled"].value)
    agent.soft_timeout_seconds = fields["soft_timeout_seconds"].value
    agent.soft_timeout_message = fields["soft_timeout_message"].value
    agent.soft_timeout_use_llm = fields["soft_timeout_use_llm"].value
    agent.voicemail_detection_enabled = fields["voicemail_detection_enabled"].value
    agent.max_call_duration_seconds = fields["max_call_duration_seconds"].value


def _revision_to_response(revision: AgentConfigRevision) -> AgentConfigRevisionResponse:
    return AgentConfigRevisionResponse(
        id=revision.id,
        agent_id=revision.agent_id,
        revision_number=revision.revision_number,
        config=json.loads(revision.config),
        schema_version=revision.schema_version,
        source=revision.source,
        created_by=revision.created_by,
        created_at=revision.created_at,
        note=revision.note,
        elevenlabs_sync_status=revision.elevenlabs_sync_status,
    )


async def _sync_revision_to_elevenlabs(
    session: AsyncSession, request: Request, agent: Agent, revision: AgentConfigRevision
) -> None:
    """Run the existing agent-scoped EL sync and record the outcome on *revision*.

    Reuses ElevenLabsService.sync_agent_config unchanged (design.md D7). Mirrors
    the outcome onto Agent.elevenlabs_sync_status / elevenlabs_last_synced_at
    exactly like the existing manual sync-elevenlabs endpoint, so legacy readers
    of those columns keep working during the transition.
    """
    settings = request.app.state.settings
    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    revision.elevenlabs_sync_status = result.outcome
    if result.outcome == "synced":
        agent.elevenlabs_sync_status = "synced"
        agent.elevenlabs_last_synced_at = datetime.now(tz=timezone.utc)
    elif result.outcome in ("drift", "error"):
        agent.elevenlabs_sync_status = result.outcome
    # "skipped" — no Agent column update, matches existing sync-elevenlabs endpoint behavior.


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
    responses = []
    for a in agents:
        incomplete, missing = await _agent_completeness(session, a)
        responses.append(
            _agent_to_response(a, config_incomplete=incomplete, missing_required_fields=missing)
        )
    return responses


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=AgentResponse, dependencies=[Depends(require_superadmin)])
async def create_agent(
    client_id: str,
    payload: AgentCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Create a new agent for a client.

    Returns:
        201: AgentResponse with the created agent.
        404: If client does not exist.
        409: If slug already exists for this client.
        403: If the client's plan agent limit is reached.
        422: If tools_enabled or slug validation fails (Pydantic).
    """
    await _require_client(session, client_id)

    from app.entitlements.service import check_agent_limit

    limit_block = await check_agent_limit(session, await tenant_service.get_client(session, client_id))
    if limit_block is not None:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "plan_limit_reached",
                "limit": limit_block.detail,
                "message": limit_block.error,
            },
        )

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
            elevenlabs_agent_id=payload.elevenlabs_agent_id,
            elevenlabs_phone_number_id=payload.elevenlabs_phone_number_id,
            tts_speed=payload.tts_speed,
            tts_stability=payload.tts_stability,
            tts_similarity_boost=payload.tts_similarity_boost,
            tts_model=payload.tts_model,
            tool_config=json.dumps(payload.tool_config) if payload.tool_config is not None else None,
            soft_timeout_seconds=payload.soft_timeout_seconds,
            soft_timeout_message=payload.soft_timeout_message,
            soft_timeout_use_llm=payload.soft_timeout_use_llm,
            voicemail_detection_enabled=payload.voicemail_detection_enabled,
            max_call_duration_seconds=payload.max_call_duration_seconds,
            goal=payload.goal,
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

    # Fire-and-forget ElevenLabs sync when conditions are met
    if _should_trigger_sync(agent):
        settings = request.app.state.settings
        asyncio.create_task(sync_to_elevenlabs(agent_id=agent.id, settings=settings))

    incomplete, missing = await _agent_completeness(session, agent)
    return _agent_to_response(agent, config_incomplete=incomplete, missing_required_fields=missing)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/{agent_id}/sync-elevenlabs
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/sync-elevenlabs", response_model=SyncStatusResponse, dependencies=[Depends(require_superadmin)])
async def sync_agent_to_elevenlabs(
    client_id: str,
    agent_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> SyncStatusResponse:
    """Manually trigger a synchronous ElevenLabs re-sync for an agent.

    Awaits the sync result (not fire-and-forget) and returns the outcome.
    Updates elevenlabs_sync_status and elevenlabs_last_synced_at in DB.

    Returns:
        200: SyncStatusResponse with sync_status, synced_at, error_detail.
        404: If client or agent does not exist.
    """
    await _require_client(session, client_id)

    agent = await tenant_service.get_agent(session, agent_id)
    if agent is None or agent.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent not found", "agent_id": agent_id},
        )

    settings = request.app.state.settings
    from app.elevenlabs.service import ElevenLabsService

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    synced_at = None
    if result.outcome == "synced":
        synced_at = datetime.now(tz=timezone.utc)
        agent.elevenlabs_sync_status = "synced"
        agent.elevenlabs_last_synced_at = synced_at
        await session.commit()
    elif result.outcome == "drift":
        agent.elevenlabs_sync_status = "drift"
        await session.commit()
    elif result.outcome == "error":
        agent.elevenlabs_sync_status = "error"
        await session.commit()
    # "skipped" → no DB update

    return SyncStatusResponse(
        sync_status=result.outcome,
        synced_at=synced_at,
        error_detail=result.error_detail,
    )


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
    incomplete, missing = await _agent_completeness(session, agent)
    return _agent_to_response(agent, config_incomplete=incomplete, missing_required_fields=missing)


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.patch("/{agent_id}", response_model=AgentResponse, dependencies=[Depends(require_superadmin)])
async def update_agent(
    client_id: str,
    agent_id: str,
    payload: AgentUpdate,
    request: Request,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Partially update an agent. Only provided fields are updated.

    TRANSITIONAL (design.md D7's "route config fields through revisions" item,
    updated for 1b's sparse V2 model): any changed field that belongs to
    AgentConfigV2 (design.md D18 agent_required/overridable fields) is routed
    through the same sparse-patch path as PATCH .../config, so inheritance is
    preserved instead of re-pinning every field as an explicit agent override.
    Non-config columns (name, slug, is_active, tool_config, etc.) keep being
    updated directly. This does not change this endpoint's request/response
    contract.

    Returns:
        200: Updated AgentResponse.
        404: If client or agent does not exist.
        422: If a changed config field sets a locked/client_only value, or
             removes a previously-set agent_required field.
    """
    await _require_client(session, client_id)
    agent = await _require_agent(session, client_id, agent_id)

    update_data = payload.model_dump(exclude_unset=True)
    # Track which fields are being changed (for sync trigger decision)
    changed_fields = set(update_data.keys())
    config_fields = changed_fields & ALLOWED_AGENT_OVERRIDE_FIELDS
    non_config_data = {k: v for k, v in update_data.items() if k not in config_fields}

    # Validate + write the config part FIRST (design.md D18's sparse-patch
    # path) so a 422 here leaves no column change applied at all.
    if config_fields:
        patch = {k: update_data[k] for k in config_fields}
        try:
            await revisions_service.create_agent_config_revision(
                session,
                agent=agent,
                patch=patch,
                source="api",
                created_by=caller.email or "api",
                note="legacy PATCH /agents/{agent_id}",
            )
        except revisions_service.AgentConfigWriteError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_config", "fields": exc.fields, "detail": str(exc)},
            ) from exc

        effective = await _resolve_effective_for_agent(session, agent)
        _mirror_effective_config_to_agent(agent, effective)

    # Serialize tool_config dict to JSON string for DB storage
    if "tool_config" in non_config_data and isinstance(
        non_config_data["tool_config"], dict
    ):
        non_config_data["tool_config"] = json.dumps(non_config_data["tool_config"])

    if non_config_data:
        agent = await tenant_service.update_agent(
            session, agent_id, client_id, **non_config_data
        )
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "agent not found", "agent_id": agent_id},
            )

    await session.commit()
    await session.refresh(agent)

    # Fire-and-forget ElevenLabs sync when conditions are met
    if _should_trigger_sync(agent, changed_fields=changed_fields):
        settings = request.app.state.settings
        asyncio.create_task(sync_to_elevenlabs(agent_id=agent.id, settings=settings))

    incomplete, missing = await _agent_completeness(session, agent)
    return _agent_to_response(agent, config_incomplete=incomplete, missing_required_fields=missing)


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}/agents/{agent_id}/config
# ---------------------------------------------------------------------------


@router.patch(
    "/{agent_id}/config",
    response_model=AgentConfigRevisionResponse,
    dependencies=[Depends(require_superadmin)],
)
async def patch_agent_config(
    client_id: str,
    agent_id: str,
    payload: AgentConfigV2Patch,
    request: Request,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AgentConfigRevisionResponse:
    """Sparse override write (design.md D18): the patch is merged over the
    agent's current sparse overrides (promoting a V1 active revision to V2
    overrides on first write) and validated against FIELD_POLICY before a new
    AgentConfigV2 revision is created and activated. A null value removes an
    existing override (inherit again).

    Returns:
        200: The newly-activated AgentConfigRevisionResponse.
        404: If client or agent does not exist.
        422: If the write sets a locked/client_only field, or removes a
             previously-set agent_required field.
    """
    await _require_client(session, client_id)
    agent = await _require_agent(session, client_id, agent_id)

    patch_data = payload.model_dump(exclude_unset=True, exclude={"note"})
    try:
        revision = await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch=patch_data,
            source="api",
            created_by=caller.email or "api",
            note=payload.note,
        )
    except revisions_service.AgentConfigWriteError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_config", "fields": exc.fields, "detail": str(exc)},
        ) from exc

    # TRANSITIONAL (design.md D18 decision #4): every agent revision write
    # still mirrors the EFFECTIVE values into the legacy Agent.* columns, so
    # the runtime (still reading columns until the Phase 5 cutover) behaves
    # identically regardless of which level a field's value came from.
    effective = await _resolve_effective_for_agent(session, agent)
    _mirror_effective_config_to_agent(agent, effective)

    await session.commit()
    await session.refresh(agent)
    await session.refresh(revision)

    await _sync_revision_to_elevenlabs(session, request, agent, revision)
    await session.commit()
    await session.refresh(revision)

    return _revision_to_response(revision)


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/agents/{agent_id}/revisions
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/revisions", response_model=list[AgentConfigRevisionResponse])
async def list_agent_revisions(
    client_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentConfigRevisionResponse]:
    """Return every revision for an agent, newest first.

    Returns:
        200: List of AgentConfigRevisionResponse.
        404: If client or agent does not exist.
    """
    await _require_client(session, client_id)
    await _require_agent(session, client_id, agent_id)

    revisions = await revisions_service.list_revisions(session, client_id, agent_id)
    return [_revision_to_response(r) for r in revisions]


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/agents/{agent_id}/revisions/{revision_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{agent_id}/revisions/{revision_id}", response_model=AgentConfigRevisionResponse
)
async def get_agent_revision(
    client_id: str,
    agent_id: str,
    revision_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentConfigRevisionResponse:
    """Return a single revision by id, scoped to this agent and client.

    Returns:
        200: AgentConfigRevisionResponse.
        404: If client, agent, or revision does not exist (or belongs to
             another agent/client — identical response, no probing signal).
    """
    await _require_client(session, client_id)
    await _require_agent(session, client_id, agent_id)

    revision = await revisions_service.get_revision(session, client_id, agent_id, revision_id)
    if revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_id": revision_id},
        )
    return _revision_to_response(revision)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/{agent_id}/revisions/{revision_id}/rollback
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_id}/revisions/{revision_id}/rollback",
    response_model=AgentConfigRevisionResponse,
    dependencies=[Depends(require_superadmin)],
)
async def rollback_agent_config(
    client_id: str,
    agent_id: str,
    revision_id: str,
    request: Request,
    caller: CallerIdentity = Depends(require_client_access),
    session: AsyncSession = Depends(get_db_session),
) -> AgentConfigRevisionResponse:
    """Roll back to a prior revision: creates a NEW revision (source="rollback")
    copying the target's config, then activates it. The target row is never
    reactivated or mutated.

    Returns:
        200: The newly-created rollback AgentConfigRevisionResponse.
        404: If client, agent, or target revision does not exist.
    """
    await _require_client(session, client_id)
    agent = await _require_agent(session, client_id, agent_id)

    new_revision = await revisions_service.rollback_to_revision(
        session, client_id, agent_id, revision_id, created_by=caller.email or "api"
    )
    if new_revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_id": revision_id},
        )

    # TRANSITIONAL (design.md D18 decision #4): rollback preserves whichever
    # schema_version the target revision was recorded in (V1 full snapshot or
    # V2 sparse overrides); mirror the resolved EFFECTIVE values either way.
    effective = await _resolve_effective_for_agent(session, agent)
    _mirror_effective_config_to_agent(agent, effective)

    await session.commit()
    await session.refresh(agent)
    await session.refresh(new_revision)

    await _sync_revision_to_elevenlabs(session, request, agent, new_revision)
    await session.commit()
    await session.refresh(new_revision)

    return _revision_to_response(new_revision)


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/agents/{agent_id}/deactivate
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/deactivate", response_model=AgentResponse, dependencies=[Depends(require_superadmin)])
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
        if "cannot_deactivate_last_active_agent" in msg:
            raise HTTPException(
                status_code=409,
                detail={"error": "cannot deactivate last active agent", "detail": msg},
            ) from exc
        # Unexpected ValueError — return 500, not a misleading 404
        raise HTTPException(
            status_code=500,
            detail={"error": "internal error", "detail": msg},
        ) from exc

    await session.commit()
    await session.refresh(agent)
    incomplete, missing = await _agent_completeness(session, agent)
    return _agent_to_response(agent, config_incomplete=incomplete, missing_required_fields=missing)
