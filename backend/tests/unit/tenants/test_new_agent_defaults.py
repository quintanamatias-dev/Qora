"""Phase 0 (agent-config-revisions-routing) — new-agent defaults.

Covers task 0.1: Agent.model / Agent.tts_model defaults and the AgentCreate
schema defaults must match the production standard confirmed in
agent-config-inheritance/design.md D17 (model=gpt-4.1-mini,
tts_model=eleven_v4_turbo), while existing rows stay untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    """Provide an isolated async session backed by the real migration chain."""
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/new_agent_defaults_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as session:
        yield session

    await db_module.engine.dispose()


async def test_new_agent_defaults_match_production_standard(session: AsyncSession):
    """A new agent created without model/tts_model gets the production standard."""
    from app.tenants.service import create_client, resolve_single_active_agent

    await create_client(
        session,
        id="defaults-check",
        name="Defaults Check",
        voice_id="voice-xyz",
    )

    agent = await resolve_single_active_agent(session, "defaults-check")
    assert agent is not None
    assert agent.model == "gpt-4.1-mini"
    assert agent.tts_model == "eleven_v4_turbo"


def test_agent_create_schema_defaults_match_production_standard():
    """AgentCreate's model/tts_model defaults match the production standard."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(slug="main-agent", name="Main Agent", voice_id="voice-123")

    assert agent.model == "gpt-4.1-mini"
    assert agent.tts_model == "eleven_v4_turbo"
