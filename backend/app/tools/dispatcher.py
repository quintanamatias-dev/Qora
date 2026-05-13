"""QORA Tools — Dispatcher that routes tool calls to handlers.

Used by the Custom LLM webhook to execute tools mid-stream.

Covers: T5.5 tool registry + dispatcher.
Phase 2: adds load_skill routing.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead
from app.tools.get_lead_details import get_lead_details
from app.tools.get_lead_history import get_lead_history
from app.tools.get_lead_pain_points import get_lead_pain_points
from app.tools.get_lead_profile import get_lead_profile
from app.tools.mark_not_interested import mark_not_interested
from app.tools.register_interest import register_interest
from app.tools.schedule_followup import schedule_followup

if TYPE_CHECKING:
    from app.prompts.skill_loader import SkillRegistryEntry


# Tool registry: name → handler function
_TOOL_REGISTRY = {
    "get_lead_details": get_lead_details,
    "get_lead_profile": get_lead_profile,
    "get_lead_history": get_lead_history,
    "get_lead_pain_points": get_lead_pain_points,
    "register_interest": register_interest,
    "mark_not_interested": mark_not_interested,
    "schedule_followup": schedule_followup,
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

    Returns:
        Tool result dict. Always returns a dict — never raises.
    """
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
        # Error case: return the error message as a plain string
        return raw.get("error", "Unknown error loading skill.")

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
        elif tool_name == "register_interest":
            return await register_interest(
                session=sess,
                lead_id=effective_lead_id,
                car_make=tool_args.get("car_make"),
                car_model=tool_args.get("car_model"),
                car_year=tool_args.get("car_year"),
                current_insurance=tool_args.get("current_insurance"),
                notes=tool_args.get("notes"),
            )
        elif tool_name == "mark_not_interested":
            return await mark_not_interested(
                session=sess,
                lead_id=effective_lead_id,
                reason=tool_args.get("reason", ""),
            )
        elif tool_name == "schedule_followup":
            return await schedule_followup(
                session=sess,
                lead_id=effective_lead_id,
                followup_date=tool_args.get("followup_date", ""),
                note=tool_args.get("note"),
                client_id=client_id,
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
