"""Integration tests for the full dynamic-agent-skills pipeline — Phase 3, Tasks 3.1 & 3.4.

Tests:
- 3.1: build_voice_context() with real registry fixture (qora-demo/qora-explainer)
       - skills_index appears in assembled system content
       - skills_content is None
       - jaumpablo (empty registry) → skills_index is None
- 3.4: Full tool-call flow
       - load_skill is called → filler emitted → handler reads real file → content returned
       - Multi-skill scenario: load one skill, then load another in the same session
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Path to the real clients directory (production fixture)
# test file lives at backend/tests/unit/voice/test_pipeline_integration.py
# parents[3] = backend/
_CLIENTS_DIR = Path(__file__).resolve().parents[3] / "clients"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    client_id: str,
    slug: str,
    system_prompt: str = "You are a helpful agent.",
) -> MagicMock:
    """Build a minimal Agent mock for build_voice_context()."""
    agent = MagicMock()
    agent.client_id = client_id
    agent.slug = slug
    agent.name = slug
    agent.system_prompt = system_prompt
    agent.knowledge_base = None
    agent.model = "gpt-4o"
    agent.temperature = 0.7
    agent.max_tokens = 300
    agent.tools_enabled = None
    agent.tts_speed = 0.95
    agent.tts_stability = 0.4
    agent.tts_similarity_boost = 0.75
    return agent


def _make_client(client_id: str) -> MagicMock:
    client = MagicMock()
    client.id = client_id
    client.broker_name = client_id
    client.agent_name = "Agent"
    return client


# ---------------------------------------------------------------------------
# Task 3.1a — build_voice_context() with qora-demo/qora-explainer real registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_qora_explainer_has_skills_index():
    """build_voice_context() with real qora-demo/qora-explainer registry returns skills_index.

    GIVEN qora-demo/qora-explainer has a valid registry.yaml on disk (Qora-info skill)
    WHEN build_voice_context() is called (PromptLoader uses real clients dir)
    THEN skills_index is not None and contains '## Available Skills'
    AND skills_content is None (registry mode)
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    agent = _make_agent("qora-demo", "qora-explainer")
    client = _make_client("qora-demo")
    mock_db = AsyncMock()

    # Use real PromptLoader (real filesystem) but mock only render_for_agent
    # to avoid DB calls while keeping load_agent_skills as real code
    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader

        # Mock render_for_agent so no DB is needed
        real_loader.render_for_agent = AsyncMock(return_value="You are Mariano, the Qora demo agent.")

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skills_index is not None, (
        "qora-explainer has a registry.yaml — skills_index must be populated"
    )
    assert "## Available Skills" in result.skills_index, (
        "skills_index must contain '## Available Skills' header"
    )
    assert result.skills_content is None, (
        "skills_content must be None in registry mode"
    )


@pytest.mark.asyncio
async def test_build_voice_context_qora_explainer_index_contains_skill_name():
    """skills_index contains 'Qora-info' from the real registry.yaml.

    GIVEN qora-demo/qora-explainer registry.yaml lists 'Qora-info'
    WHEN build_voice_context() assembles the context
    THEN skills_index contains 'Qora-info'
    AND skills_index contains 'load_skill' instruction
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    agent = _make_agent("qora-demo", "qora-explainer")
    client = _make_client("qora-demo")
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader
        real_loader.render_for_agent = AsyncMock(return_value="system prompt")

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert "Qora-info" in (result.skills_index or ""), (
        "skills_index must contain 'Qora-info' from the real registry entry"
    )
    assert "load_skill" in (result.skills_index or ""), (
        "skills_index must contain load_skill instruction"
    )


@pytest.mark.asyncio
async def test_build_voice_context_qora_explainer_registry_entries_populated():
    """build_voice_context() populates skill_registry_entries from real registry.

    GIVEN qora-demo/qora-explainer has a valid registry.yaml
    WHEN build_voice_context() is called
    THEN skill_registry_entries is a non-empty tuple
    AND the first entry has name='Qora-info'
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    agent = _make_agent("qora-demo", "qora-explainer")
    client = _make_client("qora-demo")
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader
        real_loader.render_for_agent = AsyncMock(return_value="system prompt")

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert len(result.skill_registry_entries) == 1, (
        "qora-explainer registry has exactly 1 skill — Qora-info"
    )
    assert result.skill_registry_entries[0].name == "Qora-info", (
        "The registry entry name must match the file stem: 'Qora-info'"
    )


