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

# Fixed ordering of facts keys — deterministic, not dict-insertion-order dependent.
_FACTS_FIELDS = [
    ("current_insurance", "Seguro actual"),
    ("interest_level", "Nivel de interés"),
    ("next_action_suggested", "Acción sugerida"),
]


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
    confirmed_facts = _format_confirmed_facts(
        _coerce_extracted_facts(lead.extracted_facts)
    )
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
    """Format extracted_facts into a bulleted string in fixed field order.

    Args:
        extracted_facts: Parsed dict from Lead.extracted_facts, or None.

    Returns:
        Multi-line bullet string.
        Empty string if no facts or no recognised keys.
    """
    if not extracted_facts:
        return ""

    lines: list[str] = []

    for key, label in _FACTS_FIELDS:
        value = extracted_facts.get(key)
        if value is None:
            continue
        if key == "interest_level":
            lines.append(f"- {label}: {value}/100")
        else:
            lines.append(f"- {label}: {value}")

    return "\n".join(lines)


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
