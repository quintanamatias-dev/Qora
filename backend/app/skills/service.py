"""Skill packages — service layer (design.md P4-D1/P4-D2/P4-D3).

resolve_agent_skills() combines the Qora package's general-section skills,
the client's package's general-section skills, and that client's package's
agent-section skills scoped to one agent, with agent > client-general >
qora winning on a slug collision — the dropped lower-priority entry is
logged at WARNING, never silently discarded.

create_skill_revision / get_revision / list_revisions / rollback_skill are
built on revisions_service.py's generic private helpers (_create_revision/
_get_revision/_list_revisions), parameterized for SkillRevision — the
fourth owner table on that reuse pattern after agent/client/analysis-profile
config revisions. SkillRevision's content columns (content_md, filler_text,
trigger_hint, description) are passed through _create_revision's generic
**fields rather than the single config/schema_version JSON blob the other
three owner tables use.

AgentSkillsCache is an in-process cache keyed by agent_id, invalidated
explicitly via invalidate_agent()/invalidate_client() on writes — every
write path in this module (create_skill_revision, rollback_skill) changes
a skill's active_revision_id, so the caller is responsible for invalidating
the affected agent(s) after committing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.skill_loader import SkillRegistryEntry
from app.tenants import revisions_service
from app.tenants.models import Agent, Skill, SkillPackage, SkillRevision

logger = logging.getLogger(__name__)

RevisionSource = Literal["import", "api", "rollback"]


@dataclass(frozen=True)
class ResolvedAgentSkills:
    """resolve_agent_skills()'s return shape: the SkillRegistryEntry list
    load_skill_registry() returns today, plus a content lookup by slug for
    the load_skill tool's eventual DB-backed read (task 3)."""

    entries: list[SkillRegistryEntry]
    content_by_slug: dict[str, str]


# ---------------------------------------------------------------------------
# Revision CRUD — built on revisions_service.py's generic private helpers.
# ---------------------------------------------------------------------------


