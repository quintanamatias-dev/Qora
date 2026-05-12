"""Unit tests for PromptLoader.load_agent_skills() — registry-based mode.

Phase 1 (dynamic-agent-skills): The old glob-all behavior has been REMOVED.
load_agent_skills() now returns a registry index block (## Available Skills)
when registry.yaml is present, or '' when it is absent/empty.

Covers:
- Registry present → returns ## Available Skills index block
- No registry.yaml → '' (NO glob-all fallback, even if *.agent-skill.md exist)
- Empty registry → ''
- Missing skills directory → ''
- Old glob-all tests retained as documentation that the behavior no longer works
  (renamed to describe the new expected behavior)
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# New behavior: registry present → index block returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_with_registry_returns_index_block(tmp_path: Path):
    """With registry.yaml present, load_agent_skills returns ## Available Skills block.

    GIVEN clients/acme/agents/aria/skills/registry.yaml with two entries
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns the formatted ## Available Skills index block (not raw file content)
    AND the block contains skill names from the registry
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: greeting-skill
    description: Greeting skill content
    trigger_hint: when starting conversation
    filler_text: Cargando...
  - name: objections-skill
    description: Objections skill content
    trigger_hint: when user objects to price
    filler_text: Revisando...
"""
    )

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert "## Available Skills" in result
    assert "greeting-skill" in result
    assert "objections-skill" in result
    assert "load_skill" in result


@pytest.mark.asyncio
async def test_load_agent_skills_registry_index_has_both_skill_names(tmp_path: Path):
    """Triangulation: both skill names and descriptions appear in the index block."""
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "client1" / "agents" / "bot" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: alpha
    description: Alpha skill description
    trigger_hint: alpha trigger
    filler_text: Loading alpha...
  - name: beta
    description: Beta skill description
    trigger_hint: beta trigger
    filler_text: Loading beta...
"""
    )

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("client1", "bot")

    assert "alpha" in result
    assert "Alpha skill description" in result
    assert "beta" in result
    assert "Beta skill description" in result


# ---------------------------------------------------------------------------
# New behavior: no registry.yaml → '' (NEVER glob-all)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_missing_directory_returns_empty(tmp_path: Path):
    """load_agent_skills returns '' when skills directory doesn't exist.

    GIVEN clients/acme/agents/aria/skills/ does not exist
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns ''
    """
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", f"Expected empty string for missing directory, got: {result!r}"


@pytest.mark.asyncio
async def test_load_agent_skills_no_registry_returns_empty_even_with_skill_files(tmp_path: Path):
    """No registry.yaml → '' even when *.agent-skill.md files exist (NO glob-all).

    GIVEN the skills directory has *.agent-skill.md files but NO registry.yaml
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns '' — NO glob-all fallback
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "greeting.agent-skill.md").write_text("# Greeting skill content")
    (skills_dir / "objections.agent-skill.md").write_text("# Objections skill content")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", (
        "Without registry.yaml, load_agent_skills MUST return '' — no glob-all allowed"
    )
    assert "# Greeting skill content" not in result
    assert "# Objections skill content" not in result


@pytest.mark.asyncio
async def test_load_agent_skills_empty_registry_returns_empty(tmp_path: Path):
    """Empty registry → '' (agent operates without skills).

    GIVEN the skills directory has an empty registry.yaml (skills: [])
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns ''
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text("skills: []\n")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", (
        f"Expected empty string for empty registry, got: {result!r}"
    )


@pytest.mark.asyncio
async def test_load_agent_skills_single_entry_returns_index(tmp_path: Path):
    """Single registry entry → ## Available Skills block with one row."""
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "client" / "agents" / "agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "registry.yaml").write_text(
        """
skills:
  - name: only-skill
    description: The only skill
    trigger_hint: when needed
    filler_text: Loading...
"""
    )

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("client", "agent")

    assert "## Available Skills" in result
    assert "only-skill" in result
    assert "load_skill" in result
