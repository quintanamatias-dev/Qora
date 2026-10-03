"""list_agents / get_agent (design.md M-D1) — get_agent returns effective
config with per-field provenance (which layer each value resolved from) and
active revision numbers, never a secret-shaped value."""

from __future__ import annotations

import app.tenants.service as tenant_service
from app.mcp.schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AgentEffectiveConfig,
    AgentSummary,
    EffectiveFieldOut,
)
from app.tenants import revisions_service
from app.tenants.materialize import resolve_effective_for_agent
from app.tenants.models import Agent
from sqlalchemy.ext.asyncio import AsyncSession


def _to_summary(agent: Agent) -> AgentSummary:
    return AgentSummary(
        agent_id=agent.id,
        client_id=agent.client_id,
        slug=agent.slug,
        name=agent.name,
        voice_id=agent.voice_id,
        is_active=agent.is_active,
        is_default=agent.is_default,
        elevenlabs_agent_id=agent.elevenlabs_agent_id,
    )


async def list_agents(
    session: AsyncSession,
    client_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[AgentSummary]:
    """List active agents for one client. client_id is required."""
    if not client_id:
        raise ValueError("client_id is required")
    bounded_limit = min(limit, MAX_PAGE_SIZE)
    agents = await tenant_service.list_agents_for_client(session, client_id)
    page = agents[offset : offset + bounded_limit]
    return [_to_summary(a) for a in page]


async def get_agent(
    session: AsyncSession, client_id: str, agent_id: str
) -> AgentEffectiveConfig | None:
    """Return one agent's effective config + provenance, scoped to client_id.

    An agent that belongs to another client is reported as not found (cross-
    tenant lookup never leaks existence).
    """
    if not client_id:
        raise ValueError("client_id is required")

    agent = await tenant_service.get_agent(session, agent_id)
    if agent is None or agent.client_id != client_id:
        return None

    effective = await resolve_effective_for_agent(session, agent)
    config = {
        name: EffectiveFieldOut(value=field.value, source_layer=field.provenance)
        for name, field in effective.fields.items()
    }

    agent_revision = await revisions_service.get_active_revision(
        session, client_id, agent.id
    )
    client_revision = await revisions_service.get_active_client_revision(
        session, client_id
    )

    return AgentEffectiveConfig(
        agent_id=agent.id,
        client_id=agent.client_id,
        slug=agent.slug,
        config=config,
        missing_required=effective.missing_required,
        agent_active_revision_number=(
            agent_revision.revision_number if agent_revision is not None else None
        ),
        client_active_revision_number=(
            client_revision.revision_number if client_revision is not None else None
        ),
    )
