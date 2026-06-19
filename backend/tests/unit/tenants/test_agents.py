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
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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
        name=f"{client_id} SA",
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
        "id",
        "client_id",
        "slug",
        "name",
        "voice_id",
        "system_prompt",
        "knowledge_base",
        "model",
        "temperature",
        "max_tokens",
        "tools_enabled",
        "is_active",
        "is_default",
        "created_at",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


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
    """create_client() auto-creates a default agent; the agent has is_default=True."""
    from app.tenants.service import get_default_agent

    await _make_client(session, "broker-default-flag")

    # create_client() now auto-bootstraps the default agent
    agent = await get_default_agent(session, "broker-default-flag")
    assert agent is not None
    assert agent.is_default is True


async def test_duplicate_default_raises(session: AsyncSession):
    """Creating a second is_default=True agent for the same client raises ValueError.

    create_client() auto-creates the first default agent; attempting to create
    a second one must raise ValueError.
    """
    from app.tenants.service import create_agent

    await _make_client(session, "broker-dup-test")
    # _make_client → create_client already created a default agent

    # Attempt to add a second default — must raise
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
    """Two different clients may each have their own is_default=True agent.

    create_client() auto-bootstraps a default agent per client.
    """
    from app.tenants.service import get_default_agent

    await _make_client(session, "broker-alpha")
    await _make_client(session, "broker-beta")

    agent_a = await get_default_agent(session, "broker-alpha")
    agent_b = await get_default_agent(session, "broker-beta")

    assert agent_a is not None
    assert agent_b is not None
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
    """get_default_agent(session, client_id) returns the is_default=True agent.

    create_client() auto-creates the default agent. Additional non-default agents
    must not interfere with get_default_agent().
    """
    from app.tenants.service import create_agent, get_default_agent

    await _make_client(session, "broker-dflt")

    # Auto-created default agent exists — fetch it
    auto_default = await get_default_agent(session, "broker-dflt")
    assert auto_default is not None

    # Add a non-default agent — must not change the result
    non_default = await create_agent(
        session,
        client_id="broker-dflt",
        slug="non-default",
        name="Non Default",
        voice_id="v-nd",
        is_default=False,
    )

    result = await get_default_agent(session, "broker-dflt")
    assert result is not None
    assert result.id == auto_default.id
    assert result.is_default is True
    # Make sure the non-default was NOT returned
    assert result.id != non_default.id


async def test_get_default_agent_returns_none_when_no_default(session: AsyncSession):
    """get_default_agent() returns None when no active agent has is_default=True.

    We deactivate the auto-created default agent then add only a non-default one
    to confirm the query returns None.
    """
    from app.tenants.service import create_agent, get_default_agent
    from app.tenants.models import Agent
    from sqlalchemy import update

    await _make_client(session, "broker-no-default")

    # Deactivate the auto-created default agent (simulate it being disabled)
    auto_default = await get_default_agent(session, "broker-no-default")
    assert auto_default is not None
    await session.execute(
        update(Agent).where(Agent.id == auto_default.id).values(is_active=False)
    )
    await session.flush()

    # Add a non-default agent — should not affect the result
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


# ---------------------------------------------------------------------------
# Tasks 1.1–1.3 (RED) — Quintana DB-backed prompt/knowledge seed
# ---------------------------------------------------------------------------


async def test_seed_quintana_sets_system_prompt_and_knowledge(session: AsyncSession):
    """seed_quintana() creates a default agent with non-empty system_prompt and knowledge_base.

    Spec scenario: Quintana default agent has no prompt or knowledge.
    After seed_quintana() runs, both fields must be non-empty strings (DB source of truth).
    """
    from app.tenants.service import seed_quintana, get_default_agent

    await seed_quintana(session)

    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None
    assert agent.system_prompt is not None
    assert len(agent.system_prompt) > 0, "system_prompt must be non-empty after seed"
    assert agent.knowledge_base is not None
    assert len(agent.knowledge_base) > 0, "knowledge_base must be non-empty after seed"


