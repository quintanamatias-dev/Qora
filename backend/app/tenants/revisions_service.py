"""QORA Agent Config Revisions — service layer (design.md D4/D7).

agent_config_revisions rows are insert-only: no UPDATE or DELETE path exists
anywhere in this module. Every lookup function (get_active_revision,
get_revision, list_revisions, activate_revision, rollback_to_revision) is
scoped by both client_id and agent_id, so a revision belonging to another
agent or client is never readable or activatable — the lookup simply
returns None/[] as if the revision did not exist.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.agent_config_schema import AgentConfigV1
from app.tenants.models import Agent, AgentConfigRevision

RevisionSource = Literal["import", "api", "rollback"]


async def create_revision(
    session: AsyncSession,
    *,
    agent: Agent,
    config: AgentConfigV1,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> AgentConfigRevision:
    """Insert-only revision creation + activation.

    revision_number = max(existing for agent.id) + 1, starting at 1. Single
    pointer swap on agent.active_revision_id — no other revision row is
    touched.
    """
    existing_max = await session.execute(
        select(AgentConfigRevision.revision_number)
        .where(AgentConfigRevision.agent_id == agent.id)
        .order_by(AgentConfigRevision.revision_number.desc())
        .limit(1)
    )
    next_number = (existing_max.scalar_one_or_none() or 0) + 1

    revision = AgentConfigRevision(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        revision_number=next_number,
        config=config.model_dump_json(),
        schema_version=config.schema_version,
        source=source,
        created_by=created_by,
        note=note,
    )
    session.add(revision)
    await session.flush()

    agent.active_revision_id = revision.id
    await session.flush()
    return revision


async def _get_agent_in_client(
    session: AsyncSession, client_id: str, agent_id: str
) -> Agent | None:
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.client_id == client_id)
    )
    return result.scalar_one_or_none()


async def get_active_revision(
    session: AsyncSession, client_id: str, agent_id: str
) -> AgentConfigRevision | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None or agent.active_revision_id is None:
        return None
    return await session.get(AgentConfigRevision, agent.active_revision_id)


async def get_revision(
    session: AsyncSession, client_id: str, agent_id: str, revision_id: str
) -> AgentConfigRevision | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    result = await session.execute(
        select(AgentConfigRevision).where(
            AgentConfigRevision.id == revision_id,
            AgentConfigRevision.agent_id == agent.id,
        )
    )
    return result.scalar_one_or_none()


async def list_revisions(
    session: AsyncSession, client_id: str, agent_id: str
) -> list[AgentConfigRevision]:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return []
    result = await session.execute(
        select(AgentConfigRevision)
        .where(AgentConfigRevision.agent_id == agent.id)
        .order_by(AgentConfigRevision.revision_number.desc())
    )
    return list(result.scalars().all())


async def activate_revision(
    session: AsyncSession, client_id: str, agent_id: str, revision_id: str
) -> Agent | None:
    """Point agent.active_revision_id at revision_id. Single UPDATE, same agent only."""
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    revision = await get_revision(session, client_id, agent_id, revision_id)
    if revision is None:
        return None
    agent.active_revision_id = revision.id
    await session.flush()
    return agent


async def rollback_to_revision(
    session: AsyncSession,
    client_id: str,
    agent_id: str,
    target_revision_id: str,
    created_by: str,
) -> AgentConfigRevision | None:
    """Copy target_revision_id's config into a NEW revision (source="rollback"),
    then activate it. Never mutates or reactivates the old row directly.
    """
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    target = await get_revision(session, client_id, agent_id, target_revision_id)
    if target is None:
        return None

    config = AgentConfigV1.model_validate_json(target.config)
    return await create_revision(
        session,
        agent=agent,
        config=config,
        source="rollback",
        created_by=created_by,
        note=f"rollback to revision {target.revision_number}",
    )
