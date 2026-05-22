"""Unit tests for VoiceSessionContext and build_voice_context() — VSC-1, VSC-2.

TDD RED phase for Tasks 1.2, 1.3, 1.4.
Covers spec scenarios:
- VoiceSessionContext: all fields populated (happy path)
- VoiceSessionContext: missing optional data
- build_voice_context: full initiation path
- build_voice_context: no lead provided (anonymous call)
- build_voice_context: exception propagation from PromptLoader
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
    name: str = "Aria",
    system_prompt: str = "",
    knowledge_base: str | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.client_id = client_id
    agent.slug = slug
    agent.name = name
    agent.system_prompt = system_prompt
    agent.knowledge_base = knowledge_base
    agent.model = model
    agent.temperature = temperature
    agent.max_tokens = max_tokens
    agent.tools_enabled = tools_enabled
    return agent


def make_lead(
    name: str = "Carlos Méndez",
    car_make: str = "Toyota",
    car_model: str = "Corolla",
    car_year: int = 2021,
    current_insurance: str | None = "La Caja",
    status: str = "new",
    notes: str | None = None,
    extracted_facts: dict | None = None,
) -> MagicMock:
    lead = MagicMock()
    lead.name = name
    lead.car_make = car_make
    lead.car_model = car_model
    lead.car_year = car_year
    lead.current_insurance = current_insurance
    lead.status = status
    lead.notes = notes
    lead.extracted_facts = extracted_facts or {}
    return lead


def make_client(
    id: str = "acme",
    broker_name: str = "Acme Seguros",
    agent_name: str = "Aria",
) -> MagicMock:
    client = MagicMock()
    client.id = id
    client.broker_name = broker_name
    client.agent_name = agent_name
    return client


# ---------------------------------------------------------------------------
# Task 1.2 — VSC-1: VoiceSessionContext dataclass
# ---------------------------------------------------------------------------


def test_voice_session_context_is_importable():
    """VoiceSessionContext is importable from app.voice.context."""
    from app.voice.context import VoiceSessionContext  # noqa: F401


def test_voice_session_context_all_fields_populated():
    """VSC-1 happy path: all fields can be set and accessed.

    GIVEN a VoiceSessionContext instantiated with all fields
    WHEN accessing each field
    THEN each field holds its string value with no None values
    """
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="You are Aria.",
        skills_content="# Skill one",
        misc_notes="Cliente interesado en granizo",
        lead_profile="Nombre: Carlos\nAuto: Toyota Corolla 2021",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    assert ctx.system_prompt == "You are Aria."
    assert ctx.skills_content == "# Skill one"
    assert ctx.misc_notes == "Cliente interesado en granizo"
    assert ctx.lead_profile == "Nombre: Carlos\nAuto: Toyota Corolla 2021"
    assert ctx.model == "gpt-4o"
    assert ctx.temperature == 0.7
    assert ctx.max_tokens == 300
    assert ctx.tools is None


def test_voice_session_context_missing_optional_fields():
    """VSC-1 missing optional data: empty string defaults for missing fields.

    GIVEN a lead with no car data and no misc_notes
    WHEN VoiceSessionContext is instantiated
    THEN misc_notes is '' and lead_profile contains only non-empty fields
    """
    from app.voice.context import VoiceSessionContext

    ctx = VoiceSessionContext(
        system_prompt="You are Aria.",
        skills_content="",
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )

    assert ctx.misc_notes == ""
    assert ctx.lead_profile == ""
    assert ctx.skills_content == ""


def test_voice_session_context_is_frozen():
    """VoiceSessionContext must be immutable (frozen dataclass)."""
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

    with pytest.raises((AttributeError, TypeError)):
        ctx.system_prompt = "mutated"  # type: ignore[misc]


def test_voice_session_context_with_tools_list():
    """Triangulation: tools field accepts list[dict] value."""
    from app.voice.context import VoiceSessionContext

    tools = [{"type": "function", "function": {"name": "get_lead"}}]
    ctx = VoiceSessionContext(
        system_prompt="prompt",
        skills_content="",
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=tools,
    )

    assert ctx.tools == tools
    assert len(ctx.tools) == 1  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Task 1.3 — VSC-2: build_voice_context() async factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_returns_voice_session_context():
    """build_voice_context returns a VoiceSessionContext instance."""
    from app.voice.context import VoiceSessionContext, build_voice_context

    agent = make_agent()
    lead = make_lead()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="Rendered system prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="# Skill content")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=lead,
            db=mock_db,
            client=client,
        )

    assert isinstance(result, VoiceSessionContext)


@pytest.mark.asyncio
async def test_build_voice_context_system_prompt_from_render_for_agent():
    """VSC-2 full path: system_prompt equals output of PromptLoader.render_for_agent().

    GIVEN agent, lead, db, client are all provided
    WHEN build_voice_context() is called
    THEN VoiceSessionContext.system_prompt equals what render_for_agent returned
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    lead = make_lead()
    client = make_client()
    mock_db = AsyncMock()

    expected_prompt = "You are Aria, agent for Acme Seguros."

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value=expected_prompt)
        mock_instance.load_agent_skills = AsyncMock(return_value="")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=lead,
            db=mock_db,
            client=client,
        )

    assert result.system_prompt == expected_prompt


