"""Unit tests for tenants service — CRUD, unknown tenant, seed guard.

RED: References app.tenants.models and app.tenants.service which do NOT exist yet.
These tests define the contract before implementation.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path
from pydantic import SecretStr

from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    """Provide an isolated async session for each test."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tenants_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Test: create_client + get_client
# ---------------------------------------------------------------------------


async def test_create_client_persists_record(session: AsyncSession):
    """create_client() persists a Client record that can be retrieved by id."""
    from app.tenants.service import create_client, get_client

    client = await create_client(
        session,
        id="test-broker",
        name="Test Broker SA",
        agent_name="TestAgent",
        voice_id="voice-abc123",
    )

    assert client.id == "test-broker"
    assert client.name == "Test Broker SA"
    assert client.name == "Test Broker SA"
    assert client.agent_name == "TestAgent"
    assert client.voice_id == "voice-abc123"
    assert client.is_active is True

    # Fetch by id and verify round-trip
    fetched = await get_client(session, "test-broker")
    assert fetched is not None
    assert fetched.id == "test-broker"
    assert fetched.name == "Test Broker SA"


async def test_get_client_returns_none_for_missing_id(session: AsyncSession):
    """get_client() returns None when the id does not exist."""
    from app.tenants.service import get_client

    result = await get_client(session, "nonexistent-id")
    assert result is None


# ---------------------------------------------------------------------------
# Test: get_client_by_name
# ---------------------------------------------------------------------------


async def test_get_client_by_name_finds_existing(session: AsyncSession):
    """get_client_by_name() returns the correct client by its unique name."""
    from app.tenants.service import create_client, get_client_by_name

    await create_client(
        session,
        id="broker-xyz",
        name="Broker XYZ",
        agent_name="Agent",
        voice_id="v1",
    )

    found = await get_client_by_name(session, "Broker XYZ")
    assert found is not None
    assert found.id == "broker-xyz"


async def test_get_client_by_name_returns_none_for_missing(session: AsyncSession):
    """get_client_by_name() returns None when no client has that name."""
    from app.tenants.service import get_client_by_name

    result = await get_client_by_name(session, "Does Not Exist")
    assert result is None


# ---------------------------------------------------------------------------
# Test: update_client
# ---------------------------------------------------------------------------


async def test_update_client_changes_fields(session: AsyncSession):
    """update_client() persists field updates to the client record."""
    from app.tenants.service import create_client, update_client, get_client

    await create_client(
        session,
        id="updatable",
        name="Old Broker",
        agent_name="OldAgent",
        voice_id="old-voice",
    )

    updated = await update_client(
        session,
        client_id="updatable",
        name="New Broker",
    )

    assert updated is not None
    assert updated.name == "New Broker"
    # Unchanged field must stay the same
    assert updated.agent_name == "OldAgent"

    # Verify persistence (re-fetch)
    fetched = await get_client(session, "updatable")
    assert fetched is not None
    assert fetched.name == "New Broker"


async def test_update_client_returns_none_for_missing(session: AsyncSession):
    """update_client() returns None when the client id does not exist."""
    from app.tenants.service import update_client

    result = await update_client(session, client_id="ghost", name="Ghost")
    assert result is None


# ---------------------------------------------------------------------------
# Test: Quintana Seguros seed
# ---------------------------------------------------------------------------


async def test_seed_quintana_creates_client(session: AsyncSession):
    """seed_quintana() creates the Quintana Seguros client if it does not exist."""
    from app.tenants.service import seed_quintana, get_client

    await seed_quintana(session)

    client = await get_client(session, "quintana-seguros")
    assert client is not None
    assert client.name == "Quintana Seguros"
    assert client.agent_name == "Jaumpablo"
    assert client.voice_id == "pNInz6obpgDQGcFmaJgB"


async def test_seed_quintana_is_idempotent(session: AsyncSession):
    """seed_quintana() called twice does not raise and does not duplicate."""
    from app.tenants.service import seed_quintana
    from sqlalchemy import select
    from app.tenants.models import Client

    await seed_quintana(session)
    await seed_quintana(session)  # second call — must not error or duplicate

    result = await session.execute(
        select(Client).where(Client.id == "quintana-seguros")
    )
    clients = result.scalars().all()
    assert len(clients) == 1  # exactly one record, not two


# ---------------------------------------------------------------------------
# Phase 7 — Task 2.1: list_agents_for_client()
# ---------------------------------------------------------------------------


