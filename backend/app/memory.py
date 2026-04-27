"""QORA Memory — Shared memory context builder.

Single source of truth for computing memory variables from a lead's
call history and extracted facts. Used by both:
- voice/initiation.py (Twilio/SIP path via ElevenLabs dynamic_variables)
- prompts/loader.py (custom-LLM WebSocket render path)

Architecture decision (design.md AD-1): top-level app/memory.py — not nested
under prompts or calls because it serves both subsystems.

Architecture decision (design.md AD-2): MemoryContext is a TypedDict so it
merges naturally into the variables dict via ``{**vars, **memory}``.

Architecture decision (design.md AD-3): Dates are converted to
America/Argentina/Buenos_Aires timezone before formatting.

Architecture decision (design.md AD-6): confirmed_facts ordering is fixed by
code (not dict iteration): current_insurance → interest_level → next_action_suggested.

Covers: CAP-1 (T01-T13).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession

if TYPE_CHECKING:
    from app.leads.models import Lead

logger = structlog.get_logger()

_TZ_BA = ZoneInfo("America/Argentina/Buenos_Aires")

# Tier 1: Known keys — fixed order, Spanish labels.
# These always appear first so existing tests continue to pass.
_KNOWN_FACTS: list[tuple[str, str]] = [
    ("current_insurance", "Seguro actual"),
    ("interest_level", "Nivel de interés"),
    ("next_action_suggested", "Acción sugerida"),
    ("misc_notes", "Notas adicionales"),
    ("data_corrections", "Correcciones de datos"),
    ("summary", "Resumen"),
]

# Build a lookup for fast membership checks
_KNOWN_FACTS_KEYS: frozenset[str] = frozenset(k for k, _ in _KNOWN_FACTS)
_KNOWN_FACTS_LABELS: dict[str, str] = {k: label for k, label in _KNOWN_FACTS}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class MemoryContext(TypedDict):
    """Return type for build_memory_context.

    All four fields are required:
    - call_history: multi-line string, one line per session (empty if none).
    - confirmed_facts: bulleted multi-line string from extracted_facts.
    - is_returning_caller: True iff ≥1 completed session exists.
    - call_number: lead.call_count + 1.
    """

    call_history: str
    confirmed_facts: str
    is_returning_caller: bool
    call_number: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_memory_context(db: AsyncSession, lead: "Lead") -> MemoryContext:
    """Build memory context for a lead from its call history and extracted facts.

    Args:
        db: Active async DB session.
        lead: Lead ORM instance to build context for.

    Returns:
        MemoryContext TypedDict with call_history, confirmed_facts,
        is_returning_caller, call_number.

    Raises:
        ValueError: If lead is None.
    """
    if lead is None:
        raise ValueError("lead must not be None")

    # Query 1: Does ANY completed session exist for this lead?
    # Drives is_returning_caller (summary-independent per REQ-1.5).
    from sqlalchemy import literal

    has_any_completed_result = await db.execute(
        select(literal(True))
        .where(
            and_(
                CallSession.lead_id == lead.id,
                CallSession.status == "completed",
            )
        )
        .limit(1)
    )
    has_any_completed = has_any_completed_result.scalar() is not None

    # Query 2: Completed sessions WITH non-empty summary, newest first, LIMIT 3.
    # Drives call_history formatting only.
    sessions_result = await db.execute(
        select(CallSession)
        .where(
            and_(
                CallSession.lead_id == lead.id,
                CallSession.status == "completed",
                CallSession.summary.is_not(None),
                CallSession.summary != "",
            )
        )
        .order_by(CallSession.ended_at.desc())
        .limit(3)
    )
    sessions = list(sessions_result.scalars().all())

    call_history = _format_call_history(sessions, _TZ_BA)
    # Legacy scalar facts from extracted_facts JSON
    confirmed_facts = _format_confirmed_facts(
        _coerce_extracted_facts(lead.extracted_facts)
    )
    # Issue #36: Append accumulated relational profile facts (token-budgeted)
    accumulated_section = await _format_accumulated_profile(db, lead.id)
    if accumulated_section:
        if confirmed_facts:
            confirmed_facts = confirmed_facts + "\n" + accumulated_section
        else:
            confirmed_facts = accumulated_section

    # REQ-1.5: is_returning_caller is True iff ANY completed session exists,
    # regardless of whether it has a summary.
    is_returning_caller = has_any_completed
    call_number = (lead.call_count or 0) + 1

    logger.info(
        "memory_context_built",
        lead_id=lead.id,
        session_count=len(sessions),
        has_completed_sessions=has_any_completed,
        has_facts=bool(confirmed_facts),
        call_number=call_number,
    )

    return MemoryContext(
        call_history=call_history,
        confirmed_facts=confirmed_facts,
        is_returning_caller=is_returning_caller,
        call_number=call_number,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _format_call_history(sessions: list[CallSession], tz: ZoneInfo) -> str:
    """Format sessions as dated summary lines.

    Args:
        sessions: Completed CallSession instances ordered by ended_at DESC.
        tz: Timezone for date display.

    Returns:
        Multi-line string: one line per session.
        Empty string if no sessions.
    """
    if not sessions:
        return ""

    lines: list[str] = []
    for cs in sessions:
        ref_dt = cs.ended_at or cs.started_at
        if ref_dt is not None:
            # Convert to BA timezone for display
            if ref_dt.tzinfo is None:
                from datetime import timezone as _tz

                ref_dt = ref_dt.replace(tzinfo=_tz.utc)
            date_str = ref_dt.astimezone(tz).strftime("%d/%m/%Y")
        else:
            date_str = "fecha desconocida"

        # Summary is guaranteed non-None/non-empty by the query filter,
        # but guard defensively.
        summary_text = (cs.summary or "")[:150]
        lines.append(f'Llamada del {date_str}: "{summary_text}"')

    return "\n".join(lines)


def _format_confirmed_facts(extracted_facts: dict | None) -> str:
    """Format extracted_facts into a bulleted string.

    Issue #21: Dynamic two-tier rendering.
    Tier 1: Known keys in fixed order with Spanish labels (deterministic).
    Tier 2: Unknown string/scalar keys alphabetically with raw key name as label.
    Nested dicts: flattened to one-line summaries via _format_axis().
    Lists: joined with ", ".
    None/empty values: skipped.

    Args:
        extracted_facts: Parsed dict from Lead.extracted_facts, or None.

    Returns:
        Multi-line bullet string.
        Empty string if no facts or all values are empty/None.
    """
    if not extracted_facts:
        return ""

    lines: list[str] = []

    # Tier 1: Known keys — fixed order, Spanish labels
    for key, label in _KNOWN_FACTS:
        value = extracted_facts.get(key)
        if value is None or value == "" or value == [] or value == {}:
            continue
        rendered = _render_fact_value(key, value)
        if rendered:
            lines.append(f"- {label}: {rendered}")

    # Tier 2: Unknown keys — alphabetical, raw key as label
    unknown_keys = sorted(k for k in extracted_facts if k not in _KNOWN_FACTS_KEYS)
    for key in unknown_keys:
        value = extracted_facts[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        rendered = _render_fact_value(key, value)
        if rendered:
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {rendered}")

    return "\n".join(lines)


def _render_fact_value(key: str, value: object) -> str:
    """Render a single fact value to a display string.

    - interest_level → '{value}/100'
    - dict → _format_axis(key, value)
    - list → ', '.join(str(v) for v in value)
    - other → str(value)

    Returns empty string for None/empty after coercion.
    """
    if value is None:
        return ""
    if key == "interest_level":
        return f"{value}/100"
    if isinstance(value, dict):
        return _format_axis(key, value)
    if isinstance(value, list):
        joined = ", ".join(str(v) for v in value if v is not None and v != "")
        return joined
    return str(value)


def _format_axis(key: str, axis_dict: dict) -> str:
    """Flatten a nested axis dict to a one-line summary.

    call_outcome → "interested (high engagement) — reason text"
    detected_interests → "products=[...], needs=[...], signals=[...]"
    identified_problem → "primary_need (urgency) — pain_points"
    Unknown axes → "key: value; key2: value2" format

    Args:
        key: The fact key (e.g. 'call_outcome').
        axis_dict: The nested dict value.

    Returns:
        One-line string summary. Empty string if dict has no useful content.
    """
    if not axis_dict:
        return ""

    if key == "call_outcome":
        classification = axis_dict.get("classification", "")
        quality = axis_dict.get("engagement_quality", "")
        reason = axis_dict.get("reason", "")
        if classification and quality:
            core = f"{classification} ({quality} engagement)"
        elif classification:
            core = str(classification)
        else:
            core = str(quality) if quality else ""
        return f"{core} — {reason}".strip(" —") if (core and reason) else core or reason

    if key == "detected_interests":
        products = axis_dict.get("products") or []
        needs = axis_dict.get("specific_needs") or []
        signals = axis_dict.get("buying_signals") or []
        parts = []
        if products:
            parts.append(f"products={products}")
        if needs:
            parts.append(f"needs={needs}")
        if signals:
            parts.append(f"signals={signals}")
        return ", ".join(parts) if parts else ""

    if key == "identified_problem":
        primary = axis_dict.get("primary_need", "")
        urgency = axis_dict.get("urgency", "")
        pain_points = axis_dict.get("pain_points") or []
        core = f"{primary} ({urgency})" if (primary and urgency) else primary or urgency
        if pain_points:
            core += f" — {', '.join(pain_points)}"
        return core

    # Generic fallback for unknown nested dicts
    pairs = []
    for k, v in axis_dict.items():
        if v is not None and v != "" and v != [] and v != {}:
            pairs.append(f"{k}: {v}")
    return "; ".join(pairs) if pairs else ""


def _coerce_extracted_facts(raw: object) -> dict | None:
    """Coerce Lead.extracted_facts to a dict or None.

    Handles all edge cases:
    - None → None
    - "" → None
    - "{}" → {}
    - "{...}" → dict
    - {} → {}
    - {...} → as-is
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Issue #36: Accumulated profile facts from relational tables
# ---------------------------------------------------------------------------

