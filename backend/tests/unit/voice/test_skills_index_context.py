"""Unit tests for VoiceSessionContext.skills_index field — Phase 1 Task 1.3/1.4.

TDD RED phase: Tests reference skills_index field and build_voice_context()
registry integration before the implementation exists.

Covers spec scenarios:
- VoiceSessionContext has skills_index: str | None field (default None)
- build_voice_context() sets skills_index from load_agent_skills() return value
- build_voice_context() sets skills_content to None always (registry mode)
- _assemble_context_system_content() injects skills_index after system_prompt
- _assemble_context_system_content() does NOT inject when skills_index is None
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent(
    client_id: str = "acme",
    slug: str = "aria",
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str | None = None,
    system_prompt: str = "",
) -> MagicMock:
    agent = MagicMock()
    agent.client_id = client_id
    agent.slug = slug
    agent.name = "Aria"
    agent.system_prompt = system_prompt
    agent.knowledge_base = None
    agent.model = model
    agent.temperature = temperature
    agent.max_tokens = max_tokens
    agent.tools_enabled = tools_enabled
    agent.tts_speed = 0.95
    agent.tts_stability = 0.4
    agent.tts_similarity_boost = 0.75
    return agent


def make_client(id: str = "acme") -> MagicMock:
    client = MagicMock()
    client.id = id
    client.broker_name = "Acme Seguros"
    client.agent_name = "Aria"
    return client


# ---------------------------------------------------------------------------
# Task 1.3 — VoiceSessionContext.skills_index field
# ---------------------------------------------------------------------------


def test_voice_session_context_has_skills_index_field():
    """VoiceSessionContext has a skills_index: str | None field."""
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index="## Available Skills\nsome content",
    )

    assert ctx.skills_index == "## Available Skills\nsome content"


def test_voice_session_context_skills_index_defaults_to_none():
    """VoiceSessionContext.skills_index defaults to None when not provided."""
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    assert ctx.skills_index is None


def test_voice_session_context_skills_content_accepts_none():
    """VoiceSessionContext.skills_content can be None (registry mode sets it to None)."""
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    assert ctx.skills_content is None


def test_voice_session_context_still_accepts_empty_string_skills_content():
    """Backward compat: skills_content can still be '' (empty string)."""
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content="",
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    assert ctx.skills_content == ""


# ---------------------------------------------------------------------------
# Task 1.4 — build_voice_context() uses registry index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_sets_skills_index_from_load_agent_skills():
    """build_voice_context() stores load_agent_skills() result in skills_index.

    GIVEN an agent with a registry (load_agent_skills returns index block)
    WHEN build_voice_context() is called
    THEN skills_index equals the return value of load_agent_skills()
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    expected_index = "## Available Skills\n| skill-a | desc | trigger |"

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="system prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value=expected_index)
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skills_index == expected_index


@pytest.mark.asyncio
async def test_build_voice_context_skills_content_is_none():
    """build_voice_context() sets skills_content to None in registry mode.

    GIVEN any agent (with or without registry)
    WHEN build_voice_context() is called
    THEN skills_content is None — registry mode is the only mode
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skills_content is None


@pytest.mark.asyncio
async def test_build_voice_context_no_registry_skills_index_is_none():
    """build_voice_context() sets skills_index to None when no registry (empty string → None).

    GIVEN an agent with no registry (load_agent_skills returns '')
    WHEN build_voice_context() is called
    THEN skills_index is None
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="")  # no registry
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skills_index is None


# ---------------------------------------------------------------------------
# Task 1.5 — _assemble_context_system_content() injects skills_index
# ---------------------------------------------------------------------------


def test_assemble_context_injects_skills_index_after_system_prompt():
    """_assemble_context_system_content injects skills_index after system_prompt.

    GIVEN VoiceSessionContext with skills_index populated
    WHEN _assemble_context_system_content(ctx) is called
    THEN the result contains the system_prompt AND skills_index, in that order
    AND '## Available Skills' appears after the system_prompt content
    """
    from app.voice.webhook import _assemble_context_system_content
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="You are an agent.",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index="## Available Skills\n| qora-info | Qora details | when needed |",
    )

    result = _assemble_context_system_content(ctx)

    assert "You are an agent." in result
    assert "## Available Skills" in result
    assert "qora-info" in result

    # skills_index must appear AFTER system_prompt
    system_pos = result.index("You are an agent.")
    skills_pos = result.index("## Available Skills")
    assert system_pos < skills_pos, "skills_index must appear AFTER system_prompt"


