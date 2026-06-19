"""Unit tests for load_skill tool definition and dispatcher routing — Phase 2, Tasks 2.3 & 2.4.

Tests:
- load_skill appears in QORA_TOOL_DEFINITIONS
- _build_tool_definitions includes load_skill when in the enabled list
- load_skill schema has correct structure (function name, skill_name param, required)
- dispatch_tool routes load_skill to handle_load_skill
- dispatch_tool passes client_id and agent_slug to load_skill handler
- filler speech emitted before _execute_tool runs (Task 2.5)
"""

from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Task 2.3: Tool definition schema
# ---------------------------------------------------------------------------


def test_load_skill_in_qora_tool_definitions():
    """load_skill must be present in QORA_TOOL_DEFINITIONS."""
    from app.voice.webhook import QORA_TOOL_DEFINITIONS

    assert "load_skill" in QORA_TOOL_DEFINITIONS


def test_load_skill_tool_schema_structure():
    """load_skill definition must have correct OpenAI function calling schema."""
    from app.voice.webhook import QORA_TOOL_DEFINITIONS

    tool = QORA_TOOL_DEFINITIONS["load_skill"]
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "load_skill"
    assert "description" in fn
    assert len(fn["description"]) > 20  # Non-trivial description

    params = fn["parameters"]
    assert params["type"] == "object"
    assert "skill_name" in params["properties"]
    assert "skill_name" in params["required"]


def test_load_skill_param_is_string_type():
    """load_skill skill_name parameter must be of type string."""
    from app.voice.webhook import QORA_TOOL_DEFINITIONS

    tool = QORA_TOOL_DEFINITIONS["load_skill"]
    skill_name_param = tool["function"]["parameters"]["properties"]["skill_name"]
    assert skill_name_param["type"] == "string"


def test_build_tool_definitions_includes_load_skill():
    """_build_tool_definitions returns load_skill when it's in the enabled list."""
    from app.voice.webhook import _build_tool_definitions

    tools = _build_tool_definitions(["load_skill"])
    assert tools is not None
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "load_skill"


def test_build_tool_definitions_includes_load_skill_alongside_crm_tools():
    """_build_tool_definitions includes both load_skill and CRM tools correctly."""
    from app.voice.webhook import _build_tool_definitions

    tools = _build_tool_definitions(["load_skill", "get_lead_details"])
    assert tools is not None
    names = [t["function"]["name"] for t in tools]
    assert "load_skill" in names
    assert "get_lead_details" in names


@pytest.mark.asyncio
async def test_stream_passes_agent_tool_config_to_execute_tool():
    """_stream_llm_response forwards cached context tool_config to tool dispatch.

    This covers the end-to-end webhook → dispatcher → capture_data gap: the
    dispatcher can only validate capture_data if the webhook passes the agent's
    parsed tool_config from VoiceSessionContext.
    """
    import json
    from unittest.mock import MagicMock, patch

    from app.ai.llm_streaming import StreamDone, ToolCallDelta
    from app.voice.context import VoiceSessionContext
    from app.voice.session import ConversationState
    from app.voice.webhook import _stream_llm_response

    tool_config = {
        "capture_data": {
            "parameters": {
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "marca": {"type": "string"}},
                "required": ["lead_id", "marca"],
            }
        }
    }
    captured_kwargs = {}

    async def fake_stream_events(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-001",
            function_name="capture_data",
            function_args=json.dumps({"lead_id": "lead-1", "marca": "Toyota"}),
        )
        yield StreamDone()

    async def fake_execute_tool(tool_name, tool_args, client_id, lead_id, **kwargs):
        captured_kwargs.update(kwargs)
        return {"status": "captured", "fields": ["marca"]}

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events
    conv_state = ConversationState(
        conversation_id="conv-1",
        client_id="client-1",
        lead_id="lead-1",
        session_id="session-1",
        context=VoiceSessionContext(
            system_prompt="prompt",
            skills_content=None,
            misc_notes="",
            lead_profile="",
            model="gpt-4o",
            temperature=0.7,
            max_tokens=300,
            tools=None,
            agent_tool_config=tool_config,
        ),
    )

    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute_tool):
        async for _chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Hola"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="client-1",
            lead_id="lead-1",
            session_id=None,
            conversation_id="conv-1",
            conv_state=conv_state,
        ):
            pass

    assert captured_kwargs["agent_tool_config"] == tool_config


def test_crm_tools_unchanged_after_load_skill_added():
    """CRM tool schemas must be unchanged after adding load_skill to QORA_TOOL_DEFINITIONS.

    Phase 2: register_interest, mark_not_interested, and schedule_followup removed.
    Only the remaining active CRM tools are checked here.
    """
    from app.voice.webhook import QORA_TOOL_DEFINITIONS

    # Phase 2: legacy tools removed from QORA_TOOL_DEFINITIONS
    active_crm_tools = [
        "get_lead_details",
        "get_lead_profile",
        "get_lead_history",
        "get_lead_pain_points",
        "capture_data",
    ]
    for name in active_crm_tools:
        assert name in QORA_TOOL_DEFINITIONS, f"Active CRM tool {name!r} missing from definitions"
        tool = QORA_TOOL_DEFINITIONS[name]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == name

    # Legacy tools must NOT be in definitions post-Phase 2
    removed_tools = ["register_interest", "mark_not_interested", "schedule_followup"]
    for name in removed_tools:
        assert name not in QORA_TOOL_DEFINITIONS, (
            f"Legacy tool {name!r} must be removed from QORA_TOOL_DEFINITIONS in Phase 2"
        )


