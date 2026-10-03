"""Generic second tenant for cross-tenant isolation tests.

Used whenever a test needs a second, genuinely distinct client + agent (not
just quintana-seguros) to exercise tenant isolation, multi-tenant resync, or
sync-trigger behavior.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

SECOND_TENANT_CLIENT_ID = "acme-widgets"
SECOND_TENANT_AGENT_SLUG = "acme-widgets-agent"


async def seed_second_tenant(session: AsyncSession) -> None:
    """Idempotently create a second client + default agent for isolation tests."""
    from app.tenants.service import create_client, get_client

    existing = await get_client(session, SECOND_TENANT_CLIENT_ID)
    if existing is None:
        await create_client(
            session,
            id=SECOND_TENANT_CLIENT_ID,
            name="Acme Widgets",
            agent_name=SECOND_TENANT_AGENT_SLUG,
            voice_id="voice-acme-test",
        )
