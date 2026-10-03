"""Unit tests for fail-closed agent resolution (design.md D2/D3, agent-routing spec).

resolve_single_active_agent() and get_agent_for_client() replace is_default-based
lookups on legacy/no-agent-id call sites without deleting get_default_agent yet
(get_default_agent/set_default_agent removal is deferred to the end of Phase 4b).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agent_resolution_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.close_db()


async def test_resolve_single_active_agent_returns_the_only_active_agent(session):
    from app.tenants.service import create_client, resolve_single_active_agent

    client = await create_client(
        session,
        id="single-agent-client",
        name="Single Agent Co",
        agent_name="Solo",
        voice_id="v-solo",
    )
    await session.commit()

    agent = await resolve_single_active_agent(session, client.id)
    assert agent.client_id == "single-agent-client"


async def test_resolve_single_active_agent_raises_when_zero_active_agents(session):
    from app.tenants.service import (
        create_client,
        get_default_agent,
        resolve_single_active_agent,
        NoActiveAgentError,
    )
    from app.tenants.models import Agent
    from sqlalchemy import update

    client = await create_client(
        session,
        id="zero-agent-client",
        name="Zero Agent Co",
        agent_name="Ghost",
        voice_id="v-ghost",
    )
    only_agent = await get_default_agent(session, client.id)
    await session.execute(
        update(Agent).where(Agent.id == only_agent.id).values(is_active=False)
    )
    await session.commit()

    with pytest.raises(NoActiveAgentError):
        await resolve_single_active_agent(session, client.id)


async def test_resolve_single_active_agent_raises_when_multiple_active_agents(session):
    from app.tenants.service import (
        create_agent,
        create_client,
        resolve_single_active_agent,
        AmbiguousAgentError,
    )

    client = await create_client(
        session,
        id="multi-agent-client",
        name="Multi Agent Co",
        agent_name="First",
        voice_id="v-first",
    )
    await create_agent(
        session,
        client_id=client.id,
        slug="second-agent",
        name="Second",
        voice_id="v-second",
    )
    await session.commit()

    with pytest.raises(AmbiguousAgentError):
        await resolve_single_active_agent(session, client.id)


async def test_resolve_single_active_agent_never_consults_is_default(session):
    """Two active agents, neither is_default — still ambiguous (not a silent pick)."""
    from app.tenants.service import (
        create_agent,
        create_client,
        get_default_agent,
        resolve_single_active_agent,
        AmbiguousAgentError,
    )
    from app.tenants.models import Agent
    from sqlalchemy import update

    client = await create_client(
        session,
        id="no-default-flag-client",
        name="No Default Flag Co",
        agent_name="First",
        voice_id="v-first",
    )
    first_agent = await get_default_agent(session, client.id)
    await session.execute(
        update(Agent).where(Agent.id == first_agent.id).values(is_default=False)
    )
    await create_agent(
        session,
        client_id=client.id,
        slug="second-agent",
        name="Second",
        voice_id="v-second",
        is_default=False,
    )
    await session.commit()

    with pytest.raises(AmbiguousAgentError):
        await resolve_single_active_agent(session, client.id)


async def test_get_agent_for_client_returns_active_agent_in_same_client(session):
    from app.tenants.service import create_client, get_agent_for_client, get_default_agent

    client = await create_client(
        session,
        id="isolated-client-a",
        name="Isolated A",
        agent_name="Agent A",
        voice_id="v-a",
    )
    await session.commit()
    agent = await get_default_agent(session, client.id)

    fetched = await get_agent_for_client(session, "isolated-client-a", agent.id)
    assert fetched is not None
    assert fetched.id == agent.id


async def test_get_agent_for_client_returns_none_for_cross_client_agent(session):
    """Tenant isolation: an agent_id belonging to another client is never returned."""
    from app.tenants.service import create_client, get_agent_for_client, get_default_agent

    client_a = await create_client(
        session,
        id="isolated-client-b",
        name="Isolated B",
        agent_name="Agent B",
        voice_id="v-b",
    )
    client_c = await create_client(
        session,
        id="isolated-client-c",
        name="Isolated C",
        agent_name="Agent C",
        voice_id="v-c",
    )
    await session.commit()
    agent_b = await get_default_agent(session, client_a.id)

    # agent_b belongs to client_a ("isolated-client-b"); requesting it under
    # client_c must return None, not the agent.
    fetched = await get_agent_for_client(session, client_c.id, agent_b.id)
    assert fetched is None


async def test_get_agent_for_client_returns_none_for_inactive_agent(session):
    from app.tenants.service import create_client, get_agent_for_client, get_default_agent
    from app.tenants.models import Agent
    from sqlalchemy import update

    client = await create_client(
        session,
        id="inactive-agent-client",
        name="Inactive Agent Co",
        agent_name="Gone",
        voice_id="v-gone",
    )
    await session.commit()
    agent = await get_default_agent(session, client.id)
    await session.execute(
        update(Agent).where(Agent.id == agent.id).values(is_active=False)
    )
    await session.commit()

    fetched = await get_agent_for_client(session, client.id, agent.id)
    assert fetched is None
