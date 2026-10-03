"""Unit tests for skill registry resolution — Phase 1 Task 1.1 + skill-packages
P4-D3 runtime cutover.

load_skill_registry() is now DB-backed (app.skills.service.resolve_agent_skills()
via the per-process AgentSkillsCache) — the filesystem registry.yaml parser this
file originally tested is fully removed. YAML-parse-error/missing-field validation
now belongs to the one-time import migration (20261003_0026), not this runtime path.

Covers spec scenarios:
- Valid DB-seeded skills resolved → returns list of SkillRegistryEntry objects
- No contributing skills → returns empty list (same semantics as a missing
  registry.yaml had before this cutover)
- Multi-tenant isolation (an agent never resolves another client's skills)
- build_skills_index() output format (unchanged by the cutover)

See tests/unit/prompts/test_load_agent_skills.py for PromptLoader.load_agent_skills()
/ load_skill_registry_entries() / load_skill_content_by_slug() coverage, and
tests/unit/skills/test_service.py for resolve_agent_skills()'s collision-resolution
rules (P4-D2).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/skill_registry_test.db",
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


async def _seed_skill(session: AsyncSession, *, agent, slug: str, **revision_kwargs):
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

    defaults = {
        "content_md": "content",
        "filler_text": "filler",
        "trigger_hint": "hint",
        "description": "desc",
    }
    defaults.update(revision_kwargs)
    await create_skill_revision(
        session, skill=skill, source="import", created_by="tester", **defaults
    )
    await session.commit()
    return skill


# ---------------------------------------------------------------------------
# Task 1.1 — SkillRegistryEntry dataclass
# ---------------------------------------------------------------------------


def test_skill_registry_entry_is_importable():
    """SkillRegistryEntry is importable from app.prompts.skill_loader."""
    from app.prompts.skill_loader import SkillRegistryEntry  # noqa: F401


def test_skill_registry_entry_has_required_fields():
    """SkillRegistryEntry has name, description, trigger_hint, filler_text fields."""
    from app.prompts.skill_loader import SkillRegistryEntry

    entry = SkillRegistryEntry(
        name="qora-info",
        description="Qora platform details",
        trigger_hint="when user asks about qora",
        filler_text="Dejame revisar eso...",
    )

    assert entry.name == "qora-info"
    assert entry.description == "Qora platform details"
    assert entry.trigger_hint == "when user asks about qora"
    assert entry.filler_text == "Dejame revisar eso..."


def test_skill_registry_entry_is_frozen():
    """SkillRegistryEntry must be immutable (frozen dataclass)."""
    from app.prompts.skill_loader import SkillRegistryEntry

    entry = SkillRegistryEntry(
        name="test",
        description="desc",
        trigger_hint="trigger",
        filler_text="filler",
    )

    with pytest.raises((AttributeError, TypeError)):
        entry.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Task 1.1 — load_skill_registry(): happy path
# ---------------------------------------------------------------------------


async def test_load_skill_registry_resolves_db_seeded_skills(session: AsyncSession):
    """DB-seeded skills resolve to SkillRegistryEntry objects with correct fields."""
    from app.prompts.skill_loader import load_skill_registry

    _, agent = await _make_client_and_agent(session, "acme", "aria")
    await _seed_skill(
        session,
        agent=agent,
        slug="qora-info",
        content_md="Qora info content",
        description="Qora platform details",
        trigger_hint="when user asks about qora",
        filler_text="Dejame revisar eso...",
    )
    await _seed_skill(
        session,
        agent=agent,
        slug="pricing-guide",
        content_md="Pricing content",
        description="Pricing and objection handling",
        trigger_hint="when user asks about price",
        filler_text="Un momento...",
    )

    entries = await load_skill_registry(session, agent)

    assert {e.name for e in entries} == {"qora-info", "pricing-guide"}
    by_name = {e.name: e for e in entries}
    assert by_name["qora-info"].description == "Qora platform details"
    assert by_name["qora-info"].trigger_hint == "when user asks about qora"
    assert by_name["qora-info"].filler_text == "Dejame revisar eso..."
    assert by_name["pricing-guide"].description == "Pricing and objection handling"


# ---------------------------------------------------------------------------
# No contributing skills → empty (NO filesystem fallback)
# ---------------------------------------------------------------------------


async def test_load_skill_registry_no_skills_returns_empty(session: AsyncSession):
    """No contributing skills → empty list — the same semantics a missing
    registry.yaml had before this cutover."""
    from app.prompts.skill_loader import load_skill_registry

    _, agent = await _make_client_and_agent(session, "acme", "aria")

    entries = await load_skill_registry(session, agent)

    assert entries == []


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------


async def test_load_skill_registry_cross_tenant_isolation(session: AsyncSession):
    """Cross-tenant isolation: client-a's agent never resolves client-b's skills.

    GIVEN client-a and client-b each have their own agent-section skill
    WHEN load_skill_registry(session, client_a_agent) is called
    THEN only client-a's skill is returned
    """
    from app.prompts.skill_loader import load_skill_registry

    _, agent_a = await _make_client_and_agent(session, "client-a", "agent-1")
    await _seed_skill(session, agent=agent_a, slug="client-a-skill")

    _, agent_b = await _make_client_and_agent(session, "client-b", "agent-2")
    await _seed_skill(session, agent=agent_b, slug="client-b-skill")

    entries = await load_skill_registry(session, agent_a)

    assert len(entries) == 1
    assert entries[0].name == "client-a-skill"
    assert all(e.name != "client-b-skill" for e in entries)


# ---------------------------------------------------------------------------
# Task 1.2 — build_skills_index(): index text generation
# ---------------------------------------------------------------------------


def test_build_skills_index_is_importable():
    """build_skills_index is importable from app.prompts.skill_loader."""
    from app.prompts.skill_loader import build_skills_index  # noqa: F401


def test_build_skills_index_empty_list_returns_empty_string():
    """build_skills_index([]) returns empty string — no block injected.

    GIVEN no registry entries
    WHEN build_skills_index([]) is called
    THEN returns ''
    """
    from app.prompts.skill_loader import build_skills_index

    result = build_skills_index([])

    assert result == "", f"Expected empty string for empty entries, got: {result!r}"


def test_build_skills_index_single_entry_has_header_and_skill():
    """build_skills_index with one entry contains the ## Available Skills header.

    GIVEN one SkillRegistryEntry
    WHEN build_skills_index() is called
    THEN result contains '## Available Skills' header
    AND contains the skill name
    AND contains the description
    AND contains instruction to call load_skill
    """
    from app.prompts.skill_loader import SkillRegistryEntry, build_skills_index

    entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform details",
            trigger_hint="when user asks about qora",
            filler_text="Dejame revisar eso...",
        )
    ]

    result = build_skills_index(entries)

    assert "## Available Skills" in result, "Must include ## Available Skills header"
    assert "qora-info" in result, "Must include skill name"
    assert "Qora platform details" in result, "Must include description"
    assert "load_skill" in result, "Must instruct LLM to call load_skill tool"


def test_build_skills_index_multiple_entries_all_present():
    """Triangulation: all entries appear in the index block.

    GIVEN two SkillRegistryEntry objects
    WHEN build_skills_index() is called
    THEN both names and descriptions appear in the result
    AND instruction to call load_skill appears
    """
    from app.prompts.skill_loader import SkillRegistryEntry, build_skills_index

    entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform details",
            trigger_hint="when user asks about qora",
            filler_text="Dejame revisar eso...",
        ),
        SkillRegistryEntry(
            name="pricing-guide",
            description="Pricing and objection handling",
            trigger_hint="when user asks about price",
            filler_text="Un momento...",
        ),
    ]

    result = build_skills_index(entries)

    assert "qora-info" in result
    assert "Qora platform details" in result
    assert "pricing-guide" in result
    assert "Pricing and objection handling" in result
    assert "load_skill" in result
    # Must have only ONE header (not duplicated)
    assert result.count("## Available Skills") == 1


def test_build_skills_index_contains_once_per_conversation_hint():
    """Index block must contain 'once' reminder to prevent repeated loads."""
    from app.prompts.skill_loader import SkillRegistryEntry, build_skills_index

    entries = [
        SkillRegistryEntry(
            name="some-skill",
            description="Some skill",
            trigger_hint="trigger",
            filler_text="Loading...",
        )
    ]

    result = build_skills_index(entries)

    assert "once" in result.lower(), (
        "Index block must remind LLM to load each skill only once per conversation"
    )


# ---------------------------------------------------------------------------
# Task 1.3 — PromptLoader.load_agent_skills() coverage moved
# ---------------------------------------------------------------------------
# See tests/unit/prompts/test_load_agent_skills.py for DB-backed
# load_agent_skills()/load_skill_registry_entries()/load_skill_content_by_slug()
# coverage (skill-packages P4-D3 runtime cutover).
