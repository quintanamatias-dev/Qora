"""Unit tests for agent_id propagation in call session service.

Covers:
- create_session() with explicit agent_id stores it on CallSession
- create_session() without agent_id resolves the client's sole active agent
  (agent-config-revisions-routing D2 fail-closed resolution, not is_default)
- create_session() without agent_id raises when the client has zero active
  agents, or more than one (ambiguous) — never a silent pick
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """DB with quintana client + one lead + default agent pre-loaded."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agent_calls_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Agent Test Lead",
            phone="+5491100222333",
            lead_id="agent-test-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_session_with_explicit_agent_id(seeded_db):
    """create_session() with explicit agent_id stores it on CallSession."""
    from app.calls.service import create_session
    from app.tenants.service import resolve_single_active_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await resolve_single_active_agent(sess, "quintana-seguros")
        assert agent is not None, "seed_quintana must create a default agent"
        agent_id = agent.id

    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="agent-test-lead-001",
            agent_id=agent_id,
        )
        await sess.commit()

    assert cs.agent_id == agent_id


async def test_create_session_without_agent_id_resolves_default(seeded_db):
    """create_session() without agent_id auto-resolves to the client's default agent."""
    from app.calls.service import create_session
    from app.tenants.service import resolve_single_active_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await resolve_single_active_agent(sess, "quintana-seguros")
        expected_agent_id = agent.id

    async with seeded_db.async_session_factory() as sess:
        # No agent_id passed — must resolve to default
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="agent-test-lead-001",
        )
        await sess.commit()

    assert cs.agent_id == expected_agent_id


async def test_create_session_no_active_agent_raises(tmp_path: Path):
    """create_session() without agent_id raises when the client has zero active agents.

    This simulates a pre-migration client that has no active agent, or a client whose
    only agent was deactivated. We force this by deactivating the auto-created
    agent before attempting create_session().
    """
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.core import database as db_module
    from sqlalchemy import update

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/no_agent_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import create_client, resolve_single_active_agent
        from app.leads.service import create_lead
        from app.tenants.models import Agent

        await create_client(
            sess,
            id="no-agent-client",
            name="No Agent",
            agent_name="Ghost",
            voice_id="v-ghost",
        )
        await create_lead(
            sess,
            client_id="no-agent-client",
            name="Ghost Lead",
            phone="+5491100000011",
            lead_id="ghost-lead-001",
        )

        # Deactivate the auto-created agent to simulate "zero active agents"
        default_agent = await resolve_single_active_agent(sess, "no-agent-client")
        assert default_agent is not None
        await sess.execute(
            update(Agent).where(Agent.id == default_agent.id).values(is_active=False)
        )

        await sess.commit()

    async with db_module.async_session_factory() as sess:
        from app.calls.service import create_session
        from app.tenants.service import NoActiveAgentError

        with pytest.raises(NoActiveAgentError):
            await create_session(
                sess,
                client_id="no-agent-client",
                lead_id="ghost-lead-001",
            )

    await db_module.close_db()


async def test_create_session_without_agent_id_fails_closed_for_multi_agent_client(
    seeded_db,
):
    """create_session() without agent_id raises when the client has 2+ active agents.

    Never silently picks one — agent-routing spec "Explicit Agent Identification
    on Every Call-Creating Path" scenario.
    """
    from app.calls.service import create_session
    from app.tenants.service import AmbiguousAgentError, create_agent

    async with seeded_db.async_session_factory() as sess:
        await create_agent(
            sess,
            client_id="quintana-seguros",
            slug="second-agent",
            name="Second",
            voice_id="v-second",
        )
        await sess.commit()

    async with seeded_db.async_session_factory() as sess:
        with pytest.raises(AmbiguousAgentError):
            await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="agent-test-lead-001",
            )


async def test_create_session_records_agent_config_revision_id(seeded_db):
    """create_session() stamps agent_config_revision_id from the resolved agent's
    active_revision_id (agent-config-revisions-routing D4).
    """
    from app.calls.service import create_session
    from app.tenants.service import resolve_single_active_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await resolve_single_active_agent(sess, "quintana-seguros")
        assert agent.active_revision_id is not None, (
            "seed_quintana must activate a revision for every seeded agent"
        )
        expected_revision_id = agent.active_revision_id
        agent_id = agent.id

    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="agent-test-lead-001",
            agent_id=agent_id,
        )
        await sess.commit()

    assert cs.agent_config_revision_id == expected_revision_id


async def test_create_session_without_agent_id_records_resolved_revision(seeded_db):
    """create_session() without agent_id stamps the AUTO-RESOLVED agent's revision."""
    from app.calls.service import create_session
    from app.tenants.service import resolve_single_active_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await resolve_single_active_agent(sess, "quintana-seguros")
        expected_revision_id = agent.active_revision_id

    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="agent-test-lead-001",
        )
        await sess.commit()

    assert cs.agent_config_revision_id == expected_revision_id
