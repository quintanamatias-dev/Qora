"""Unit tests for tools registry — build_tool_definitions and capture_data support.

Spec: Dynamic Schema Resolution for capture_data
Requirements:
- build_tool_definitions with agent_tool_config returns dynamic capture_data schema
- build_tool_definitions without config excludes capture_data, no exception
- capture_data present in QORA_TOOL_NAMES
- build_capture_data_definition returns None when tool_config missing key
- Static tools (get_lead_details etc.) are unaffected by agent_tool_config

Task 1.5 RED/GREEN — tests for registry changes.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Scenario: capture_data in QORA_TOOL_NAMES
# Spec: AC-3 — capture_data is a valid tool name for AgentCreate
# ---------------------------------------------------------------------------


def test_capture_data_in_qora_tool_names():
    """capture_data must be in QORA_TOOL_NAMES (derived from TOOL_DEFINITIONS)."""
    from app.tools.registry import TOOL_DEFINITIONS

    assert "capture_data" in TOOL_DEFINITIONS, (
        "capture_data must be registered in TOOL_DEFINITIONS"
    )


# ---------------------------------------------------------------------------
# Scenario: Dynamic schema injected at call time
# Spec: AC-1 — build_tool_definitions with agent_tool_config returns capture_data entry
# ---------------------------------------------------------------------------


def test_build_tool_definitions_with_tool_config_includes_capture_data():
    """build_tool_definitions with agent_tool_config returns capture_data with dynamic schema.

    GIVEN agent has tool_config with capture_data parameters
    WHEN build_tool_definitions([capture_data], agent_tool_config=...) is called
    THEN returned list includes capture_data with agent-specific parameters
    """
    from app.tools.registry import build_tool_definitions

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "marca": {"type": "string"},
                "modelo": {"type": "string"},
            },
            "required": ["lead_id", "marca"],
        }
    }

    result = build_tool_definitions(["capture_data"], agent_tool_config=tool_config)

    assert result is not None
    assert len(result) == 1
    capture_def = result[0]
    assert capture_def["function"]["name"] == "capture_data"
    # The dynamic parameters must include the agent-specific properties
    params = capture_def["function"]["parameters"]
    assert "marca" in params["properties"]
    assert "modelo" in params["properties"]
    # lead_id must always be present
    assert "lead_id" in params["properties"]
    # required must include lead_id
    assert "lead_id" in params["required"]
    assert "marca" in params["required"]


def test_build_tool_definitions_with_mixed_tools_and_config():
    """build_tool_definitions with capture_data + static tools returns both.

    GIVEN agent requesting [capture_data, get_lead_details] with tool_config
    WHEN build_tool_definitions is called
    THEN capture_data uses dynamic schema; get_lead_details uses static definition
    """
    from app.tools.registry import build_tool_definitions

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {"marca": {"type": "string"}},
            "required": ["lead_id", "marca"],
        }
    }

    result = build_tool_definitions(
        ["capture_data", "get_lead_details"],
        agent_tool_config=tool_config,
    )

    assert result is not None
    assert len(result) == 2
    names = {d["function"]["name"] for d in result}
    assert "capture_data" in names
    assert "get_lead_details" in names


# ---------------------------------------------------------------------------
# Scenario: No agent_tool_config supplied
# Spec: AC-2 — capture_data excluded, no exception
# ---------------------------------------------------------------------------


def test_build_tool_definitions_without_config_excludes_capture_data():
    """build_tool_definitions without agent_tool_config excludes capture_data.

    GIVEN build_tool_definitions([capture_data], agent_tool_config=None)
    WHEN called
    THEN result is None (empty list → None) and no exception raised
    """
    from app.tools.registry import build_tool_definitions

    result = build_tool_definitions(["capture_data"], agent_tool_config=None)
    assert result is None


def test_build_tool_definitions_capture_data_missing_key_returns_none():
    """build_tool_definitions with tool_config missing capture_data key excludes it.

    GIVEN tool_config = {"other_key": {...}} (no capture_data)
    WHEN build_tool_definitions([capture_data], agent_tool_config=tool_config)
    THEN capture_data excluded; no exception
    """
    from app.tools.registry import build_tool_definitions

    tool_config = {"unknown_key": {"some": "value"}}
    result = build_tool_definitions(["capture_data"], agent_tool_config=tool_config)
    assert result is None


# ---------------------------------------------------------------------------
# Scenario: Static tools unaffected by agent_tool_config
# ---------------------------------------------------------------------------


def test_build_tool_definitions_static_tools_unaffected_by_config():
    """Static tools (non-capture_data) are unchanged regardless of agent_tool_config."""
    from app.tools.registry import build_tool_definitions, TOOL_DEFINITIONS

    # Without config
    result_no_config = build_tool_definitions(["get_lead_details"])
    # With config
    result_with_config = build_tool_definitions(
        ["get_lead_details"],
        agent_tool_config={"capture_data": {}},
    )

    assert result_no_config is not None
    assert result_with_config is not None
    # Both should return the same static definition
    assert result_no_config == result_with_config
    assert result_no_config[0] == TOOL_DEFINITIONS["get_lead_details"]


# ---------------------------------------------------------------------------
# build_capture_data_definition — pure function tests
# ---------------------------------------------------------------------------


def test_build_capture_data_definition_returns_none_for_empty_config():
    """build_capture_data_definition returns None for empty dict."""
    from app.tools.registry import build_capture_data_definition

    assert build_capture_data_definition({}) is None


def test_build_capture_data_definition_returns_none_for_missing_key():
    """build_capture_data_definition returns None when capture_data key absent."""
    from app.tools.registry import build_capture_data_definition

    result = build_capture_data_definition({"other_tool": {}})
    assert result is None


def test_build_capture_data_definition_produces_valid_openai_schema():
    """build_capture_data_definition returns a valid OpenAI function-calling schema."""
    from app.tools.registry import build_capture_data_definition

    tool_config = {
        "capture_data": {
            "description": "Capturá los datos del vehículo",
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
                "car_year": {"type": "integer"},
            },
            "required": ["lead_id", "car_make"],
        }
    }

    result = build_capture_data_definition(tool_config)

    assert result is not None
    assert result["type"] == "function"
    assert result["function"]["name"] == "capture_data"
    assert result["function"]["description"] == "Capturá los datos del vehículo"
    params = result["function"]["parameters"]
    assert "car_make" in params["properties"]
    assert "car_year" in params["properties"]
    assert "lead_id" in params["properties"]
    assert "lead_id" in params["required"]
    assert "car_make" in params["required"]


def test_build_capture_data_definition_injects_lead_id_when_missing():
    """build_capture_data_definition injects lead_id into properties and required."""
    from app.tools.registry import build_capture_data_definition

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {"marca": {"type": "string"}},
            "required": ["marca"],  # no lead_id
        }
    }

    result = build_capture_data_definition(tool_config)

    assert result is not None
    params = result["function"]["parameters"]
    assert "lead_id" in params["properties"]
    assert "lead_id" in params["required"]
    # Original required fields preserved
    assert "marca" in params["required"]
