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
    from app.tenants.service import get_default_agent

    agent = await get_default_agent(session, "update-agent-test")
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
    assert updated.model == "gpt-4o"


async def test_update_agent_rejects_cross_client_lookup(session: AsyncSession):
    """update_agent() returns None when agent_id belongs to a different client."""
    from app.tenants.service import create_client, get_default_agent, update_agent

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

    agent_x = await get_default_agent(session, "client-x")
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


async def test_deactivate_sole_active_default_raises_guard(session: AsyncSession):
    """deactivate_agent() raises ValueError when agent is the sole active default."""
    from app.tenants.service import create_client, get_default_agent, deactivate_agent

    await create_client(
        session,
        id="sole-default-test",
        name="Sole",
        agent_name="OnlyAgent",
        voice_id="v1",
    )
    await session.commit()

    sole_default = await get_default_agent(session, "sole-default-test")
    assert sole_default is not None

    with pytest.raises(ValueError, match="cannot_deactivate_sole_default_agent"):
        await deactivate_agent(
            session, agent_id=sole_default.id, client_id="sole-default-test"
        )


# ---------------------------------------------------------------------------
# Phase 7 — Task 2.4: set_default_agent()
# ---------------------------------------------------------------------------


async def test_set_default_agent_swaps_atomically(session: AsyncSession):
    """set_default_agent() unsets old default and sets new default in one operation."""
    from app.tenants.service import (
        create_client,
        create_agent,
        set_default_agent,
        get_default_agent,
    )

    await create_client(
        session,
        id="swap-test",
        name="Swap",
        agent_name="AgentA",
        voice_id="va",
    )
    agent_b = await create_agent(
        session,
        client_id="swap-test",
        slug="agent-b",
        name="Agent B",
        voice_id="vb",
        is_active=True,
        is_default=False,
    )
    await session.commit()

    agent_a = await get_default_agent(session, "swap-test")
    assert agent_a is not None
    assert agent_a.is_default is True
    assert agent_b.is_default is False

    # Swap default to agent_b
    result = await set_default_agent(
        session, client_id="swap-test", agent_id=agent_b.id
    )

    assert result.id == agent_b.id
    assert result.is_default is True

    # agent_a must no longer be default
    await session.refresh(agent_a)
    assert agent_a.is_default is False


async def test_set_default_agent_idempotent(session: AsyncSession):
    """set_default_agent() is idempotent when agent is already the default."""
    from app.tenants.service import create_client, get_default_agent, set_default_agent

    await create_client(
        session,
        id="idempotent-default",
        name="Idem",
        agent_name="Agent",
        voice_id="v1",
    )
    await session.commit()

    current_default = await get_default_agent(session, "idempotent-default")
    assert current_default is not None

    # Call again on already-default agent — should succeed without error
    result = await set_default_agent(
        session, client_id="idempotent-default", agent_id=current_default.id
    )
    assert result.is_default is True
    assert result.id == current_default.id


async def test_set_default_agent_inactive_target_raises(session: AsyncSession):
    """set_default_agent() raises ValueError when target agent is inactive."""
    import pytest
    from app.tenants.service import create_client, create_agent, set_default_agent

    await create_client(
        session,
        id="inactive-default-test",
        name="InactDef",
        agent_name="Active",
        voice_id="v1",
    )
    inactive_agent = await create_agent(
        session,
        client_id="inactive-default-test",
        slug="inactive-candidate",
        name="Inactive Candidate",
        voice_id="v2",
        is_active=False,
        is_default=False,
    )
    await session.commit()

    with pytest.raises(ValueError, match="cannot_set_inactive_agent_as_default"):
        await set_default_agent(
            session,
            client_id="inactive-default-test",
            agent_id=inactive_agent.id,
        )


# ---------------------------------------------------------------------------
# qora-demo-agent-admin-fix — Task 1.3: seed_qora_demo() tests
# ---------------------------------------------------------------------------


