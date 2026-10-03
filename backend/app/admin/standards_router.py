"""QORA Admin — standards resync endpoint (agent-config-inheritance task 5.6/D15/D19).

    POST /api/v1/admin/standards/resync

Moved here (task 6, follow-up) from `app/clients/router.py`'s temporary
`/admin/standards/resync` mount — that deviation existed only because
`backend/app/main.py` was outside the allowed edit surface for task 5.6.
This router is now registered directly in `main.py`, giving the intended
platform-wide `/admin` mount point with no client-id scoping.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import require_superadmin
from app.elevenlabs.service import sync_to_elevenlabs
from app.tenants.materialize import materialize_agent_config, snapshot_mirrored_fields
from app.tenants.models import Agent

router = APIRouter(prefix="/admin", tags=["admin"])


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


@router.post(
    "/standards/resync",
    dependencies=[Depends(require_superadmin)],
)
async def resync_standard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Re-materialize every active agent platform-wide against the current
    AgentConfigStandard, and trigger the existing EL sync (fire-and-forget)
    only for agents whose resolved config actually changed, or whose
    materialized_standard_version no longer matches STANDARD_VERSION.

    design.md D15: a STANDARD_VERSION code deploy never auto-syncs anyone —
    this explicit endpoint is the only path that fans EL syncs out across a
    standard change, avoiding a deploy-time API-rate-limited sync storm.

    Returns:
        200: {standard_version, agents_checked, agents_changed, synced}
    """
    from app.tenants.config_standard import STANDARD_VERSION

    result = await session.execute(select(Agent).where(Agent.is_active == True))  # noqa: E712
    agents = list(result.scalars().all())

    agents_checked = 0
    agents_changed = 0
    agents_to_sync: list[str] = []
    for agent in agents:
        agents_checked += 1
        was_drifted_version = agent.materialized_standard_version != STANDARD_VERSION
        before = snapshot_mirrored_fields(agent)
        await materialize_agent_config(session, agent)
        after = snapshot_mirrored_fields(agent)
        changed = any(before[field] != after[field] for field in before)
        if changed:
            agents_changed += 1
        if (changed or was_drifted_version) and agent.elevenlabs_agent_id:
            agents_to_sync.append(agent.id)

    await session.commit()

    settings = request.app.state.settings
    for agent_id in agents_to_sync:
        asyncio.create_task(sync_to_elevenlabs(agent_id=agent_id, settings=settings))

    return {
        "standard_version": STANDARD_VERSION,
        "agents_checked": agents_checked,
        "agents_changed": agents_changed,
        "synced": len(agents_to_sync),
    }
