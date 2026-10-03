"""list_clients / get_client (design.md M-D1) — read-only, no tenant scoping
needed since these return identity/config shape only, never tenant data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, ClientSummary
from app.tenants.models import Client


def _to_summary(client: Client) -> ClientSummary:
    return ClientSummary(
        client_id=client.id,
        name=client.name,
        agent_name=client.agent_name,
        voice_id=client.voice_id,
        is_active=client.is_active,
        plan=client.plan or "pilot",
        analysis_language=client.analysis_language,
        scheduler_enabled=client.scheduler_enabled,
        created_at=client.created_at,
    )


async def list_clients(
    session: AsyncSession, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> list[ClientSummary]:
    """Return active clients ordered by id, capped at MAX_PAGE_SIZE."""
    bounded_limit = min(limit, MAX_PAGE_SIZE)
    result = await session.execute(
        select(Client)
        .where(Client.is_active == True)  # noqa: E712
        .order_by(Client.id)
        .offset(offset)
        .limit(bounded_limit)
    )
    return [_to_summary(c) for c in result.scalars().all()]


async def get_client(session: AsyncSession, client_id: str) -> ClientSummary | None:
    """Return a single client by id, or None if it does not exist."""
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return _to_summary(client)