async def create_skill_revision(
    session: AsyncSession,
    *,
    skill: Skill,
    content_md: str,
    filler_text: str,
    trigger_hint: str,
    description: str,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> SkillRevision:
    """Insert + activate a new, immutable SkillRevision. Never mutates an
    existing revision row."""
    return await revisions_service._create_revision(
        session,
        model=SkillRevision,
        owner=skill,
        owner_id_attr="skill_id",
        active_pointer_attr="active_revision_id",
        source=source,
        created_by=created_by,
        note=note,
        content_md=content_md,
        filler_text=filler_text,
        trigger_hint=trigger_hint,
        description=description,
    )


async def get_revision(
    session: AsyncSession, skill_id: str, revision_id: str
) -> SkillRevision | None:
    return await revisions_service._get_revision(
        session,
        model=SkillRevision,
        owner_id_attr="skill_id",
        owner_id=skill_id,
        revision_id=revision_id,
    )


async def list_revisions(session: AsyncSession, skill_id: str) -> list[SkillRevision]:
    return await revisions_service._list_revisions(
        session, model=SkillRevision, owner_id_attr="skill_id", owner_id=skill_id
    )


async def rollback_skill(
    session: AsyncSession,
    *,
    skill: Skill,
    target_revision_id: str,
    created_by: str,
) -> SkillRevision | None:
    """Creates a NEW revision copying target_revision_id's content; does not
    resurrect or reactivate the old row. Returns None when target_revision_id
    does not belong to this skill."""
    target = await get_revision(session, skill.id, target_revision_id)
    if target is None:
        return None
    return await create_skill_revision(
        session,
        skill=skill,
        content_md=target.content_md,
        filler_text=target.filler_text,
        trigger_hint=target.trigger_hint,
        description=target.description,
        source="rollback",
        created_by=created_by,
        note=f"rollback to revision {target.revision_number}",
    )


# ---------------------------------------------------------------------------
# resolve_agent_skills — Qora general + client general + client agent
# section, agent > client-general > qora on slug collision (P4-D2).
# ---------------------------------------------------------------------------


async def _package_skills(
    session: AsyncSession,
    package: SkillPackage | None,
    *,
    section: str,
    agent_id: str | None = None,
) -> list[Skill]:
    if package is None:
        return []
    stmt = select(Skill).where(Skill.package_id == package.id, Skill.section == section)
    if agent_id is not None:
        stmt = stmt.where(Skill.agent_id == agent_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def resolve_agent_skills(session: AsyncSession, agent: Agent) -> ResolvedAgentSkills:
    """Qora general + client general + client agent-section, with
    agent > client-general > qora on slug collision. Dropped lower-priority
    entries are logged at WARNING, never silently discarded without a
    trace. Returns the same SkillRegistryEntry shape load_skill_registry()
    returns today, plus a content lookup by slug.
    """
    qora_package = (
        await session.execute(select(SkillPackage).where(SkillPackage.owner_type == "qora"))
    ).scalars().first()
    client_package = (
        await session.execute(
            select(SkillPackage).where(
                SkillPackage.owner_type == "client",
                SkillPackage.client_id == agent.client_id,
            )
        )
    ).scalars().first()

    qora_skills = await _package_skills(session, qora_package, section="general")
    client_general_skills = await _package_skills(session, client_package, section="general")
    client_agent_skills = await _package_skills(
        session, client_package, section="agent", agent_id=agent.id
    )

    # Merge in increasing-specificity order so the last write per slug wins
    # (agent > client_general > qora, P4-D2).
    winning_source: dict[str, tuple[str, Skill]] = {}
    for source_name, skills in (
        ("qora", qora_skills),
        ("client_general", client_general_skills),
        ("agent", client_agent_skills),
    ):
        for skill in skills:
            if skill.slug in winning_source:
                dropped_source, _ = winning_source[skill.slug]
                logger.warning(
                    "skill_collision_dropped: slug=%s dropped_source=%s kept_source=%s "
                    "agent_id=%s client_id=%s",
                    skill.slug,
                    dropped_source,
                    source_name,
                    agent.id,
                    agent.client_id,
                )
            winning_source[skill.slug] = (source_name, skill)

    entries: list[SkillRegistryEntry] = []
    content_by_slug: dict[str, str] = {}
    for slug, (_, skill) in winning_source.items():
        if skill.active_revision_id is None:
            continue
        revision = await session.get(SkillRevision, skill.active_revision_id)
        if revision is None:
            continue
        entries.append(
            SkillRegistryEntry(
                name=slug,
                description=revision.description,
                trigger_hint=revision.trigger_hint,
                filler_text=revision.filler_text,
            )
        )
        content_by_slug[slug] = revision.content_md

    return ResolvedAgentSkills(entries=entries, content_by_slug=content_by_slug)


# ---------------------------------------------------------------------------
# AgentSkillsCache — in-process cache keyed by agent_id, explicit
# invalidation on writes (invalidate_agent / invalidate_client).
# ---------------------------------------------------------------------------


@dataclass
class AgentSkillsCache:
    """Per-process cache of resolve_agent_skills() results, keyed by
    agent_id. A write to any contributing skill does NOT automatically miss
    the cache — the caller must invalidate_agent()/invalidate_client() after
    committing a write."""

    _cache: dict[str, ResolvedAgentSkills] = field(default_factory=dict)
    _agent_client: dict[str, str] = field(default_factory=dict)

    async def get(self, session: AsyncSession, agent: Agent) -> ResolvedAgentSkills:
        if agent.id in self._cache:
            return self._cache[agent.id]
        resolved = await resolve_agent_skills(session, agent)
        self._cache[agent.id] = resolved
        self._agent_client[agent.id] = agent.client_id
        return resolved

    def invalidate_agent(self, agent_id: str) -> None:
        self._cache.pop(agent_id, None)
        self._agent_client.pop(agent_id, None)

    def invalidate_client(self, client_id: str) -> None:
        stale_agent_ids = [
            agent_id
            for agent_id, owning_client_id in self._agent_client.items()
            if owning_client_id == client_id
        ]
        for agent_id in stale_agent_ids:
            self.invalidate_agent(agent_id)
