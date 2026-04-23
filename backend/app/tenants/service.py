"""QORA Tenants — Service layer for Client CRUD, Agent CRUD, and seed operations."""

from __future__ import annotations

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
    )
    session.add(client)
    await session.flush()  # Flush to DB within current transaction

    # Bootstrap a default Agent for this client (CRITICAL 1b: every client must have one)
    slug = (agent_name or "agent").lower().replace(" ", "-")
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
