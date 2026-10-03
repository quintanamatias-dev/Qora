"""Integration tests for the full dynamic-agent-skills pipeline — Phase 3, Tasks 3.1 & 3.4.

Tests:
- 3.1: build_voice_context() with real registry fixture (quintana-seguros/leads-agent)
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


async def _make_quintana_migrated_db(tmp_path: Path):
    """Run the real migration chain (including 20261003_0026's import of the real
    quintana-seguros/leads-agent registry.yaml + *.agent-skill.md files) against a
    tmp DB, seed quintana-seguros + leads-agent + jaumpablo rows, then return real
    Agent ORM instances for both (skill-packages P4-D3 runtime cutover —
    build_voice_context() now resolves skills from the DB, not the filesystem).
    """
    import concurrent.futures
    import sqlite3

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.tenants.models import Agent

    backend_dir = Path(__file__).resolve().parents[3]
    db_file = tmp_path / "pipeline_integration.db"
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file}")
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    def _upgrade(revision: str) -> None:
        # Run in a separate thread so alembic/env.py's asyncio.run() gets a
        # fresh event loop (this helper runs inside an async test's running loop).
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(command.upgrade, cfg, revision).result()

    _upgrade("20261003_0025")

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO clients (id, name, voice_id, is_active, created_at) "
        "VALUES ('quintana-seguros', 'Quintana Seguros', 'v1', 1, '2026-10-03T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO agents (id, client_id, slug, name, voice_id, created_at) "
        "VALUES ('leads-agent-id', 'quintana-seguros', 'leads-agent', 'Leads Agent', "
        "'v1', '2026-10-03T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO agents (id, client_id, slug, name, voice_id, created_at) "
        "VALUES ('jaumpablo-id', 'quintana-seguros', 'jaumpablo', 'Jaumpablo', "
        "'v1', '2026-10-03T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    _upgrade("head")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session = AsyncSession(engine)
    leads_agent = (
        await session.execute(select(Agent).where(Agent.slug == "leads-agent"))
    ).scalar_one()
    jaumpablo = (
        await session.execute(select(Agent).where(Agent.slug == "jaumpablo"))
    ).scalar_one()
    return session, engine, leads_agent, jaumpablo


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
    client.name = client_id
    client.agent_name = "Agent"
    return client


# ---------------------------------------------------------------------------
# Task 3.1a — build_voice_context() with quintana-seguros/leads-agent real registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_leads_agent_has_skills_index(tmp_path: Path):
    """build_voice_context() with real quintana-seguros/leads-agent skills (DB-backed,
    seeded by the real import migration) returns skills_index.

    GIVEN quintana-seguros/leads-agent's skills were imported from the real
          registry.yaml + *.agent-skill.md files (auto-insurance-knowledge, lead-qualification)
    WHEN build_voice_context() is called
    THEN skills_index is not None and contains '## Available Skills'
    AND skills_content is None (registry mode)
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            # Mock render_for_agent only — skills resolution stays real (DB-backed)
            real_loader.render_for_agent = AsyncMock(return_value="You are a leads agent.")

            result = await build_voice_context(
                agent=leads_agent,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

    assert result.skills_index is not None, (
        "leads-agent has imported skills — skills_index must be populated"
    )
    assert "## Available Skills" in result.skills_index, (
        "skills_index must contain '## Available Skills' header"
    )
    assert result.skills_content is None, (
        "skills_content must be None in registry mode"
    )


@pytest.mark.asyncio
async def test_build_voice_context_leads_agent_index_contains_skill_name(tmp_path: Path):
    """skills_index contains 'auto-insurance-knowledge' from the imported skill.

    GIVEN quintana-seguros/leads-agent's imported skills include 'auto-insurance-knowledge'
    WHEN build_voice_context() assembles the context
    THEN skills_index contains 'auto-insurance-knowledge'
    AND skills_index contains 'load_skill' instruction
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            real_loader.render_for_agent = AsyncMock(return_value="system prompt")

            result = await build_voice_context(
                agent=leads_agent,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

    assert "auto-insurance-knowledge" in (result.skills_index or ""), (
        "skills_index must contain 'auto-insurance-knowledge' from the imported skill"
    )
    assert "load_skill" in (result.skills_index or ""), (
        "skills_index must contain load_skill instruction"
    )


@pytest.mark.asyncio
async def test_build_voice_context_leads_agent_registry_entries_populated(tmp_path: Path):
    """build_voice_context() populates skill_registry_entries from the imported skills.

    GIVEN quintana-seguros/leads-agent has two imported skills
    WHEN build_voice_context() is called
    THEN skill_registry_entries is a non-empty tuple
    AND one entry has name='auto-insurance-knowledge'
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            real_loader.render_for_agent = AsyncMock(return_value="system prompt")

            result = await build_voice_context(
                agent=leads_agent,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

    assert len(result.skill_registry_entries) == 2, (
        "leads-agent's imported skills must number exactly 2 — "
        "auto-insurance-knowledge, lead-qualification"
    )
    assert {e.name for e in result.skill_registry_entries} == {
        "auto-insurance-knowledge",
        "lead-qualification",
    }


# ---------------------------------------------------------------------------
# Task 3.1b — skills_index appears in assembled system content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assembled_system_content_contains_skills_index_for_leads_agent(tmp_path: Path):
    """_assemble_context_system_content includes the skills_index block.

    GIVEN build_voice_context() returned a context with skills_index populated
    WHEN _assemble_context_system_content(ctx) is called
    THEN the assembled content contains '## Available Skills'
    AND 'auto-insurance-knowledge' appears in the result
    AND the system prompt appears BEFORE the skills block
    """
    from app.voice.context import build_voice_context
    from app.voice.webhook import _assemble_context_system_content
    from app.prompts.loader import PromptLoader

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            real_loader.render_for_agent = AsyncMock(return_value="You are Mariano.")

            ctx = await build_voice_context(
                agent=leads_agent,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

    assembled = _assemble_context_system_content(ctx)

    assert "## Available Skills" in assembled, (
        "Assembled system content must contain '## Available Skills' when registry is present"
    )
    assert "auto-insurance-knowledge" in assembled, (
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
async def test_build_voice_context_jaumpablo_no_skills_index(tmp_path: Path):
    """build_voice_context() with jaumpablo (no imported skills) → skills_index is None.

    GIVEN quintana-seguros/jaumpablo's registry.yaml is skills: [] — the import
          migration creates zero rows for it
    WHEN build_voice_context() is called
    THEN skills_index is None (no contributing skills = no block injected)
    AND skill_registry_entries is an empty tuple
    """
    from app.voice.context import build_voice_context
    from app.prompts.loader import PromptLoader

    session, engine, _leads_agent, jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            real_loader.render_for_agent = AsyncMock(return_value="You are Jaumpablo.")

            result = await build_voice_context(
                agent=jaumpablo,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

    assert result.skills_index is None, (
        "Empty registry → skills_index must be None (no ## Available Skills block)"
    )
    assert result.skill_registry_entries == (), (
        "Empty registry → skill_registry_entries must be empty tuple"
    )


@pytest.mark.asyncio
async def test_assembled_content_no_skills_block_for_jaumpablo(tmp_path: Path):
    """_assemble_context_system_content has NO ## Available Skills for jaumpablo.

    GIVEN jaumpablo has no imported skills → skills_index is None
    WHEN _assemble_context_system_content(ctx) is called
    THEN '## Available Skills' does NOT appear in the result
    """
    from app.voice.context import build_voice_context
    from app.voice.webhook import _assemble_context_system_content
    from app.prompts.loader import PromptLoader

    session, engine, _leads_agent, jaumpablo = await _make_quintana_migrated_db(tmp_path)
    client = _make_client("quintana-seguros")

    try:
        with patch("app.voice.context.PromptLoader") as MockLoader:
            real_loader = PromptLoader()
            MockLoader.return_value = real_loader
            real_loader.render_for_agent = AsyncMock(return_value="You are Jaumpablo.")

            ctx = await build_voice_context(
                agent=jaumpablo,
                lead=None,
                db=session,
                client=client,
            )
    finally:
        await session.close()
        await engine.dispose()

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
async def test_full_tool_flow_load_skill_returns_real_file_content(tmp_path: Path):
    """Full tool-call flow: LLM calls load_skill → handler returns the imported
    auto-insurance-knowledge content from the DB (skill-packages P4-D3).

    GIVEN quintana-seguros/leads-agent's skills were imported from the real
          registry.yaml + *.agent-skill.md files
    WHEN dispatch_tool is called with tool_name='load_skill', skill_name='auto-insurance-knowledge'
    THEN the result contains the imported content
    AND the content includes real text from the original auto-insurance-knowledge.agent-skill.md
    """
    from app.prompts.loader import PromptLoader
    from app.tools.dispatcher import dispatch_tool

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    try:
        loader = PromptLoader()
        registry_entries = await loader.load_skill_registry_entries(session, leads_agent)
        content_by_slug = await loader.load_skill_content_by_slug(session, leads_agent)

        assert len(registry_entries) > 0, (
            "leads-agent must have imported skills"
        )

        result = await dispatch_tool(
            tool_name="load_skill",
            tool_args={"skill_name": "auto-insurance-knowledge"},
            client_id="quintana-seguros",
            lead_id=None,
            agent_slug="leads-agent",
            registry_entries=registry_entries,
            content_by_slug=content_by_slug,
        )
    finally:
        await session.close()
        await engine.dispose()

    # dispatch_tool('load_skill') returns plain string (WARNING-2 fix)
    assert isinstance(result, str), f"Expected plain string, got {type(result)}: {result!r}"
    assert "error" not in result.lower() or "Quintana" in result, (
        f"Expected success (skill content), got error: {result}"
    )
    # The imported content contains 'Quintana' (same text as the original file)
    assert "Quintana" in result, (
        "Content must come from the imported auto-insurance-knowledge content"
    )


@pytest.mark.asyncio
async def test_full_tool_flow_load_skill_filler_emitted_with_real_registry(tmp_path: Path):
    """Full flow: SSE stream emits registry filler_text before the tool executes.

    GIVEN quintana-seguros/leads-agent's imported skills include 'auto-insurance-knowledge'
    WHEN _stream_llm_response processes a load_skill ToolCallDelta
    THEN the filler_text from the registry ('Dejame buscar esa informacion...')
         is emitted to SSE BEFORE the tool executes
    """
    from app.prompts.loader import PromptLoader
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response

    session, engine, leads_agent, _jaumpablo = await _make_quintana_migrated_db(tmp_path)
    try:
        loader = PromptLoader()
        registry_entries = await loader.load_skill_registry_entries(session, leads_agent)
    finally:
        await session.close()
        await engine.dispose()

    # Verify the imported registry entry has a filler_text
    assert registry_entries, "Registry must have entries"
    skill_entry = next(e for e in registry_entries if e.name == "auto-insurance-knowledge")
    expected_filler = skill_entry.filler_text  # e.g. "Dejame buscar esa informacion..."

    execution_order: list[str] = []

    async def fake_stream(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-real-001",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "auto-insurance-knowledge"}),
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
            client_id="quintana-seguros",
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
async def test_full_tool_flow_multi_skill_sequential_calls():
    """Two sequential load_skill calls in one session load different skills independently.

    GIVEN a registry with skill-a and skill-b
    WHEN load_skill('skill-a') is called, then load_skill('skill-b')
    THEN each call returns its own skill's content independently
    AND neither call is blocked by the previous
    """
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.tools.dispatcher import dispatch_tool

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
    content_by_slug = {
        "skill-a": "# Skill A\nContent of skill A.",
        "skill-b": "# Skill B\nContent of skill B.",
    }

    # First call: load skill-a
    result_a = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "skill-a"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        content_by_slug=content_by_slug,
    )

    # Second call in same session: load skill-b
    result_b = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "skill-b"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        content_by_slug=content_by_slug,
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
