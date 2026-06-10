"""QORA Tools — Dispatcher that routes tool calls to handlers.

Used by the Custom LLM webhook to execute tools mid-stream.

Covers: T5.5 tool registry + dispatcher.
Phase 2: adds load_skill routing.
Phase 1 (configurable-agent-tools): adds capture_data routing with agent_tool_config.
Phase 2 (configurable-agent-tools): removes register_interest, mark_not_interested,
    schedule_followup from _TOOL_REGISTRY. Calls to these names return tool_removed
    so old agents don't crash — they receive a structured error via the SSE stream.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead
from app.tools.capture_data import capture_data as _capture_data_handler
from app.tools.get_lead_details import get_lead_details
from app.tools.get_lead_history import get_lead_history
from app.tools.get_lead_pain_points import get_lead_pain_points
from app.tools.get_lead_profile import get_lead_profile

if TYPE_CHECKING:
    from app.integrations.crm_config import CRMConfig
    from app.prompts.skill_loader import SkillRegistryEntry

# Legacy tool names removed in Phase 2 (imported from registry for single source of truth).
from app.tools.registry import _REMOVED_TOOLS as _LEGACY_REMOVED_TOOLS

# Tool registry: name → handler function
# Note: capture_data is NOT in this dict — it requires special routing via agent_tool_config
# Phase 2: register_interest, mark_not_interested, schedule_followup removed.
_TOOL_REGISTRY = {
    "get_lead_details": get_lead_details,
    "get_lead_profile": get_lead_profile,
    "get_lead_history": get_lead_history,
    "get_lead_pain_points": get_lead_pain_points,
}


async def dispatch_tool(
    tool_name: str,
    tool_args: dict,
    client_id: str,
    lead_id: str | None,
    session: AsyncSession | None = None,
    *,
    agent_slug: str | None = None,
    registry_entries: "list[SkillRegistryEntry] | None" = None,
    clients_dir: Path | None = None,
    agent_tool_config: dict | None = None,
    crm_config: "CRMConfig | None" = None,
) -> dict:
    """Route a tool call to the correct handler.

    Args:
        tool_name: Name of the tool to invoke.
        tool_args: Arguments dict from the LLM's function call.
        client_id: Tenant client id (for context).
        lead_id: Lead ID from conversation context (fallback if not in args).
        session: Optional async DB session. If None, a new session is opened.
        agent_slug: Agent slug — required for load_skill routing.
        registry_entries: Parsed registry entries for this session — required for
            load_skill validation (allowlist check).
        clients_dir: Override clients root — used in tests via tmp_path.
        agent_tool_config: Optional per-agent tool config dict (parsed from JSON).
            Required for capture_data routing — passed to the handler for schema
            validation. Ignored for all other tool names.
        crm_config: Optional CRMConfig — when present, capture_data uses
            field_definitions for schema validation and field_type coercion.
            Takes priority over agent_tool_config for capture_data schema.

    Returns:
        Tool result dict. Always returns a dict — never raises.
    """
    # --- Phase 2: legacy tools return structured tool_removed error ---
    if tool_name in _LEGACY_REMOVED_TOOLS:
        return {
            "error": "tool_removed",
            "detail": (
                f"'{tool_name}' was removed in Phase 2. "
                "Use capture_data to capture lead data; "
                "status transitions are now handled by post-call analysis."
            ),
        }

    # --- capture_data is handled separately — requires agent_tool_config or crm_config ---
    if tool_name == "capture_data":
        # Resolve effective tool_config and field_type_map.
        # Priority 1: CRMConfig.custom_fields → build synthetic tool_config + field_type_map
        # Priority 2: agent_tool_config (legacy JSON column)
        _effective_tool_config: dict = agent_tool_config or {}
        _effective_field_type_map: dict[str, str] = {}
        if crm_config is not None and crm_config.custom_fields:
            # Build a synthetic tool_config["capture_data"] from crm.yaml field_definitions
            _props: dict = {"lead_id": {"type": "string", "description": "ID del lead"}}
            # Only lead_id is required: CustomFieldDef.required is for quote-ready
            # evaluation, not tool-call validation. Partial captures (one field at
            # a time) must be accepted mid-call (P1 fix: partial capture).
            _required: list[str] = ["lead_id"]
            for _fd in crm_config.custom_fields:
                _props[_fd.field_key] = {"type": _fd.field_type, "description": _fd.label}
                _effective_field_type_map[_fd.field_key] = _fd.field_type
            _effective_tool_config = {
                "capture_data": {
                    "parameters": {
                        "type": "object",
                        "properties": _props,
                        "required": _required,
                    }
                }
            }

        async def _call_capture_data(sess: AsyncSession) -> dict:
            effective_lead_id = tool_args.get("lead_id") or lead_id or None
            if not effective_lead_id:
                return {"error": "lead_not_found"}
            # Build captured_fields: all tool_args except lead_id
            captured_fields = {k: v for k, v in tool_args.items() if k != "lead_id"}
            return await _capture_data_handler(
                session=sess,
                lead_id=effective_lead_id,
                tool_config=_effective_tool_config,
                captured_fields=captured_fields,
                client_id=client_id,
                field_type_map=_effective_field_type_map or None,
            )

        if session is not None:
            return await _call_capture_data(session)
        else:
            from app.core.database import get_session

            async with get_session() as new_session:
                return await _call_capture_data(new_session)

    # --- load_skill is handled separately (no DB session needed) ---
    if tool_name == "load_skill":
        from app.tools.skill_loader import handle_load_skill

        skill_name = tool_args.get("skill_name", "")
        raw = await handle_load_skill(
            client_id=client_id,
            agent_slug=agent_slug or "",
            skill_name=skill_name,
            registry_entries=registry_entries or [],
            clients_dir=clients_dir,
        )
        # Unwrap the handler result to a plain string — the LLM needs raw text,
        # not JSON metadata. handle_load_skill returns {"content": ...} on success
        # or {"error": ...} on failure; both are unwrapped here so the tool result
        # in the conversation is the text itself (not a dict-encoded JSON wrapper).
        if "content" in raw:
            return raw["content"]
        # Error case: always prefix with "Error:" so the webhook cache guard
        # (which checks `not tool_result.startswith("Error:")`) can reliably
        # reject failures without relying on specific error message wording.
        error_msg = raw.get("error", "Unknown error loading skill.")
        return f"Error: {error_msg}"

    handler = _TOOL_REGISTRY.get(tool_name)
    if handler is None:
        return {"error": f"unknown_tool: {tool_name}"}

    # Resolve lead_id: prefer from tool_args, fall back to conversation context
    effective_lead_id = tool_args.get("lead_id") or lead_id or None

    async def _validate_lead_scope(sess: AsyncSession) -> dict | None:
        """Return an error dict if the lead does not belong to client_id, else None."""
        if effective_lead_id and client_id:
            lead = await get_lead(sess, effective_lead_id)
            if lead and lead.client_id != client_id:
                return {
                    "error": "lead_not_found",
                    "detail": "Lead does not belong to this client",
                }
        return None

    async def _call_with_session(sess: AsyncSession) -> dict:
        """Call the appropriate handler with the right arguments."""
        scope_error = await _validate_lead_scope(sess)
        if scope_error is not None:
            return scope_error
        if tool_name == "get_lead_details":
            return await get_lead_details(
                session=sess,
                lead_id=effective_lead_id,
                client_id=client_id,
            )
        elif tool_name == "get_lead_profile":
            return await get_lead_profile(
                session=sess,
                lead_id=effective_lead_id,
            )
        elif tool_name == "get_lead_history":
            return await get_lead_history(
                session=sess,
                lead_id=effective_lead_id,
            )
        elif tool_name == "get_lead_pain_points":
            return await get_lead_pain_points(
                session=sess,
                lead_id=effective_lead_id,
            )
        else:
            return {"error": f"unknown_tool: {tool_name}"}

    if session is not None:
        return await _call_with_session(session)
    else:
        # Open a new session from the module-level factory
        from app.core.database import get_session

        async with get_session() as new_session:
            result = await _call_with_session(new_session)
            return result