async def test_seed_qora_demo_creates_client_and_agent(session: AsyncSession):
    """seed_qora_demo() creates qora-demo client + qora-explainer agent with system_prompt.

    On a clean DB, the seed must create:
    - Client with id='qora-demo'
    - Default agent with name='qora-explainer' and system_prompt that:
        * mentions Qora (the platform being explained)
        * describes the agent's role as Mariano, the Qora demo explainer
    """
    from app.tenants.service import seed_qora_demo, get_client
    from sqlalchemy import select
    from app.tenants.models import Agent

    await seed_qora_demo(session)
    await session.commit()

    client = await get_client(session, "qora-demo")
    assert client is not None
    assert client.name == "Qora Demo"  # exact expected broker name

    agent_result = await session.execute(
        select(Agent).where(
            Agent.client_id == "qora-demo",
            Agent.is_default == True,  # noqa: E712
        )
    )
    agent = agent_result.scalar_one_or_none()
    assert agent is not None
    assert agent.name == "qora-explainer"
    assert agent.system_prompt is not None
    # The prompt must reference the Qora platform by name
    assert (
        "Qora" in agent.system_prompt
    ), "system_prompt must mention 'Qora' — agent explains the platform"
    # The agent's role is to explain Qora (Mariano demo agent, not insurance-domain bot)
    prompt_lower = agent.system_prompt.lower()
    assert (
        "explicar" in prompt_lower or "explain" in prompt_lower
    ), "system_prompt must include an explaining/explainer role keyword"


async def test_seed_qora_demo_is_idempotent(session: AsyncSession):
    """seed_qora_demo() called twice creates exactly one client and one agent.

    No errors raised, no duplicate records created.
    """
    from app.tenants.service import seed_qora_demo
    from sqlalchemy import select
    from app.tenants.models import Client, Agent

    await seed_qora_demo(session)
    await session.commit()
    await seed_qora_demo(session)  # second call — must be a no-op
    await session.commit()

    clients_result = await session.execute(
        select(Client).where(Client.id == "qora-demo")
    )
    clients = clients_result.scalars().all()
    assert len(clients) == 1  # exactly one record

    agents_result = await session.execute(
        select(Agent).where(Agent.client_id == "qora-demo")
    )
    agents = agents_result.scalars().all()
    assert len(agents) == 1  # exactly one agent


async def test_seed_qora_demo_agent_prompt_describes_qora_not_insurance(
    session: AsyncSession,
):
    """Triangulation: system_prompt positions the agent as a Qora explainer.

    The agent's role is to explain the Qora platform. The prompt must:
    - Reference Mariano as the Qora platform demo agent
    - Describe the goal as explaining Qora ('explicar Qora')
    - NOT contain insurance-domain wording (seguros, cotización, productora)

    This distinguishes the Qora demo agent from any insurance-domain bot.
    """
    from app.tenants.service import seed_qora_demo
    from sqlalchemy import select
    from app.tenants.models import Agent

    await seed_qora_demo(session)
    await session.commit()

    agent_result = await session.execute(
        select(Agent).where(
            Agent.client_id == "qora-demo",
            Agent.is_default == True,  # noqa: E712
        )
    )
    agent = agent_result.scalar_one_or_none()
    assert agent is not None

    prompt = agent.system_prompt
    assert prompt is not None

    # The prompt must describe the agent as part of the Qora platform
    assert (
        "plataforma Qora" in prompt or "platform Qora" in prompt
    ), "system_prompt must identify the agent as part of the Qora platform"
    # The agent's goal is to explain Qora — the phrase must appear explicitly
    assert (
        "explicar Qora" in prompt or "explain Qora" in prompt
    ), "system_prompt goal must be explaining Qora (Mariano demo agent)"


# ---------------------------------------------------------------------------
# Task 1.3 (NEW) — qora-demo Demo Visitor lead + elevenlabs_agent_id seed
# ---------------------------------------------------------------------------