async def test_list_agents_for_client_returns_all_agents(session: AsyncSession):
    """list_agents_for_client() returns all agents for a client ordered by created_at."""
    from app.tenants.service import create_client, create_agent, list_agents_for_client

    await create_client(
        session,
        id="list-test",
        name="List Test",
        agent_name="Agent1",
        voice_id="v1",
    )
    await session.commit()

    # Create a second agent manually
    await create_agent(
        session,
        client_id="list-test",
        slug="second-agent",
        name="Agent2",
        voice_id="v2",
        is_active=True,
        is_default=False,
    )
    await session.commit()

    agents = await list_agents_for_client(session, "list-test")
    assert len(agents) == 2
    slugs = [a.slug for a in agents]
    assert "agent1" in slugs
    assert "second-agent" in slugs


async def test_list_agents_for_client_returns_empty_for_no_agents(
    session: AsyncSession,
):
    """list_agents_for_client() returns empty list for client with no agents.

    We create a client with no auto-bootstrapped agents by directly inserting
    to test the empty-list path.
    """
    from app.tenants.models import Client
    from app.tenants.service import list_agents_for_client

    bare_client = Client(
        id="bare-client",
        name="Bare",
        agent_name="X",
        voice_id="v0",
    )
    session.add(bare_client)
    await session.flush()
    await session.commit()

    agents = await list_agents_for_client(session, "bare-client")
    assert agents == []


async def test_list_agents_for_client_isolation(session: AsyncSession):
    """list_agents_for_client() returns only agents for the specified client."""
    from app.tenants.service import create_client, list_agents_for_client

    # Create two clients — each auto-bootstraps one default agent
    await create_client(
        session,
        id="client-a",
        name="A",
        agent_name="AgentA",
        voice_id="va",
    )
    await create_client(
        session,
        id="client-b",
        name="B",
        agent_name="AgentB",
        voice_id="vb",
    )
    await session.commit()

    agents_a = await list_agents_for_client(session, "client-a")
    agents_b = await list_agents_for_client(session, "client-b")

    assert len(agents_a) == 1
    assert len(agents_b) == 1
    assert all(a.client_id == "client-a" for a in agents_a)
    assert all(a.client_id == "client-b" for a in agents_b)


async def test_list_agents_for_client_excludes_inactive_by_default(
    session: AsyncSession,
):
    """list_agents_for_client() excludes inactive agents by default.

    Triangulation: include_inactive=True shows ALL agents including deactivated.
    """
    from app.tenants.service import create_client, create_agent, list_agents_for_client

    await create_client(
        session,
        id="inactive-test",
        name="Inactive",
        agent_name="DefaultAgent",
        voice_id="v1",
    )
    # Add a second inactive agent
    inactive = await create_agent(
        session,
        client_id="inactive-test",
        slug="inactive-agent",
        name="Inactive",
        voice_id="v2",
        is_active=False,
        is_default=False,
    )
    await session.commit()

    # Default: exclude inactive
    active_agents = await list_agents_for_client(session, "inactive-test")
    assert len(active_agents) == 1
    assert all(a.is_active for a in active_agents)

    # With include_inactive=True: include all
    all_agents = await list_agents_for_client(
        session, "inactive-test", include_inactive=True
    )
    assert len(all_agents) == 2
    ids = {a.id for a in all_agents}
    assert inactive.id in ids


# ---------------------------------------------------------------------------
# elevenlabs-reconciler Phase 6 (6.1): is_default write-time uniqueness removed
# ---------------------------------------------------------------------------


async def test_create_agent_no_longer_enforces_is_default_uniqueness(
    session: AsyncSession,
):
    """create_agent() no longer raises when a second is_default=True agent is
    created for the same client (design.md R-D3: resolve_single_active_agent
    already ignores is_default; the write-time check is dead-weight cleanup).
    """
    from app.tenants.service import create_client, create_agent

    await create_client(
        session,
        id="dup-default-ok",
        name="Dup Default OK",
        agent_name="DefaultAgent",
        voice_id="v1",
    )
    # create_client() already bootstrapped one is_default=True agent.

    second = await create_agent(
        session,
        client_id="dup-default-ok",
        slug="agent-two",
        name="Agent Two",
        voice_id="v2",
        is_default=True,
    )
    assert second is not None
    assert second.is_default is True


# ---------------------------------------------------------------------------
# Phase 7 — Task 2.2: update_agent()
# ---------------------------------------------------------------------------


