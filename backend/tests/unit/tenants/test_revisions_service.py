"""Phase 2 (agent-config-revisions-routing) — Tasks 2.2/2.3: revisions_service.

Covers: create_revision (insert-only, monotonic), get_active_revision,
get_revision, list_revisions, activate_revision, rollback_to_revision.
Tenant isolation: every lookup function is scoped by client_id + agent_id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_FULL_CONFIG = {
    "schema_version": "v1",
    "system_prompt": "You are a helpful assistant.",
    "voice_id": "voice-abc123",
    "tts_model": "eleven_v4_turbo",
    "tts_speed": 0.95,
    "tts_stability": 0.4,
    "tts_similarity_boost": 0.75,
    "model": "gpt-4.1-mini",
    "temperature": 0.7,
    "max_tokens": 300,
    "tools_enabled": ["get_lead_details"],
}


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/revisions_service_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.engine.dispose()


async def _seed_two_agents(session: AsyncSession):
    """Seed quintana-seguros (1 agent) + a second distinct tenant for isolation tests."""
    from app.tenants.service import seed_quintana
    from tests.helpers.second_tenant import seed_second_tenant

    await seed_quintana(session)
    await seed_second_tenant(session)
    await session.commit()


async def test_create_revision_is_insert_only_and_monotonic(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.models import AgentConfigRevision
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    starting_count = len(
        (
            await session.execute(
                select(AgentConfigRevision).where(
                    AgentConfigRevision.agent_id == agent.id
                )
            )
        )
        .scalars()
        .all()
    )

    config = AgentConfigV1(**_FULL_CONFIG)
    rev_a = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    rev_b = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )

    assert rev_a.revision_number == starting_count + 1
    assert rev_b.revision_number == starting_count + 2

    result = await session.execute(
        select(AgentConfigRevision).where(AgentConfigRevision.agent_id == agent.id)
    )
    assert len(result.scalars().all()) == starting_count + 2


async def test_create_revision_monotonic_independent_across_agents(
    session: AsyncSession,
):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await resolve_single_active_agent(session, "quintana-seguros")
    agent_b = await resolve_single_active_agent(session, "acme-widgets")
    assert agent_a is not None and agent_b is not None

    config = AgentConfigV1(**_FULL_CONFIG)
    rev_a = await revisions_service.create_revision(
        session, agent=agent_a, config=config, source="api", created_by="tester"
    )
    rev_b = await revisions_service.create_revision(
        session, agent=agent_b, config=config, source="api", created_by="tester"
    )

    assert rev_a.agent_id == agent_a.id
    assert rev_b.agent_id == agent_b.id


async def test_rollback_creates_new_revision_not_reactivation(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None
    client_id = agent.client_id
    agent_id = agent.id

    revision_1 = await revisions_service.get_active_revision(session, client_id, agent_id)
    assert revision_1 is not None
    import json as _json

    original_revision_1_config = _json.loads(revision_1.config)

    config = AgentConfigV1(**_FULL_CONFIG)
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    revision_3 = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    assert agent.active_revision_id == revision_3.id

    new_revision = await revisions_service.rollback_to_revision(
        session, client_id, agent_id, revision_1.id, created_by="tester"
    )
    assert new_revision is not None
    assert new_revision.id != revision_1.id
    assert new_revision.revision_number == revision_3.revision_number + 1
    assert new_revision.source == "rollback"
    assert _json.loads(new_revision.config) == original_revision_1_config
    assert agent.active_revision_id == new_revision.id

    # revision_1's row is untouched
    untouched = await session.get(type(revision_1), revision_1.id)
    assert _json.loads(untouched.config) == original_revision_1_config
    assert untouched.revision_number == revision_1.revision_number
    assert untouched.source == revision_1.source


async def test_activate_revision_changes_only_the_pointer(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None
    client_id, agent_id = agent.client_id, agent.id

    revision_1 = await revisions_service.get_active_revision(session, client_id, agent_id)
    assert revision_1 is not None

    config = AgentConfigV1(**_FULL_CONFIG)
    revision_2 = await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    assert agent.active_revision_id == revision_2.id

    result = await revisions_service.activate_revision(
        session, client_id, agent_id, revision_1.id
    )
    assert result is not None
    assert agent.active_revision_id == revision_1.id

    # content unchanged for both revisions
    refreshed_1 = await session.get(type(revision_1), revision_1.id)
    refreshed_2 = await session.get(type(revision_2), revision_2.id)
    assert refreshed_1.config == revision_1.config
    assert refreshed_2.config == revision_2.config


async def test_list_revisions_returns_newest_first(session: AsyncSession):
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None
    client_id, agent_id = agent.client_id, agent.id

    config = AgentConfigV1(**_FULL_CONFIG)
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )
    await revisions_service.create_revision(
        session, agent=agent, config=config, source="api", created_by="tester"
    )

    revisions = await revisions_service.list_revisions(session, client_id, agent_id)
    numbers = [r.revision_number for r in revisions]
    assert numbers == sorted(numbers, reverse=True)
    assert len(numbers) >= 3


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_revision_of_another_agent_is_not_readable(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await resolve_single_active_agent(session, "quintana-seguros")
    agent_b = await resolve_single_active_agent(session, "acme-widgets")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    # Fetching agent_a's revision while scoped to agent_b's (client_id, agent_id) fails.
    leaked = await revisions_service.get_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id
    )
    assert leaked is None


async def test_revision_of_another_agent_is_not_activatable(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await resolve_single_active_agent(session, "quintana-seguros")
    agent_b = await resolve_single_active_agent(session, "acme-widgets")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    result = await revisions_service.activate_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id
    )
    assert result is None
    assert agent_b.active_revision_id != revision_a.id


async def test_rollback_across_tenant_boundary_is_rejected(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent_a = await resolve_single_active_agent(session, "quintana-seguros")
    agent_b = await resolve_single_active_agent(session, "acme-widgets")
    assert agent_a is not None and agent_b is not None

    revision_a = await revisions_service.get_active_revision(
        session, agent_a.client_id, agent_a.id
    )
    assert revision_a is not None

    result = await revisions_service.rollback_to_revision(
        session, agent_b.client_id, agent_b.id, revision_a.id, created_by="tester"
    )
    assert result is None


# ---------------------------------------------------------------------------
# agent-config-inheritance Task 3.3 — client-level revisions (generalized helpers)
# ---------------------------------------------------------------------------


async def test_create_client_revision_is_insert_only_and_monotonic(session: AsyncSession):
    from app.tenants.client_config_schema import ClientConfigV1
    from app.tenants.models import Client, ClientConfigRevision
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None

    starting_count = len(
        (
            await session.execute(
                select(ClientConfigRevision).where(
                    ClientConfigRevision.client_id == client.id
                )
            )
        )
        .scalars()
        .all()
    )

    config = ClientConfigV1(language="es")
    rev_a = await revisions_service.create_client_revision(
        session, client=client, config=config, source="api", created_by="tester"
    )
    rev_b = await revisions_service.create_client_revision(
        session, client=client, config=config, source="api", created_by="tester"
    )

    assert rev_a.revision_number == starting_count + 1
    assert rev_b.revision_number == starting_count + 2
    assert client.active_config_revision_id == rev_b.id

    result = await session.execute(
        select(ClientConfigRevision).where(ClientConfigRevision.client_id == client.id)
    )
    assert len(result.scalars().all()) == starting_count + 2


async def test_create_client_revision_content_is_sparse(session: AsyncSession):
    from app.tenants.client_config_schema import ClientConfigV1
    from app.tenants.models import Client
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None

    config = ClientConfigV1(language="es")
    revision = await revisions_service.create_client_revision(
        session, client=client, config=config, source="api", created_by="tester"
    )

    import json as _json

    stored = _json.loads(revision.config)
    assert stored == {"schema_version": "v1", "language": "es"}


async def test_client_rollback_creates_new_revision_not_reactivation(session: AsyncSession):
    from app.tenants.client_config_schema import ClientConfigV1
    from app.tenants.models import Client
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None
    client_id = client.id

    revision_1 = await revisions_service.create_client_revision(
        session,
        client=client,
        config=ClientConfigV1(language="es"),
        source="api",
        created_by="tester",
    )
    import json as _json

    original_revision_1_config = _json.loads(revision_1.config)

    config = ClientConfigV1(language="en")
    await revisions_service.create_client_revision(
        session, client=client, config=config, source="api", created_by="tester"
    )
    revision_3 = await revisions_service.create_client_revision(
        session, client=client, config=config, source="api", created_by="tester"
    )
    assert client.active_config_revision_id == revision_3.id

    new_revision = await revisions_service.rollback_client_revision(
        session, client_id, revision_1.id, created_by="tester"
    )
    assert new_revision is not None
    assert new_revision.id != revision_1.id
    assert new_revision.revision_number == revision_3.revision_number + 1
    assert new_revision.source == "rollback"
    assert _json.loads(new_revision.config) == original_revision_1_config
    assert client.active_config_revision_id == new_revision.id

    # revision_1's row is untouched
    untouched = await session.get(type(revision_1), revision_1.id)
    assert _json.loads(untouched.config) == original_revision_1_config
    assert untouched.revision_number == revision_1.revision_number
    assert untouched.source == revision_1.source


async def test_client_revision_of_another_client_is_not_readable(session: AsyncSession):
    from app.tenants.client_config_schema import ClientConfigV1
    from app.tenants.models import Client
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    client = await session.get(Client, "quintana-seguros")
    assert client is not None

    revision_a = await revisions_service.create_client_revision(
        session,
        client=client,
        config=ClientConfigV1(language="es"),
        source="api",
        created_by="tester",
    )

    leaked = await revisions_service.get_client_revision(
        session, "acme-widgets", revision_a.id
    )
    assert leaked is None


# ---------------------------------------------------------------------------
# agent-config-inheritance Phase 4 (D18) — AgentConfigV2 write validation +
# grandfathering (task 4.2)
# ---------------------------------------------------------------------------


async def test_create_revision_rejects_locked_field_write(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    with pytest.raises(revisions_service.AgentConfigWriteError) as exc_info:
        await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch={"end_call_tool_enabled": True},
            source="api",
            created_by="tester",
        )
    assert exc_info.value.fields == ["end_call_tool_enabled"]


async def test_create_revision_rejects_client_only_field_write(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    with pytest.raises(revisions_service.AgentConfigWriteError) as exc_info:
        await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch={"language": "es"},
            source="api",
            created_by="tester",
        )
    assert exc_info.value.fields == ["language"]


async def test_create_agent_revision_rejects_missing_required_field_for_new_agent(
    session: AsyncSession,
):
    from app.tenants.service import create_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await create_agent(
        session,
        client_id="quintana-seguros",
        slug="brand-new",
        name="Brand New",
        voice_id="voice-new",
    )

    with pytest.raises(revisions_service.AgentConfigWriteError) as exc_info:
        await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch={"system_prompt": "Hi"},
            source="api",
            created_by="tester",
            is_new_agent=True,
        )
    assert "goal" in exc_info.value.fields


async def test_grandfathered_agent_existing_revision_still_resolves(session: AsyncSession):
    """All seeded agents lack `goal` on their (V1) active revision — confirms
    the pre-existing active revision keeps resolving without being touched."""
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    active = await revisions_service.get_active_revision(
        session, agent.client_id, agent.id
    )
    assert active is not None
    import json as _json

    assert _json.loads(active.config).get("goal") is None


async def test_grandfathered_agent_can_write_revision_without_required_field(
    session: AsyncSession,
):
    """design.md D18: an existing agent that already lacked `goal` may keep
    writing revisions that omit it — the write is not blocked on that account.
    """
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    revision = await revisions_service.create_agent_config_revision(
        session,
        agent=agent,
        patch={"temperature": 0.33},
        source="api",
        created_by="tester",
    )
    import json as _json

    stored = _json.loads(revision.config)
    assert stored["temperature"] == 0.33
    assert "goal" not in stored
    assert revision.schema_version == "v2"


async def test_once_set_required_field_cannot_be_removed(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    await revisions_service.create_agent_config_revision(
        session,
        agent=agent,
        patch={"goal": "Book a demo."},
        source="api",
        created_by="tester",
    )

    with pytest.raises(revisions_service.AgentConfigWriteError) as exc_info:
        await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch={"goal": None},
            source="api",
            created_by="tester",
        )
    assert exc_info.value.fields == ["goal"]


async def test_v1_active_revision_is_promoted_to_v2_overrides_on_first_write(
    session: AsyncSession,
):
    """design.md D18: writing a V2 revision over a V1 active revision carries
    every non-None V1 value forward as an explicit override, so unrelated
    fields (e.g. tts_speed) are preserved even though the patch never touched
    them.
    """
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    previous = await revisions_service.get_active_revision(
        session, agent.client_id, agent.id
    )
    assert previous.schema_version == "v1"

    revision = await revisions_service.create_agent_config_revision(
        session,
        agent=agent,
        patch={"temperature": 0.5},
        source="api",
        created_by="tester",
    )
    import json as _json

    stored = _json.loads(revision.config)
    assert stored["temperature"] == 0.5
    assert stored["voice_id"] == agent.voice_id
    assert stored["tts_speed"] == agent.tts_speed
    assert "language" not in stored


async def test_patch_null_removes_an_existing_v2_override(session: AsyncSession):
    from app.tenants.service import resolve_single_active_agent
    from app.tenants import revisions_service

    await _seed_two_agents(session)
    agent = await resolve_single_active_agent(session, "quintana-seguros")
    assert agent is not None

    await revisions_service.create_agent_config_revision(
        session,
        agent=agent,
        patch={"first_message": "Hi there"},
        source="api",
        created_by="tester",
    )
    revision = await revisions_service.create_agent_config_revision(
        session,
        agent=agent,
        patch={"first_message": None},
        source="api",
        created_by="tester",
    )
    import json as _json

    stored = _json.loads(revision.config)
    assert "first_message" not in stored
