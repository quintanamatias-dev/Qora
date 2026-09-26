"""QORA Calls — Read-only service for the "en vivo" live calls view.

ABSOLUTE SAFETY RULE: this module performs SELECT-only queries. It must never
write to call_sessions, never mutate ConversationState, never enqueue jobs,
and never touch app.voice / app.outbound / app.calls.states / the scheduler.

Data sources (all already exist — no new columns/tables):
  - CallSession.telephony_status (app/calls/states.py — CallStatus enum) for
    the live/dialing/talking state of each call.
  - Agent (app/tenants/models.py) for the agent display name.
  - Lead.name (app/leads/models.py) for the lead's first name.
  - LeadProfileFact (app/leads/models.py) for the "recent memories" feed —
    populated by the post-call profile-facts pipeline (app/summarizer.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession
from app.calls.states import CallStatus
from app.leads.models import Lead, LeadProfileFact
from app.tenants.models import Agent, Client

#: Non-terminal telephony states shown as "live" on the canvas.
_LIVE_STATUSES: tuple[str, ...] = (
    CallStatus.queued.value,
    CallStatus.dialing.value,
    CallStatus.ringing.value,
    CallStatus.connected.value,
)

#: Stale protection — a non-terminal session older than this is excluded from
#: the live view (never mutated; purely a display-side filter).
_STALE_BOUND = timedelta(hours=2)

#: Max entries in the "recent memories" feed.
_RECENT_FACTS_LIMIT = 6

#: Max in-flight sessions returned by the live canvas — newest kept first.
MAX_ACTIVE_CALLS = 50


def _first_name(full_name: str | None) -> str | None:
    if not full_name:
        return None
    return full_name.strip().split(" ")[0] or None


async def _today_bounds(session: AsyncSession, client_id: str) -> tuple[datetime, datetime]:
    """Return (start, end) of "today" in the client's scheduler timezone, as UTC-aware datetimes."""
    tz_name = "America/Argentina/Buenos_Aires"
    result = await session.execute(select(Client.scheduler_timezone).where(Client.id == client_id))
    row = result.scalar_one_or_none()
    if row:
        tz_name = row

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/Argentina/Buenos_Aires")

    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


async def get_active_calls(session: AsyncSession, client_id: str) -> list[dict]:
    """Return in-flight (non-terminal, non-stale) call sessions for a client.

    Read-only SELECT — joins Agent for display name only. Never mutates
    CallSession.telephony_status or any other column.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - _STALE_BOUND

    stmt = (
        select(
            CallSession.id,
            CallSession.lead_id,
            CallSession.agent_id,
            CallSession.telephony_status,
            CallSession.started_at,
            Lead.name.label("lead_name"),
            Agent.name.label("agent_name"),
        )
        .outerjoin(Lead, Lead.id == CallSession.lead_id)
        .outerjoin(Agent, Agent.id == CallSession.agent_id)
        .where(CallSession.client_id == client_id)
        .where(CallSession.telephony_status.in_(_LIVE_STATUSES))
        .where(CallSession.started_at >= stale_cutoff)
        .order_by(CallSession.started_at.desc())
        .limit(MAX_ACTIVE_CALLS)
    )
    result = await session.execute(stmt)

    calls: list[dict] = []
    for row in result.all():
        started_at = row.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        calls.append(
            {
                "session_id": row.id,
                "lead_id": row.lead_id,
                "lead_first_name": _first_name(row.lead_name),
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
                "telephony_status": row.telephony_status,
                "started_at": started_at,
            }
        )
    return calls


async def count_active_calls(session: AsyncSession, client_id: str) -> int:
    """Count every in-flight session for *client_id*, ignoring MAX_ACTIVE_CALLS.

    get_active_calls caps the rows it returns; this keeps the "en curso"
    counter truthful when more sessions are live than the canvas shows.
    """
    stale_cutoff = datetime.now(timezone.utc) - _STALE_BOUND
    stmt = (
        select(func.count(CallSession.id))
        .where(CallSession.client_id == client_id)
        .where(CallSession.telephony_status.in_(_LIVE_STATUSES))
        .where(CallSession.started_at >= stale_cutoff)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_today_summary(session: AsyncSession, client_id: str) -> dict:
    """Return {calls_total, completed} for the client's "today" (client timezone)."""
    start, end = await _today_bounds(session, client_id)

    stmt = (
        select(
            func.count(CallSession.id),
            func.count(CallSession.id).filter(CallSession.status == "completed"),
        )
        .where(CallSession.client_id == client_id)
        .where(CallSession.started_at >= start)
        .where(CallSession.started_at < end)
        .where(CallSession.merged_into_session_id.is_(None))
    )
    result = await session.execute(stmt)
    total, completed = result.one()
    return {"calls_total": int(total), "completed": int(completed)}


async def get_recent_facts(session: AsyncSession, client_id: str) -> tuple[list[dict], int]:
    """Return (recent_facts from today, memory_total) sourced from LeadProfileFact.

    recent_facts: last _RECENT_FACTS_LIMIT active facts recorded today for this
    client's leads, newest first, with lead first name and call duration.
    memory_total: count of all active (non-superseded) facts for this client's leads.
    """
    start, end = await _today_bounds(session, client_id)

    recent_stmt = (
        select(
            LeadProfileFact.fact_value,
            LeadProfileFact.recorded_at,
            Lead.name.label("lead_name"),
            CallSession.duration_seconds,
        )
        .join(Lead, Lead.id == LeadProfileFact.lead_id)
        .outerjoin(CallSession, CallSession.id == LeadProfileFact.source_call_id)
        .where(Lead.client_id == client_id)
        .where(LeadProfileFact.superseded_at.is_(None))
        .where(LeadProfileFact.recorded_at >= start)
        .where(LeadProfileFact.recorded_at < end)
        .order_by(LeadProfileFact.recorded_at.desc())
        .limit(_RECENT_FACTS_LIMIT)
    )
    recent_result = await session.execute(recent_stmt)
    recent_facts = [
        {
            "text": row.fact_value,
            "lead_first_name": _first_name(row.lead_name),
            "duration_seconds": row.duration_seconds,
        }
        for row in recent_result.all()
    ]

    total_stmt = (
        select(func.count(LeadProfileFact.id))
        .join(Lead, Lead.id == LeadProfileFact.lead_id)
        .where(Lead.client_id == client_id)
        .where(LeadProfileFact.superseded_at.is_(None))
    )
    total_result = await session.execute(total_stmt)
    memory_total = int(total_result.scalar_one())

    return recent_facts, memory_total