def test_assemble_context_no_skills_block_when_skills_index_is_none():
    """_assemble_context_system_content does NOT inject ## Available Skills when skills_index is None.

    GIVEN VoiceSessionContext with skills_index=None
    WHEN _assemble_context_system_content(ctx) is called
    THEN the result does NOT contain '## Available Skills'
    AND the system_prompt is unchanged
    """
    from app.voice.webhook import _assemble_context_system_content
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="You are an agent.",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index=None,
    )

    result = _assemble_context_system_content(ctx)

    assert "## Available Skills" not in result
    assert result == "You are an agent."


def test_assemble_context_skills_index_with_misc_notes_and_lead_profile():
    """Triangulation: all 4 components (system_prompt + skills_index + misc_notes + lead_profile) assembled.

    GIVEN VoiceSessionContext with all components populated
    WHEN _assemble_context_system_content(ctx) is called
    THEN all components appear in the result in correct order
    """
    from app.voice.webhook import _assemble_context_system_content
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="Base prompt.",
        skills_content=None,
        misc_notes="Some notes.",
        lead_profile="[CONTEXTO DEL LEAD]\nNombre: Juan",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index="## Available Skills\n| skill-a | desc | trigger |",
    )

    result = _assemble_context_system_content(ctx)

    assert "Base prompt." in result
    assert "## Available Skills" in result
    assert "Some notes." in result
    assert "Juan" in result

    # Order: system_prompt → skills_index → misc_notes → lead_profile
    positions = [
        result.index("Base prompt."),
        result.index("## Available Skills"),
        result.index("Some notes."),
        result.index("Juan"),
    ]
    assert positions == sorted(positions), "Components must appear in: system_prompt, skills_index, misc_notes, lead_profile order"


def test_assemble_context_empty_skills_index_not_injected():
    """Empty string skills_index ('' not None) → no injection.

    Per design: skills_content='' and skills_index='' both mean 'no skills'.
    The assembler must not inject an empty block.
    """
    from app.voice.webhook import _assemble_context_system_content
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="Only base.",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index="",
    )

    result = _assemble_context_system_content(ctx)

    assert result == "Only base."
    assert "## Available Skills" not in result


# ---------------------------------------------------------------------------
# Phase 2 — skill_registry_entries field in VoiceSessionContext
# ---------------------------------------------------------------------------


def test_voice_session_context_has_skill_registry_entries_field():
    """VoiceSessionContext has a skill_registry_entries field (default empty tuple)."""
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    # Default: empty tuple (no registry entries)
    assert hasattr(ctx, "skill_registry_entries")
    assert ctx.skill_registry_entries == ()


def test_voice_session_context_stores_registry_entries():
    """VoiceSessionContext stores SkillRegistryEntry objects as a tuple."""
    from app.voice.context import VoiceSessionContext
    from app.prompts.skill_loader import SkillRegistryEntry

    entries = (
        SkillRegistryEntry(
            name="qora-info",
            description="Qora details",
            trigger_hint="About Qora",
            filler_text="Déjame revisar...",
        ),
    )

    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skill_registry_entries=entries,
    )

    assert len(ctx.skill_registry_entries) == 1
    assert ctx.skill_registry_entries[0].name == "qora-info"


@pytest.mark.asyncio
async def test_build_voice_context_populates_skill_registry_entries():
    """build_voice_context() stores registry entries in skill_registry_entries when registry exists."""
    from app.voice.context import build_voice_context
    from app.prompts.skill_loader import SkillRegistryEntry

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    expected_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Déjame revisar...",
        )
    ]
    expected_index = "## Available Skills\n| qora-info | Qora platform info | About Qora |"

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="system prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value=expected_index)
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=expected_entries)

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert len(result.skill_registry_entries) == 1
    assert result.skill_registry_entries[0].name == "qora-info"


@pytest.mark.asyncio
async def test_build_voice_context_empty_registry_entries_when_no_registry():
    """build_voice_context() sets skill_registry_entries to empty tuple when no registry."""
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skill_registry_entries == ()
