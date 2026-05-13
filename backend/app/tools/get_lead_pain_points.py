"""QORA Tools — get_lead_pain_points handler (Issue #36).

Returns all active LeadProfileFact rows with 'pain:' and 'service_issue:'
prefixes, formatted as plain Spanish text. Voice-first format (AD-4).

Covers: Issue #36 agent-lead-query-tools.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, get_facts_by_namespace

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_lead_pain_points",
        "description": "Obtenés los puntos de dolor y problemas de servicio acumulados del lead",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "ID del lead"}
            },
            "required": ["lead_id"],
        },
    },
}


async def get_lead_pain_points(
    session: AsyncSession,
    lead_id: str,
) -> dict:
    """Fetch pain points and service issues for a lead.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.

    Returns:
        {"result": "<Spanish text>"} or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    pain_rows = await get_facts_by_namespace(session, lead_id, "pain:")
    service_rows = await get_facts_by_namespace(session, lead_id, "service_issue:")

    if not pain_rows and not service_rows:
        return {
            "result": f"No se registraron puntos de dolor para el lead {lead.name}."
        }

    lines = [f"Puntos de dolor de {lead.name}:"]

    if pain_rows:
        pain_items = [
            r["fact_value"] or r["fact_key"][len("pain:") :] for r in pain_rows
        ]
        lines.append(f"- Dolor principal: {', '.join(pain_items)}")

    if service_rows:
        svc_items = [
            r["fact_value"] or r["fact_key"][len("service_issue:") :]
            for r in service_rows
        ]
        lines.append(f"- Problemas de servicio: {', '.join(svc_items)}")

    return {"result": "\n".join(lines)}
