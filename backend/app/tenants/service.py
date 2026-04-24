"""QORA Tenants — Service layer for Client CRUD, Agent CRUD, and seed operations."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.models import Agent, Client


async def create_client(
    session: AsyncSession,
    *,
    id: str,
    name: str,
    broker_name: str,
    agent_name: str = "Jaumpablo",
    voice_id: str,
    system_prompt_override: str | None = None,
    knowledge_base: str | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str = '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    is_active: bool = True,
    # Scheduler configuration (Phase 7 — bootstrappable at create time)
    scheduler_enabled: bool = False,
    scheduler_max_attempts: int = 3,
    scheduler_cooldown_minutes: int = 60,
    scheduler_allowed_hours_start: int = 9,
    scheduler_allowed_hours_end: int = 20,
    scheduler_retry_on_outcomes: str = '["call_again","follow_up"]',
    scheduler_timezone: str = "America/Argentina/Buenos_Aires",
) -> Client:
    """Create and persist a new Client record and its default Agent.

    Automatically creates a default Agent for the new client, copying agent
    configuration fields (agent_name → name, voice_id, model, temperature,
    max_tokens, tools_enabled, system_prompt_override → system_prompt, knowledge_base).

    Args:
        session: Active async DB session.
        id: Human-readable slug (e.g., "quintana-seguros").
        name: Display name (must be unique).
        broker_name: Name of the broker company.
        agent_name: Name of the AI agent.
        voice_id: ElevenLabs voice ID.
        ...

    Returns:
        The persisted Client instance.
    """
    client = Client(
        id=id,
        name=name,
        broker_name=broker_name,
        agent_name=agent_name,
        voice_id=voice_id,
        system_prompt_override=system_prompt_override,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=is_active,
        scheduler_enabled=scheduler_enabled,
        scheduler_max_attempts=scheduler_max_attempts,
        scheduler_cooldown_minutes=scheduler_cooldown_minutes,
        scheduler_allowed_hours_start=scheduler_allowed_hours_start,
        scheduler_allowed_hours_end=scheduler_allowed_hours_end,
        scheduler_retry_on_outcomes=scheduler_retry_on_outcomes,
        scheduler_timezone=scheduler_timezone,
    )
    session.add(client)
    await session.flush()  # Flush to DB within current transaction

    # Bootstrap a default Agent for this client (CRITICAL 1b: every client must have one)
    # Sanitize slug: lowercase, keep only [a-z0-9-], collapse consecutive hyphens,
    # strip leading/trailing hyphens so the slug passes the _SLUG_RE validation.
    raw_slug = (agent_name or "agent").lower()
    raw_slug = re.sub(r"[^a-z0-9-]", "-", raw_slug)  # replace invalid chars with hyphen
    raw_slug = re.sub(r"-+", "-", raw_slug)  # collapse consecutive hyphens
    raw_slug = raw_slug.strip("-")  # strip leading/trailing hyphens
    slug = raw_slug or "agent"  # fallback if empty after sanitization

    await create_agent(
        session,
        client_id=id,
        slug=slug,
        name=agent_name,
        voice_id=voice_id,
        system_prompt=system_prompt_override,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=True,
        is_default=True,
    )

    return client


async def get_client(session: AsyncSession, client_id: str) -> Client | None:
    """Fetch a Client by its id slug.

    Returns:
        Client instance or None if not found.
    """
    result = await session.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


async def get_client_by_name(session: AsyncSession, name: str) -> Client | None:
    """Fetch a Client by its unique display name.

    Returns:
        Client instance or None if not found.
    """
    result = await session.execute(select(Client).where(Client.name == name))
    return result.scalar_one_or_none()


async def update_client(
    session: AsyncSession,
    client_id: str,
    **kwargs,
) -> Client | None:
    """Update fields on an existing Client record.

    Args:
        session: Active async DB session.
        client_id: The id of the client to update.
        **kwargs: Fields to update (e.g., name="New Name", broker_name="New Broker").

    Returns:
        Updated Client instance or None if client not found.
    """
    client = await get_client(session, client_id)
    if client is None:
        return None

    for key, value in kwargs.items():
        if hasattr(client, key):
            setattr(client, key, value)

    await session.flush()
    return client


async def seed_quintana(session: AsyncSession) -> None:
    """Seed the Quintana Seguros client if it does not already exist.

    Idempotent: calling this multiple times has no effect if the record exists.
    create_client() automatically creates the default Agent alongside the Client.
    """
    existing = await get_client(session, "quintana-seguros")
    if existing is not None:
        return  # Already seeded — skip

    await create_client(
        session,
        id="quintana-seguros",
        name="Quintana Seguros",
        broker_name="Quintana Seguros",
        agent_name="Jaumpablo",
        voice_id="pNInz6obpgDQGcFmaJgB",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled='["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    )
    # Note: create_client() auto-creates the default Agent — no separate create_agent() needed.


async def seed_demo_inmobiliaria(session: AsyncSession) -> None:
    """Seed the Propiedades del Sur (demo-inmobiliaria) client if it does not already exist.

    Idempotent: calling this multiple times has no effect if the record exists.
    """
    existing = await get_client(session, "demo-inmobiliaria")
    if existing is not None:
        return  # Already seeded — skip

    await create_client(
        session,
        id="demo-inmobiliaria",
        name="demo-inmobiliaria",
        broker_name="Propiedades del Sur",
        agent_name="Valentina",
        voice_id="pNInz6obpgDQGcFmaJgB",  # Adam — update when Valentina voice is configured
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled='["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    )
    # Note: create_client() auto-creates the default Agent — no separate create_agent() needed.


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


async def create_agent(
    session: AsyncSession,
    *,
    client_id: str,
    slug: str,
    name: str,
    voice_id: str,
    system_prompt: str | None = None,
    knowledge_base: str | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str = '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    is_active: bool = True,
    is_default: bool = False,
) -> Agent:
    """Create and persist a new Agent record.

    Enforces that at most one Agent per client has is_default=True.

    Args:
        session: Active async DB session.
        client_id: Foreign key to the owning Client.
        slug: URL-friendly identifier (unique per client).
        name: Display name for the agent.
        voice_id: ElevenLabs voice ID.
        ...

    Returns:
        The persisted Agent instance.

    Raises:
        ValueError: If is_default=True and another default already exists for this client.
    """
    if is_default:
        existing_default = await get_default_agent(session, client_id)
        if existing_default is not None:
            raise ValueError(
                f"Client {client_id!r} already has a default agent: {existing_default.id!r}. "
                "Only one agent per client may have is_default=True."
            )

    # Validate slug uniqueness per client (before DB flush to give a clean error)
    existing_slug = await session.execute(
        select(Agent).where(
            Agent.client_id == client_id,
            Agent.slug == slug,
        )
    )
    if existing_slug.scalar_one_or_none() is not None:
        raise ValueError(
            f"Agent with slug {slug!r} already exists for client {client_id!r}. "
            "slug must be unique per client."
        )

    agent = Agent(
        id=str(uuid.uuid4()),
        client_id=client_id,
        slug=slug,
        name=name,
        voice_id=voice_id,
        system_prompt=system_prompt,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=is_active,
        is_default=is_default,
    )
    session.add(agent)
    await session.flush()
    return agent


async def get_agent(session: AsyncSession, agent_id: str) -> Agent | None:
    """Fetch an Agent by its UUID id.

    Returns:
        Agent instance or None if not found.
    """
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def get_default_agent(session: AsyncSession, client_id: str) -> Agent | None:
    """Fetch the default Agent for a client.

    Returns:
        The active Agent with is_default=True for the given client_id, or None.
        Deactivated agents are excluded even if they have is_default=True.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.client_id == client_id,
            Agent.is_default == True,  # noqa: E712
            Agent.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# New Agent service functions (Phase 7)
