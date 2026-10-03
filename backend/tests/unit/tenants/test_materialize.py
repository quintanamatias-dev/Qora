"""Phase 5 (agent-config-inheritance) — Task 5.1-5.3: materialize_agent_config
as the single derivation point for Agent.* config columns (design.md D19).
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


@pytest_asyncio.fixture
async def materialize_db(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/materialize_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana, seed_qora_demo

        await seed_quintana(session)
        await seed_qora_demo(session)
        await session.commit()

    yield db_module
    await db_module.close_db()


async def test_materialize_agent_config_stamps_standard_version(materialize_db):
    from app.tenants.materialize import materialize_agent_config
    from app.tenants.config_standard import STANDARD_VERSION
    from app.tenants.service import resolve_single_active_agent

    async with materialize_db.async_session_factory() as session:
        agent = await resolve_single_active_agent(session, "qora-demo")
        assert agent.materialized_standard_version is None

        await materialize_agent_config(session, agent)
        await session.commit()

        assert agent.materialized_standard_version == STANDARD_VERSION


async def test_materialize_agent_config_returns_effective_config(materialize_db):
    from app.tenants.materialize import materialize_agent_config
    from app.tenants.service import resolve_single_active_agent

    async with materialize_db.async_session_factory() as session:
        agent = await resolve_single_active_agent(session, "qora-demo")
        effective = await materialize_agent_config(session, agent)

        assert effective.fields["voice_id"].value == agent.voice_id
        assert effective.fields["model"].provenance == "agent"


async def test_materialize_agent_config_overridable_null_inherits_standard(
    materialize_db,
):
    """jaumpablo (quintana) never had voicemail_detection_enabled /
    max_call_duration_seconds set — materializing fills them from the
    standard (design.md D19's one documented behavioral delta vs. 1a).
    """
    from app.tenants.materialize import materialize_agent_config
    from app.tenants.config_standard import AgentConfigStandard
    from app.tenants.service import resolve_single_active_agent

    async with materialize_db.async_session_factory() as session:
        agent = await resolve_single_active_agent(session, "quintana-seguros")
        assert agent.voicemail_detection_enabled is None
        assert agent.max_call_duration_seconds is None

        await materialize_agent_config(session, agent)
        await session.commit()

        assert (
            agent.voicemail_detection_enabled
            == AgentConfigStandard.voicemail_detection_enabled
        )
        assert (
            agent.max_call_duration_seconds
            == AgentConfigStandard.max_call_duration_seconds
        )
