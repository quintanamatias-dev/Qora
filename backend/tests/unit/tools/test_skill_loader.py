"""Unit tests for handle_load_skill() — Phase 2, Task 2.1.

Tests: valid load, unknown skill rejected, missing file, path traversal blocked
by registry allowlist.
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers — build a minimal registry entry list and skill files
# ---------------------------------------------------------------------------


def _make_entries(tmp_path: Path, skills: list[dict]) -> list:
    """Create SkillRegistryEntry objects and optionally write skill files."""
    from app.prompts.skill_loader import SkillRegistryEntry

    entries = []
    for s in skills:
        entries.append(
            SkillRegistryEntry(
                name=s["name"],
                description=s.get("description", "Test skill"),
                trigger_hint=s.get("trigger_hint", "When relevant"),
                filler_text=s.get("filler_text", "Un momento..."),
            )
        )
        if s.get("write_file", True):
            skill_dir = tmp_path / "clients" / "test-client" / "agents" / "test-agent" / "skills"
            skill_dir.mkdir(parents=True, exist_ok=True)
            file_path = skill_dir / f"{s['name']}.agent-skill.md"
            file_path.write_text(s.get("content", f"# {s['name']}\nSkill content here."))
    return entries


# ---------------------------------------------------------------------------
# Happy path: valid skill loaded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_returns_file_content(tmp_path: Path):
    """handle_load_skill returns the file content when skill exists in registry and on disk."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries(tmp_path, [
        {"name": "qora-info", "content": "# Qora Info\nThis is Qora knowledge."}
    ])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="qora-info",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert "error" not in result
    assert result["content"] == "# Qora Info\nThis is Qora knowledge."


@pytest.mark.asyncio
async def test_handle_load_skill_returns_exact_file_content(tmp_path: Path):
    """handle_load_skill returns the EXACT bytes on disk — no stripping, no wrapping."""
    from app.tools.skill_loader import handle_load_skill

    long_content = "# Pricing Guide\n" + ("- Item\n" * 50)
    entries = _make_entries(tmp_path, [
        {"name": "pricing-guide", "content": long_content}
    ])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="pricing-guide",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert result["content"] == long_content


# ---------------------------------------------------------------------------
# Error: skill not in registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_unknown_name_returns_error_string(tmp_path: Path):
    """handle_load_skill returns a graceful error when skill_name not in registry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries(tmp_path, [
        {"name": "qora-info"}
    ])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="unknown-skill",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert "error" in result
    assert "unknown-skill" in result["error"]


@pytest.mark.asyncio
async def test_handle_load_skill_empty_registry_returns_error(tmp_path: Path):
    """handle_load_skill returns error when registry is empty."""
    from app.tools.skill_loader import handle_load_skill

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="any-skill",
        registry_entries=[],
        clients_dir=tmp_path / "clients",
    )

    assert "error" in result
    assert "any-skill" in result["error"]


# ---------------------------------------------------------------------------
# Error: skill in registry but file missing from disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_file_missing_returns_error(tmp_path: Path):
    """handle_load_skill returns graceful error when file is not on disk."""
    from app.tools.skill_loader import handle_load_skill

    # Entry exists in registry but write_file=False (no file on disk)
    entries = _make_entries(tmp_path, [
        {"name": "broken-skill", "write_file": False}
    ])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="broken-skill",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert "error" in result
    assert "broken-skill" in result["error"]


# ---------------------------------------------------------------------------
# Security: path traversal blocked by registry allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_path_traversal_blocked(tmp_path: Path):
    """Path traversal attempt is blocked — registry acts as allowlist."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries(tmp_path, [
        {"name": "qora-info"}
    ])

    # Attacker tries to escape skills directory via traversal
    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="../../../etc/passwd",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert "error" in result
    # Must NOT contain actual file system data
    assert "root" not in result.get("error", "")
    assert "root" not in result.get("content", "")


@pytest.mark.asyncio
async def test_handle_load_skill_dotdot_name_blocked(tmp_path: Path):
    """Skill names with '..' components are rejected by registry allowlist."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries(tmp_path, [
        {"name": "legitimate-skill"}
    ])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="legitimate-skill/../../../secret",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert "error" in result


# ---------------------------------------------------------------------------
# Session continues: handler never raises exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_never_raises(tmp_path: Path):
    """handle_load_skill must return a dict even when everything goes wrong."""
    from app.tools.skill_loader import handle_load_skill

    # Completely broken inputs
    result = await handle_load_skill(
        client_id="nonexistent-client",
        agent_slug="nonexistent-agent",
        skill_name="nonexistent-skill",
        registry_entries=[],
        clients_dir=tmp_path / "clients",
    )

    # Must return a dict, never raise
    assert isinstance(result, dict)
    assert "error" in result or "content" in result


# ---------------------------------------------------------------------------
# Multiple skills: independent calls work correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_multiple_skills_independent(tmp_path: Path):
    """handle_load_skill loads different skills independently in the same registry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries(tmp_path, [
        {"name": "skill-a", "content": "Content of skill A"},
        {"name": "skill-b", "content": "Content of skill B"},
    ])

    result_a = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="skill-a",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )
    result_b = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="skill-b",
        registry_entries=entries,
        clients_dir=tmp_path / "clients",
    )

    assert result_a["content"] == "Content of skill A"
    assert result_b["content"] == "Content of skill B"
