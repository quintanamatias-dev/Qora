"""Unit tests for Agent entity model — Phase 7 (Task 1.1 RED).

Covers:
- Agent model defaults (slug, name, voice_id, model, temperature, max_tokens, tools_enabled)
- Duplicate is_default=True for same client raises validation error
- get_agent(session, agent_id) returns the matching Agent
- get_default_agent(session, client_id) returns the is_default=True agent
- get_default_agent returns None when no default exists
- seed_quintana creates default Agent alongside Client
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agents_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Helper: create a client for tests
# ---------------------------------------------------------------------------


async def _make_client(session: AsyncSession, client_id: str = "test-broker") -> object:
    """Create a minimal Client record for agent tests."""
    from app.tenants.service import create_client

    return await create_client(
        session,
        id=client_id,
        name=f"Test Broker {client_id}",
        broker_name="Test Broker SA",
        agent_name="TestAgent",
        voice_id="voice-abc123",
    )


# ---------------------------------------------------------------------------
# Task 1.1 — Agent model defaults
# ---------------------------------------------------------------------------


async def test_agent_model_has_expected_fields():
    """Agent model has all required fields with correct types."""
    from app.tenants.models import Agent

    # Check table name
    assert Agent.__tablename__ == "agents"

    # Check column names exist
    col_names = {c.name for c in Agent.__table__.columns}
    expected = {
        "id", "client_id", "slug", "name", "voice_id",
        "system_prompt", "knowledge_base", "model", "temperature",
        "max_tokens", "tools_enabled", "is_active", "is_default", "created_at",
    }
    assert expected.issubset(col_names), (
        f"Missing columns: {expected - col_names}"
    )


async def test_create_agent_with_defaults(session: AsyncSession):
    """create_agent() persists an Agent with correct defaults."""
    from app.tenants.service import create_agent

    client = await _make_client(session, "broker-defaults")

    agent = await create_agent(
        session,
        client_id=client.id,
        slug="default-agent",
        name="Default Agent",
        voice_id="voice-xyz",
    )

    assert agent.id is not None
    assert agent.client_id == client.id
    assert agent.slug == "default-agent"
    assert agent.name == "Default Agent"
    assert agent.voice_id == "voice-xyz"
    assert agent.model == "gpt-4o"
    assert agent.temperature == 0.7
    assert agent.max_tokens == 300
    assert agent.is_active is True
    assert agent.is_default is False  # not default unless explicitly set
    assert agent.system_prompt is None
    assert agent.knowledge_base is None


async def test_create_agent_as_default(session: AsyncSession):
    """create_agent() with is_default=True creates a default agent."""
    from app.tenants.service import create_agent

    await _make_client(session, "broker-default-flag")

    agent = await create_agent(
        session,
        client_id="broker-default-flag",
        slug="main-agent",
        name="Main Agent",
        voice_id="voice-main",
        is_default=True,
    )

    assert agent.is_default is True


async def test_duplicate_default_raises(session: AsyncSession):
    """Creating a second is_default=True agent for the same client raises ValueError."""
    from app.tenants.service import create_agent

    await _make_client(session, "broker-dup-test")

    # First default agent — OK
    await create_agent(
        session,
        client_id="broker-dup-test",
        slug="agent-one",
        name="Agent One",
        voice_id="voice-1",
        is_default=True,
    )

    # Second default agent for same client — must raise
    with pytest.raises(ValueError, match="default"):
        await create_agent(
            session,
            client_id="broker-dup-test",
            slug="agent-two",
            name="Agent Two",
            voice_id="voice-2",
            is_default=True,
        )


async def test_two_clients_can_each_have_default(session: AsyncSession):
    """Two different clients may each have their own is_default=True agent."""
    from app.tenants.service import create_agent

    await _make_client(session, "broker-alpha")
    await _make_client(session, "broker-beta")

    agent_a = await create_agent(
        session,
        client_id="broker-alpha",
        slug="agent-a",
        name="Agent A",
        voice_id="v-a",
        is_default=True,
    )

    agent_b = await create_agent(
        session,
        client_id="broker-beta",
        slug="agent-b",
        name="Agent B",
        voice_id="v-b",
        is_default=True,
    )

    assert agent_a.is_default is True
    assert agent_b.is_default is True
    assert agent_a.client_id == "broker-alpha"
    assert agent_b.client_id == "broker-beta"


# ---------------------------------------------------------------------------
# Task 1.1 — Agent resolution helpers
# ---------------------------------------------------------------------------


async def test_get_agent_returns_agent(session: AsyncSession):
    """get_agent(session, agent_id) returns the Agent with that id."""
    from app.tenants.service import create_agent, get_agent

    await _make_client(session, "broker-get")

    created = await create_agent(
        session,
        client_id="broker-get",
        slug="fetch-me",
        name="Fetch Me",
        voice_id="v-fetch",
    )

    fetched = await get_agent(session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Fetch Me"


async def test_get_agent_returns_none_for_missing(session: AsyncSession):
    """get_agent() returns None for unknown agent_id."""
    from app.tenants.service import get_agent

    result = await get_agent(session, "nonexistent-agent-id")
    assert result is None


async def test_get_default_agent_returns_default(session: AsyncSession):
    """get_default_agent(session, client_id) returns the is_default=True agent."""
    from app.tenants.service import create_agent, get_default_agent

    await _make_client(session, "broker-dflt")

    non_default = await create_agent(
        session,
        client_id="broker-dflt",
        slug="non-default",
        name="Non Default",
        voice_id="v-nd",
        is_default=False,
    )

    default_agent = await create_agent(
        session,
        client_id="broker-dflt",
        slug="is-default",
        name="Is Default",
        voice_id="v-d",
        is_default=True,
    )

    result = await get_default_agent(session, "broker-dflt")
    assert result is not None
    assert result.id == default_agent.id
    assert result.is_default is True
    # Make sure the non-default was NOT returned
    assert result.id != non_default.id


async def test_get_default_agent_returns_none_when_no_default(session: AsyncSession):
    """get_default_agent() returns None when no agent has is_default=True."""
    from app.tenants.service import create_agent, get_default_agent

    await _make_client(session, "broker-no-default")

    await create_agent(
        session,
        client_id="broker-no-default",
        slug="just-an-agent",
        name="Just An Agent",
        voice_id="v-1",
        is_default=False,
    )

    result = await get_default_agent(session, "broker-no-default")
    assert result is None


async def test_get_default_agent_returns_none_for_unknown_client(session: AsyncSession):
    """get_default_agent() returns None for a client_id with no agents."""
    from app.tenants.service import get_default_agent

    result = await get_default_agent(session, "ghost-client")
    assert result is None


# ---------------------------------------------------------------------------
# Task 1.1 — Seed creates default Agent
# ---------------------------------------------------------------------------


async def test_seed_quintana_creates_default_agent(session: AsyncSession):
    """seed_quintana() creates a Client AND a default Agent for that client."""
    from app.tenants.service import seed_quintana, get_default_agent

    await seed_quintana(session)

    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None
    assert agent.is_default is True
    assert agent.client_id == "quintana-seguros"
    assert agent.name == "Jaumpablo"
    assert agent.voice_id == "pNInz6obpgDQGcFmaJgB"
    assert agent.model == "gpt-4o"


async def test_seed_quintana_agent_is_idempotent(session: AsyncSession):
    """seed_quintana() called twice creates exactly one default Agent."""
    from app.tenants.service import seed_quintana
    from sqlalchemy import select
    from app.tenants.models import Agent

    await seed_quintana(session)
    await seed_quintana(session)  # second call — must not duplicate

    result = await session.execute(
        select(Agent).where(
            Agent.client_id == "quintana-seguros",
            Agent.is_default.is_(True),
        )
    )
    agents = result.scalars().all()
    assert len(agents) == 1


async def test_seed_demo_inmobiliaria_creates_default_agent(session: AsyncSession):
    """seed_demo_inmobiliaria() creates a default Agent for demo-inmobiliaria."""
    from app.tenants.service import seed_demo_inmobiliaria, get_default_agent

    await seed_demo_inmobiliaria(session)

    agent = await get_default_agent(session, "demo-inmobiliaria")
    assert agent is not None
    assert agent.is_default is True
    assert agent.name == "Valentina"