@pytest.mark.asyncio
async def test_build_voice_context_skills_index_from_load_agent_skills():
    """Phase 1 (dynamic-agent-skills): skills_index holds load_agent_skills() result.

    The old skills_content field is always None in registry mode.
    load_agent_skills() now returns a ## Available Skills index block (or '').
    build_voice_context() stores it in skills_index (None when empty string).

    GIVEN load_agent_skills returns a non-empty index block
    WHEN build_voice_context() is called
    THEN skills_index equals the load_agent_skills() output
    AND skills_content is None (registry mode is the only mode)
    """
    from app.voice.context import build_voice_context

    agent = make_agent(client_id="acme", slug="aria")
    lead = make_lead()
    client = make_client()
    mock_db = AsyncMock()

    expected_index = "## Available Skills\n| qora-info | Qora details | when needed |"

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value=expected_index)
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=lead,
            db=mock_db,
            client=client,
        )

    assert result.skills_index == expected_index
    assert result.skills_content is None  # Always None in registry mode
    # Verify load_agent_skills was called with correct args
    mock_instance.load_agent_skills.assert_called_once_with("acme", "aria")


@pytest.mark.asyncio
async def test_build_voice_context_misc_notes_from_extracted_facts():
    """VSC-2: misc_notes comes from lead.extracted_facts['misc_notes']."""
    from app.voice.context import build_voice_context

    lead = make_lead(extracted_facts={"misc_notes": "Cliente mencionó granizo"})
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
            lead=lead,
            db=mock_db,
            client=client,
        )

    assert result.misc_notes == "Cliente mencionó granizo"


@pytest.mark.asyncio
async def test_build_voice_context_lead_profile_contains_lead_name():
    """VSC-2: lead_profile contains lead name when lead is provided."""
    from app.voice.context import build_voice_context

    lead = make_lead(name="María López", car_make="Honda", car_model="Civic", car_year=2020)
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
            lead=lead,
            db=mock_db,
            client=client,
        )

    assert "María López" in result.lead_profile
    assert "Honda" in result.lead_profile


@pytest.mark.asyncio
async def test_build_voice_context_no_lead_returns_empty_misc_and_profile():
    """VSC-2 anonymous call: lead=None → misc_notes='' and lead_profile=''.

    GIVEN lead=None
    WHEN build_voice_context() is called
    THEN misc_notes is '' and lead_profile is ''
    AND system_prompt is still rendered
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt without lead")
        mock_instance.load_agent_skills = AsyncMock(return_value="")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.misc_notes == ""
    assert result.lead_profile == ""
    assert result.system_prompt == "prompt without lead"


@pytest.mark.asyncio
async def test_build_voice_context_model_temperature_max_tokens_from_agent():
    """VSC-2: model, temperature, max_tokens come from agent config."""
    from app.voice.context import build_voice_context

    agent = make_agent(model="gpt-4o-mini", temperature=0.5, max_tokens=500)
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

    assert result.model == "gpt-4o-mini"
    assert result.temperature == 0.5
    assert result.max_tokens == 500


# ---------------------------------------------------------------------------
# Task 1.4 — Exception propagation from PromptLoader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_propagates_render_for_agent_exception():
    """VSC-2 exception propagation: errors from render_for_agent bubble up.

    GIVEN PromptLoader.render_for_agent() raises an exception
    WHEN build_voice_context() is called
    THEN the exception propagates — no silent swallowing
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(
            side_effect=RuntimeError("DB connection failed")
        )
        mock_instance.load_agent_skills = AsyncMock(return_value="")

        with pytest.raises(RuntimeError, match="DB connection failed"):
            await build_voice_context(
                agent=agent,
                lead=None,
                db=mock_db,
                client=client,
            )