async def test_seed_quintana_does_not_overwrite_existing_prompt(session: AsyncSession):
    """seed_quintana() called a second time does NOT overwrite existing non-empty values.

    Spec scenario: Quintana default agent already has non-empty DB config.
    The existing system_prompt and knowledge_base must remain unchanged after re-seed.
    """
    from app.tenants.service import seed_quintana, get_default_agent

    # First seed — populates the fields
    await seed_quintana(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None

    # Simulate an admin UI edit: overwrite with custom values
    custom_prompt = "CUSTOM PROMPT — must not be overwritten"
    custom_knowledge = "CUSTOM KNOWLEDGE — must not be overwritten"
    agent.system_prompt = custom_prompt
    agent.knowledge_base = custom_knowledge
    await session.flush()

    # Second seed — must NOT overwrite the custom values
    await seed_quintana(session)
    agent_after = await get_default_agent(session, "quintana-seguros")
    assert agent_after is not None
    assert (
        agent_after.system_prompt == custom_prompt
    ), "seed_quintana() must not overwrite non-empty system_prompt"
    assert (
        agent_after.knowledge_base == custom_knowledge
    ), "seed_quintana() must not overwrite non-empty knowledge_base"


async def test_seed_quintana_populates_partial_missing_knowledge(session: AsyncSession):
    """seed_quintana() fills empty knowledge_base when system_prompt is already set.

    Spec scenario: Quintana default agent has partial config (only prompt set).
    system_prompt remains unchanged; empty knowledge_base gets populated.
    """
    from app.tenants.service import seed_quintana, get_default_agent

    # First seed — populates both fields
    await seed_quintana(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None

    # Simulate a partial state: keep system_prompt, clear knowledge_base
    original_prompt = agent.system_prompt
    agent.knowledge_base = None
    await session.flush()

    # Second seed — must preserve system_prompt and repopulate knowledge_base
    await seed_quintana(session)
    agent_after = await get_default_agent(session, "quintana-seguros")
    assert agent_after is not None
    assert (
        agent_after.system_prompt == original_prompt
    ), "seed_quintana() must not overwrite non-empty system_prompt"
    assert agent_after.knowledge_base is not None
    assert (
        len(agent_after.knowledge_base) > 0
    ), "seed_quintana() must repopulate empty knowledge_base"


async def test_seed_quintana_treats_empty_string_prompt_as_missing(
    session: AsyncSession,
):
    """seed_quintana() treats system_prompt='' as missing and populates it.

    Spec scenario: Quintana default agent has system_prompt='' and knowledge_base=''.
    Empty-string fields MUST be treated as missing — both get populated on re-seed.
    """
    from app.tenants.service import seed_quintana, get_default_agent

    # First seed — creates the client + agent with populated fields
    await seed_quintana(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None

    # Simulate empty-string state (e.g., admin cleared the fields to "")
    agent.system_prompt = ""
    agent.knowledge_base = ""
    await session.flush()

    # Second seed — empty strings must be treated as missing and populated
    await seed_quintana(session)
    agent_after = await get_default_agent(session, "quintana-seguros")
    assert agent_after is not None
    assert (
        len(agent_after.system_prompt) > 0
    ), "seed_quintana() must populate system_prompt when it is an empty string"
    assert (
        len(agent_after.knowledge_base) > 0
    ), "seed_quintana() must populate knowledge_base when it is an empty string"


async def test_seed_quintana_treats_empty_string_knowledge_as_missing(
    session: AsyncSession,
):
    """seed_quintana() treats knowledge_base='' as missing while preserving non-empty prompt.

    Spec scenario: Quintana default agent has a custom system_prompt but knowledge_base=''.
    The empty knowledge_base MUST be populated; the custom prompt must NOT be overwritten.
    """
    from app.tenants.service import seed_quintana, get_default_agent

    # First seed — creates the client + agent with populated fields
    await seed_quintana(session)
    agent = await get_default_agent(session, "quintana-seguros")
    assert agent is not None

    # Simulate partial state: custom non-empty prompt, but knowledge cleared to ""
    custom_prompt = "CUSTOM PROMPT — must not be overwritten"
    agent.system_prompt = custom_prompt
    agent.knowledge_base = ""
    await session.flush()

    # Second seed — must preserve prompt and repopulate empty-string knowledge
    await seed_quintana(session)
    agent_after = await get_default_agent(session, "quintana-seguros")
    assert agent_after is not None
    assert (
        agent_after.system_prompt == custom_prompt
    ), "seed_quintana() must not overwrite non-empty system_prompt"
    assert (
        len(agent_after.knowledge_base) > 0
    ), "seed_quintana() must populate knowledge_base when it is an empty string"


# ---------------------------------------------------------------------------
# CRITICAL 1: Agent.slug unique per client — DB constraint + service validation
# ---------------------------------------------------------------------------


async def test_agent_table_has_unique_constraint_on_client_id_slug():
    """Agent.__table_args__ contains a UniqueConstraint on (client_id, slug)."""
    from sqlalchemy import UniqueConstraint
    from app.tenants.models import Agent

    args = Agent.__table_args__
    unique_constraints = [a for a in args if isinstance(a, UniqueConstraint)]
    # At least one UniqueConstraint should cover (client_id, slug)
    found = any(
        set(uc.columns.keys()) == {"client_id", "slug"} for uc in unique_constraints
    )
    assert found, (
        f"No UniqueConstraint on (client_id, slug) found. " f"table_args={args}"
    )


async def test_duplicate_slug_same_client_raises_on_create(session: AsyncSession):
    """create_agent() raises ValueError when slug already exists for the same client."""
    from app.tenants.service import create_agent

    await _make_client(session, "broker-slug-dup")

    # First agent with slug "sales-bot" — OK
    await create_agent(
        session,
        client_id="broker-slug-dup",
        slug="sales-bot",
        name="Sales Bot v1",
        voice_id="v-sales-1",
    )

    # Second agent with the same slug for the same client — must raise
    with pytest.raises(ValueError, match="slug"):
        await create_agent(
            session,
            client_id="broker-slug-dup",
            slug="sales-bot",
            name="Sales Bot v2",
            voice_id="v-sales-2",
        )


async def test_same_slug_different_clients_is_allowed(session: AsyncSession):
    """The same slug may be used across different clients without error."""
    from app.tenants.service import create_agent

    await _make_client(session, "client-one")
    await _make_client(session, "client-two")

    agent_1 = await create_agent(
        session,
        client_id="client-one",
        slug="advisor",
        name="Advisor for One",
        voice_id="v-one",
    )
    agent_2 = await create_agent(
        session,
        client_id="client-two",
        slug="advisor",
        name="Advisor for Two",
        voice_id="v-two",
    )

    assert agent_1.slug == "advisor"
    assert agent_2.slug == "advisor"
    assert agent_1.client_id != agent_2.client_id


# ---------------------------------------------------------------------------
# Task 2.1 (RED) — ElevenLabs soft timeout columns on Agent model
# Spec: sdd/elevenlabs-provisioning — Agent Model Soft Timeout Columns requirement
# ---------------------------------------------------------------------------


async def test_agent_model_has_soft_timeout_columns():
    """Agent model exposes the 5 new nullable ElevenLabs soft timeout columns.

    Spec: soft_timeout_seconds, soft_timeout_message, soft_timeout_use_llm,
          elevenlabs_sync_status, elevenlabs_last_synced_at — all nullable, DEFAULT NULL.
    """
    from app.tenants.models import Agent

    col_names = {c.name for c in Agent.__table__.columns}
    expected_new_cols = {
        "soft_timeout_seconds",
        "soft_timeout_message",
        "soft_timeout_use_llm",
        "elevenlabs_sync_status",
        "elevenlabs_last_synced_at",
    }
    assert expected_new_cols.issubset(col_names), (
        f"Missing soft timeout columns: {expected_new_cols - col_names}"
    )


async def test_agent_soft_timeout_columns_default_to_none(session: AsyncSession):
    """New soft timeout columns default to None on agent creation.

    Spec: NULL values = 'use ElevenLabs dashboard defaults' — no PATCH is sent.
    Existing agents with all new columns NULL must behave identically to before.
    """
    from app.tenants.service import create_agent

    await _make_client(session, "broker-soft-timeout")

    agent = await create_agent(
        session,
        client_id="broker-soft-timeout",
        slug="default-timeouts",
        name="Default Timeouts Agent",
        voice_id="voice-x1",
    )

    assert agent.soft_timeout_seconds is None
    assert agent.soft_timeout_message is None
    assert agent.soft_timeout_use_llm is None
    assert agent.elevenlabs_sync_status is None
    assert agent.elevenlabs_last_synced_at is None


async def test_agent_soft_timeout_columns_nullable_type():
    """Soft timeout columns are nullable (no NOT NULL constraint).

    Triangulation: verify Python type annotations allow None for all 5 columns.
    """
    from app.tenants.models import Agent

    # Each column must be nullable (nullable=True in SQLAlchemy)
    col_map = {c.name: c for c in Agent.__table__.columns}
    for col_name in [
        "soft_timeout_seconds",
        "soft_timeout_message",
        "soft_timeout_use_llm",
        "elevenlabs_sync_status",
        "elevenlabs_last_synced_at",
    ]:
        col = col_map[col_name]
        assert col.nullable is True, (
            f"Column {col_name!r} must be nullable, got nullable={col.nullable}"
        )
