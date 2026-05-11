"""Unit tests for agents schemas — AgentCreate, AgentUpdate, AgentResponse.

Covers:
- AgentCreate field defaults
- AgentCreate slug validation (^[a-z0-9][a-z0-9-]*[a-z0-9]?$)
- AgentCreate tools_enabled validation (must be list[str] of known tool names)
- AgentUpdate all fields optional, slug NOT allowed
- AgentResponse model fields

tools_enabled is list[str] in the API contract (not a JSON string).
The service layer serializes to/from JSON string for DB storage.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Task 1.1 — AgentCreate defaults and required fields
# ---------------------------------------------------------------------------


def test_agent_create_minimal_valid():
    """AgentCreate accepts minimal required fields with correct defaults."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(slug="main-agent", name="Main Agent", voice_id="voice-123")

    assert agent.slug == "main-agent"
    assert agent.name == "Main Agent"
    assert agent.voice_id == "voice-123"
    # Defaults
    assert agent.model == "gpt-4o"
    assert agent.temperature == 0.7
    assert agent.max_tokens == 300
    assert agent.is_default is False
    assert agent.system_prompt is None
    assert agent.knowledge_base is None
    # tools_enabled default is a list with all registered tools (Issue #36 adds 3 more)
    assert isinstance(agent.tools_enabled, list)
    # Must include the original 4 tools
    expected_original = {
        "get_lead_details",
        "register_interest",
        "mark_not_interested",
        "schedule_followup",
    }
    assert expected_original.issubset(
        set(agent.tools_enabled)
    ), f"Original tools missing from default: {expected_original - set(agent.tools_enabled)}"
    # Must also include Issue #36 new tools
    expected_new = {
        "get_lead_profile",
        "get_lead_history",
        "get_lead_pain_points",
    }
    assert expected_new.issubset(
        set(agent.tools_enabled)
    ), f"New Issue #36 tools missing from default: {expected_new - set(agent.tools_enabled)}"


def test_agent_create_custom_values():
    """AgentCreate accepts all fields when provided."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(
        slug="custom-agent",
        name="Custom",
        voice_id="v-abc",
        model="gpt-3.5-turbo",
        temperature=0.5,
        max_tokens=500,
        system_prompt="You are helpful.",
        knowledge_base="kb-content",
        tools_enabled=["get_lead_details"],
        is_default=True,
    )

    assert agent.model == "gpt-3.5-turbo"
    assert agent.temperature == 0.5
    assert agent.max_tokens == 500
    assert agent.system_prompt == "You are helpful."
    assert agent.knowledge_base == "kb-content"
    assert agent.is_default is True


# ---------------------------------------------------------------------------
# Task 1.1 — Slug validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "main",
        "main-agent",
        "agent-v2",
        "a",
        "1",
        "abc123",
        "a1b2-c3",
    ],
)
def test_agent_create_valid_slugs(slug: str):
    """AgentCreate accepts valid slugs."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(slug=slug, name="Test", voice_id="v1")
    assert agent.slug == slug


@pytest.mark.parametrize(
    "bad_slug",
    [
        "Main",  # uppercase
        "main agent",  # space
        "-main",  # leading hyphen
        "main-",  # trailing hyphen
        "My Client!",  # special chars
        "",  # empty
        "MAIN-AGENT",  # all uppercase
    ],
)
def test_agent_create_invalid_slug_raises_422(bad_slug: str):
    """AgentCreate raises ValidationError for invalid slugs."""
    from app.agents.schemas import AgentCreate

    with pytest.raises(ValidationError):
        AgentCreate(slug=bad_slug, name="Test", voice_id="v1")


# ---------------------------------------------------------------------------
# Task 1.1 — tools_enabled validation
# ---------------------------------------------------------------------------


def test_agent_create_invalid_tool_raises_422():
    """AgentCreate raises ValidationError when tools_enabled contains unknown tool."""
    from app.agents.schemas import AgentCreate

    with pytest.raises(ValidationError) as exc_info:
        AgentCreate(
            slug="test",
            name="Test",
            voice_id="v1",
            tools_enabled=["get_lead_details", "nonexistent_tool"],
        )

    # Error message should mention the invalid tool
    assert "nonexistent_tool" in str(exc_info.value)