# ---------------------------------------------------------------------------
# Task 2.4: Dispatcher routes load_skill correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_routes_load_skill(tmp_path: Path):
    """dispatch_tool routes 'load_skill' to handle_load_skill handler."""
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.tools.dispatcher import dispatch_tool

    # Write skill file to tmp_path
    skills_dir = tmp_path / "clients" / "test-client" / "agents" / "test-agent" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "qora-info.agent-skill.md").write_text("# Qora Info\nPlatform details.")

    registry_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Déjame revisar eso...",
        )
    ]

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "qora-info"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        clients_dir=tmp_path / "clients",
    )

    # dispatch_tool returns plain string (not wrapped dict) — WARNING-2 fix
    assert isinstance(result, str), f"Expected plain string, got {type(result)}: {result!r}"
    assert "error" not in result.lower() or result == "# Qora Info\nPlatform details.", (
        f"Unexpected error in result: {result}"
    )
    assert result == "# Qora Info\nPlatform details."


@pytest.mark.asyncio
async def test_dispatch_tool_load_skill_unknown_name(tmp_path: Path):
    """dispatch_tool returns graceful error for unknown skill name."""
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.tools.dispatcher import dispatch_tool

    registry_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Déjame revisar eso...",
        )
    ]

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "nonexistent-skill"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        clients_dir=tmp_path / "clients",
    )

    # dispatch_tool returns plain string (not wrapped dict) — WARNING-2 fix
    assert isinstance(result, str), f"Expected plain string, got {type(result)}: {result!r}"
    assert "nonexistent-skill" in result


@pytest.mark.asyncio
async def test_dispatch_tool_load_skill_no_registry_entries(tmp_path: Path):
    """dispatch_tool returns error when registry_entries is empty."""
    from app.tools.dispatcher import dispatch_tool

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "any-skill"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=[],
        clients_dir=tmp_path / "clients",
    )

    # dispatch_tool returns plain string (not wrapped dict) — WARNING-2 fix
    assert isinstance(result, str), f"Expected plain string, got {type(result)}: {result!r}"
    # Error message should describe the problem
    assert "any-skill" in result or "error" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_tool_crm_tools_unchanged_after_load_skill_wired(tmp_path: Path):
    """CRM tools still route correctly after load_skill is wired into dispatcher."""
    from app.tools.dispatcher import dispatch_tool
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/disp_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads
        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    try:
        async with db_module.async_session_factory() as sess:
            result = await dispatch_tool(
                tool_name="get_lead_details",
                tool_args={"lead_id": "lead-quintana-001"},
                client_id="quintana-seguros",
                lead_id="lead-quintana-001",
                session=sess,
            )

        assert "error" not in result
        assert result["id"] == "lead-quintana-001"
    finally:
        await db_module.close_db()


# ---------------------------------------------------------------------------
# WARNING 2: dispatch_tool returns raw skill text, not wrapped dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_tool_load_skill_returns_plain_string(tmp_path: Path):
    """dispatch_tool('load_skill') must return a plain string, not {'content': ...}.

    The LLM receives the tool result via json.dumps(tool_result). A plain string
    gives the LLM clean text. A wrapped dict forces the LLM to parse JSON metadata.
    """
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.tools.dispatcher import dispatch_tool

    skills_dir = tmp_path / "clients" / "test-client" / "agents" / "test-agent" / "skills"
    skills_dir.mkdir(parents=True)
    skill_content = "# Qora Info\nThis is the platform overview."
    (skills_dir / "qora-info.agent-skill.md").write_text(skill_content)

    registry_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Déjame revisar...",
        )
    ]

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "qora-info"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=registry_entries,
        clients_dir=tmp_path / "clients",
    )

    # Result must be a plain string (the skill text), not a dict
    assert isinstance(result, str), (
        f"dispatch_tool('load_skill') must return a plain string. Got {type(result)}: {result!r}"
    )
    assert result == skill_content, (
        f"Expected skill file content. Got: {result!r}"
    )