# ---------------------------------------------------------------------------
# Task 3.1b — skills_index appears in assembled system content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assembled_system_content_contains_skills_index_for_qora_explainer():
    """_assemble_context_system_content includes the skills_index block.

    GIVEN build_voice_context() returned a context with skills_index populated
    WHEN _assemble_context_system_content(ctx) is called
    THEN the assembled content contains '## Available Skills'
    AND 'Qora-info' appears in the result
    AND the system prompt appears BEFORE the skills block
    """
    from app.voice.context import build_voice_context
    from app.voice.webhook import _assemble_context_system_content
    from app.prompts.loader import PromptLoader

    agent = _make_agent("qora-demo", "qora-explainer", system_prompt="You are Mariano.")
    client = _make_client("qora-demo")
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader
        real_loader.render_for_agent = AsyncMock(return_value="You are Mariano.")

        ctx = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assembled = _assemble_context_system_content(ctx)

    assert "## Available Skills" in assembled, (
        "Assembled system content must contain '## Available Skills' when registry is present"
    )
    assert "Qora-info" in assembled, (
        "Assembled content must contain the skill name from the registry"
    )
    assert "You are Mariano." in assembled, (
        "Assembled content must contain the system prompt"
    )

    # System prompt must appear BEFORE skills block
    system_pos = assembled.index("You are Mariano.")
    skills_pos = assembled.index("## Available Skills")
    assert system_pos < skills_pos, (
        "System prompt must appear BEFORE the ## Available Skills block"
    )