def test_agent_create_valid_subset_of_tools():
    """AgentCreate accepts a valid subset of tool names."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(
        slug="test",
        name="Test",
        voice_id="v1",
        tools_enabled=["get_lead_details", "register_interest"],
    )
    assert isinstance(agent.tools_enabled, list)
    assert agent.tools_enabled == ["get_lead_details", "register_interest"]


def test_agent_create_invalid_tool_name_string_raises_422():
    """AgentCreate raises ValidationError when tools_enabled contains an unknown tool name."""
    from app.agents.schemas import AgentCreate

    with pytest.raises(ValidationError):
        AgentCreate(
            slug="test",
            name="Test",
            voice_id="v1",
            tools_enabled=["nonexistent_tool"],
        )


def test_agent_create_tools_not_a_list_raises_422():
    """AgentCreate raises ValidationError when tools_enabled is not a list (e.g. str)."""
    from app.agents.schemas import AgentCreate

    with pytest.raises(ValidationError):
        AgentCreate(
            slug="test",
            name="Test",
            voice_id="v1",
            tools_enabled="get_lead_details",  # string instead of list
        )


# ---------------------------------------------------------------------------
# Task 1.1 — AgentUpdate: all fields optional, slug NOT allowed
# ---------------------------------------------------------------------------


def test_agent_update_empty_body_is_valid():
    """AgentUpdate with no fields is valid (PATCH no-op)."""
    from app.agents.schemas import AgentUpdate

    update = AgentUpdate()
    data = update.model_dump(exclude_unset=True)
    assert data == {}


def test_agent_update_partial_fields():
    """AgentUpdate accepts partial fields."""
    from app.agents.schemas import AgentUpdate

    update = AgentUpdate(name="New Name", temperature=0.9)
    data = update.model_dump(exclude_unset=True)
    assert data["name"] == "New Name"
    assert data["temperature"] == 0.9
    # Other fields not set
    assert "voice_id" not in data
    assert "model" not in data


def test_agent_update_invalid_tool_raises_422():
    """AgentUpdate raises ValidationError when tools_enabled has invalid tool."""
    from app.agents.schemas import AgentUpdate

    with pytest.raises(ValidationError) as exc_info:
        AgentUpdate(tools_enabled=["bad_tool_name"])

    assert "bad_tool_name" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Task 1.1 — AgentResponse shape
# ---------------------------------------------------------------------------


def test_agent_response_from_dict():
    """AgentResponse can be constructed from a dict with all required fields."""
    from datetime import datetime, timezone

    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="uuid-1234",
        client_id="test-client",
        slug="main",
        name="Main Agent",
        voice_id="v1",
        system_prompt=None,
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=["get_lead_details"],
        is_active=True,
        is_default=True,
        created_at=now,
    )

    assert resp.agent_id == "uuid-1234"
    assert resp.client_id == "test-client"
    assert resp.slug == "main"
    assert resp.is_default is True
    assert resp.is_active is True
    assert isinstance(resp.tools_enabled, list)
    assert resp.tools_enabled == ["get_lead_details"]


# ---------------------------------------------------------------------------
# Task 1.1 (NEW) — elevenlabs_agent_id in AgentCreate, AgentUpdate, AgentResponse
# ---------------------------------------------------------------------------


def test_agent_create_elevenlabs_agent_id_defaults_to_none():
    """AgentCreate defaults elevenlabs_agent_id to None when not provided."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(slug="main", name="Main", voice_id="v1")
    assert agent.elevenlabs_agent_id is None


