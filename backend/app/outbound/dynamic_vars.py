"""QORA Outbound — Shared dynamic variable builder for ElevenLabs agent prompts.

Extracted from app.voice.initiation so both the manual trigger endpoint and the
future scheduler tick can share the same variable-building logic.

Spec: outbound-call-trigger — Requirement: Scheduler Reuse Contract
  "Shared build_dynamic_variables() helper extracted from initiation.py"

Design (design.md): "Extract build_dynamic_variables() as importable helper"
  The initiation.py endpoint continues to build variables inline (no change
  to that code path). This helper mirrors the same logic for outbound calls.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)


async def build_dynamic_variables(
    *,
    db: AsyncSession,
    lead,
    agent,
    client,
) -> dict[str, str | int | bool]:
    """Build the conversation_initiation_client_data dynamic_variables dict.

    Mirrors the logic in app.voice.initiation.initiation_webhook() for outbound
    calls. Returns the same variable structure so agents receive identical context
    whether initiated by the browser widget or by an outbound trigger.

    Args:
        db: Async DB session for custom field lookup.
        lead: Lead ORM instance (required — outbound calls always have a lead).
        agent: Agent ORM instance.
        client: Client ORM instance.

    Returns:
        Dict of dynamic variable strings, ints, and bools compatible with
        ElevenLabs conversation_initiation_client_data.

    Spec: outbound-call-trigger — "build_dynamic_variables(lead, agent, client)"
    """
    # Resolve agent name (agent → client fallback matches initiation.py pattern)
    resolved_agent_name: str = (
        agent.name if agent is not None else client.agent_name
    )

    # Initialize variable defaults (same empty-string pattern as initiation.py)
    lead_name: str = lead.name if lead else ""
    lead_status: str = lead.status if lead else ""
    lead_notes: str = (lead.notes or "") if lead else ""

    car_make: str = ""
    car_model: str = ""
    car_year: str = ""
    current_insurance: str = ""

    # Attempt to load custom fields (same pattern as initiation.py — graceful on failure)
    if lead is not None:
        try:
            from app.leads import lead_custom_fields_service as cf_service

            lcf = await cf_service.get_all(db, lead.id, lead.client_id)
            car_make = lcf.get("car_make", "")
            car_model = lcf.get("car_model", "")
            _cy_raw = lcf.get("car_year", "")
            car_year = str(_cy_raw) if _cy_raw else ""
            current_insurance = lcf.get("current_insurance", "")
        except Exception as exc:
            logger.warning(
                "outbound_dynamic_vars_cf_error",
                lead_id=lead.id if lead else None,
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )

    # Resolve lead identity fields — always strings for ElevenLabs dynamic vars
    lead_id_str: str = str(lead.id) if lead else ""
    lead_phone: str = lead.phone if lead else ""

    return {
        # Lead identity — allows the agent to resolve CRM context during the call
        "lead_id": lead_id_str,
        "lead_phone": lead_phone,
        # Plain names — kept for backward-compat with initiation.py contract
        "lead_name": lead_name,
        "car_make": car_make,
        "car_model": car_model,
        "car_year": car_year,
        "current_insurance": current_insurance,
        "lead_status": lead_status,
        "lead_notes": lead_notes,
        "company_name": client.name,
        # DEPRECATED: use company_name instead (matches initiation.py backward-compat)
        "broker_name": client.name,
        "agent_name": resolved_agent_name,
        # Underscore-wrapped names required by the ElevenLabs agent template syntax
        "_lead_name_": lead_name,
        "_car_make_": car_make,
        "_car_model_": car_model,
        "_car_year_": car_year,
        "_current_insurance_": current_insurance,
        "_company_name_": client.name,
        # DEPRECATED: use _company_name_ instead
        "_broker_name_": client.name,
        "_agent_name_": resolved_agent_name,
    }