# ---------------------------------------------------------------------------
# Task 3.1c — jaumpablo (empty registry) → skills_index is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_jaumpablo_no_skills_index():
    """build_voice_context() with jaumpablo (empty registry) → skills_index is None.

    GIVEN quintana-seguros/jaumpablo has registry.yaml with empty skills list
    WHEN build_voice_context() is called
    THEN skills_index is None (empty registry = no block injected)
    AND skill_registry_entries is an empty tuple
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    agent = _make_agent("quintana-seguros", "jaumpablo")
    client = _make_client("quintana-seguros")
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader
        real_loader.render_for_agent = AsyncMock(return_value="You are Jaumpablo.")

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.skills_index is None, (
        "Empty registry → skills_index must be None (no ## Available Skills block)"
    )
    assert result.skill_registry_entries == (), (
        "Empty registry → skill_registry_entries must be empty tuple"
    )


@pytest.mark.asyncio
async def test_assembled_content_no_skills_block_for_jaumpablo():
    """_assemble_context_system_content has NO ## Available Skills for jaumpablo.

    GIVEN jaumpablo has an empty registry → skills_index is None
    WHEN _assemble_context_system_content(ctx) is called
    THEN '## Available Skills' does NOT appear in the result
    """
    from app.voice.context import build_voice_context
    from app.voice.webhook import _assemble_context_system_content
    from app.prompts.loader import PromptLoader

    agent = _make_agent("quintana-seguros", "jaumpablo", system_prompt="You are Jaumpablo.")
    client = _make_client("quintana-seguros")
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        real_loader = PromptLoader(clients_dir=_CLIENTS_DIR)
        MockLoader.return_value = real_loader
        real_loader.render_for_agent = AsyncMock(return_value="You are Jaumpablo.")

        ctx = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assembled = _assemble_context_system_content(ctx)

    assert "## Available Skills" not in assembled, (
        "Empty registry → no ## Available Skills block must appear in assembled content"
    )
    assert "You are Jaumpablo." in assembled, (
        "System prompt must still appear in assembled content"
    )


# ---------------------------------------------------------------------------
# Task 3.4a — Full tool-flow test: load_skill → filler → real file content returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_tool_flow_load_skill_returns_real_file_content():
    """Full tool-call flow: LLM calls load_skill → handler reads real Qora-info file.

    GIVEN qora-demo/qora-explainer registry with 'Qora-info' skill
    AND the real Qora-info.agent-skill.md file exists on disk
    WHEN dispatch_tool is called with tool_name='load_skill', skill_name='Qora-info'
    THEN the result contains the file content
    AND the content includes real text from Qora-info.agent-skill.md
    """
    from app.prompts.skill_loader import load_skill_registry
    from app.tools.dispatcher import dispatch_tool

    # Load real registry entries (no mocking)
    registry_entries = await load_skill_registry(
        client_id="qora-demo",
        agent_slug="qora-explainer",
        clients_dir=_CLIENTS_DIR,
    )

    assert len(registry_entries) > 0, (
        "Registry must have entries — registry.yaml must be present"
    )

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "Qora-info"},
        client_id="qora-demo",
        lead_id=None,
        agent_slug="qora-explainer",
        registry_entries=registry_entries,
        clients_dir=_CLIENTS_DIR,
    )

    # dispatch_tool('load_skill') returns plain string (WARNING-2 fix)
    assert isinstance(result, str), f"Expected plain string, got {type(result)}: {result!r}"
    assert "error" not in result.lower() or "Qora" in result, (
        f"Expected success (skill content), got error: {result}"
    )
    # The real file contains 'Qora' in its content
    assert "Qora" in result, (
        "Content must come from the real Qora-info.agent-skill.md file"
    )


@pytest.mark.asyncio
async def test_full_tool_flow_load_skill_filler_emitted_with_real_registry():
    """Full flow: SSE stream emits registry filler_text before file is read.

    GIVEN qora-demo/qora-explainer registry with 'Qora-info' entry
    WHEN _stream_llm_response processes a load_skill ToolCallDelta
    THEN the filler_text from the registry ('Dejame buscar esa informacion...')
         is emitted to SSE BEFORE the skill file is read
    """
    from app.prompts.skill_loader import load_skill_registry, SkillRegistryEntry
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response

    registry_entries = await load_skill_registry(
        client_id="qora-demo",
        agent_slug="qora-explainer",
        clients_dir=_CLIENTS_DIR,
    )

    # Verify the real registry entry has a filler_text
    assert registry_entries, "Registry must have entries"
    qora_info_entry = next(e for e in registry_entries if e.name == "Qora-info")
    expected_filler = qora_info_entry.filler_text  # e.g. "Dejame buscar esa informacion..."

    execution_order: list[str] = []

    async def fake_stream(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-real-001",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "Qora-info"}),
        )
        yield StreamDone()

    async def fake_execute(tool_name, tool_args, client_id, lead_id, **kwargs):
        execution_order.append("tool_executed")
        return {"content": "# Qora\nReal content."}

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream

    collected_chunks: list[str] = []

    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Contame sobre Qora"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="qora-demo",
            lead_id=None,
            session_id=None,
            conversation_id=None,
            registry_entries=registry_entries,
        ):
            collected_chunks.append(chunk)
            # Check if this chunk contains the real filler text
            # Use a substring that is ASCII-safe (no tilde)
            filler_key = "buscar"  # from "Dejame buscar esa informacion..."
            if filler_key in chunk and "tool_executed" not in execution_order:
                execution_order.append("filler_yielded")

    assert "filler_yielded" in execution_order, (
        f"Real filler text (containing '{filler_key}') must be emitted. "
        f"Expected filler: {expected_filler!r}. "
        f"Chunks: {collected_chunks}"
    )
    assert "tool_executed" in execution_order, "Tool must have been executed"

    filler_idx = execution_order.index("filler_yielded")
    tool_idx = execution_order.index("tool_executed")
    assert filler_idx < tool_idx, (
        f"Filler (idx={filler_idx}) must be emitted BEFORE tool execution (idx={tool_idx})"
    )


# ---------------------------------------------------------------------------
# Task 3.4b — Multi-skill scenario: load two skills in the same session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_tool_flow_multi_skill_sequential_calls(tmp_path: Path):
    """Two sequential load_skill calls in one session load different skills independently.

    GIVEN a registry with skill-a and skill-b
    WHEN load_skill('skill-a') is called, then load_skill('skill-b')
    THEN each call returns its own skill's content independently
    AND neither call is blocked by the previous
    """
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.tools.dispatcher import dispatch_tool

    # Set up two skill files
    skills_dir = tmp_path / "test-client" / "agents" / "test-agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "skill-a.agent-skill.md").write_text("# Skill A\nContent of skill A.")
    (skills_dir / "skill-b.agent-skill.md").write_text("# Skill B\nContent of skill B.")

    registry_entries = [
        SkillRegistryEntry(
            name="skill-a",
            description="Skill A knowledge",
            trigger_hint="topic A",
            filler_text="Loading skill A...",
        ),
        SkillRegistryEntry(
            name="skill-b",
            description="Skill B knowledge",
            trigger_hint="topic B",
            filler_text="Loading skill B...",
        ),
    ]

    # First call: load skill-a
    result_a = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "skill-a"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        clients_dir=tmp_path,
    )

    # Second call in same session: load skill-b
    result_b = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "skill-b"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        clients_dir=tmp_path,
    )

    # dispatch_tool('load_skill') returns plain string (WARNING-2 fix)
    assert isinstance(result_a, str), f"skill-a: expected str, got {type(result_a)}: {result_a!r}"
    assert isinstance(result_b, str), f"skill-b: expected str, got {type(result_b)}: {result_b!r}"

    assert result_a == "# Skill A\nContent of skill A.", (
        "First skill must return its own content"
    )
    assert result_b == "# Skill B\nContent of skill B.", (
        "Second skill must return its own content"
    )


@pytest.mark.asyncio
async def test_full_tool_flow_two_stream_events_both_skills_loaded(tmp_path: Path):
    """Two ToolCallDelta events in one stream session load two skills correctly.

    GIVEN registry with skill-x and skill-y, both with files on disk
    WHEN _stream_llm_response receives two sequential ToolCallDelta events
    THEN both skills are loaded and their filler texts are emitted
    """
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response

    # Set up skill files
    skills_dir = tmp_path / "multi-client" / "agents" / "multi-agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "skill-x.agent-skill.md").write_text("# Skill X\nX content.")
    (skills_dir / "skill-y.agent-skill.md").write_text("# Skill Y\nY content.")

    registry_entries = [
        SkillRegistryEntry(
            name="skill-x",
            description="X knowledge",
            trigger_hint="topic X",
            filler_text="Loading X...",
        ),
        SkillRegistryEntry(
            name="skill-y",
            description="Y knowledge",
            trigger_hint="topic Y",
            filler_text="Loading Y...",
        ),
    ]

    async def fake_stream(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-x",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "skill-x"}),
        )
        yield ToolCallDelta(
            tool_call_id="call-y",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "skill-y"}),
        )
        yield StreamDone()

    tools_executed: list[str] = []

    async def fake_execute(tool_name, tool_args, client_id, lead_id, **kwargs):
        tools_executed.append(tool_args.get("skill_name", ""))
        return {"content": f"# {tool_args.get('skill_name', '')}\nContent."}

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream

    collected_chunks: list[str] = []
    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Tell me everything"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="multi-client",
            lead_id=None,
            session_id=None,
            conversation_id=None,
            registry_entries=registry_entries,
        ):
            collected_chunks.append(chunk)

    assert "skill-x" in tools_executed, "skill-x must have been loaded"
    assert "skill-y" in tools_executed, "skill-y must have been loaded"

    # Both fillers must appear in the chunks
    all_chunks = " ".join(collected_chunks)
    assert "Loading X" in all_chunks, "Filler for skill-x must appear in SSE stream"
    assert "Loading Y" in all_chunks, "Filler for skill-y must appear in SSE stream"
