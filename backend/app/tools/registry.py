"""QORA Tools — central registry of tool definitions.

Single source of truth for:
- TOOL_DEFINITIONS: all OpenAI function-calling schemas, keyed by tool name
- TOOL_FILLER_PHRASES: per-tool filler speech phrases
- DEFAULT_FILLER: fallback filler phrase
- build_tool_definitions(): filter + assemble tool list for OpenAI API

Each tool module owns its TOOL_DEFINITION constant. This module assembles them.
"""

from __future__ import annotations

from app.tools.get_lead_details import TOOL_DEFINITION as _get_lead_details_def
from app.tools.register_interest import TOOL_DEFINITION as _register_interest_def
from app.tools.mark_not_interested import TOOL_DEFINITION as _mark_not_interested_def
from app.tools.schedule_followup import TOOL_DEFINITION as _schedule_followup_def
from app.tools.get_lead_profile import TOOL_DEFINITION as _get_lead_profile_def
from app.tools.get_lead_history import TOOL_DEFINITION as _get_lead_history_def
from app.tools.get_lead_pain_points import TOOL_DEFINITION as _get_lead_pain_points_def
from app.tools.skill_loader import TOOL_DEFINITION as _load_skill_def
from app.tools.skill_loader import FILLER_TEXT as _load_skill_filler

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
# Builder helper
# ---------------------------------------------------------------------------


def build_tool_definitions(tool_names: list[str]) -> list[dict] | None:
    """Build OpenAI tool definitions for the given tool names."""
    tools = [
        TOOL_DEFINITIONS[name]
        for name in tool_names
        if name in TOOL_DEFINITIONS
    ]
    return tools if tools else None