@pytest.mark.asyncio
async def test_build_voice_context_no_silent_exception_swallowing():
    """Triangulation: ValueError from render_for_agent also propagates."""
    from app.voice.context import build_voice_context

    agent = make_agent()
    client = make_client()
    mock_db = AsyncMock()

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(
            side_effect=ValueError("Agent not found")
        )
        mock_instance.load_agent_skills = AsyncMock(return_value="")

        with pytest.raises(ValueError, match="Agent not found"):
            await build_voice_context(
                agent=agent,
                lead=None,
                db=mock_db,
                client=client,
            )


# ---------------------------------------------------------------------------
# TTS fields in VoiceSessionContext
# ---------------------------------------------------------------------------


def make_agent_with_tts(
    tts_speed: float = 0.95,
    tts_stability: float = 0.4,
    tts_similarity_boost: float = 0.75,
) -> MagicMock:
    """Build a mock Agent with TTS fields set."""
    agent = make_agent()
    agent.tts_speed = tts_speed
    agent.tts_stability = tts_stability
    agent.tts_similarity_boost = tts_similarity_boost
    return agent


def test_voice_session_context_includes_tts_fields():
    """VoiceSessionContext can be constructed with tts_speed, tts_stability, tts_similarity_boost."""
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
        tts_speed=1.2,
        tts_stability=0.5,
        tts_similarity_boost=0.8,
    )

    assert ctx.tts_speed == 1.2
    assert ctx.tts_stability == 0.5
    assert ctx.tts_similarity_boost == 0.8


def test_voice_session_context_tts_defaults():
    """VoiceSessionContext defaults: tts_speed=0.95, tts_stability=0.4, tts_similarity_boost=0.75."""
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

    assert ctx.tts_speed == 0.95
    assert ctx.tts_stability == 0.4
    assert ctx.tts_similarity_boost == 0.75


@pytest.mark.asyncio
async def test_build_voice_context_reads_tts_from_agent():
    """build_voice_context() reads tts_speed/stability/similarity_boost from agent.

    GIVEN an agent with tts_speed=0.9, tts_stability=0.5, tts_similarity_boost=0.8
    WHEN build_voice_context() is called
    THEN VoiceSessionContext.tts_speed/stability/similarity_boost match the agent values
    """
    from app.voice.context import build_voice_context

    agent = make_agent_with_tts(tts_speed=0.9, tts_stability=0.5, tts_similarity_boost=0.8)
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

    assert result.tts_speed == 0.9
    assert result.tts_stability == 0.5
    assert result.tts_similarity_boost == 0.8


@pytest.mark.asyncio
async def test_build_voice_context_tts_falls_back_to_defaults_when_agent_columns_are_none():
    """build_voice_context() falls back to defaults when agent tts_* columns are None.

    GIVEN an agent where tts_speed/tts_stability/tts_similarity_boost are explicitly None
    WHEN build_voice_context() is called
    THEN tts_speed=0.95, tts_stability=0.4, tts_similarity_boost=0.75 (defaults)
    """
    from app.voice.context import build_voice_context

    agent = make_agent()
    # Simulate NULL columns (e.g. old DB row before migration backfill)
    agent.tts_speed = None
    agent.tts_stability = None
    agent.tts_similarity_boost = None
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

    assert result.tts_speed == 0.95
    assert result.tts_stability == 0.4
    assert result.tts_similarity_boost == 0.75


# ---------------------------------------------------------------------------
# CRITICAL 1: load_skill always available when agent has registry entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_load_skill_injected_when_registry_has_entries():
    """load_skill must be in tools when agent has registry entries, even if tools_enabled is '[]'.

    GIVEN an agent with tools_enabled='[]' (empty) but with registry entries
    WHEN build_voice_context() is called
    THEN the returned context.tools contains load_skill
    """
    from app.voice.context import build_voice_context
    from app.prompts.skill_loader import SkillRegistryEntry

    agent = make_agent(tools_enabled="[]")  # Empty tools list in DB
    client = make_client()
    mock_db = AsyncMock()

    registry_entry = SkillRegistryEntry(
        name="qora-info",
        description="Platform info",
        trigger_hint="About Qora",
        filler_text="Un momento...",
    )

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="## Available Skills\n...")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[registry_entry])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.tools is not None, "tools must not be None when registry has entries"
    tool_names = [t["function"]["name"] for t in result.tools]
    assert "load_skill" in tool_names, (
        f"load_skill must be in tools when registry has entries. Got: {tool_names}"
    )


