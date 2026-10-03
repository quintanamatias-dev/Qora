"""Unit tests for handle_load_skill() — skill-packages P4-D3 runtime cutover.

Tests: valid load from content_by_slug, unknown skill rejected, missing
content, path traversal blocked by registry allowlist (check runs before
any content lookup, DB or otherwise).
"""

from __future__ import annotations

import pytest


def _make_entries(skills: list[dict]) -> list:
    """Build SkillRegistryEntry objects (no filesystem involved)."""
    from app.prompts.skill_loader import SkillRegistryEntry

    return [
        SkillRegistryEntry(
            name=s["name"],
            description=s.get("description", "Test skill"),
            trigger_hint=s.get("trigger_hint", "When relevant"),
            filler_text=s.get("filler_text", "Un momento..."),
        )
        for s in skills
    ]


# ---------------------------------------------------------------------------
# Happy path: valid skill loaded from content_by_slug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_returns_content_by_slug_value():
    """handle_load_skill returns content_by_slug[name] when skill is in the registry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "qora-info"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="qora-info",
        registry_entries=entries,
        content_by_slug={"qora-info": "# Qora Info\nThis is Qora knowledge."},
    )

    assert "error" not in result
    assert result["content"] == "# Qora Info\nThis is Qora knowledge."


@pytest.mark.asyncio
async def test_handle_load_skill_returns_exact_content_bytes():
    """handle_load_skill returns the EXACT content_by_slug value — no stripping, no wrapping."""
    from app.tools.skill_loader import handle_load_skill

    long_content = "# Pricing Guide\n" + ("- Item\n" * 50)
    entries = _make_entries([{"name": "pricing-guide"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="pricing-guide",
        registry_entries=entries,
        content_by_slug={"pricing-guide": long_content},
    )

    assert result["content"] == long_content


# ---------------------------------------------------------------------------
# Error: skill not in registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_unknown_name_returns_error_string():
    """handle_load_skill returns a graceful error when skill_name not in registry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "qora-info"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="unknown-skill",
        registry_entries=entries,
        content_by_slug={"qora-info": "content"},
    )

    assert "error" in result
    assert "unknown-skill" in result["error"]


@pytest.mark.asyncio
async def test_handle_load_skill_empty_registry_returns_error():
    """handle_load_skill returns error when registry is empty."""
    from app.tools.skill_loader import handle_load_skill

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="any-skill",
        registry_entries=[],
        content_by_slug={},
    )

    assert "error" in result
    assert "any-skill" in result["error"]


# ---------------------------------------------------------------------------
# Error: skill in registry but no content resolved (e.g. active_revision missing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_content_missing_returns_error():
    """handle_load_skill returns graceful error when content_by_slug has no entry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "broken-skill"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="broken-skill",
        registry_entries=entries,
        content_by_slug={},
    )

    assert "error" in result
    assert "broken-skill" in result["error"]


@pytest.mark.asyncio
async def test_handle_load_skill_content_by_slug_none_returns_error():
    """handle_load_skill tolerates content_by_slug=None (defaults to empty map)."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "qora-info"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="qora-info",
        registry_entries=entries,
        content_by_slug=None,
    )

    assert "error" in result


# ---------------------------------------------------------------------------
# Security: path traversal blocked by registry allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_path_traversal_blocked():
    """Path traversal attempt is blocked — registry acts as allowlist."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "qora-info"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="../../../etc/passwd",
        registry_entries=entries,
        content_by_slug={"qora-info": "content"},
    )

    assert "error" in result
    assert "root" not in result.get("error", "")
    assert "root" not in result.get("content", "")


@pytest.mark.asyncio
async def test_handle_load_skill_dotdot_name_blocked():
    """Skill names with '..' components are rejected by registry allowlist."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "legitimate-skill"}])

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="legitimate-skill/../../../secret",
        registry_entries=entries,
        content_by_slug={"legitimate-skill": "content"},
    )

    assert "error" in result