def test_agent_create_accepts_elevenlabs_agent_id():
    """AgentCreate accepts a non-null elevenlabs_agent_id string."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(
        slug="main", name="Main", voice_id="v1", elevenlabs_agent_id="el_abc123"
    )
    assert agent.elevenlabs_agent_id == "el_abc123"


def test_agent_update_elevenlabs_agent_id_defaults_to_none():
    """AgentUpdate defaults elevenlabs_agent_id to None when not provided."""
    from app.agents.schemas import AgentUpdate

    update = AgentUpdate()
    data = update.model_dump(exclude_unset=True)
    # Not set — should not appear in the unset dump
    assert "elevenlabs_agent_id" not in data


def test_agent_update_accepts_elevenlabs_agent_id():
    """AgentUpdate accepts elevenlabs_agent_id string."""
    from app.agents.schemas import AgentUpdate

    update = AgentUpdate(elevenlabs_agent_id="el_xyz")
    data = update.model_dump(exclude_unset=True)
    assert data["elevenlabs_agent_id"] == "el_xyz"


def test_agent_response_includes_elevenlabs_agent_id_null():
    """AgentResponse can have elevenlabs_agent_id=None."""
    from datetime import datetime, timezone
    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="uuid-1",
        client_id="c1",
        slug="main",
        name="Main",
        voice_id="v1",
        system_prompt=None,
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=[],
        is_active=True,
        is_default=False,
        created_at=now,
        elevenlabs_agent_id=None,
        custom_llm_url="/api/v1/voice/c1/custom-llm/chat/completions",
        is_conversation_ready=False,
        has_prompt=False,
        has_elevenlabs_agent_id=False,
    )
    assert resp.elevenlabs_agent_id is None
    assert resp.custom_llm_url == "/api/v1/voice/c1/custom-llm/chat/completions"
    assert resp.is_conversation_ready is False
    assert resp.has_prompt is False
    assert resp.has_elevenlabs_agent_id is False


def test_agent_response_includes_elevenlabs_agent_id_value():
    """AgentResponse can have a non-null elevenlabs_agent_id."""
    from datetime import datetime, timezone
    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="uuid-2",
        client_id="c2",
        slug="main",
        name="Main",
        voice_id="v1",
        system_prompt="You are Sofia...",
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=[],
        is_active=True,
        is_default=True,
        created_at=now,
        elevenlabs_agent_id="el_abc",
        custom_llm_url="/api/v1/voice/c2/custom-llm/chat/completions",
        is_conversation_ready=True,
        has_prompt=True,
        has_elevenlabs_agent_id=True,
    )
    assert resp.elevenlabs_agent_id == "el_abc"
    assert resp.is_conversation_ready is True
    assert resp.has_prompt is True
    assert resp.has_elevenlabs_agent_id is True


# ---------------------------------------------------------------------------
# Task 1.1 (NEW) — Readiness flags computed logic
# ---------------------------------------------------------------------------


def test_readiness_ready_agent():
    """is_conversation_ready is True when agent has prompt AND elevenlabs_agent_id."""
    from datetime import datetime, timezone
    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="r1",
        client_id="c1",
        slug="main",
        name="Main",
        voice_id="v1",
        system_prompt="You are Sofia.",
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=[],
        is_active=True,
        is_default=True,
        created_at=now,
        elevenlabs_agent_id="el_abc",
        custom_llm_url="/api/v1/voice/c1/custom-llm/chat/completions",
        is_conversation_ready=True,
        has_prompt=True,
        has_elevenlabs_agent_id=True,
    )
    assert resp.is_conversation_ready is True
    assert resp.has_prompt is True
    assert resp.has_elevenlabs_agent_id is True


def test_readiness_missing_el_id():
    """is_conversation_ready is False when elevenlabs_agent_id is null."""
    from datetime import datetime, timezone
    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="r2",
        client_id="c1",
        slug="main",
        name="Main",
        voice_id="v1",
        system_prompt="You are Sofia.",
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=[],
        is_active=True,
        is_default=False,
        created_at=now,
        elevenlabs_agent_id=None,
        custom_llm_url="/api/v1/voice/c1/custom-llm/chat/completions",
        is_conversation_ready=False,
        has_prompt=True,
        has_elevenlabs_agent_id=False,
    )
    assert resp.is_conversation_ready is False
    assert resp.has_elevenlabs_agent_id is False


def test_readiness_missing_prompt():
    """is_conversation_ready is False when system_prompt is empty."""
    from datetime import datetime, timezone
    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="r3",
        client_id="c1",
        slug="main",
        name="Main",
        voice_id="v1",
        system_prompt="",
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=[],
        is_active=True,
        is_default=False,
        created_at=now,
        elevenlabs_agent_id="el_abc",
        custom_llm_url="/api/v1/voice/c1/custom-llm/chat/completions",
        is_conversation_ready=False,
        has_prompt=False,
        has_elevenlabs_agent_id=True,
    )
    assert resp.is_conversation_ready is False
    assert resp.has_prompt is False