@pytest.mark.asyncio
async def test_dispatch_tool_load_skill_error_still_returns_string(tmp_path: Path):
    """Triangulation: dispatch_tool('load_skill') returns error string when skill not found."""
    from app.tools.dispatcher import dispatch_tool

    result = await dispatch_tool(
        tool_name="load_skill",
        tool_args={"skill_name": "nonexistent"},
        client_id="test-client",
        lead_id=None,
        agent_slug="test-agent",
        registry_entries=[],
        clients_dir=tmp_path / "clients",
    )

    # Error case must also be a plain string
    assert isinstance(result, str), (
        f"dispatch_tool('load_skill') error must be a plain string. Got {type(result)}: {result!r}"
    )
    assert "nonexistent" in result or "error" in result.lower(), (
        f"Expected error info about 'nonexistent' skill. Got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Task 2.5: Filler speech — emitted BEFORE _execute_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filler_emitted_before_tool_execution():
    """Filler SSE tokens are emitted BEFORE _execute_tool is called.

    GIVEN a ToolCallDelta for load_skill with filler_text in the registry
    WHEN _stream_llm_response processes the event
    THEN the filler text SSE chunk is yielded BEFORE the tool handler runs.
    """
    import json
    from unittest.mock import MagicMock, patch
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response

    execution_order = []

    async def fake_stream_events(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-001",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "qora-info"}),
        )
        yield StreamDone()

    async def fake_execute_tool(tool_name, tool_args, client_id, lead_id, **kwargs):
        execution_order.append("tool_executed")
        return {"content": "# Qora\nContent."}

    collected_chunks = []

    # We need to intercept when chunks are yielded vs when tool executes
    # Use a custom wrapper that tracks ordering
    from app.prompts.skill_loader import SkillRegistryEntry

    registry_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Déjame revisar eso...",
        )
    ]

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events

    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute_tool):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Hola"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="test-client",
            lead_id=None,
            session_id=None,
            conversation_id=None,
            registry_entries=registry_entries,
        ):
            collected_chunks.append(chunk)
            # SSE chunks contain JSON — check for the filler text (may be unicode-escaped)
            # "revisar eso" is ASCII-safe portion of "Déjame revisar eso..."
            if "revisar eso" in chunk and "tool_executed" not in execution_order:
                execution_order.append("filler_chunk_yielded")

    # Filler must appear before tool execution in the execution order
    assert "filler_chunk_yielded" in execution_order, (
        "Filler text chunk must be yielded before tool execution. "
        f"Execution order: {execution_order}. "
        f"Chunks: {collected_chunks}"
    )
    assert "tool_executed" in execution_order, "Tool must have been executed"

    filler_idx = execution_order.index("filler_chunk_yielded")
    tool_idx = execution_order.index("tool_executed")
    assert filler_idx < tool_idx, (
        f"Filler (idx={filler_idx}) must be emitted BEFORE tool execution (idx={tool_idx})"
    )


@pytest.mark.asyncio
async def test_filler_contains_registry_filler_text():
    """Filler chunk contains the filler_text from the registry entry."""
    import json
    from unittest.mock import MagicMock, patch
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response
    from app.prompts.skill_loader import SkillRegistryEntry

    registry_entries = [
        SkillRegistryEntry(
            name="pricing-guide",
            description="Pricing info",
            trigger_hint="Pricing questions",
            filler_text="Un momento, consultando precios...",
        )
    ]

    async def fake_stream(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-002",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "pricing-guide"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream

    async def fake_execute(tool_name, tool_args, client_id, lead_id, **kwargs):
        return {"content": "pricing content"}

    collected_chunks = []
    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "¿Cuánto cuesta?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="test-client",
            lead_id=None,
            session_id=None,
            conversation_id=None,
            registry_entries=registry_entries,
        ):
            collected_chunks.append(chunk)

    # "consultando precios" is ASCII-safe — no unicode escape needed
    filler_chunks = [c for c in collected_chunks if "consultando precios" in c]
    assert filler_chunks, (
        "Expected filler text 'consultando precios...' in SSE chunks. "
        f"Got chunks: {collected_chunks}"
    )


@pytest.mark.asyncio
async def test_default_filler_for_non_load_skill_tool():
    """Default filler is emitted for CRM tools when no registry filler applies."""
    import json
    from unittest.mock import MagicMock, patch
    from app.ai.llm_streaming import ToolCallDelta, StreamDone
    from app.voice.webhook import _stream_llm_response

    async def fake_stream(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-003",
            function_name="get_lead_details",
            function_args=json.dumps({"lead_id": "lead-001"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream

    async def fake_execute(tool_name, tool_args, client_id, lead_id, **kwargs):
        return {"id": "lead-001", "name": "Juan"}

    collected_chunks = []
    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Dame datos"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="test-client",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            registry_entries=[],
        ):
            collected_chunks.append(chunk)

    # Must emit the DEFAULT_FILLER text before tool execution
    from app.voice.webhook import DEFAULT_FILLER
    # DEFAULT_FILLER may contain non-ASCII — check by decoding the JSON chunks
    import json as _json
    filler_found = False
    for chunk in collected_chunks:
        if not chunk.startswith("data: "):
            continue
        raw = chunk[len("data: "):]
        if raw.strip() == "[DONE]":
            continue
        try:
            parsed = _json.loads(raw)
            choices = parsed.get("choices", [])
            if choices:
                delta_content = choices[0].get("delta", {}).get("content", "")
                if delta_content == DEFAULT_FILLER:
                    filler_found = True
                    break
        except Exception:
            continue
    assert filler_found, (
        f"Expected DEFAULT_FILLER {DEFAULT_FILLER!r} in SSE content chunks. "
        f"Got chunks: {collected_chunks}"
    )