@pytest.mark.asyncio
async def test_build_voice_context_load_skill_not_injected_when_registry_empty():
    """load_skill must NOT appear in tools when agent has no registry entries.

    GIVEN an agent with tools_enabled='[]' and no registry entries
    WHEN build_voice_context() is called
    THEN the returned context.tools is None (or doesn't contain load_skill)
    """
    from app.voice.context import build_voice_context

    agent = make_agent(tools_enabled="[]")
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

    # tools should be None (empty tools_enabled + no registry → no tools)
    if result.tools is not None:
        tool_names = [t["function"]["name"] for t in result.tools]
        assert "load_skill" not in tool_names, (
            "load_skill must NOT appear in tools when registry is empty"
        )


@pytest.mark.asyncio
async def test_build_voice_context_load_skill_alongside_crm_tools():
    """Triangulation: load_skill injected alongside CRM tools from tools_enabled.

    GIVEN an agent with tools_enabled='["get_lead_details"]' and registry entries
    WHEN build_voice_context() is called
    THEN both get_lead_details and load_skill are in context.tools
    """
    from app.voice.context import build_voice_context
    from app.prompts.skill_loader import SkillRegistryEntry

    agent = make_agent(tools_enabled='["get_lead_details"]')
    client = make_client()
    mock_db = AsyncMock()

    registry_entry = SkillRegistryEntry(
        name="qora-info",
        description="Platform info",
        trigger_hint="About Qora",
        filler_text="Un momento...",
    )

    with patch("app.voice.context.PromptLoader") as MockLoader:
        mock_instance = MockLoader.return_value
        mock_instance.render_for_agent = AsyncMock(return_value="prompt")
        mock_instance.load_agent_skills = AsyncMock(return_value="## Available Skills\n...")
        mock_instance.load_skill_registry_entries = AsyncMock(return_value=[registry_entry])

        result = await build_voice_context(
            agent=agent,
            lead=None,
            db=mock_db,
            client=client,
        )

    assert result.tools is not None
    tool_names = [t["function"]["name"] for t in result.tools]
    assert "load_skill" in tool_names, f"load_skill missing. Got: {tool_names}"
    assert "get_lead_details" in tool_names, f"get_lead_details missing. Got: {tool_names}"


# ---------------------------------------------------------------------------
# Task 1.5 — build_voice_context passes tool_config to build_tool_definitions
# Spec: Dynamic Schema Resolution for capture_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_voice_context_passes_tool_config_for_capture_data():
    """build_voice_context passes agent.tool_config to build_tool_definitions.

    GIVEN an agent with tools_enabled=["capture_data"] and tool_config JSON
    WHEN build_voice_context() is called
    THEN context.tools contains capture_data with dynamic schema from tool_config
    """
    from app.voice.context import build_voice_context
    import json

    tool_config_dict = {
        "capture_data": {
            "type": "object",
            "properties": {
                "marca": {"type": "string"},
                "modelo": {"type": "string"},
            },
            "required": ["lead_id", "marca"],
        }
    }
    agent = make_agent(tools_enabled='["capture_data"]')
    agent.tool_config = json.dumps(tool_config_dict)  # stored as JSON TEXT in DB
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

    assert result.tools is not None, "tools must not be None when capture_data has config"
    tool_names = [t["function"]["name"] for t in result.tools]
    assert "capture_data" in tool_names, f"capture_data missing from tools. Got: {tool_names}"
    # Verify dynamic schema was injected
    capture_def = next(t for t in result.tools if t["function"]["name"] == "capture_data")
    params = capture_def["function"]["parameters"]
    assert "marca" in params["properties"], "Dynamic property 'marca' must be in schema"


@pytest.mark.asyncio
async def test_build_voice_context_excludes_capture_data_when_tool_config_missing():
    """build_voice_context excludes capture_data when tool_config is NULL.

    GIVEN an agent with tools_enabled=["capture_data"] but tool_config=NULL
    WHEN build_voice_context() is called
    THEN context.tools is None or does not contain capture_data
    AND no exception is raised
    """
    from app.voice.context import build_voice_context

    agent = make_agent(tools_enabled='["capture_data"]')
    agent.tool_config = None  # NULL — no config stored
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

    # capture_data must be excluded (graceful degradation)
    if result.tools is not None:
        tool_names = [t["function"]["name"] for t in result.tools]
        assert "capture_data" not in tool_names, (
            "capture_data must be excluded when tool_config is NULL"
        )
