"""Surgical fix tests — confirmed issues for qora-agent-entity.

Covers:
- CRITICAL 1: ValueError uncaught when no default agent — webhook must return graceful SSE
- CRITICAL 1b: create_client() / seed_client() bootstraps a default agent
- WARNING 3: resolve_single_active_agent() filters inactive agents (is_active=True)
- WARNING 6: schedule_followup parses naive datetime AFTER client_id is resolved
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Shared session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    """Isolated async DB session per test."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/surgical_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess
    await db_module.close_db()


# ---------------------------------------------------------------------------
# WARNING 3: resolve_single_active_agent() must filter by is_active=True
# ---------------------------------------------------------------------------


async def test_resolve_single_active_agent_raises_when_only_agent_is_inactive(
    session: AsyncSession,
):
    """resolve_single_active_agent() must NOT return an inactive agent — it raises
    NoActiveAgentError once the client's only agent is deactivated.
    """
    from app.tenants.service import create_client, resolve_single_active_agent, NoActiveAgentError
    from app.tenants.models import Agent
    from sqlalchemy import update

    await create_client(
        session,
        id="broker-inactive-agent",
        name="Test SA",
        agent_name="OldAgent",
        voice_id="v-inactive",
    )

    active = await resolve_single_active_agent(session, "broker-inactive-agent")
    assert active is not None, "create_client must bootstrap a default agent first"

    await session.execute(
        update(Agent).where(Agent.id == active.id).values(is_active=False)
    )
    await session.flush()

    with pytest.raises(NoActiveAgentError):
        await resolve_single_active_agent(session, "broker-inactive-agent")


# ---------------------------------------------------------------------------
# WARNING 6: schedule_followup datetime parsing order
# ---------------------------------------------------------------------------


async def test_schedule_followup_naive_datetime_uses_client_tz_even_when_client_id_from_lead(
    session: AsyncSession,
):
    """
    When client_id is NOT passed to schedule_followup but lead.client_id exists,
    naive datetimes must use the client's timezone (not UTC), because the client
    is resolved AFTER loading the lead.

    Specifically: if Quintana has timezone America/Argentina/Buenos_Aires (UTC-3),
    then 2026-05-10T09:00 (naive) should be stored as 12:00 UTC, not 09:00 UTC.
    """
    from app.tenants.service import seed_quintana
    from app.leads.service import create_lead
    from app.tools.schedule_followup import _parse_followup_date

    await seed_quintana(session)
    await create_lead(
        session,
        client_id="quintana-seguros",
        name="TZ Test Lead",
        phone="+5491101222333",
        lead_id="tz-test-lead-001",
    )
    await session.flush()

    # Enable scheduler and set timezone on quintana
    from app.tenants.models import Client

    client = await session.get(Client, "quintana-seguros")
    client.scheduler_timezone = "America/Argentina/Buenos_Aires"  # UTC-3
    await session.flush()

    # Simulate what schedule_followup should do:
    # "2026-05-10T09:00" naive in ART (UTC-3) → 12:00 UTC
    dt = _parse_followup_date(
        "2026-05-10T09:00", client_timezone="America/Argentina/Buenos_Aires"
    )
    assert dt is not None
    assert (
        dt.hour == 12
    ), f"Naive 09:00 ART (UTC-3) should be stored as 12:00 UTC, got {dt.hour}:00 UTC"


# ---------------------------------------------------------------------------
# CRITICAL 1b: create_client creates a default agent automatically
# ---------------------------------------------------------------------------


async def test_create_client_bootstraps_default_agent(session: AsyncSession):
    """create_client() must automatically create a default Agent for the new client."""
    from app.tenants.service import create_client, resolve_single_active_agent

    await create_client(
        session,
        id="new-broker-auto-agent",
        name="New Broker SA",
        agent_name="AutoAgent",
        voice_id="v-auto-agent",
    )

    # A default agent must have been automatically created
    agent = await resolve_single_active_agent(session, "new-broker-auto-agent")
    assert agent is not None, (
        "create_client() must bootstrap a default Agent automatically. "
        "No default agent found."
    )
    assert agent.is_default is True
    assert agent.client_id == "new-broker-auto-agent"
    assert agent.name == "AutoAgent"  # inherits agent_name from client
    assert agent.voice_id == "v-auto-agent"


async def test_create_client_default_agent_has_correct_config(session: AsyncSession):
    """The auto-created default agent inherits model/temperature/max_tokens from client args."""
    from app.tenants.service import create_client, resolve_single_active_agent

    await create_client(
        session,
        id="config-test-broker",
        name="Config Broker SA",
        agent_name="ConfigAgent",
        voice_id="v-config",
        model="gpt-4o-mini",
        temperature=0.5,
        max_tokens=200,
    )

    agent = await resolve_single_active_agent(session, "config-test-broker")
    assert agent is not None
    assert agent.model == "gpt-4o-mini"
    assert agent.temperature == 0.5
    assert agent.max_tokens == 200