# ---------------------------------------------------------------------------
# Security: explicit path-separator rejection (defense-in-depth), BEFORE lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_forward_slash_in_name_rejected_with_specific_message():
    """skill_name containing '/' is rejected by explicit char validation with specific error message.

    This validates the char-validation runs BEFORE the content_by_slug lookup — the
    error message must mention path separators, not 'not found in registry' or
    'could not be read'.
    """
    from app.tools.skill_loader import handle_load_skill

    class _FakeEntry:
        name = "valid/hack"  # Poisoned registry entry with slash in name
        description = "d"
        trigger_hint = "t"
        filler_text = "f"

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="valid/hack",
        registry_entries=[_FakeEntry()],
        content_by_slug={"valid/hack": "SECRET CONTENT"},
    )

    assert "error" in result
    assert "invalid" in result["error"].lower(), (
        f"Expected 'invalid' in error message for path-separator rejection, got: {result['error']!r}"
    )


@pytest.mark.asyncio
async def test_handle_load_skill_backslash_in_name_rejected():
    """skill_name containing '\\' is rejected by explicit char validation."""
    from app.tools.skill_loader import handle_load_skill

    class _FakeEntry:
        name = "skill\\hack"
        description = "d"
        trigger_hint = "t"
        filler_text = "f"

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="skill\\hack",
        registry_entries=[_FakeEntry()],
        content_by_slug={},
    )

    assert "error" in result
    assert "invalid" in result["error"].lower(), (
        f"Expected 'invalid' in error message for backslash rejection, got: {result['error']!r}"
    )


@pytest.mark.asyncio
async def test_handle_load_skill_dotdot_component_rejected():
    """skill_name containing '..' is rejected by explicit char validation."""
    from app.tools.skill_loader import handle_load_skill

    class _FakeEntry:
        name = "..secret"
        description = "d"
        trigger_hint = "t"
        filler_text = "f"

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="..secret",
        registry_entries=[_FakeEntry()],
        content_by_slug={},
    )

    assert "error" in result
    assert "invalid" in result["error"].lower(), (
        f"Expected 'invalid' in error message for dotdot rejection, got: {result['error']!r}"
    )


@pytest.mark.asyncio
async def test_handle_load_skill_rejects_unsafe_skill_name_before_db_lookup():
    """The path-separator check runs before any content_by_slug lookup — even when
    content_by_slug already contains the poisoned name, the unsafe-char check wins."""
    from app.tools.skill_loader import handle_load_skill

    class _FakeEntry:
        name = "a/../b"
        description = "d"
        trigger_hint = "t"
        filler_text = "f"

    result = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="a/../b",
        registry_entries=[_FakeEntry()],
        content_by_slug={"a/../b": "SHOULD NEVER BE RETURNED"},
    )

    assert "error" in result
    assert "invalid" in result["error"].lower()
    assert result.get("content") != "SHOULD NEVER BE RETURNED"


# ---------------------------------------------------------------------------
# Session continues: handler never raises exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_never_raises():
    """handle_load_skill must return a dict even when everything goes wrong."""
    from app.tools.skill_loader import handle_load_skill

    result = await handle_load_skill(
        client_id="nonexistent-client",
        agent_slug="nonexistent-agent",
        skill_name="nonexistent-skill",
        registry_entries=[],
        content_by_slug=None,
    )

    assert isinstance(result, dict)
    assert "error" in result or "content" in result


# ---------------------------------------------------------------------------
# Multiple skills: independent calls work correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_load_skill_multiple_skills_independent():
    """handle_load_skill loads different skills independently in the same registry."""
    from app.tools.skill_loader import handle_load_skill

    entries = _make_entries([{"name": "skill-a"}, {"name": "skill-b"}])
    content_by_slug = {
        "skill-a": "Content of skill A",
        "skill-b": "Content of skill B",
    }

    result_a = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="skill-a",
        registry_entries=entries,
        content_by_slug=content_by_slug,
    )
    result_b = await handle_load_skill(
        client_id="test-client",
        agent_slug="test-agent",
        skill_name="skill-b",
        registry_entries=entries,
        content_by_slug=content_by_slug,
    )

    assert result_a["content"] == "Content of skill A"
    assert result_b["content"] == "Content of skill B"
