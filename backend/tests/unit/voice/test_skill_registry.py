"""Unit tests for skill registry parsing — Phase 1 Task 1.1.

TDD RED phase: Tests reference SkillRegistryEntry, load_skill_registry(),
and build_skills_index() before the implementation exists.

Covers spec scenarios:
- Valid registry loaded → returns list of SkillRegistryEntry objects
- Registry with missing required field → logs warning + returns empty (design override)
- Malformed YAML → logs warning + returns empty
- No registry.yaml → returns empty list (NO glob-all fallback)
- Empty registry file → returns empty list
- Multi-tenant isolation via client_id / agent_slug scoping
- build_skills_index() output format
- load_agent_skills() returns index text (not skill content)
"""

from __future__ import annotations

from pathlib import Path

import pytest


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


@pytest.mark.asyncio
async def test_load_skill_registry_valid_yaml_returns_entries(tmp_path: Path):
    """Valid registry.yaml with 2 entries returns list of 2 SkillRegistryEntry objects.

    GIVEN a valid registry.yaml with two entries
    WHEN load_skill_registry('acme', 'aria') is called
    THEN returns a list of two SkillRegistryEntry objects with correct fields
    """
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: qora-info
    description: Qora platform details
    trigger_hint: when user asks about qora
    filler_text: "Dejame revisar eso..."
  - name: pricing-guide
    description: Pricing and objection handling
    trigger_hint: when user asks about price
    filler_text: "Un momento..."
"""
    )

    entries = await load_skill_registry(
        client_id="acme", agent_slug="aria", clients_dir=tmp_path
    )

    assert len(entries) == 2
    assert entries[0].name == "qora-info"
    assert entries[0].description == "Qora platform details"
    assert entries[0].trigger_hint == "when user asks about qora"
    assert entries[0].filler_text == "Dejame revisar eso..."
    assert entries[1].name == "pricing-guide"
    assert entries[1].description == "Pricing and objection handling"


@pytest.mark.asyncio
async def test_load_skill_registry_entry_order_preserved(tmp_path: Path):
    """Triangulation: registry entries are returned in declaration order."""
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "client" / "agents" / "bot" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: alpha
    description: Alpha skill
    trigger_hint: alpha trigger
    filler_text: Loading alpha...
  - name: beta
    description: Beta skill
    trigger_hint: beta trigger
    filler_text: Loading beta...
  - name: gamma
    description: Gamma skill
    trigger_hint: gamma trigger
    filler_text: Loading gamma...
"""
    )

    entries = await load_skill_registry(
        client_id="client", agent_slug="bot", clients_dir=tmp_path
    )

    assert [e.name for e in entries] == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Task 1.1 — Missing registry → empty (NO glob-all fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_skill_registry_missing_file_returns_empty(tmp_path: Path):
    """No registry.yaml → empty list. NEVER falls back to glob-all.

    GIVEN an agent directory exists but has NO registry.yaml
    WHEN load_skill_registry() is called
    THEN returns [] — no *.agent-skill.md files are loaded
    """
    from app.prompts.skill_loader import load_skill_registry

    # Create agent skills dir with skill files BUT no registry.yaml
    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "some-skill.agent-skill.md").write_text("# This should never be loaded")

    entries = await load_skill_registry(
        client_id="acme", agent_slug="aria", clients_dir=tmp_path
    )

    assert entries == [], (
        "Missing registry.yaml MUST return empty list — no glob-all fallback allowed"
    )