# Token budget: max 10 items per namespace (AD-3 from design.md)
_MAX_FACTS_PER_NAMESPACE = 10

# Max interest history points to include in memory context (Issue #36 CRITICAL 1)
_MAX_INTEREST_HISTORY = 5

# Namespace prefix → Spanish section label
_NAMESPACE_LABELS: list[tuple[str, str]] = [
    ("profile:", "Datos personales"),
    ("pain:", "Puntos de dolor"),
    ("service_issue:", "Problemas de servicio"),
    ("signal:", "Señales de compromiso"),
    ("buying_signal:", "Señales de compra"),
]


async def _format_accumulated_profile(db: AsyncSession, lead_id: str) -> str:
    """Build a structured string of accumulated LeadProfileFact rows and interest
    history for this lead.

    Queries active (superseded_at IS NULL) LeadProfileFact rows grouped by namespace.
    Caps each namespace at _MAX_FACTS_PER_NAMESPACE (token budget, AD-3).
    Ordered by recorded_at DESC within each namespace.

    Also queries the last _MAX_INTEREST_HISTORY LeadInterestHistory rows (newest first)
    and formats them as 'Evolución de interés: 75→60→85' (oldest→newest within cap).

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead.

    Returns:
        Multi-line string with grouped facts and interest history,
        or empty string if no data exists.
    """
    from app.leads.models import LeadInterestHistory, LeadProfileFact

    # Query 1: Active profile facts
    result = await db.execute(
        select(LeadProfileFact)
        .where(
            LeadProfileFact.lead_id == lead_id,
            LeadProfileFact.superseded_at == None,  # noqa: E711
        )
        .order_by(LeadProfileFact.recorded_at.desc())
    )
    all_rows = list(result.scalars().all())

    # Query 2: Interest history — last 5, newest first
    interest_result = await db.execute(
        select(LeadInterestHistory)
        .where(LeadInterestHistory.lead_id == lead_id)
        .order_by(LeadInterestHistory.recorded_at.desc())
        .limit(_MAX_INTEREST_HISTORY)
    )
    interest_rows = list(interest_result.scalars().all())

    if not all_rows and not interest_rows:
        return ""

    # Group profile fact rows by namespace prefix
    by_namespace: dict[str, list[str]] = {}
    for row in all_rows:
        for prefix, _label in _NAMESPACE_LABELS:
            if row.fact_key.startswith(prefix):
                value = row.fact_value or row.fact_key[len(prefix) :]
                by_namespace.setdefault(prefix, []).append(value)
                break

    # Build section lines
    lines: list[str] = []

    if by_namespace:
        lines.append("--- Perfil acumulado ---")
        for prefix, label in _NAMESPACE_LABELS:
            items = by_namespace.get(prefix)
            if not items:
                continue
            # Apply token budget cap
            capped = items[:_MAX_FACTS_PER_NAMESPACE]
            lines.append(f"- {label}: {', '.join(capped)}")

    # Append interest evolution line (reverse to oldest→newest order)
    if interest_rows:
        # interest_rows is newest-first; reverse to get chronological order
        chronological = list(reversed(interest_rows))
        levels = "→".join(str(r.interest_level) for r in chronological)
        lines.append(f"- Evolución de interés: {levels}")

    return "\n".join(lines) if lines else ""
