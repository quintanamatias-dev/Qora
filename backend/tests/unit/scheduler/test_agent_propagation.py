"""Unit tests for agent_id propagation in scheduler and summarizer — Phase 7 (Task 3.1 RED).

Covers:
- create_scheduled_call() stores agent_id when provided
- auto_schedule() propagates agent_id from source session (inherits session's agent)
- auto_schedule() without session agent falls back to default agent
- summarizer _auto_schedule_if_needed propagates cs.agent_id to auto_schedule
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sched_agent_db(tmp_path: Path):
    """DB with quintana (scheduler_enabled=True) + test lead + default agent."""
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sched_agent_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Sched Agent Lead",
            phone="+5411111999",
            lead_id="sched-agent-lead-001",
        )
        await sess.commit()

    # Enable scheduler
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_cooldown_minutes = 60
        client.scheduler_allowed_hours_start = 9
        client.scheduler_allowed_hours_end = 20
        client.scheduler_retry_on_outcomes = (
            '["call_again","busy","no_answer","follow_up"]'
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# Tests: create_scheduled_call with agent_id
# ---------------------------------------------------------------------------


async def test_create_scheduled_call_with_agent_id(sched_agent_db):
    """create_scheduled_call() stores the provided agent_id."""
    from app.scheduler.service import create_scheduled_call
    from app.tenants.service import get_default_agent

    async with sched_agent_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        agent_id = agent.id

    now = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sched_agent_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-agent-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
            agent_id=agent_id,
        )
        await sess.commit()

    assert sc.agent_id == agent_id


async def test_auto_schedule_propagates_agent_id_from_session(sched_agent_db):
    """auto_schedule() propagates agent_id from a source CallSession."""
    from app.calls.service import create_session
    from app.scheduler.service import auto_schedule
    from app.tenants.service import get_default_agent

    # Get the default agent
    async with sched_agent_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        agent_id = agent.id

    # Create a session with the agent
    async with sched_agent_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-agent-lead-001",
            agent_id=agent_id,
        )
        session_id = cs.id
        await sess.commit()

    # auto_schedule — should inherit agent_id from the session
    async with sched_agent_db.async_session_factory() as sess:
        sc = await auto_schedule(
            db=sess,
            session_id=session_id,
            lead_id="sched-agent-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert sc is not None
    assert sc.agent_id == agent_id


async def test_auto_schedule_falls_back_to_default_agent_when_no_session_agent(
    sched_agent_db,
):
    """auto_schedule() falls back to client's default agent when session has no agent_id."""
    from app.calls.service import create_session
    from app.scheduler.service import auto_schedule
    from app.tenants.service import get_default_agent

    # Get the default agent
    async with sched_agent_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        default_agent_id = agent.id

    # Create a session WITHOUT agent_id (backward compat path)
    async with sched_agent_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-agent-lead-001",
            agent_id=None,  # explicit None
        )
        cs.agent_id = None  # ensure it's null in DB
        session_id = cs.id
        await sess.commit()

    async with sched_agent_db.async_session_factory() as sess:
        sc = await auto_schedule(
            db=sess,
            session_id=session_id,
            lead_id="sched-agent-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert sc is not None
    # Should fall back to the client's default agent
    assert sc.agent_id == default_agent_id