@pytest.mark.asyncio
async def test_load_skill_registry_missing_skills_dir_returns_empty(tmp_path: Path):
    """No skills directory at all → empty list.

    GIVEN the agent has no skills/ directory
    WHEN load_skill_registry() is called
    THEN returns []
    """
    from app.prompts.skill_loader import load_skill_registry

    entries = await load_skill_registry(
        client_id="no-client", agent_slug="no-agent", clients_dir=tmp_path
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Task 1.1 — Empty registry → empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_skill_registry_empty_skills_list_returns_empty(tmp_path: Path):
    """registry.yaml with empty skills: list → returns [].

    GIVEN registry.yaml exists but skills: is an empty list
    WHEN load_skill_registry() is called
    THEN returns []
    """
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text("skills: []\n")

    entries = await load_skill_registry(
        client_id="acme", agent_slug="aria", clients_dir=tmp_path
    )

    assert entries == []


@pytest.mark.asyncio
async def test_load_skill_registry_null_skills_key_returns_empty(tmp_path: Path):
    """registry.yaml with skills: null → returns []."""
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text("skills:\n")

    entries = await load_skill_registry(
        client_id="acme", agent_slug="aria", clients_dir=tmp_path
    )

    assert entries == []


# ---------------------------------------------------------------------------
# Task 1.1 — Malformed YAML → log warning + return empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_skill_registry_malformed_yaml_returns_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Malformed YAML → logs warning and returns [].

    GIVEN registry.yaml contains invalid YAML syntax
    WHEN load_skill_registry() is called
    THEN returns [] and a warning is logged
    """
    import logging
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        "skills:\n  - name: broken\n    description: [unclosed bracket\n"
    )

    with caplog.at_level(logging.WARNING):
        entries = await load_skill_registry(
            client_id="acme", agent_slug="aria", clients_dir=tmp_path
        )

    assert entries == [], "Malformed YAML must return empty list"
    # A warning must have been logged
    assert any("registry" in record.message.lower() or "yaml" in record.message.lower()
               for record in caplog.records), (
        "A warning about malformed YAML or registry must be logged"
    )


@pytest.mark.asyncio
async def test_load_skill_registry_missing_required_field_returns_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """Entry missing required field → logs warning and returns [].

    GIVEN a registry.yaml entry is missing filler_text
    WHEN load_skill_registry() is called
    THEN returns [] and a warning is logged (design: log+empty on malformed)
    """
    import logging
    from app.prompts.skill_loader import load_skill_registry

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: incomplete-skill
    description: Missing filler_text field
    trigger_hint: some trigger
"""
    )

    with caplog.at_level(logging.WARNING):
        entries = await load_skill_registry(
            client_id="acme", agent_slug="aria", clients_dir=tmp_path
        )

    assert entries == [], "Entry with missing required field must return empty list"
    assert len(caplog.records) >= 1, "A warning must be logged for missing required field"


# ---------------------------------------------------------------------------
# Task 1.1 — Multi-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_skill_registry_cross_tenant_isolation(tmp_path: Path):
    """Cross-tenant isolation: client_a registry never loads client_b skills.

    GIVEN client-a and client-b have separate registries
    WHEN load_skill_registry('client-a', 'agent-1') is called
    THEN only client-a's skills are returned
    """
    from app.prompts.skill_loader import load_skill_registry

    # Set up client-a
    dir_a = tmp_path / "client-a" / "agents" / "agent-1" / "skills"
    dir_a.mkdir(parents=True)
    (dir_a / "registry.yaml").write_text(
        """
skills:
  - name: client-a-skill
    description: Client A skill
    trigger_hint: trigger a
    filler_text: Loading A...
"""
    )

    # Set up client-b (should NOT be loaded)
    dir_b = tmp_path / "client-b" / "agents" / "agent-2" / "skills"
    dir_b.mkdir(parents=True)
    (dir_b / "registry.yaml").write_text(
        """
skills:
  - name: client-b-skill
    description: Client B skill
    trigger_hint: trigger b
    filler_text: Loading B...
"""
    )

    entries = await load_skill_registry(
        client_id="client-a", agent_slug="agent-1", clients_dir=tmp_path
    )

    assert len(entries) == 1
    assert entries[0].name == "client-a-skill"
    # client-b skill must never appear
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
# Task 1.3 — load_agent_skills() returns index text (not skill content)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_with_registry_returns_index_text(tmp_path: Path):
    """load_agent_skills() returns registry index text when registry.yaml exists.

    GIVEN an agent with a valid registry.yaml
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns the formatted ## Available Skills index block (NOT raw skill content)
    AND the result contains '## Available Skills'
    AND the result contains skill names from the registry
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: qora-info
    description: Qora platform details
    trigger_hint: when user asks about qora
    filler_text: "Dejame revisar eso..."
"""
    )

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert "## Available Skills" in result, (
        "With registry.yaml present, load_agent_skills must return index block"
    )
    assert "qora-info" in result, "Skill name must appear in index text"
    assert "Qora platform details" in result, "Description must appear in index text"
    assert "load_skill" in result, "Index must contain load_skill instruction"


@pytest.mark.asyncio
async def test_load_agent_skills_without_registry_returns_empty(tmp_path: Path):
    """Triangulation: load_agent_skills() returns '' when no registry.yaml exists.

    GIVEN an agent with skill files BUT no registry.yaml
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns '' — NO glob-all of *.agent-skill.md files
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    # Skill files present but no registry.yaml
    (skills_dir / "some-skill.agent-skill.md").write_text("# Rich skill content")
    (skills_dir / "other-skill.agent-skill.md").write_text("# Other skill content")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", (
        "Without registry.yaml, load_agent_skills must return '' — NO glob-all fallback"
    )
    assert "Rich skill content" not in result, "Skill file content must NOT be loaded without registry"


@pytest.mark.asyncio
async def test_load_agent_skills_empty_registry_returns_empty(tmp_path: Path):
    """Empty registry → load_agent_skills returns ''."""
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text("skills: []\n")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", "Empty registry must produce empty string from load_agent_skills"
