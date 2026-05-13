"""QORA Tools — get_lead_profile handler (Issue #36).

Returns all active LeadProfileFact rows for a lead, formatted as plain
Spanish text grouped by namespace category. Voice-first format (AD-4).

Covers: Issue #36 agent-lead-query-tools.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, get_active_profile_facts

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "get_lead_profile",
        "description": "Obtenés el perfil acumulado del lead: datos personales, puntos de dolor, señales de compra y más",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "ID del lead"}
            },
            "required": ["lead_id"],
        },
    },
}


# Namespace prefix → Spanish section label for voice output
_NAMESPACE_LABELS = [
    ("profile:", "Datos personales"),
    ("pain:", "Puntos de dolor"),
    ("service_issue:", "Problemas de servicio"),
    ("signal:", "Señales de compromiso"),
    ("buying_signal:", "Señales de compra"),
]


async def get_lead_profile(
    session: AsyncSession,
    lead_id: str,
) -> dict:
    """Fetch all active profile facts for a lead, grouped by namespace.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead to fetch profile for.

    Returns:
        {"result": "<Spanish text>"} or {"error": "lead_not_found"}.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    rows = await get_active_profile_facts(session, lead_id)

    if not rows:
        return {"result": f"No hay perfil acumulado para el lead {lead.name}."}

    # Group rows by namespace prefix
    by_namespace: dict[str, list[str]] = {}
    for row in rows:
        key = row["fact_key"]
        for prefix, _label in _NAMESPACE_LABELS:
            if key.startswith(prefix):
                value = row["fact_value"] or key[len(prefix) :]
                by_namespace.setdefault(prefix, []).append(value)
                break

    # Build Spanish text output
    lines = [f"Perfil del lead {lead.name}:"]
    for prefix, label in _NAMESPACE_LABELS:
        items = by_namespace.get(prefix)
        if items:
            lines.append(f"- {label}: {', '.join(items)}")

    return {"result": "\n".join(lines)}
