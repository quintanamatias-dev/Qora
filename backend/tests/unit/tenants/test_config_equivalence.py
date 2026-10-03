"""Phase 5.1 (agent-config-inheritance) — equivalence test (hard acceptance
criterion, design.md D19).

materialize_agent_config() must leave every Agent.* config column unchanged
for every agent seeded/created today, EXCEPT the THREE documented exceptions
below (empirically verified against the current seed_quintana/create_agent
fixtures — this is deliberately wider than D19's original single
"voicemail_detection_enabled" example, which did not anticipate the other two):

  - voicemail_detection_enabled: NULL -> AgentConfigStandard.voicemail_detection_enabled
    (True), for agents that never had it set (jaumpablo, a plain create_agent()).
  - max_call_duration_seconds: NULL -> AgentConfigStandard.max_call_duration_seconds
    (120), same NULL-carrying agents.
  - system_prompt: changes for any agent whose active revision's agent-override
    system_prompt differs from the raw Agent.system_prompt column. Two cases:
      (a) a brand-new agent with no system_prompt at all: NULL -> "" (the
          AgentConfigV1/V2 empty-string coercion already used elsewhere).
      (b) jaumpablo: the Agent column holds the legacy DB-seed constant, but
          the active revision's agent-override captures
          _resolve_seed_system_prompt()'s filesystem-file content (design.md
          D6's "filesystem wins over the DB column" priority, which
          PromptLoader.render_for_agent() ALREADY applies at call time today).
          Materializing therefore does not change runtime behavior — it makes
          the column match what render_for_agent() already serves.

Every other mirrored column must be unchanged (tools_enabled is compared as
a decoded list — see materialize.snapshot_mirrored_fields — since JSON
dumps separator formatting differs for an identical list value) for every
agent produced by seed_quintana and a plain tenant_service.create_agent() call.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr

from app.tenants.materialize import MIRRORED_AGENT_FIELDS, snapshot_mirrored_fields

# design.md D19's documented behavioral deltas (see module docstring). Any
# OTHER difference fails the test below — this list is exhaustive, not
# illustrative.
_DOCUMENTED_EXCEPTIONS = {
    "voicemail_detection_enabled",
    "max_call_duration_seconds",
    "system_prompt",
}
_NULL_TO_STANDARD_EXCEPTIONS = {"voicemail_detection_enabled", "max_call_duration_seconds"}


@pytest_asyncio.fixture
async def equivalence_db(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/equivalence_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_agent, seed_quintana

        await seed_quintana(session)
        # Plain create_agent() call, per task 5.1's "+ a plain create_agent".
        await create_agent(
            session,
            client_id="quintana-seguros",
            slug="plain-created-agent",
            name="Plain Created Agent",
            voice_id="v-plain",
            goal="plain goal",
        )
        await session.commit()

    yield db_module
    await db_module.close_db()


async def test_effective_config_unchanged_for_every_existing_agent(equivalence_db):
    from app.tenants.materialize import materialize_agent_config
    from app.tenants.service import list_agents_for_client

    async with equivalence_db.async_session_factory() as session:
        agents = []
        for client_id in ("quintana-seguros",):
            agents.extend(await list_agents_for_client(session, client_id))
        assert len(agents) >= 2, "expected seed_quintana + plain create_agent"

        for agent in agents:
            before = snapshot_mirrored_fields(agent)
            await materialize_agent_config(session, agent)
            after = snapshot_mirrored_fields(agent)

            diffs = {
                field
                for field in MIRRORED_AGENT_FIELDS
                if before[field] != after[field]
            }
            unexpected = diffs - _DOCUMENTED_EXCEPTIONS
            assert not unexpected, (
                f"agent {agent.slug!r} ({agent.client_id!r}): unexpected column "
                f"change(s) {sorted(unexpected)} not in the documented exception "
                f"list {sorted(_DOCUMENTED_EXCEPTIONS)}. before={before} after={after}"
            )
            for field in diffs & _NULL_TO_STANDARD_EXCEPTIONS:
                assert before[field] is None, (
                    f"agent {agent.slug!r}: documented exception {field!r} changed "
                    f"from a non-NULL value {before[field]!r} — only a NULL-> "
                    "standard transition is an allowed exception for this field."
                )

        await session.commit()


async def test_documented_exceptions_actually_occur(equivalence_db):
    """Guard against the exception list silently going stale: at least one
    seeded agent must actually exercise each documented exception, so a
    future seeder change that makes these fields match is caught here
    instead of letting the exception list become dead code.
    """
    from app.tenants.materialize import materialize_agent_config
    from app.tenants.service import list_agents_for_client

    observed: set[str] = set()
    async with equivalence_db.async_session_factory() as session:
        agents = []
        for client_id in ("quintana-seguros",):
            agents.extend(await list_agents_for_client(session, client_id))

        for agent in agents:
            before = snapshot_mirrored_fields(agent)
            await materialize_agent_config(session, agent)
            after = snapshot_mirrored_fields(agent)
            observed |= {
                field
                for field in MIRRORED_AGENT_FIELDS
                if before[field] != after[field]
            }

    assert observed == _DOCUMENTED_EXCEPTIONS, (
        f"observed exceptions {sorted(observed)} no longer match the documented "
        f"list {sorted(_DOCUMENTED_EXCEPTIONS)} — update this test's module "
        "docstring together with the exception set if the seeded fixtures changed."
    )