async def test_update_agent_changes_specified_fields(session: AsyncSession):
    """update_agent() applies partial updates, leaving other fields unchanged."""
    from app.tenants.service import create_client, update_agent

    await create_client(
        session,
        id="update-agent-test",
        name="Update",
        agent_name="OriginalAgent",
        voice_id="v-original",
    )
    await session.commit()

    # Get the agent that was bootstrapped
    from app.tenants.service import resolve_single_active_agent

    agent = await resolve_single_active_agent(session, "update-agent-test")
    assert agent is not None

    updated = await update_agent(
        session,
        agent_id=agent.id,
        client_id="update-agent-test",
        name="Updated Name",
        temperature=0.9,
    )

    assert updated is not None
    assert updated.name == "Updated Name"
    assert updated.temperature == 0.9
    # Unchanged fields preserved
    assert updated.voice_id == "v-original"
    assert updated.model == "gpt-4.1-mini"


async def test_update_agent_rejects_cross_client_lookup(session: AsyncSession):
    """update_agent() returns None when agent_id belongs to a different client."""
    from app.tenants.service import create_client, resolve_single_active_agent, update_agent

    await create_client(
        session,
        id="client-x",
        name="X",
        agent_name="AgentX",
        voice_id="vx",
    )
    await create_client(
        session,
        id="client-y",
        name="Y",
        agent_name="AgentY",
        voice_id="vy",
    )
    await session.commit()

    agent_x = await resolve_single_active_agent(session, "client-x")
    assert agent_x is not None

    # Try to update agent from client-x using client-y's context
    result = await update_agent(
        session,
        agent_id=agent_x.id,
        client_id="client-y",  # wrong client
        name="Hijacked",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Phase 7 — Task 2.3: deactivate_agent()
# ---------------------------------------------------------------------------


async def test_deactivate_non_default_agent_succeeds(session: AsyncSession):
    """deactivate_agent() sets is_active=False on a non-default agent."""
    from app.tenants.service import create_client, create_agent, deactivate_agent

    await create_client(
        session,
        id="deact-test",
        name="Deact",
        agent_name="DefaultAgent",
        voice_id="v1",
    )
    second_agent = await create_agent(
        session,
        client_id="deact-test",
        slug="second",
        name="Second",
        voice_id="v2",
        is_active=True,
        is_default=False,
    )
    await session.commit()

    deactivated = await deactivate_agent(
        session, agent_id=second_agent.id, client_id="deact-test"
    )

    assert deactivated.is_active is False
    assert deactivated.id == second_agent.id


async def test_deactivate_sole_active_agent_raises_guard_regardless_of_is_default(
    session: AsyncSession,
):
    """deactivate_agent() raises ValueError when agent is the client's last
    remaining active agent — counted by active-agent count, not is_default
    (agent-routing spec D3: Deactivation guard no longer depends on is_default).
    """
    from app.tenants.service import create_client, resolve_single_active_agent, deactivate_agent
    from app.tenants.models import Agent
    from sqlalchemy import update

    await create_client(
        session,
        id="sole-active-test",
        name="Sole",
        agent_name="OnlyAgent",
        voice_id="v1",
    )
    await session.commit()

    sole_agent = await resolve_single_active_agent(session, "sole-active-test")
    # Flip off is_default to prove the guard no longer reads that flag.
    await session.execute(
        update(Agent).where(Agent.id == sole_agent.id).values(is_default=False)
    )
    await session.commit()

    with pytest.raises(ValueError, match="cannot_deactivate_last_active_agent"):
        await deactivate_agent(
            session, agent_id=sole_agent.id, client_id="sole-active-test"
        )


async def test_deactivate_one_of_two_active_agents_succeeds_regardless_of_is_default(
    session: AsyncSession,
):
    """A client with two active agents, neither is_default, may deactivate one."""
    from app.tenants.service import create_client, create_agent, resolve_single_active_agent, deactivate_agent
    from app.tenants.models import Agent
    from sqlalchemy import update

    await create_client(
        session,
        id="two-active-test",
        name="Two",
        agent_name="First",
        voice_id="v1",
    )
    first_agent = await resolve_single_active_agent(session, "two-active-test")
    await session.execute(
        update(Agent).where(Agent.id == first_agent.id).values(is_default=False)
    )
    second_agent = await create_agent(
        session,
        client_id="two-active-test",
        slug="second-agent",
        name="Second",
        voice_id="v2",
        is_default=False,
    )
    await session.commit()

    deactivated = await deactivate_agent(
        session, agent_id=first_agent.id, client_id="two-active-test"
    )

    assert deactivated.is_active is False
    assert deactivated.id == first_agent.id


# ---------------------------------------------------------------------------
# elevenlabs_agent_id is part of the Alembic baseline migration (PR 2 cutover).
# The startup compat test below was removed when _ensure_startup_schema_compat
# was deleted from app.main (phase-b-db-migration-foundation/design.md).
# The column is verified to exist in tests/unit/test_alembic_tooling.py instead.
# ---------------------------------------------------------------------------
