"""Skill packages API router (skill-packages, P4-D5) — Task 4.

Endpoints:
    GET    /api/v1/clients/{client_id}/skill-packages
        The client's own package + the Qora package, summarized (no content).
    GET    /api/v1/clients/{client_id}/agents/{agent_id}/skills
        Resolved skills for this agent, with origin (qora|client_general|agent)
        and active revision number.
    POST   /api/v1/clients/{client_id}/skills
        Create a skill in the client's own package (superadmin-only).
    PUT    /api/v1/clients/{client_id}/skills/{skill_id}
        New revision (never mutates an existing one), activates it.
    GET    /api/v1/clients/{client_id}/skills/{skill_id}/revisions
    POST   /api/v1/clients/{client_id}/skills/{skill_id}/rollback
    DELETE /api/v1/clients/{client_id}/skills/{skill_id}
        Soft deactivate: clears active_revision_id (skill no longer
        resolves); revision history is kept, nothing is hard-deleted.

Access control: every route is nested under {client_id} and gated by
require_client_access (tenant isolation — a non-superadmin caller scoped to
a different client gets 403 before any DB lookup). A skill_id is additionally
resolved against its OWNING package: a client-package skill whose package
does not belong to {client_id} returns 404 (no probing signal, same
precedent as every other revisions router in this codebase). A Qora-package
skill is reachable through any valid {client_id} path (the Qora package has
no client owner) but every write (POST/PUT/DELETE/rollback) still requires
superadmin, matching every other client-config write route in this codebase
(create_client, update_client, create_agent, patch_agent_config, ...) —
there is no separate "client-write" role in this API today.

Every write invalidates the skills cache (design.md P4-D3 says the cache
is session-scoped with no TTL — a stale entry is a correctness bug, not a
performance tradeoff): a client-package write invalidates only that
client's cached agents; a Qora-package write invalidates every cached
agent, since a Qora skill can be resolved by any client's agents.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_client_access, require_superadmin
from app.core.auth import CallerIdentity, require_api_key
from app.skills.service import (
    create_skill_revision,
    get_default_skills_cache,
    list_revisions,
    resolve_agent_skills_with_origin,
    rollback_skill,
)
from app.tenants.models import Agent, Client, Skill, SkillPackage, SkillRevision

router = APIRouter(
    prefix="/clients/{client_id}",
    tags=["skills"],
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
# Schemas
# ---------------------------------------------------------------------------


class SkillBrief(BaseModel):
    skill_id: str
    slug: str
    section: str
    agent_id: str | None
    active_revision_number: int | None


class SkillPackageSummary(BaseModel):
    package_id: str
    owner_type: str
    client_id: str | None
    name: str
    skills: list[SkillBrief]


class SkillPackagesResponse(BaseModel):
    client_package: SkillPackageSummary | None
    qora_package: SkillPackageSummary | None


class ResolvedSkillResponse(BaseModel):
    slug: str
    origin: Literal["qora", "client_general", "agent"]
    description: str
    trigger_hint: str
    filler_text: str
    active_revision_number: int


class SkillCreate(BaseModel):
    slug: str
    section: Literal["general", "agent"]
    agent_id: str | None = None
    description: str
    trigger_hint: str
    filler_text: str
    content_md: str


class SkillContentUpdate(BaseModel):
    content_md: str
    filler_text: str
    trigger_hint: str
    description: str
    note: str | None = None


class SkillDetailResponse(BaseModel):
    skill_id: str
    package_id: str
    slug: str
    section: str
    agent_id: str | None
    active_revision_number: int | None
    description: str | None
    trigger_hint: str | None
    filler_text: str | None
    content_md: str | None


class RollbackPayload(BaseModel):
    revision_number: int


class SkillRevisionResponse(BaseModel):
    id: str
    skill_id: str
    revision_number: int
    content_md: str
    filler_text: str
    trigger_hint: str
    description: str
    source: str
    created_by: str
    note: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_client(session: AsyncSession, client_id: str) -> None:
    if await session.get(Client, client_id) is None:
        raise HTTPException(
            status_code=404, detail={"error": "client not found", "client_id": client_id}
        )


async def _require_agent(session: AsyncSession, client_id: str, agent_id: str) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.client_id != client_id:
        raise HTTPException(
            status_code=404, detail={"error": "agent not found", "agent_id": agent_id}
        )
    return agent


async def _get_client_package(session: AsyncSession, client_id: str) -> SkillPackage | None:
    result = await session.execute(
        select(SkillPackage).where(
            SkillPackage.owner_type == "client", SkillPackage.client_id == client_id
        )
    )
    return result.scalars().first()


async def _get_qora_package(session: AsyncSession) -> SkillPackage | None:
    result = await session.execute(select(SkillPackage).where(SkillPackage.owner_type == "qora"))
    return result.scalars().first()


async def _ensure_client_package(session: AsyncSession, client_id: str) -> SkillPackage:
    package = await _get_client_package(session, client_id)
    if package is not None:
        return package
    package = SkillPackage(owner_type="client", client_id=client_id, name=f"{client_id} skills")
    session.add(package)
    await session.flush()
    return package


async def _active_revision_number(session: AsyncSession, skill: Skill) -> int | None:
    if skill.active_revision_id is None:
        return None
    revision = await session.get(SkillRevision, skill.active_revision_id)
    return revision.revision_number if revision is not None else None


async def _package_summary(session: AsyncSession, package: SkillPackage) -> SkillPackageSummary:
    result = await session.execute(select(Skill).where(Skill.package_id == package.id))
    skills = list(result.scalars().all())
    briefs = [
        SkillBrief(
            skill_id=s.id,
            slug=s.slug,
            section=s.section,
            agent_id=s.agent_id,
            active_revision_number=await _active_revision_number(session, s),
        )
        for s in skills
    ]
    return SkillPackageSummary(
        package_id=package.id,
        owner_type=package.owner_type,
        client_id=package.client_id,
        name=package.name,
        skills=briefs,
    )


async def _skill_detail(session: AsyncSession, skill: Skill) -> SkillDetailResponse:
    revision = (
        await session.get(SkillRevision, skill.active_revision_id)
        if skill.active_revision_id
        else None
    )
    return SkillDetailResponse(
        skill_id=skill.id,
        package_id=skill.package_id,
        slug=skill.slug,
        section=skill.section,
        agent_id=skill.agent_id,
        active_revision_number=revision.revision_number if revision else None,
        description=revision.description if revision else None,
        trigger_hint=revision.trigger_hint if revision else None,
        filler_text=revision.filler_text if revision else None,
        content_md=revision.content_md if revision else None,
    )


def _revision_to_response(revision: SkillRevision) -> SkillRevisionResponse:
    return SkillRevisionResponse(
        id=revision.id,
        skill_id=revision.skill_id,
        revision_number=revision.revision_number,
        content_md=revision.content_md,
        filler_text=revision.filler_text,
        trigger_hint=revision.trigger_hint,
        description=revision.description,
        source=revision.source,
        created_by=revision.created_by,
        note=revision.note,
    )


def _invalid_slug(slug: str) -> bool:
    """No path separators, no '..' — same defense-in-depth rule as the
    load_skill tool's filesystem-path check (design.md P4-D3)."""
    return "/" in slug or "\\" in slug or ".." in slug or not slug