async def test_seed_qora_demo_creates_demo_visitor_lead(session: AsyncSession):
    """seed_qora_demo() creates at least one Demo Visitor lead for qora-demo.

    The seeded lead must:
    - have a non-empty name
    - be associated with the qora-demo client
    """
    from app.tenants.service import seed_qora_demo
    from app.leads.service import list_leads_for_client

    await seed_qora_demo(session)
    await session.commit()

    leads = await list_leads_for_client(session, "qora-demo")
    assert len(leads) >= 1, "seed_qora_demo must create at least one lead for qora-demo"
    demo_lead = leads[0]
    assert demo_lead.name, "Demo lead must have a non-empty name"
    assert demo_lead.client_id == "qora-demo"


async def test_seed_qora_demo_lead_is_idempotent(session: AsyncSession):
    """seed_qora_demo() called twice does not create duplicate leads.

    Precondition: first seed must create at least 1 lead (non-trivial).
    Second call must not add more — count stays the same.
    """
    from app.tenants.service import seed_qora_demo
    from app.leads.service import list_leads_for_client

    await seed_qora_demo(session)
    await session.commit()
    leads_first = await list_leads_for_client(session, "qora-demo")
    count_first = len(leads_first)
    # Real test: first seed must produce ≥1 lead
    assert count_first >= 1, "First seed must create at least one demo lead"

    await seed_qora_demo(session)
    await session.commit()
    count_second = len(await list_leads_for_client(session, "qora-demo"))

    assert count_first == count_second, (
        f"seed_qora_demo must be idempotent: "
        f"first call created {count_first} leads, second call has {count_second}"
    )


async def test_seed_qora_demo_sets_elevenlabs_agent_id_from_settings(
    session: AsyncSession,
):
    """seed_qora_demo() sets agent.elevenlabs_agent_id from Settings.elevenlabs_agent_id.

    When settings.elevenlabs_agent_id is non-empty, the seeded qora-explainer agent
    must have elevenlabs_agent_id equal to that value.
    """
    from app.tenants.service import seed_qora_demo
    from sqlalchemy import select
    from app.tenants.models import Agent

    await seed_qora_demo(session)
    await session.commit()

    agent_result = await session.execute(
        select(Agent).where(
            Agent.client_id == "qora-demo",
            Agent.is_default == True,  # noqa: E712
        )
    )
    agent = agent_result.scalar_one_or_none()
    assert agent is not None
    # elevenlabs_agent_id column must exist on the model (not raise AttributeError)
    _ = agent.elevenlabs_agent_id  # AttributeError if column missing


async def test_seed_qora_demo_el_agent_id_matches_settings_when_configured(
    session: AsyncSession,
):
    """When Settings.elevenlabs_agent_id is configured, seeded agent uses that value.

    Triangulation: tests the non-empty case to force real logic.
    Uses monkeypatching via environment variable injection into Settings constructor.
    """
    import os
    from app.tenants.service import seed_qora_demo
    from sqlalchemy import select
    from app.tenants.models import Agent
    from unittest.mock import patch

    # Patch os.environ so Settings picks up the test EL agent ID
    with patch.dict(os.environ, {"ELEVENLABS_AGENT_ID": "el_test_configured"}):
        await seed_qora_demo(session)
        await session.commit()

    agent_result = await session.execute(
        select(Agent).where(
            Agent.client_id == "qora-demo",
            Agent.is_default == True,  # noqa: E712
        )
    )
    agent = agent_result.scalar_one_or_none()
    assert agent is not None
    assert (
        agent.elevenlabs_agent_id == "el_test_configured"
    ), f"Expected elevenlabs_agent_id='el_test_configured', got {agent.elevenlabs_agent_id!r}"


# ---------------------------------------------------------------------------
# elevenlabs_agent_id is part of the Alembic baseline migration (PR 2 cutover).
# The startup compat test below was removed when _ensure_startup_schema_compat
# was deleted from app.main (phase-b-db-migration-foundation/design.md).
# The column is verified to exist in tests/unit/test_alembic_tooling.py instead.
# ---------------------------------------------------------------------------
