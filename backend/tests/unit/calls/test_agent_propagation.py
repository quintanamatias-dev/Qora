"""Unit tests for agent_id propagation in call session service — Phase 7 (Task 3.1 RED).

Covers:
- create_session() with explicit agent_id stores it on CallSession
- create_session() without agent_id resolves to default agent for client
- create_session() without agent_id and no default agent raises ValueError
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
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Agent Test Lead",
            phone="+5411222333",
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
    from app.tenants.service import get_default_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
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
    from app.tenants.service import get_default_agent

    async with seeded_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
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


async def test_create_session_no_default_agent_raises(tmp_path: Path):
    """create_session() without agent_id raises ValueError when client has no active default agent.

    This simulates a pre-migration client that has no default agent, or a client whose
    only default agent was deactivated. We force this by deactivating the auto-created
    default agent before attempting create_session().
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
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import create_client, get_default_agent
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
            phone="+549000000",
            lead_id="ghost-lead-001",
        )

        # Deactivate the auto-created default agent to simulate "no default agent"
        default_agent = await get_default_agent(sess, "no-agent-client")
        assert default_agent is not None
        await sess.execute(
            update(Agent).where(Agent.id == default_agent.id).values(is_active=False)
        )

        await sess.commit()

    async with db_module.async_session_factory() as sess:
        from app.calls.service import create_session

        with pytest.raises(ValueError, match="default agent"):
            await create_session(
                sess,
                client_id="no-agent-client",
                lead_id="ghost-lead-001",
            )

    await db_module.close_db()
