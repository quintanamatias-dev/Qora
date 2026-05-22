"""QORA Tools — central registry of tool definitions.

Single source of truth for:
- TOOL_DEFINITIONS: all OpenAI function-calling schemas, keyed by tool name
- TOOL_FILLER_PHRASES: per-tool filler speech phrases
- DEFAULT_FILLER: fallback filler phrase
- build_tool_definitions(): filter + assemble tool list for OpenAI API
- build_capture_data_definition(): build dynamic capture_data schema from agent config

Each tool module owns its TOOL_DEFINITION constant. This module assembles them.
"""

from __future__ import annotations

import logging

from app.tools.get_lead_details import TOOL_DEFINITION as _get_lead_details_def
from app.tools.register_interest import TOOL_DEFINITION as _register_interest_def
from app.tools.mark_not_interested import TOOL_DEFINITION as _mark_not_interested_def
from app.tools.schedule_followup import TOOL_DEFINITION as _schedule_followup_def
from app.tools.get_lead_profile import TOOL_DEFINITION as _get_lead_profile_def
from app.tools.get_lead_history import TOOL_DEFINITION as _get_lead_history_def
from app.tools.get_lead_pain_points import TOOL_DEFINITION as _get_lead_pain_points_def
from app.tools.skill_loader import TOOL_DEFINITION as _load_skill_def
from app.tools.skill_loader import FILLER_TEXT as _load_skill_filler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# capture_data base definition — parameters are replaced dynamically per agent
# ---------------------------------------------------------------------------

# Minimal static entry so capture_data is a valid QORA_TOOL_NAMES member.
# The actual parameters schema is stored per-agent in tool_config JSON.
_CAPTURE_DATA_BASE_DEF: dict = {
    "type": "function",
    "function": {
        "name": "capture_data",
        "description": "Capturás los datos del lead según el esquema configurado",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "ID del lead"},
            },
            "required": ["lead_id"],
        },
    },
}

# ---------------------------------------------------------------------------
# Assembled tool definitions — single source of truth
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: dict[str, dict] = {
    "get_lead_details": _get_lead_details_def,
    "register_interest": _register_interest_def,
    "mark_not_interested": _mark_not_interested_def,
    "schedule_followup": _schedule_followup_def,
    "get_lead_profile": _get_lead_profile_def,
    "get_lead_history": _get_lead_history_def,
    "get_lead_pain_points": _get_lead_pain_points_def,
    "load_skill": _load_skill_def,
    # capture_data is registered here so QORA_TOOL_NAMES includes it.
    # The dynamic schema is built via build_capture_data_definition().
    "capture_data": _CAPTURE_DATA_BASE_DEF,
}

# ---------------------------------------------------------------------------
# Filler speech config — emitted to SSE stream BEFORE tool execution
# ---------------------------------------------------------------------------

# Per-tool default filler phrases. load_skill uses the registry entry's
# filler_text; other tools fall back to this dict, then to DEFAULT_FILLER.
TOOL_FILLER_PHRASES: dict[str, str] = {
    "load_skill": _load_skill_filler,
    # CRM tools intentionally omitted — they're fast, no filler needed.
    # Add entries here to configure per-tool filler for future tools.
}

DEFAULT_FILLER = "Un momento por favor..."


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_capture_data_definition(tool_config: dict) -> dict | None:
    """Build an OpenAI function-calling schema for capture_data from agent config.

    The agent stores its capture_data parameters schema under tool_config["capture_data"].
    This function merges that stored schema into the base tool definition.

    Args:
        tool_config: The agent's tool_config dict (parsed from JSON column).

    Returns:
        A complete OpenAI tool definition dict, or None if tool_config does not
        contain a "capture_data" key (caller should exclude capture_data).
    """
    if not tool_config or "capture_data" not in tool_config:
        return None

    capture_config = tool_config["capture_data"]

    # Build description from stored config or fall back to base
    description = capture_config.get(
        "description",
        _CAPTURE_DATA_BASE_DEF["function"]["description"],
    )

    # The stored parameters must be a dict; if malformed, return None
    parameters = capture_config.get("parameters")
    if not isinstance(parameters, dict):
        # Fallback: treat the whole capture_config as the parameters block
        # (supports both {"parameters": {...}} and flat schema formats)
        if isinstance(capture_config, dict) and "type" in capture_config:
            parameters = capture_config
        else:
            logger.warning(
                "capture_data tool_config missing valid parameters block; "
                "excluding capture_data from tool list"
            )
            return None

    # Ensure lead_id is always in the schema (required for handler lookup)
    props = dict(parameters.get("properties", {}))
    if "lead_id" not in props:
        props["lead_id"] = {"type": "string", "description": "ID del lead"}
    required = list(parameters.get("required", []))
    if "lead_id" not in required:
        required = ["lead_id"] + required

    return {
        "type": "function",
        "function": {
            "name": "capture_data",
            "description": description,
            "parameters": {
                **parameters,
                "properties": props,
                "required": required,
            },
        },
    }


def build_tool_definitions(
    tool_names: list[str],
    *,
    agent_tool_config: dict | None = None,
) -> list[dict] | None:
    """Build OpenAI tool definitions for the given tool names.

    For capture_data, the schema is built dynamically from agent_tool_config.
    If capture_data is requested but agent_tool_config is None or lacks the key,
    capture_data is silently excluded (no exception raised).

    Args:
        tool_names: List of tool name strings to include.
        agent_tool_config: Optional parsed tool_config dict from the Agent record.

    Returns:
        List of OpenAI tool definition dicts, or None if the list is empty.
    """
    tools: list[dict] = []
    for name in tool_names:
        if name == "capture_data":
            if agent_tool_config:
                definition = build_capture_data_definition(agent_tool_config)
                if definition is not None:
                    tools.append(definition)
                else:
                    logger.warning(
                        "capture_data requested but tool_config missing or invalid; "
                        "excluding from tool list"
                    )
            else:
                logger.warning(
                    "capture_data requested but no agent_tool_config supplied; "
                    "excluding from tool list"
                )
        elif name in TOOL_DEFINITIONS:
            tools.append(TOOL_DEFINITIONS[name])
    return tools if tools else None
