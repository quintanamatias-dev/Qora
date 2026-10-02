"""Phase 2 (agent-config-revisions-routing) — Tasks 2.2/2.3: revisions_service.

Covers: create_revision (insert-only, monotonic), get_active_revision,
get_revision, list_revisions, activate_revision, rollback_to_revision.
Tenant isolation: every lookup function is scoped by client_id + agent_id.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_FULL_CONFIG = {
    "schema_version": "v1",
    "system_prompt": "You are a helpful assistant.",
    "voice_id": "voice-abc123",
    "tts_model": "eleven_v4_turbo",
    "tts_speed": 0.95,
    "tts_stability": 0.4,
    "tts_similarity_boost": 0.75,
    "model": "gpt-4.1-mini",
    "temperature": 0.7,
    "max_tokens": 300,
    "tools_enabled": ["get_lead_details"],
}


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/revisions_service_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.engine.dispose()


async def _seed_two_agents(session: AsyncSession):
    """Seed quintana-seguros (2 agents) + qora-demo (1 agent) for isolation tests."""
    from app.tenants.service import seed_quintana, seed_qora_demo

    await seed_quintana(session)
    await seed_qora_demo(session)
    await session.commit()


async def test_create_revision_is_insert_only_and_monotonic(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.models import AgentConfigRevision
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None

    starting_count = len(
        (
            await session.execute(
                select(AgentConfigRevision).where(
                    AgentConfigRevision.agent_id == agent.id
                )
            )
        )
        .scalars()
        .all()
    )

    config = AgentConfigV1(**_FULL_CONFIG)
    rev_a = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    rev_b = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )

    assert rev_a.revision_number == starting_count + 1
    assert rev_b.revision_number == starting_count + 2

    result = await session.execute(
        select(AgentConfigRevision).where(AgentConfigRevision.agent_id == agent.id)
    )
    assert len(result.scalars().all()) == starting_count + 2


async def test_create_revision_monotonic_independent_across_agents(
    session: AsyncSession,
):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await get_default_agent(session, "quintana-seguros")
    agent_b = await get_default_agent(session, "qora-demo")
    assert agent_a is not None and agent_b is not None

    config = AgentConfigV1(**_FULL_CONFIG)
    rev_a = await revisions_service.create_revision(
        session, agent=agent_a, config=config, source="api", created_by="tester"
    )
    rev_b = await revisions_service.create_revision(
        session, agent=agent_b, config=config, source="api", created_by="tester"
    )

    assert rev_a.agent_id == agent_a.id
    assert rev_b.agent_id == agent_b.id


async def test_rollback_creates_new_revision_not_reactivation(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None
    client_id = agent.client_id
    agent_id = agent.id

    revision_1 = await revisions_service.get_active_revision(session, client_id, agent_id)
    assert revision_1 is not None
    import json as _json

    original_revision_1_config = _json.loads(revision_1.config)

    config = AgentConfigV1(**_FULL_CONFIG)
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    revision_3 = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    assert agent.active_revision_id == revision_3.id

    new_revision = await revisions_service.rollback_to_revision(
        session, client_id, agent_id, revision_1.id, created_by="tester"
    )
    assert new_revision is not None
    assert new_revision.id != revision_1.id
    assert new_revision.revision_number == revision_3.revision_number + 1
    assert new_revision.source == "rollback"
    assert _json.loads(new_revision.config) == original_revision_1_config
    assert agent.active_revision_id == new_revision.id

    # revision_1's row is untouched
    untouched = await session.get(type(revision_1), revision_1.id)
    assert _json.loads(untouched.config) == original_revision_1_config
    assert untouched.revision_number == revision_1.revision_number
    assert untouched.source == revision_1.source


async def test_activate_revision_changes_only_the_pointer(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None
    client_id, agent_id = agent.client_id, agent.id

    revision_1 = await revisions_service.get_active_revision(session, client_id, agent_id)
    assert revision_1 is not None

    config = AgentConfigV1(**_FULL_CONFIG)
    revision_2 = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    assert agent.active_revision_id == revision_2.id

    result = await revisions_service.activate_revision(
        session, client_id, agent_id, revision_1.id
    )
    assert result is not None
    assert agent.active_revision_id == revision_1.id

    # content unchanged for both revisions
    refreshed_1 = await session.get(type(revision_1), revision_1.id)
    refreshed_2 = await session.get(type(revision_2), revision_2.id)
    assert refreshed_1.config == revision_1.config
    assert refreshed_2.config == revision_2.config


async def test_list_revisions_returns_newest_first(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None
    client_id, agent_id = agent.client_id, agent.id

    config = AgentConfigV1(**_FULL_CONFIG)
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )

    revisions = await revisions_service.list_revisions(session, client_id, agent_id)
    numbers = [r.revision_number for r in revisions]
    assert numbers == sorted(numbers, reverse=True)
    assert len(numbers) >= 3


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_revision_of_another_agent_is_not_readable(session: AsyncSession):
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await get_default_agent(session, "quintana-seguros")
    agent_b = await get_default_agent(session, "qora-demo")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    # Fetching agent_a's revision while scoped to agent_b's (client_id, agent_id) fails.
    leaked = await revisions_service.get_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id
    )
    assert leaked is None


async def test_revision_of_another_agent_is_not_activatable(session: AsyncSession):
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await get_default_agent(session, "quintana-seguros")
    agent_b = await get_default_agent(session, "qora-demo")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    result = await revisions_service.activate_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id
    )
    assert result is None
    assert agent_b.active_revision_id != revision_a.id


async def test_rollback_across_tenant_boundary_is_rejected(session: AsyncSession):
    from app.tenants.service import get_default_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await get_default_agent(session, "quintana-seguros")
    agent_b = await get_default_agent(session, "qora-demo")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    result = await revisions_service.rollback_to_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id, created_by="tester"
    )
    assert result is None
