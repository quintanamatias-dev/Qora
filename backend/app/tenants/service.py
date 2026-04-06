"""QORA Tenants — Service layer for Client CRUD and seed operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.models import Client


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
    """Create and persist a new Client record.

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
