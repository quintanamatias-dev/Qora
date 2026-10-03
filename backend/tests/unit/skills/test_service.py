"""skill-packages (P4-D1/P4-D2/P4-D3) — Task 2.1/2.2: skills service.

Covers: create_skill_revision (insert-only), rollback_skill (creates a NEW
revision, never resurrects), resolve_agent_skills (Qora general + client
general + client agent-section, with agent > client-general > qora on slug
collision, dropped entries logged at WARNING), and AgentSkillsCache
(in-process cache keyed by agent_id, invalidated via invalidate_agent /
invalidate_client).
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/skills_service_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.engine.dispose()


async def _make_client_and_agent(session: AsyncSession, client_id: str, agent_slug: str):
    from app.tenants.models import Agent, Client

    client = Client(id=client_id, name=client_id, voice_id="v1")
    session.add(client)
    await session.flush()

    agent = Agent(client_id=client_id, slug=agent_slug, name=agent_slug, voice_id="v1")
    session.add(agent)
    await session.flush()
    return client, agent


async def _make_package(session: AsyncSession, *, owner_type: str, client_id: str | None, name: str):
    from app.tenants.models import SkillPackage

    package = SkillPackage(owner_type=owner_type, client_id=client_id, name=name)
    session.add(package)
    await session.flush()
    return package


async def _make_skill(
    session: AsyncSession,
    *,
    package_id: str,
    slug: str,
    section: str,
    agent_id: str | None = None,
):
    from app.tenants.models import Skill

    skill = Skill(package_id=package_id, slug=slug, section=section, agent_id=agent_id)
    session.add(skill)
    await session.flush()
    return skill


async def _seed_revision(
    session: AsyncSession,
    *,
    skill,
    content_md: str = "content",
    filler_text: str = "filler",
    trigger_hint: str = "hint",
    description: str = "desc",
):
    from app.skills.service import create_skill_revision

    return await create_skill_revision(
        session,
        skill=skill,
        content_md=content_md,
        filler_text=filler_text,
        trigger_hint=trigger_hint,
        description=description,
        source="import",
        created_by="tester",
    )


# ---------------------------------------------------------------------------
# create_skill_revision / rollback_skill (Task 2.1)
# ---------------------------------------------------------------------------


async def test_create_skill_revision_does_not_mutate_existing_rows(session: AsyncSession):
    from app.tenants.models import SkillRevision

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    package = await _make_package(session, owner_type="client", client_id="acme", name="acme skills")
    skill = await _make_skill(session, package_id=package.id, slug="pricing", section="agent", agent_id=agent.id)

    rev1 = await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()
    assert rev1.revision_number == 1
    assert skill.active_revision_id == rev1.id

    rev2 = await _seed_revision(session, skill=skill, content_md="v2")
    await session.commit()

    assert rev2.revision_number == 2
    assert skill.active_revision_id == rev2.id

    original = await session.get(SkillRevision, rev1.id)
    assert original is not None
    assert original.content_md == "v1"
    assert original.revision_number == 1

    result = await session.execute(select(SkillRevision).where(SkillRevision.skill_id == skill.id))
    assert len(result.scalars().all()) == 2


async def test_rollback_skill_creates_new_revision_not_resurrection(session: AsyncSession):
    from app.skills.service import rollback_skill

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    package = await _make_package(session, owner_type="client", client_id="acme", name="acme skills")
    skill = await _make_skill(session, package_id=package.id, slug="pricing", section="agent", agent_id=agent.id)

    rev1 = await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()
    await _seed_revision(session, skill=skill, content_md="v2")
    await session.commit()
    assert skill.active_revision_id != rev1.id

    rev3 = await rollback_skill(
        session, skill=skill, target_revision_id=rev1.id, created_by="tester"
    )
    await session.commit()

    assert rev3 is not None
    assert rev3.revision_number == 3
    assert rev3.source == "rollback"
    assert rev3.content_md == "v1"
    assert skill.active_revision_id == rev3.id
    assert skill.active_revision_id != rev1.id


# ---------------------------------------------------------------------------
# resolve_agent_skills (Task 2.2)
# ---------------------------------------------------------------------------


async def test_resolve_agent_skills_returns_qora_general_skills(session: AsyncSession):
    from app.skills.service import resolve_agent_skills

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="general-knowledge", section="general")
    await _seed_revision(session, skill=skill, content_md="qora content", description="qora desc")
    await session.commit()

    resolved = await resolve_agent_skills(session, agent)

    assert [e.name for e in resolved.entries] == ["general-knowledge"]
    assert resolved.entries[0].description == "qora desc"
    assert resolved.content_by_slug["general-knowledge"] == "qora content"


async def test_resolve_agent_skills_client_general_overrides_qora_on_slug_collision(
    session: AsyncSession,
):
    from app.skills.service import resolve_agent_skills

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")

    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    qora_skill = await _make_skill(session, package_id=qora_package.id, slug="pricing", section="general")
    await _seed_revision(session, skill=qora_skill, content_md="qora pricing")

    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")
    client_skill = await _make_skill(session, package_id=client_package.id, slug="pricing", section="general")
    await _seed_revision(session, skill=client_skill, content_md="acme pricing")
    await session.commit()

    resolved = await resolve_agent_skills(session, agent)

    assert len(resolved.entries) == 1
    assert resolved.content_by_slug["pricing"] == "acme pricing"


async def test_resolve_agent_skills_agent_section_overrides_both(session: AsyncSession):
    from app.skills.service import resolve_agent_skills

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")

    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    qora_skill = await _make_skill(session, package_id=qora_package.id, slug="pricing", section="general")
    await _seed_revision(session, skill=qora_skill, content_md="qora pricing")

    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")
    client_general_skill = await _make_skill(
        session, package_id=client_package.id, slug="pricing", section="general"
    )
    await _seed_revision(session, skill=client_general_skill, content_md="acme general pricing")

    agent_skill = await _make_skill(
        session, package_id=client_package.id, slug="pricing", section="agent", agent_id=agent.id
    )
    await _seed_revision(session, skill=agent_skill, content_md="agent-specific pricing")
    await session.commit()

    resolved = await resolve_agent_skills(session, agent)

    assert len(resolved.entries) == 1
    assert resolved.content_by_slug["pricing"] == "agent-specific pricing"


async def test_resolve_agent_skills_logs_warning_on_collision(session: AsyncSession, caplog):
    import logging

    from app.skills.service import resolve_agent_skills

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")

    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    qora_skill = await _make_skill(session, package_id=qora_package.id, slug="pricing", section="general")
    await _seed_revision(session, skill=qora_skill, content_md="qora pricing")

    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")
    client_skill = await _make_skill(session, package_id=client_package.id, slug="pricing", section="general")
    await _seed_revision(session, skill=client_skill, content_md="acme pricing")
    await session.commit()

    with caplog.at_level(logging.WARNING, logger="app.skills.service"):
        await resolve_agent_skills(session, agent)

    assert any("pricing" in record.message for record in caplog.records)


async def test_resolve_agent_skills_does_not_leak_other_agents_sections(session: AsyncSession):
    from app.skills.service import resolve_agent_skills

    _, agent_a = await _make_client_and_agent(session, "acme", "sales-agent")
    from app.tenants.models import Agent

    agent_b = Agent(client_id="acme", slug="support-agent", name="support-agent", voice_id="v1")
    session.add(agent_b)
    await session.flush()

    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")
    other_agent_skill = await _make_skill(
        session, package_id=client_package.id, slug="only-for-b", section="agent", agent_id=agent_b.id
    )
    await _seed_revision(session, skill=other_agent_skill, content_md="b content")
    await session.commit()

    resolved = await resolve_agent_skills(session, agent_a)

    assert resolved.entries == []


# ---------------------------------------------------------------------------
# AgentSkillsCache (Task 2.3)
# ---------------------------------------------------------------------------


async def test_agent_skills_cache_hit_skips_resolution(session: AsyncSession, monkeypatch):
    from app.skills import service as skills_service
    from app.skills.service import AgentSkillsCache

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="x", section="general")
    await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()

    call_count = {"n": 0}
    original_resolve = skills_service.resolve_agent_skills

    async def counting_resolve(sess, agt):
        call_count["n"] += 1
        return await original_resolve(sess, agt)

    monkeypatch.setattr(skills_service, "resolve_agent_skills", counting_resolve)

    cache = AgentSkillsCache()
    first = await cache.get(session, agent)
    second = await cache.get(session, agent)

    assert call_count["n"] == 1
    assert first.content_by_slug["x"] == "v1"
    assert second.content_by_slug["x"] == "v1"


async def test_agent_skills_cache_invalidate_agent_forces_re_resolution(session: AsyncSession):
    from app.skills.service import AgentSkillsCache, create_skill_revision

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="x", section="general")
    await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()

    cache = AgentSkillsCache()
    first = await cache.get(session, agent)
    assert first.content_by_slug["x"] == "v1"

    await create_skill_revision(
        session,
        skill=skill,
        content_md="v2",
        filler_text="filler",
        trigger_hint="hint",
        description="desc",
        source="api",
        created_by="tester",
    )
    await session.commit()

    # Without invalidation, cache still serves the stale entry.
    stale = await cache.get(session, agent)
    assert stale.content_by_slug["x"] == "v1"

    cache.invalidate_agent(agent.id)
    fresh = await cache.get(session, agent)
    assert fresh.content_by_slug["x"] == "v2"


async def test_agent_skills_cache_invalidate_client_clears_all_its_agents(session: AsyncSession):
    from app.skills.service import AgentSkillsCache, create_skill_revision

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="x", section="general")
    await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()

    cache = AgentSkillsCache()
    await cache.get(session, agent)

    await create_skill_revision(
        session,
        skill=skill,
        content_md="v2",
        filler_text="filler",
        trigger_hint="hint",
        description="desc",
        source="api",
        created_by="tester",
    )
    await session.commit()

    cache.invalidate_client("acme")
    fresh = await cache.get(session, agent)
    assert fresh.content_by_slug["x"] == "v2"


async def test_agent_skills_cache_invalidate_all_clears_every_agent(session: AsyncSession):
    from app.skills.service import AgentSkillsCache, create_skill_revision

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="x", section="general")
    await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()

    cache = AgentSkillsCache()
    await cache.get(session, agent)

    await create_skill_revision(
        session,
        skill=skill,
        content_md="v2",
        filler_text="filler",
        trigger_hint="hint",
        description="desc",
        source="api",
        created_by="tester",
    )
    await session.commit()

    cache.invalidate_all()
    fresh = await cache.get(session, agent)
    assert fresh.content_by_slug["x"] == "v2"


# ---------------------------------------------------------------------------
# resolve_agent_skills_with_origin (Task 4 — API-facing origin/revision info)
# ---------------------------------------------------------------------------


async def test_resolve_agent_skills_with_origin_reports_qora_origin(session: AsyncSession):
    from app.skills.service import resolve_agent_skills_with_origin

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    qora_package = await _make_package(session, owner_type="qora", client_id=None, name="qora")
    skill = await _make_skill(session, package_id=qora_package.id, slug="general-knowledge", section="general")
    await _seed_revision(session, skill=skill, content_md="qora content")
    await session.commit()

    details = await resolve_agent_skills_with_origin(session, agent)

    assert len(details) == 1
    assert details[0].slug == "general-knowledge"
    assert details[0].origin == "qora"
    assert details[0].active_revision_number == 1


async def test_resolve_agent_skills_with_origin_reports_client_general_and_agent_origins(
    session: AsyncSession,
):
    from app.skills.service import resolve_agent_skills_with_origin

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")

    general_skill = await _make_skill(
        session, package_id=client_package.id, slug="hours", section="general"
    )
    await _seed_revision(session, skill=general_skill, content_md="hours content")

    agent_skill = await _make_skill(
        session, package_id=client_package.id, slug="pricing", section="agent", agent_id=agent.id
    )
    await _seed_revision(session, skill=agent_skill, content_md="pricing content")
    await session.commit()

    details = await resolve_agent_skills_with_origin(session, agent)

    by_slug = {d.slug: d for d in details}
    assert by_slug["hours"].origin == "client_general"
    assert by_slug["pricing"].origin == "agent"


async def test_resolve_agent_skills_with_origin_reflects_latest_revision_number(
    session: AsyncSession,
):
    from app.skills.service import resolve_agent_skills_with_origin

    _, agent = await _make_client_and_agent(session, "acme", "sales-agent")
    client_package = await _make_package(session, owner_type="client", client_id="acme", name="acme")
    skill = await _make_skill(
        session, package_id=client_package.id, slug="pricing", section="agent", agent_id=agent.id
    )
    await _seed_revision(session, skill=skill, content_md="v1")
    await session.commit()
    await _seed_revision(session, skill=skill, content_md="v2")
    await session.commit()

    details = await resolve_agent_skills_with_origin(session, agent)

    assert details[0].active_revision_number == 2
