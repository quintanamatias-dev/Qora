"""QORA Scheduler — Scheduling engine and lifecycle service (Phase 6).

Core functions:
- calculate_scheduled_at(): UTC/TZ clamping (pure function)
- create_scheduled_call(): stage a new ScheduledCall (flushed, caller must commit)
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
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduler.models import VALID_TRANSITIONS, ScheduledCall

logger = structlog.get_logger(__name__)

_TICK_INTERVAL_SECONDS = 60

# ---------------------------------------------------------------------------
# C6: Tech-retry constants (hardcoded MVP — extract to Client column if needed)
# ---------------------------------------------------------------------------

#: Maximum number of Qora-owned technical retries per lead (separate from recontact).
_TECH_RETRY_MAX_ATTEMPTS: int = 2

#: Fixed delay (minutes) for tech retries — independent of client cooldown.
_TECH_RETRY_DELAY_MINUTES: int = 5

# ---------------------------------------------------------------------------
# Phase C6b: Auto-dialer runner constants
# ---------------------------------------------------------------------------

#: Claim timeout (minutes) — a claimed row with no dial attempt past this
#: window is considered stranded (class a). Reaped in Slice 3.
_CLAIM_TIMEOUT_MINUTES: int = 10

#: Age-out cap (hours) for stranded rows — bounds a crash-loop. Reaped in Slice 3.
_MAX_STRANDED_HOURS: int = 6


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


def calculate_backoff_delay(
    cooldown_minutes: int,
    backoff_multiplier: float,
    attempt_number: int,
) -> float:
    """Calculate recontact delay applying the exponential backoff formula.

    Formula: delay = cooldown_minutes × (backoff_multiplier ^ (attempt_number − 1))
    A multiplier of 1.0 produces a flat delay identical to the original behavior.

    Args:
        cooldown_minutes: Base cooldown from client config.
        backoff_multiplier: Escalation factor (1.0 = flat, 2.0 = double per attempt).
        attempt_number: 1-indexed attempt count for this lead.

    Returns:
        Delay in minutes (float).
    """
    return cooldown_minutes * (backoff_multiplier ** (attempt_number - 1))


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
    """Stage a new ScheduledCall with status=pending.

    The row is added to the session and flushed (visible within the current
    transaction) but NOT committed. The caller is responsible for calling
    db.commit() to make the row durable. Failing to commit before the session
    is closed will silently roll back the ScheduledCall.

    Args:
        db: Active async DB session.
        client_id: Client tenant ID.
        lead_id: Lead being scheduled.
        scheduled_at: UTC datetime for the call.
        trigger_reason: One of: auto_retry | followup_tool | manual | tech_retry.
        source_session_id: Session that triggered this (or None).
        attempt_number: Which attempt this is (1-indexed).
        max_attempts: Max attempts copied from client config at creation time.
        notes: Optional free-text note.
        agent_id: Optional Agent UUID to associate with this scheduled call.

    Returns:
        The staged ScheduledCall instance (flushed, not yet committed).
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
    """Return the pending/in_progress ScheduledCall for a lead, if any.

    D7 (C6b): more than one active row per lead is a reachable state (design.md
    D1 — e.g. a stale in_progress row alongside a freshly-created pending
    recontact). scalar_one_or_none() would raise MultipleResultsFound in that
    case; instead, order by scheduled_at and deterministically return the
    earliest active row rather than crash the caller (auto_schedule's dedup
    guard).
    """
    result = await db.execute(
        select(ScheduledCall)
        .where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
            ScheduledCall.status.in_(["pending", "in_progress"]),
        )
        .order_by(ScheduledCall.scheduled_at)
        .limit(1)
    )
    return result.scalars().first()


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

    # Rule 5: max_attempts guard — count only auto_retry (recontact) rows.
    # C6: tech_retry rows are managed separately and must NOT count toward
    # the lead recontact limit. Filter by trigger_reason to isolate counters.
    all_attempts = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
            ScheduledCall.trigger_reason != "tech_retry",
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

    # Fallback: use calculate_scheduled_at with backoff formula if no override.
    # C6: apply scheduler_backoff_multiplier to escalate delay per attempt.
    if scheduled_at is None:
        backoff_multiplier = getattr(client, "scheduler_backoff_multiplier", 1.0) or 1.0
        effective_cooldown = int(
            calculate_backoff_delay(
                cooldown_minutes=client.scheduler_cooldown_minutes,
                backoff_multiplier=backoff_multiplier,
                attempt_number=attempt_count + 1,
            )
        )
        scheduled_at = calculate_scheduled_at(
            now_utc=now_utc,
            cooldown_minutes=effective_cooldown,
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
# C6: Tech-retry lane — Qora-owned technical error retry
# ---------------------------------------------------------------------------


async def schedule_tech_retry(
    db: AsyncSession,
    *,
    session_id: str,
    lead_id: str,
    client_id: str,
    agent_id: str | None = None,
) -> ScheduledCall | None:
    """Schedule a Qora-owned technical retry for a transient provider failure.

    Unlike auto_schedule (client-owned recontact), tech retry:
    - Uses a hardcoded 5-minute delay, independent of client cooldown — but
      clamped to the client's allowed-hours window (Decision 7, C6b): a
      candidate landing outside [scheduler_allowed_hours_start,
      scheduler_allowed_hours_end) in the client's scheduler_timezone rolls
      forward to the next allowed window instead of firing immediately.
    - Has a fixed max of 2 retries per lead (independent of client max_attempts).
    - Uses trigger_reason='tech_retry' so counters are isolated from auto_retry.
    - Does NOT increment the lead's recontact attempt counter.

    Returns:
        Staged (flushed, not committed) ScheduledCall on success.
        None if max tech retries reached, an active (pending/in_progress)
        tech_retry already exists for this lead (dedup guard), OR the client
        cannot be found.
    """
    # Dedup guard: if a pending or in_progress tech retry already exists for this lead,
    # do not create another one. This prevents duplicate pending rows when
    # schedule_tech_retry is called multiple times before the first retry executes.
    active_tech_retry_result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
            ScheduledCall.trigger_reason == "tech_retry",
            ScheduledCall.status.in_(["pending", "in_progress"]),
        )
    )
    active_tech_retry = active_tech_retry_result.scalar_one_or_none()
    if active_tech_retry is not None:
        logger.info(
            "tech_retry_skipped_active_exists",
            lead_id=lead_id,
            client_id=client_id,
            active_id=active_tech_retry.id,
        )
        return None

    # Count existing tech_retry rows for this lead (isolated counter — all statuses)
    tech_attempts_result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.lead_id == lead_id,
            ScheduledCall.client_id == client_id,
            ScheduledCall.trigger_reason == "tech_retry",
        )
    )
    tech_count = len(list(tech_attempts_result.scalars().all()))

    if tech_count >= _TECH_RETRY_MAX_ATTEMPTS:
        logger.info(
            "tech_retry_max_reached",
            lead_id=lead_id,
            client_id=client_id,
            tech_count=tech_count,
            max=_TECH_RETRY_MAX_ATTEMPTS,
        )
        return None

    # Resolve agent from source session or client default (same pattern as auto_schedule)
    resolved_agent_id = agent_id
    if resolved_agent_id is None:
        from app.calls.models import CallSession

        session_result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        source_session = session_result.scalar_one_or_none()
        if source_session is not None and source_session.agent_id:
            resolved_agent_id = source_session.agent_id

    if resolved_agent_id is None:
        from app.tenants.service import get_default_agent

        default_agent = await get_default_agent(db, client_id)
        if default_agent is not None:
            resolved_agent_id = default_agent.id

    # Decision 7 (C6b): clamp the candidate to the client's allowed-hours
    # window — reuses calculate_scheduled_at() (the same clamp auto_schedule
    # already uses) instead of duplicating clamp logic. Inside the window
    # this is byte-for-byte the original now+5min behaviour.
    from app.tenants.models import Client

    client = await db.get(Client, client_id)
    if client is None:
        logger.warning(
            "tech_retry_client_not_found", client_id=client_id, lead_id=lead_id
        )
        return None  # FK would reject the insert anyway

    now_utc = datetime.now(timezone.utc)
    raw_at = now_utc + timedelta(minutes=_TECH_RETRY_DELAY_MINUTES)
    scheduled_at = calculate_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=_TECH_RETRY_DELAY_MINUTES,
        start_hour=client.scheduler_allowed_hours_start,
        end_hour=client.scheduler_allowed_hours_end,
        tz_str=client.scheduler_timezone,
    )
    if scheduled_at != raw_at:
        logger.warning(
            "tech_retry_deferred_to_allowed_hours",
            lead_id=lead_id,
            raw_scheduled_at=raw_at.isoformat(),
            scheduled_at=scheduled_at.isoformat(),
            deferred_minutes=int((scheduled_at - raw_at).total_seconds() // 60),
        )

    sc = await create_scheduled_call(
        db,
        client_id=client_id,
        lead_id=lead_id,
        scheduled_at=scheduled_at,
        trigger_reason="tech_retry",
        source_session_id=session_id,
        attempt_number=tech_count + 1,
        max_attempts=_TECH_RETRY_MAX_ATTEMPTS,
        notes="Qora-owned technical retry: transient provider failure",
        agent_id=resolved_agent_id,
    )

    logger.info(
        "tech_retry_scheduled",
        client_id=client_id,
        lead_id=lead_id,
        session_id=session_id,
        attempt_number=tech_count + 1,
        scheduled_at=scheduled_at.isoformat(),
    )
    return sc


# ---------------------------------------------------------------------------
# Phase C6b: Auto-dialer CAS claim
#
# Two guards prevent double-dialing a lead across processes:
#   (a) an atomic conditional UPDATE, dial only when rowcount == 1
#   (b) uq_scheduled_calls_active_lead — at most one in_progress row per lead
# _claim_one is the single documented exception to D8 (_set_scheduled_call_status):
# it is a raw Core UPDATE, not an ORM instance write, because the claim must be
# a single atomic statement the DB can evaluate without a prior SELECT-then-write
# race window.
# ---------------------------------------------------------------------------


async def _claim_one(db: AsyncSession, sc_id: str, now: datetime) -> bool:
    """Atomically claim a pending ScheduledCall. True iff this process won.

    Design: openspec/changes/phase-c6b-auto-dialer/design.md — The Claim
    Statement (verbatim contract).
    """
    stmt = (
        sa.update(ScheduledCall)
        .where(ScheduledCall.id == sc_id, ScheduledCall.status == "pending")
        .values(status="in_progress", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    try:
        result = await db.execute(stmt)
        await db.commit()
    except IntegrityError:
        # uq_scheduled_calls_active_lead — another row for this lead is
        # already in_progress (e.g. auto_retry claimed first, this is the
        # lead's parked tech_retry). Expected under contention.
        await db.rollback()
        logger.warning(
            "auto_dialer_claim_conflict",
            scheduled_call_id=sc_id,
            reason="lead_already_in_progress",
        )
        return False
    if result.rowcount != 1:
        logger.warning(
            "auto_dialer_claim_conflict",
            scheduled_call_id=sc_id,
            reason="lost_race",
            rowcount=result.rowcount,
        )
        return False
    return True


async def claim_due_scheduled_calls(
    db: AsyncSession, limit: int
) -> list[ScheduledCall]:
    """Claim up to `limit` due pending ScheduledCalls via the CAS above.

    The candidate SELECT is advisory (bounded, ordered by scheduled_at); the
    per-row UPDATE in _claim_one is authoritative. Returns only the rows this
    process actually won — losers are silently excluded (already logged by
    _claim_one).
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ScheduledCall)
        .where(
            ScheduledCall.status == "pending",
            ScheduledCall.scheduled_at <= now,
        )
        .order_by(ScheduledCall.scheduled_at)
        .limit(limit)
    )
    candidates = list(result.scalars().all())
    if candidates:
        logger.info(
            "auto_dialer_cycle_started",
            candidates=len(candidates),
            limit=limit,
        )

    claimed: list[ScheduledCall] = []
    for sc in candidates:
        won = await _claim_one(db, sc.id, now)
        if not won:
            continue
        # _claim_one committed via a raw Core UPDATE (synchronize_session=False) —
        # refresh so this ORM instance reflects the new status/updated_at before
        # the caller (claim_due_scheduled_calls / dial loop) reads or writes it.
        await db.refresh(sc)
        claimed.append(sc)
        logger.info(
            "auto_dialer_claimed",
            scheduled_call_id=sc.id,
            lead_id=sc.lead_id,
            trigger_reason=sc.trigger_reason,
            attempt_number=sc.attempt_number,
        )
    return claimed


async def _set_scheduled_call_status(
    db: AsyncSession, sc: ScheduledCall, new_status: str
) -> None:
    """Single write seam for ScheduledCall.status transitions (D8).

    VALID_TRANSITIONS enforcement stays deferred (proposal scope decision),
    but every new status write in this slice routes through this helper so
    the follow-up enforcement change has exactly one seam to swap instead of
    a scattered set of hand-rolled if/raise checks. The CAS claim (_claim_one)
    is the single documented exception — a raw Core UPDATE, not an ORM
    instance write.
    """
    sc.status = new_status
    sc.updated_at = datetime.now(timezone.utc)
    await db.flush()


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

    promoted_ids: list[str] = []
    for sc in due_calls:
        # Snapshot before the flush — a SAVEPOINT rollback expires this row.
        sc_id, sc_lead_id = sc.id, sc.lead_id
        try:
            async with db.begin_nested():
                sc.status = "in_progress"
                sc.updated_at = now
                await db.flush()
        except IntegrityError:
            logger.warning(
                "scheduler_tick_promote_conflict", scheduled_call_id=sc_id, lead_id=sc_lead_id
            )
            continue
        promoted_ids.append(sc_id)

    if promoted_ids:
        logger.info("scheduler_tick_promoted", count=len(promoted_ids), ids=promoted_ids)
    return len(promoted_ids)


# ---------------------------------------------------------------------------
# Phase C6b: Dial loop — dials rows this process claimed
# ---------------------------------------------------------------------------


async def _dial_claimed_scheduled_call(
    db: AsyncSession, sc: ScheduledCall, settings, *, now_utc: datetime | None = None
) -> None:
    """Dial one claimed ScheduledCall and persist the outcome.

    dial_outbound_call() never raises by contract, but that contract is not a
    guarantee (design.md — Observability: auto_dialer_dial_exception) — an
    unexpected exception here still forces the row to failed rather than
    leaving it stranded in_progress with no outcome_session_id. Also
    re-validates allowed-hours at DIAL time (F2 below).

    Imports dial_outbound_call locally, matching scheduler_tick's existing
    local-import style and the patch seam design.md's Testing Strategy pins
    for unit tests (patch("app.outbound.service.dial_outbound_call")).
    """
    from app.leads.service import get_lead
    from app.tenants.models import Agent
    from app.tenants.service import get_client, get_default_agent
    from app.outbound.service import dial_outbound_call

    logger.info(
        "auto_dialer_dial_attempted",
        scheduled_call_id=sc.id,
        lead_id=sc.lead_id,
    )

    try:
        now_utc = now_utc or datetime.now(timezone.utc)
        client = await get_client(db, sc.client_id)

        # F2: don't dial an overdue row outside the client's allowed hours.
        if client is not None:
            next_allowed_at = calculate_scheduled_at(
                now_utc=now_utc,
                cooldown_minutes=0,
                start_hour=client.scheduler_allowed_hours_start,
                end_hour=client.scheduler_allowed_hours_end,
                tz_str=client.scheduler_timezone,
            )
            if next_allowed_at != now_utc:
                sc.scheduled_at = next_allowed_at
                await _set_scheduled_call_status(db, sc, "pending")
                await db.commit()
                logger.warning(
                    "auto_dialer_dial_outside_allowed_hours",
                    scheduled_call_id=sc.id, lead_id=sc.lead_id,
                    next_allowed_at=next_allowed_at.isoformat(),
                )
                return

        lead = await get_lead(db, sc.lead_id)
        agent = (
            await db.get(Agent, sc.agent_id)
            if sc.agent_id
            else await get_default_agent(db, sc.client_id)
        )
        result = await dial_outbound_call(
            db,
            lead=lead,
            agent=agent,
            client=client,
            settings=settings,
            scheduled_call=sc,
        )
    except Exception as exc:
        logger.error(
            "auto_dialer_dial_exception",
            scheduled_call_id=sc.id,
            lead_id=sc.lead_id,
            error=str(exc),
        )
        await _set_scheduled_call_status(db, sc, "failed")
        await db.commit()
        return

    if result.status == "dialing":
        sc.outcome_session_id = result.call_session_id
        await db.commit()
        logger.info(
            "auto_dialer_dial_accepted",
            scheduled_call_id=sc.id,
            call_session_id=result.call_session_id,
        )
        return

    # "failed" or "recurrent_error" — dial_outbound_call's own schedule_tech_retry
    # lane handles rescheduling; this ScheduledCall's own outcome is terminal.
    logger.error(
        "auto_dialer_dial_failed",
        scheduled_call_id=sc.id,
        lead_id=sc.lead_id,
        failure_code=result.failure_code,
        error=result.error,
    )
    await _set_scheduled_call_status(db, sc, "failed")
    await db.commit()


async def run_scheduler_cycle(
    db: AsyncSession, settings, *, now_utc: datetime | None = None
) -> None:
    """One scheduler_tick cycle — extracted so tests drive one cycle instead
    of the infinite while-True loop.

    Design: openspec/changes/phase-c6b-auto-dialer/design.md — Technical Approach.

        if enable_auto_dialer AND enable_outbound_calls
               -> claim_due_scheduled_calls(db, limit)   # CAS, replaces bulk promote
               -> asyncio.gather(dial…)
        else   -> mark_due_calls_in_progress(db)         # unchanged

    With enable_auto_dialer=False the executed path is byte-for-byte today's
    behaviour — the tick does not even query for dial candidates.
    """
    if settings.enable_auto_dialer and settings.enable_outbound_calls:
        claimed = await claim_due_scheduled_calls(
            db, settings.auto_dialer_max_concurrent_dials
        )
        if claimed:
            await asyncio.gather(
                *(_dial_claimed_scheduled_call(db, sc, settings, now_utc=now_utc) for sc in claimed)
            )
    else:
        count = await mark_due_calls_in_progress(db)
        if count > 0:
            logger.info("scheduler_tick_complete", promoted=count)


async def scheduler_tick() -> None:
    """Async background loop — runs every 60 seconds.

    Registered in main.py lifespan. Survives DB errors without crashing.
    """
    from app.core.config import Settings
    from app.core.database import get_session

    while True:
        await asyncio.sleep(_TICK_INTERVAL_SECONDS)
        try:
            settings = Settings()
            async with get_session() as db:
                await run_scheduler_cycle(db, settings)
        except Exception as exc:
            logger.warning("scheduler_tick_failed", error=str(exc))