# ---------------------------------------------------------------------------


async def list_agents_for_client(
    session: AsyncSession,
    client_id: str,
    *,
    include_inactive: bool = False,
) -> list[Agent]:
    """Return all agents for a client ordered by created_at ascending.

    Args:
        session: Active async DB session.
        client_id: The client to query agents for.
        include_inactive: When False (default), only active agents are returned.

    Returns:
        List of Agent instances sorted by created_at ascending.
    """
    from sqlalchemy import asc

    conditions = [Agent.client_id == client_id]
    if not include_inactive:
        conditions.append(Agent.is_active == True)  # noqa: E712

    result = await session.execute(
        select(Agent).where(*conditions).order_by(asc(Agent.created_at))
    )
    return list(result.scalars().all())


async def update_agent(
    session: AsyncSession,
    agent_id: str,
    client_id: str,
    **kwargs: object,
) -> Agent | None:
    """Partially update an Agent record. Only provided kwargs are written.

    Enforces client isolation: returns None if the agent_id belongs to a
    different client than client_id.

    Args:
        session: Active async DB session.
        agent_id: UUID of the agent to update.
        client_id: The owning client (used for cross-client isolation check).
        **kwargs: Fields to update (e.g., name="New Name", temperature=0.9).

    Returns:
        Updated Agent instance or None if not found / wrong client.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        return None

    for key, value in kwargs.items():
        if hasattr(agent, key):
            setattr(agent, key, value)

    await session.flush()
    return agent


async def deactivate_agent(
    session: AsyncSession,
    agent_id: str,
    client_id: str,
) -> Agent:
    """Soft-delete an agent by setting is_active=False.

    GUARD: Raises ValueError if the agent is the sole active default agent for
    its client. A client must always have at least one active default agent.

    Args:
        session: Active async DB session.
        agent_id: UUID of the agent to deactivate.
        client_id: Owning client (for isolation check).

    Returns:
        The updated Agent with is_active=False.

    Raises:
        ValueError: If agent not found, or if it is the sole active default.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent {agent_id!r} not found for client {client_id!r}.")

    # Sole-default guard: if this agent is the ONLY active default, block deactivation
    if agent.is_default and agent.is_active:
        active_defaults_result = await session.execute(
            select(Agent).where(
                Agent.client_id == client_id,
                Agent.is_default == True,  # noqa: E712
                Agent.is_active == True,  # noqa: E712
            )
        )
        active_defaults = list(active_defaults_result.scalars().all())
        if len(active_defaults) <= 1:
            raise ValueError(
                f"cannot_deactivate_sole_default_agent: agent {agent_id!r} is the "
                f"only active default for client {client_id!r}."
            )

    agent.is_active = False
    await session.flush()
    return agent


async def set_default_agent(
    session: AsyncSession,
    client_id: str,
    agent_id: str,
) -> Agent:
    """Atomically swap the default agent for a client.

    Unsets is_default on all other agents for the client, then sets is_default
    on the target agent. Both writes happen in a single flush (same transaction).

    Args:
        session: Active async DB session.
        client_id: The owning client.
        agent_id: UUID of the agent to make default.

    Returns:
        The updated Agent with is_default=True.

    Raises:
        ValueError: If agent not found or agent is inactive.
    """
    from sqlalchemy import update as sa_update

    # Fetch the target agent with client isolation
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent {agent_id!r} not found for client {client_id!r}.")

    if not agent.is_active:
        raise ValueError(
            f"cannot_set_inactive_agent_as_default: agent {agent_id!r} is inactive."
        )

    # Unset all other defaults for this client in one UPDATE
    await session.execute(
        sa_update(Agent)
        .where(
            Agent.client_id == client_id,
            Agent.id != agent_id,
        )
        .values(is_default=False)
    )

    # Set this agent as default
    agent.is_default = True
    await session.flush()
    return agent