async def _resolve_skill_scoped(
    session: AsyncSession, client_id: str, skill_id: str
) -> tuple[Skill, SkillPackage]:
    """Load a skill + its owning package, 404 when the skill does not exist
    or belongs to another client's package. A Qora-owned skill is reachable
    through any valid {client_id} path — it has no client owner to check."""
    skill = await session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(
            status_code=404, detail={"error": "skill not found", "skill_id": skill_id}
        )
    package = await session.get(SkillPackage, skill.package_id)
    if package is None or (package.owner_type == "client" and package.client_id != client_id):
        raise HTTPException(
            status_code=404, detail={"error": "skill not found", "skill_id": skill_id}
        )
    return skill, package


def _invalidate_cache_for_write(package: SkillPackage) -> None:
    cache = get_default_skills_cache()
    if package.owner_type == "qora":
        cache.invalidate_all()
    elif package.client_id is not None:
        cache.invalidate_client(package.client_id)


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/skill-packages
# ---------------------------------------------------------------------------


@router.get("/skill-packages", response_model=SkillPackagesResponse)
async def get_skill_packages(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SkillPackagesResponse:
    """Returns the client's own package (null if it has none yet) and the
    Qora package's summary. Qora package reads are allowed for any
    authenticated caller with access to this client — only writes are
    superadmin-gated.
    """
    await _require_client(session, client_id)

    client_package = await _get_client_package(session, client_id)
    qora_package = await _get_qora_package(session)

    return SkillPackagesResponse(
        client_package=(
            await _package_summary(session, client_package) if client_package else None
        ),
        qora_package=(await _package_summary(session, qora_package) if qora_package else None),
    )


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/agents/{agent_id}/skills
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/skills", response_model=list[ResolvedSkillResponse])
async def get_resolved_agent_skills(
    client_id: str,
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[ResolvedSkillResponse]:
    """Resolved skills for one agent: Qora general + client general + client
    agent-section, collapsed by slug with agent > client-general > qora on
    collision (P4-D2)."""
    await _require_client(session, client_id)
    agent = await _require_agent(session, client_id, agent_id)

    details = await resolve_agent_skills_with_origin(session, agent)
    return [
        ResolvedSkillResponse(
            slug=d.slug,
            origin=d.origin,
            description=d.description,
            trigger_hint=d.trigger_hint,
            filler_text=d.filler_text,
            active_revision_number=d.active_revision_number,
        )
        for d in details
    ]


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/skills
# ---------------------------------------------------------------------------


@router.post(
    "/skills",
    status_code=201,
    response_model=SkillDetailResponse,
    dependencies=[Depends(require_superadmin)],
)
async def create_skill(
    client_id: str,
    payload: SkillCreate,
    caller: CallerIdentity = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> SkillDetailResponse:
    """Create a new skill in the client's own package (creating the package
    on first write). Qora-package skills cannot be created through this API
    in this phase \u2014 only the import migration seeds them.

    Returns:
        201: The created skill with revision 1 active.
        404: If the client does not exist, or section="agent" names an
             agent that does not belong to this client.
        409: A skill with the same (package, slug, agent_id) already exists.
        422: Invalid slug (path separator / ".." / empty), or section="agent"
             without an agent_id (or section="general" with one).
    """
    await _require_client(session, client_id)

    if _invalid_slug(payload.slug):
        raise HTTPException(
            status_code=422, detail={"error": "invalid_slug", "slug": payload.slug}
        )

    if payload.section == "agent":
        if payload.agent_id is None:
            raise HTTPException(
                status_code=422,
                detail={"error": "agent_id required when section is 'agent'"},
            )
        await _require_agent(session, client_id, payload.agent_id)
    elif payload.agent_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"error": "agent_id must be null when section is 'general'"},
        )

    package = await _ensure_client_package(session, client_id)

    existing = await session.execute(
        select(Skill).where(
            Skill.package_id == package.id,
            Skill.slug == payload.slug,
            Skill.agent_id == payload.agent_id,
        )
    )
    if existing.scalars().first() is not None:
        raise HTTPException(
            status_code=409, detail={"error": "skill already exists", "slug": payload.slug}
        )

    skill = Skill(
        package_id=package.id,
        slug=payload.slug,
        section=payload.section,
        agent_id=payload.agent_id,
    )
    session.add(skill)
    await session.flush()

    await create_skill_revision(
        session,
        skill=skill,
        content_md=payload.content_md,
        filler_text=payload.filler_text,
        trigger_hint=payload.trigger_hint,
        description=payload.description,
        source="api",
        created_by=caller.email or "api",
    )
    await session.commit()
    await session.refresh(skill)

    _invalidate_cache_for_write(package)

    return await _skill_detail(session, skill)


# ---------------------------------------------------------------------------
# PUT /clients/{client_id}/skills/{skill_id}
# ---------------------------------------------------------------------------


@router.put(
    "/skills/{skill_id}",
    response_model=SkillDetailResponse,
    dependencies=[Depends(require_superadmin)],
)
async def put_skill_content(
    client_id: str,
    skill_id: str,
    payload: SkillContentUpdate,
    caller: CallerIdentity = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> SkillDetailResponse:
    """Creates a new revision and activates it \u2014 never mutates an existing
    revision row. A Qora-package skill is writable through any valid
    {client_id} path, still gated to superadmin.

    Returns:
        200: The updated skill with the new revision active.
        404: If the client does not exist, or the skill does not exist / is
             owned by another client's package.
    """
    await _require_client(session, client_id)
    skill, package = await _resolve_skill_scoped(session, client_id, skill_id)

    await create_skill_revision(
        session,
        skill=skill,
        content_md=payload.content_md,
        filler_text=payload.filler_text,
        trigger_hint=payload.trigger_hint,
        description=payload.description,
        source="api",
        created_by=caller.email or "api",
        note=payload.note,
    )
    await session.commit()
    await session.refresh(skill)

    _invalidate_cache_for_write(package)

    return await _skill_detail(session, skill)


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/skills/{skill_id}/revisions
# ---------------------------------------------------------------------------


@router.get("/skills/{skill_id}/revisions", response_model=list[SkillRevisionResponse])
async def get_skill_revisions(
    client_id: str,
    skill_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[SkillRevisionResponse]:
    """Returns every revision for a skill, newest first.

    Returns:
        200: List of SkillRevisionResponse.
        404: If the client does not exist, or the skill does not exist / is
             owned by another client's package.
    """
    await _require_client(session, client_id)
    skill, _package = await _resolve_skill_scoped(session, client_id, skill_id)

    revisions = await list_revisions(session, skill.id)
    return [_revision_to_response(r) for r in revisions]


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/skills/{skill_id}/rollback
# ---------------------------------------------------------------------------


@router.post(
    "/skills/{skill_id}/rollback",
    response_model=SkillRevisionResponse,
    dependencies=[Depends(require_superadmin)],
)
async def post_skill_rollback(
    client_id: str,
    skill_id: str,
    payload: RollbackPayload,
    caller: CallerIdentity = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> SkillRevisionResponse:
    """Rolls back to a prior revision_number: creates a NEW revision
    (source="rollback") copying that revision's content, then activates it.
    The target row is never reactivated or mutated.

    Returns:
        200: The newly-created rollback SkillRevisionResponse.
        404: If the client/skill does not exist, or no revision with
             revision_number belongs to this skill.
    """
    await _require_client(session, client_id)
    skill, package = await _resolve_skill_scoped(session, client_id, skill_id)

    target = await session.execute(
        select(SkillRevision).where(
            SkillRevision.skill_id == skill.id,
            SkillRevision.revision_number == payload.revision_number,
        )
    )
    target_revision = target.scalars().first()
    if target_revision is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "revision not found", "revision_number": payload.revision_number},
        )

    new_revision = await rollback_skill(
        session,
        skill=skill,
        target_revision_id=target_revision.id,
        created_by=caller.email or "api",
    )
    await session.commit()
    await session.refresh(new_revision)

    _invalidate_cache_for_write(package)

    return _revision_to_response(new_revision)


# ---------------------------------------------------------------------------
# DELETE /clients/{client_id}/skills/{skill_id} — soft deactivate
# ---------------------------------------------------------------------------


@router.delete(
    "/skills/{skill_id}",
    response_model=SkillDetailResponse,
    dependencies=[Depends(require_superadmin)],
)
async def delete_skill(
    client_id: str,
    skill_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SkillDetailResponse:
    """Soft-deactivate: clears active_revision_id so the skill no longer
    resolves for any agent. Revision history is kept \u2014 nothing is
    hard-deleted, matching the insert-only revision model.

    Returns:
        200: The deactivated skill (active_revision_number: null).
        404: If the client does not exist, or the skill does not exist / is
             owned by another client's package.
    """
    await _require_client(session, client_id)
    skill, package = await _resolve_skill_scoped(session, client_id, skill_id)

    skill.active_revision_id = None
    await session.flush()
    await session.commit()
    await session.refresh(skill)

    _invalidate_cache_for_write(package)

    return await _skill_detail(session, skill)
