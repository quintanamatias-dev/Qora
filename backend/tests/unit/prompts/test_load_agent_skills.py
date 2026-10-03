"""Unit tests for PromptLoader.load_agent_skills() / load_skill_registry_entries()
/ load_skill_content_by_slug() — skill-packages (P4-D3) runtime cutover.

DB-backed mode: these methods resolve an agent's skills from skill_packages/
skills/skill_revisions (via app.skills.service.resolve_agent_skills()) instead
of parsing registry.yaml. No contributing skills → index text is "".
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/load_agent_skills_test.db",
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


async def _seed_skill(
    session: AsyncSession,
    *,
    agent,
    slug: str,
    content_md: str = "content",
    description: str = "desc",
    trigger_hint: str = "hint",
    filler_text: str = "filler",
):
    from sqlalchemy import select

    from app.skills.service import create_skill_revision
    from app.tenants.models import Skill, SkillPackage

    package = (
        await session.execute(
            select(SkillPackage).where(
                SkillPackage.owner_type == "client", SkillPackage.client_id == agent.client_id
            )
        )
    ).scalars().first()
    if package is None:
        package = SkillPackage(owner_type="client", client_id=agent.client_id, name=agent.client_id)
        session.add(package)
        await session.flush()

    skill = Skill(package_id=package.id, slug=slug, section="agent", agent_id=agent.id)
    session.add(skill)
    await session.flush()

    await create_skill_revision(
        session,
        skill=skill,
        content_md=content_md,
        filler_text=filler_text,
        trigger_hint=trigger_hint,
        description=description,
        source="import",
        created_by="tester",
    )
    await session.commit()
    return skill


# ---------------------------------------------------------------------------
# With resolved skills → index block returned
# ---------------------------------------------------------------------------


async def test_load_agent_skills_with_skills_returns_index_block(session: AsyncSession):
    """With DB-seeded skills, load_agent_skills returns ## Available Skills block."""
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "acme", "aria")
    await _seed_skill(
        session, agent=agent, slug="greeting-skill", description="Greeting skill content"
    )
    await _seed_skill(
        session, agent=agent, slug="objections-skill", description="Objections skill content"
    )

    loader = PromptLoader()
    result = await loader.load_agent_skills(session, agent)

    assert "## Available Skills" in result
    assert "greeting-skill" in result
    assert "objections-skill" in result
    assert "load_skill" in result


async def test_load_agent_skills_index_has_both_skill_names_and_descriptions(
    session: AsyncSession,
):
    """Triangulation: both skill names and descriptions appear in the index block."""
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "client1", "bot")
    await _seed_skill(session, agent=agent, slug="alpha", description="Alpha skill description")
    await _seed_skill(session, agent=agent, slug="beta", description="Beta skill description")

    loader = PromptLoader()
    result = await loader.load_agent_skills(session, agent)

    assert "alpha" in result
    assert "Alpha skill description" in result
    assert "beta" in result
    assert "Beta skill description" in result


# ---------------------------------------------------------------------------
# No contributing skills → "" (no filesystem fallback)
# ---------------------------------------------------------------------------


async def test_load_agent_skills_no_skills_returns_empty(session: AsyncSession):
    """load_agent_skills returns '' when the agent has no contributing skills."""
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "acme", "aria")

    loader = PromptLoader()
    result = await loader.load_agent_skills(session, agent)

    assert result == "", f"Expected empty string for no skills, got: {result!r}"


async def test_load_agent_skills_single_skill_returns_index(session: AsyncSession):
    """Single resolved skill → ## Available Skills block with one row."""
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "client", "agent")
    await _seed_skill(session, agent=agent, slug="only-skill", description="The only skill")

    loader = PromptLoader()
    result = await loader.load_agent_skills(session, agent)

    assert "## Available Skills" in result
    assert "only-skill" in result
    assert "load_skill" in result


# ---------------------------------------------------------------------------
# load_skill_registry_entries() — raw entries for allowlist validation
# ---------------------------------------------------------------------------


async def test_load_skill_registry_entries_returns_entries(session: AsyncSession):
    from app.prompts.loader import PromptLoader
    from app.prompts.skill_loader import SkillRegistryEntry

    _, agent = await _make_client_and_agent(session, "acme", "aria")
    await _seed_skill(session, agent=agent, slug="only-skill")

    loader = PromptLoader()
    entries = await loader.load_skill_registry_entries(session, agent)

    assert len(entries) == 1
    assert isinstance(entries[0], SkillRegistryEntry)
    assert entries[0].name == "only-skill"


async def test_load_skill_registry_entries_empty_when_no_skills(session: AsyncSession):
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "acme", "aria")

    loader = PromptLoader()
    entries = await loader.load_skill_registry_entries(session, agent)

    assert entries == []


# ---------------------------------------------------------------------------
# load_skill_content_by_slug() — DB-sourced content map for the load_skill tool
# ---------------------------------------------------------------------------


async def test_load_skill_content_by_slug_returns_active_revision_content(
    session: AsyncSession,
):
    from app.prompts.loader import PromptLoader

    _, agent = await _make_client_and_agent(session, "acme", "aria")
    await _seed_skill(session, agent=agent, slug="only-skill", content_md="# Only skill content")

    loader = PromptLoader()
    content_by_slug = await loader.load_skill_content_by_slug(session, agent)

    assert content_by_slug == {"only-skill": "# Only skill content"}
