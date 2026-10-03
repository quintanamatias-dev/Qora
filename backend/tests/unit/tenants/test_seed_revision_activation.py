"""Phase 1 (agent-config-revisions-routing) — Task 1.5: seeders activate revision 1.

Covers: seed_quintana() must create + activate an AgentConfigRevision
(revision_number=1) for every agent it seeds, so a fresh (non-migrated) DB
matches the migrated-production invariant that every agent has a non-null
active_revision_id.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    """Provide an isolated async session backed by the real migration chain."""
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/seed_revision_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.engine.dispose()


async def test_seed_quintana_creates_active_revision_for_every_agent(
    session: AsyncSession,
):
    """seed_quintana() creates + activates a revision 1 for its seeded agent."""
    from app.tenants.models import AgentConfigRevision
    from app.tenants.service import seed_quintana, resolve_single_active_agent

    await seed_quintana(session)

    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None
    assert agent.active_revision_id is not None

    revision = await session.get(AgentConfigRevision, agent.active_revision_id)
    assert revision is not None
    assert revision.revision_number == 1
    config = json.loads(revision.config)
    assert config["voice_id"] == agent.voice_id
    assert config["model"] == agent.model


async def test_seed_quintana_revision_activation_is_idempotent(session: AsyncSession):
    """Calling seed_quintana() twice does not create a second revision."""
    from app.tenants.models import AgentConfigRevision
    from app.tenants.service import seed_quintana, resolve_single_active_agent

    await seed_quintana(session)
    await seed_quintana(session)

    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    result = await session.execute(
        select(AgentConfigRevision).where(AgentConfigRevision.agent_id == agent.id)
    )
    revisions = list(result.scalars().all())
    assert len(revisions) == 1, f"expected exactly 1 revision, got {len(revisions)}"
