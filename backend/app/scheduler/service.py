"""QORA Scheduler — Scheduling engine and lifecycle service (Phase 6).

Core functions:
- calculate_scheduled_at(): UTC/TZ clamping (pure function)
- create_scheduled_call(): persist a new ScheduledCall
- auto_schedule(): rules engine for post-call auto-scheduling
- cancel_scheduled_call(): pending/in_progress → cancelled
- reschedule_call(): update scheduled_at on pending records
- list_queue(): list ScheduledCalls for a client
- get_scheduled_call(): fetch single ScheduledCall
- mark_due_calls_in_progress(): promote due pending records (tick)
- scheduler_tick(): 60s background loop
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduler.models import VALID_TRANSITIONS, ScheduledCall

logger = structlog.get_logger(__name__)

_TICK_INTERVAL_SECONDS = 60


# ---------------------------------------------------------------------------
# Pure function — TZ-aware scheduled_at calculation
# ---------------------------------------------------------------------------


def calculate_scheduled_at(
    now_utc: datetime,
    cooldown_minutes: int,
    start_hour: int,
    end_hour: int,
    tz_str: str,
) -> datetime:
    """Calculate scheduled_at respecting allowed hours in the client's timezone.

    Algorithm:
    1. candidate = now_utc + cooldown_minutes
    2. Convert candidate to client TZ
    3. If local hour in [start_hour, end_hour) → return as UTC (no clamp)
    4. If local hour < start_hour → clamp to start_hour same day
    5. If local hour >= end_hour → clamp to start_hour next day

    Args:
        now_utc: Current UTC datetime (aware).
        cooldown_minutes: Minutes to add before checking window.
        start_hour: Allowed window start (0–23, inclusive).
        end_hour: Allowed window end (0–23, exclusive upper bound).
        tz_str: IANA timezone string (e.g. "America/Argentina/Buenos_Aires").

    Returns:
        UTC-aware datetime for the scheduled call.
    """
    tz = ZoneInfo(tz_str)
    candidate_utc = now_utc + timedelta(minutes=cooldown_minutes)
    local = candidate_utc.astimezone(tz)

    if start_hour <= local.hour < end_hour:
        # Within allowed window — no clamping needed
        return candidate_utc

    if local.hour < start_hour:
        # Before window — clamp to start_hour same day
        clamped_local = datetime.combine(
            local.date(), time(start_hour, 0, 0), tzinfo=tz
        )
    else:
        # After window — clamp to start_hour next day
        next_date = local.date() + timedelta(days=1)
        clamped_local = datetime.combine(next_date, time(start_hour, 0, 0), tzinfo=tz)

    return clamped_local.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


async def create_scheduled_call(
    db: AsyncSession,
    *,
    client_id: str,
    lead_id: str,
    scheduled_at: datetime,
    trigger_reason: str,
    source_session_id: str | None,
    attempt_number: int,
    max_attempts: int,
    notes: str | None,
    agent_id: str | None = None,
) -> ScheduledCall:
    """Persist a new ScheduledCall with status=pending.

    Args:
        db: Active async DB session.
        client_id: Client tenant ID.
        lead_id: Lead being scheduled.
        scheduled_at: UTC datetime for the call.
        trigger_reason: One of: auto_retry | followup_tool | manual.
        source_session_id: Session that triggered this (or None).
        attempt_number: Which attempt this is (1-indexed).
        max_attempts: Max attempts copied from client config at creation time.
        notes: Optional free-text note.
        agent_id: Optional Agent UUID to associate with this scheduled call.

    Returns:
        The persisted ScheduledCall instance.
    """
    sc = ScheduledCall(
        id=str(uuid.uuid4()),
        client_id=client_id,
        lead_id=lead_id,
        scheduled_at=scheduled_at,
        trigger_reason=trigger_reason,
        source_session_id=source_session_id,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        notes=notes,
        agent_id=agent_id,
    )
    db.add(sc)
    await db.flush()
    return sc


async def get_scheduled_call(
    db: AsyncSession, scheduled_call_id: str
) -> ScheduledCall | None:
    """Fetch a single ScheduledCall by ID."""
    result = await db.execute(
        select(ScheduledCall).where(ScheduledCall.id == scheduled_call_id)
    )
    return result.scalar_one_or_none()


async def list_queue(
    db: AsyncSession,
    client_id: str,
    status_filter: list[str] | None = None,
    lead_id: str | None = None,
    scheduled_from: datetime | None = None,
    scheduled_to: datetime | None = None,
) -> list[ScheduledCall]:
    """List ScheduledCalls for a client with optional filters.

    Args:
        db: Active async DB session.
        client_id: Filter by client.
        status_filter: List of statuses to include (None = all).
        lead_id: Filter by lead (None = all leads).
        scheduled_from: Inclusive lower bound for scheduled_at.
        scheduled_to: Inclusive upper bound for scheduled_at.

    Returns:
        List of matching ScheduledCall instances.
    """
    stmt = select(ScheduledCall).where(ScheduledCall.client_id == client_id)

    if status_filter:
        stmt = stmt.where(ScheduledCall.status.in_(status_filter))

    if lead_id:
        stmt = stmt.where(ScheduledCall.lead_id == lead_id)

    if scheduled_from:
        stmt = stmt.where(ScheduledCall.scheduled_at >= scheduled_from)

    if scheduled_to:
        stmt = stmt.where(ScheduledCall.scheduled_at <= scheduled_to)

    result = await db.execute(stmt.order_by(ScheduledCall.scheduled_at))
    return list(result.scalars().all())


async def get_active_scheduled_call_for_lead(
    db: AsyncSession,
    *,
    client_id: str,
    lead_id: str,
) -> ScheduledCall | None:
    """Return the pending/in_progress ScheduledCall for a lead, if any."""
    result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
            ScheduledCall.status.in_(["pending", "in_progress"]),
        )
    )
    return result.scalar_one_or_none()


async def cancel_scheduled_call(
    db: AsyncSession, scheduled_call_id: str
) -> ScheduledCall:
    """Cancel a ScheduledCall (pending or in_progress → cancelled).

    Args:
        db: Active async DB session.
        scheduled_call_id: ID of the ScheduledCall to cancel.

    Returns:
        Updated ScheduledCall.

    Raises:
        ValueError: If the call is not found or in a non-cancellable state.
    """
    sc = await get_scheduled_call(db, scheduled_call_id)
    if sc is None:
        raise ValueError(f"ScheduledCall not found: {scheduled_call_id}")

    if "cancelled" not in VALID_TRANSITIONS.get(sc.status, []):
        raise ValueError(
            f"Cannot cancel ScheduledCall in status={sc.status!r}. "
            f"Only pending and in_progress calls can be cancelled."
        )

    sc.status = "cancelled"
    sc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return sc


async def reschedule_call(
    db: AsyncSession,
    scheduled_call_id: str,
    new_scheduled_at: datetime,
    client_allowed_hours_start: int = 9,
    client_allowed_hours_end: int = 20,
    client_timezone: str = "America/Argentina/Buenos_Aires",
) -> ScheduledCall:
    """Update scheduled_at on a pending ScheduledCall.

    Validates the new time is within the client's allowed hours.

    Args:
        db: Active async DB session.
        scheduled_call_id: ID of the ScheduledCall to reschedule.
        new_scheduled_at: New UTC datetime for the call.
        client_allowed_hours_start: Allowed window start hour (0–23).
        client_allowed_hours_end: Allowed window end hour (0–23).
        client_timezone: IANA TZ string for window validation.

    Returns:
        Updated ScheduledCall.

    Raises:
        ValueError: If the call is not in pending status or time is out of window.
    """
    sc = await get_scheduled_call(db, scheduled_call_id)
    if sc is None:
        raise ValueError(f"ScheduledCall not found: {scheduled_call_id}")

    if sc.status != "pending":
        raise ValueError(
            f"Cannot reschedule ScheduledCall in status={sc.status!r}. "
            "Only pending calls can be rescheduled."
        )

    # Validate new time is within allowed hours
    tz = ZoneInfo(client_timezone)
    local_dt = new_scheduled_at.astimezone(tz)
    if not (client_allowed_hours_start <= local_dt.hour < client_allowed_hours_end):
        raise ValueError(
            f"new_scheduled_at ({local_dt.strftime('%H:%M')} local) "
            f"is outside allowed hours [{client_allowed_hours_start}–{client_allowed_hours_end})."
        )

    sc.scheduled_at = new_scheduled_at
    sc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return sc


async def complete_scheduled_call(
    db: AsyncSession, scheduled_call_id: str
) -> ScheduledCall:
    """Mark a ScheduledCall as completed.

    Phase 6 allows manual completion for pending/in_progress calls.
    """
    sc = await get_scheduled_call(db, scheduled_call_id)
    if sc is None:
        raise ValueError(f"ScheduledCall not found: {scheduled_call_id}")

    if sc.status not in {"pending", "in_progress"}:
        raise ValueError(
            f"Cannot complete ScheduledCall in status={sc.status!r}. "
            "Only pending and in_progress calls can be completed."
        )

    sc.status = "completed"
    sc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return sc


# ---------------------------------------------------------------------------
# Rules engine — auto_schedule
# ---------------------------------------------------------------------------


async def auto_schedule(
    db: AsyncSession,
    *,
    session_id: str,
    lead_id: str,
    client_id: str,
    facts: dict,
    agent_id: str | None = None,
) -> ScheduledCall | None:
    """Auto-schedule a call based on post-call analysis facts.

    Evaluates rules in order:
    1. client.scheduler_enabled must be True
    2. next_action_result.action (primary) or next_action_suggested (fallback) must be
       in client.scheduler_retry_on_outcomes
    3. lead.do_not_call must be False
    4. No existing pending/in_progress ScheduledCall for this lead (duplicate guard)
    5. Attempt count must be < max_attempts

    If all pass, creates a ScheduledCall(trigger_reason='auto_retry').
    The scheduled_at is taken from next_action_result.next_action_at when non-None,
    otherwise calculated via calculate_scheduled_at().

    Args:
        db: Active async DB session.
        session_id: Source call session ID (used to look up agent_id if not provided).
        lead_id: Lead being evaluated.
        client_id: Client tenant ID.
        facts: Extracted facts dict from post-call analysis.
        agent_id: Optional Agent UUID. When None, resolved from source session or client default.

    Returns:
        Created ScheduledCall, or None if any rule blocks creation.
    """
    from app.leads.models import Lead
    from app.tenants.models import Client

    # Load client config
    client = await db.get(Client, client_id)
    if client is None:
        logger.warning("auto_schedule_client_not_found", client_id=client_id)
        return None

    # Rule 1: scheduler_enabled
    if not client.scheduler_enabled:
        logger.info("auto_schedule_skipped_disabled", client_id=client_id)
        return None

    # Rule 2: next_action_result.action (primary) or next_action_suggested (fallback)
    # qora-next-action: read from rich NextActionResult first; legacy string is fallback
    next_action_result_raw = facts.get("next_action_result")
    if isinstance(next_action_result_raw, dict):
        next_action = next_action_result_raw.get("action") or ""
    else:
        next_action = ""

    # Fallback to legacy next_action_suggested if rich result has no action
    if not next_action:
        next_action = facts.get("next_action_suggested") or ""

    try:
        retry_outcomes: list[str] = json.loads(client.scheduler_retry_on_outcomes)
    except (json.JSONDecodeError, TypeError):
        retry_outcomes = ["busy", "no_answer", "follow_up"]

    if next_action not in retry_outcomes:
        logger.info(
            "auto_schedule_skipped_outcome",
            client_id=client_id,
            lead_id=lead_id,
            next_action=next_action,
        )
        return None

    # Rule 3: lead.do_not_call
    lead = await db.get(Lead, lead_id)
    if lead is None:
        logger.warning("auto_schedule_lead_not_found", lead_id=lead_id)
        return None

    if lead.do_not_call:
        logger.info("auto_schedule_skipped_do_not_call", lead_id=lead_id)
        return None

    # Rule 4: duplicate guard — no existing pending/in_progress for this lead
    existing = await get_active_scheduled_call_for_lead(
        db,
        client_id=client_id,
        lead_id=lead_id,
    )
    if existing is not None:
        logger.info("auto_schedule_skipped_duplicate", lead_id=lead_id)
        return None

    # Rule 5: max_attempts guard — count all historical attempts for this lead
    all_attempts = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
        )
    )
    attempt_count = len(list(all_attempts.scalars().all()))
    max_attempts = client.scheduler_max_attempts
    if attempt_count >= max_attempts:
        logger.info(
            "auto_schedule_skipped_max_attempts",
            lead_id=lead_id,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
        )
        return None

    # Resolve agent_id: prefer explicit > session's agent > client default
    resolved_agent_id = agent_id
    if resolved_agent_id is None:
        # Try to inherit from source session
        from app.calls.models import CallSession

        session_result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        source_session = session_result.scalar_one_or_none()
        if source_session is not None and source_session.agent_id:
            resolved_agent_id = source_session.agent_id

    if resolved_agent_id is None:
        # Fall back to client's default agent
        from app.tenants.service import get_default_agent

        default_agent = await get_default_agent(db, client_id)
        if default_agent is not None:
            resolved_agent_id = default_agent.id

    # Calculate scheduled_at — check for next_action_at override from NextActionResult
    # qora-next-action: if next_action_result.next_action_at is set, use it directly
    now_utc = datetime.now(timezone.utc)
    scheduled_at: datetime | None = None

    next_action_result = facts.get("next_action_result") or {}
    if isinstance(next_action_result, dict):
        nat = next_action_result.get("next_action_at")
        if nat is not None:
            if isinstance(nat, str):
                try:
                    parsed_nat = datetime.fromisoformat(nat)
                    if parsed_nat.tzinfo is None:
                        parsed_nat = parsed_nat.replace(tzinfo=timezone.utc)
                    scheduled_at = parsed_nat
                except ValueError:
                    pass
            elif isinstance(nat, datetime):
                scheduled_at = nat

    # Fallback: use calculate_scheduled_at if no override
    if scheduled_at is None:
        scheduled_at = calculate_scheduled_at(
            now_utc=now_utc,
            cooldown_minutes=client.scheduler_cooldown_minutes,
            start_hour=client.scheduler_allowed_hours_start,
            end_hour=client.scheduler_allowed_hours_end,
            tz_str=client.scheduler_timezone,
        )

    sc = await create_scheduled_call(
        db,
        client_id=client_id,
        lead_id=lead_id,
        scheduled_at=scheduled_at,
        trigger_reason="auto_retry",
        source_session_id=session_id,
        attempt_number=attempt_count + 1,
        max_attempts=max_attempts,
        notes=None,
        agent_id=resolved_agent_id,
    )

    logger.info(
        "auto_schedule_created",
        client_id=client_id,
        lead_id=lead_id,
        scheduled_at=scheduled_at.isoformat(),
        attempt_number=attempt_count + 1,
    )
    return sc


# ---------------------------------------------------------------------------
# Background tick — mark due calls as in_progress
# ---------------------------------------------------------------------------


async def mark_due_calls_in_progress(db: AsyncSession) -> int:
    """Find pending calls that are due and mark them in_progress.

    Args:
        db: Active async DB session.

    Returns:
        Number of records promoted to in_progress.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.status == "pending",
            ScheduledCall.scheduled_at <= now,
        )
    )
    due_calls = list(result.scalars().all())

    if not due_calls:
        return 0

    for sc in due_calls:
        sc.status = "in_progress"
        sc.updated_at = now

    await db.flush()

    logger.info(
        "scheduler_tick_promoted",
        count=len(due_calls),
        ids=[sc.id for sc in due_calls],
    )
    return len(due_calls)


async def scheduler_tick() -> None:
    """Async background loop — runs every 60 seconds, marks due calls in_progress.

    Registered in main.py lifespan. Survives DB errors without crashing.
    """
    from app.core.database import get_session

    while True:
        await asyncio.sleep(_TICK_INTERVAL_SECONDS)
        try:
            async with get_session() as db:
                count = await mark_due_calls_in_progress(db)
                if count > 0:
                    logger.info("scheduler_tick_complete", promoted=count)
        except Exception as exc:
            logger.warning("scheduler_tick_failed", error=str(exc))
