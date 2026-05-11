"""Unit tests for PromptLoader.load_agent_skills() — VSC-3.

TDD RED phase: Tests reference the method before it exists.
Covers VSC-3 spec scenarios:
- Two skill files concatenated in alphabetical order
- Missing directory returns empty string
- No matching .agent-skill.md files returns empty string
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# VSC-3 Scenario 1: Two skill files, alphabetical order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_two_files_alphabetical_order(tmp_path: Path):
    """load_agent_skills returns both file contents separated by separator,
    in alphabetical order.

    GIVEN clients/acme/agents/aria/skills/ contains greeting.agent-skill.md
          and objections.agent-skill.md
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns concatenated content in alphabetical order separated by '\\n\\n---\\n\\n'
    """
    from app.prompts.loader import PromptLoader

    # Set up directory structure
    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "greeting.agent-skill.md").write_text("# Greeting skill content")
    (skills_dir / "objections.agent-skill.md").write_text("# Objections skill content")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    # Both files present, separator between them
    assert "# Greeting skill content" in result
    assert "# Objections skill content" in result
    assert "\n\n---\n\n" in result

    # Alphabetical order: greeting comes before objections
    greeting_pos = result.index("# Greeting skill content")
    objections_pos = result.index("# Objections skill content")
    assert greeting_pos < objections_pos, (
        "greeting.agent-skill.md must appear before objections.agent-skill.md "
        "(alphabetical ordering required)"
    )


@pytest.mark.asyncio
async def test_load_agent_skills_exact_separator(tmp_path: Path):
    """Triangulation: separator is exactly '\\n\\n---\\n\\n' between files."""
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "client1" / "agents" / "bot" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "a_skill.agent-skill.md").write_text("FIRST")
    (skills_dir / "b_skill.agent-skill.md").write_text("SECOND")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("client1", "bot")

    assert result == "FIRST\n\n---\n\nSECOND"


# ---------------------------------------------------------------------------
# VSC-3 Scenario 2: Missing directory → empty string
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


# ---------------------------------------------------------------------------
# VSC-3 Scenario 3: Directory exists but no .agent-skill.md files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_no_matching_files_returns_empty(tmp_path: Path):
    """load_agent_skills returns '' when directory has no *.agent-skill.md files.

    GIVEN the skills directory exists but contains only README.md
    WHEN load_agent_skills('acme', 'aria') is called
    THEN returns ''
    """
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "acme" / "agents" / "aria" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "README.md").write_text("Not a skill file")
    (skills_dir / "notes.txt").write_text("Also not a skill file")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("acme", "aria")

    assert result == "", (
        f"Expected empty string when no *.agent-skill.md files exist, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Edge case: Single skill file (no separator)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_agent_skills_single_file_no_separator(tmp_path: Path):
    """Single skill file returns content without trailing separator."""
    from app.prompts.loader import PromptLoader

    skills_dir = tmp_path / "client" / "agents" / "agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "only_skill.agent-skill.md").write_text("Only skill content here")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_skills("client", "agent")

    assert result == "Only skill content here"
    assert "\n\n---\n\n" not in result, "Single file should not have separator"
