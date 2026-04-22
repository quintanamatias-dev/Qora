"""QORA Calls — Service layer for call session lifecycle and transcript management.

Covers: CAP-7 call session lifecycle, transcript turns, billable minutes.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession, TranscriptTurn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECONCILIATION_WINDOW_SECONDS = 120


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def create_session(
    session: AsyncSession,
    *,
    client_id: str,
    lead_id: str | None,
    elevenlabs_conversation_id: str | None = None,
    session_id: str | None = None,
) -> CallSession:
    """Create a new call session with status=initiated.

    Args:
        session: Active async DB session.
        client_id: Tenant client id.
        lead_id: Lead being called.
        elevenlabs_conversation_id: Optional ElevenLabs conversation ID.
        session_id: Optional pre-generated UUID (uses uuid4 if not provided).

    Returns:
        Persisted CallSession instance.
    """
    cs = CallSession(
        id=session_id or str(uuid.uuid4()),
        client_id=client_id,
        lead_id=lead_id,
        elevenlabs_conversation_id=elevenlabs_conversation_id,
        status="initiated",
    )
    session.add(cs)
    await session.flush()
    return cs


async def get_session(session: AsyncSession, session_id: str) -> CallSession | None:
    """Fetch a CallSession by its UUID id.

    Returns:
        CallSession instance or None if not found.
    """
    result = await session.execute(
        select(CallSession).where(CallSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def end_session(
    session: AsyncSession,
    *,
    session_id: str,
    outcome: str,
    duration_seconds: float,
) -> CallSession:
    """Finalize a call session with outcome and billing.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session to finalize.
        outcome: One of 'completed', 'abandoned', 'failed'.
        duration_seconds: Total duration of the call in seconds.

    Returns:
        Updated CallSession instance.

    Raises:
        ValueError: If session not found.
    """
    cs = await get_session(session, session_id)
    if cs is None:
        raise ValueError(f"CallSession not found: {session_id!r}")

    cs.ended_at = datetime.now(timezone.utc)
    cs.duration_seconds = duration_seconds
    cs.outcome = outcome
    cs.status = outcome  # status mirrors outcome for completed/abandoned/failed
    cs.billable_minutes = math.ceil(duration_seconds / 60)

    await session.flush()
    return cs


# ---------------------------------------------------------------------------
# Transcript management
# ---------------------------------------------------------------------------


async def add_transcript_turn(
    session: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    filler_detected: bool = False,
) -> TranscriptTurn:
    """Append a transcript turn to a call session.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session.
        role: 'user', 'agent', or 'tool'.
        content: Text content of the turn.
        filler_detected: Whether this turn was a filler injection.

    Returns:
        Persisted TranscriptTurn instance.
    """
    turn = TranscriptTurn(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        filler_detected=1 if filler_detected else 0,
    )
    session.add(turn)
    await session.flush()
    return turn


async def get_transcript(
    session: AsyncSession, session_id: str
) -> list[TranscriptTurn]:
    """Return all transcript turns for a call session, ordered by timestamp.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session.

    Returns:
        List of TranscriptTurn instances in chronological order.
    """
    result = await session.execute(
        select(TranscriptTurn)
        .where(TranscriptTurn.session_id == session_id)
        .order_by(TranscriptTurn.timestamp)
    )
    return list(result.scalars().all())


async def count_turns(session: AsyncSession, session_id: str) -> tuple[int, int]:
    """Return (user_turns, agent_turns) counts for a call session.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session.

    Returns:
        Tuple of (user_turn_count, agent_turn_count).
    """
    result = await session.execute(
        select(TranscriptTurn.role, func.count(TranscriptTurn.id))
        .where(TranscriptTurn.session_id == session_id)
        .group_by(TranscriptTurn.role)
    )
    counts: dict[str, int] = dict(result.all())
    return counts.get("user", 0), counts.get("agent", 0)


async def get_call_metrics(
    session: AsyncSession,
    *,
    client_id: str,
    lead_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Return aggregated call metrics for a client in a single query.

    Args:
        session: Active async DB session.
        client_id: Tenant client id — scopes all results.
        lead_id: Optional lead filter.
        date_from: Optional lower bound on CallSession.started_at (inclusive).
        date_to: Optional upper bound on CallSession.started_at (inclusive).

    Returns:
        Dict with keys: total_calls, completed_calls, abandoned_calls,
        total_duration_seconds, average_duration_seconds, total_billable_minutes.
    """
    completed_flag = case((CallSession.status == "completed", 1))
    abandoned_flag = case((CallSession.status == "abandoned", 1))

    stmt = (
        select(
            func.count(CallSession.id).label("total_calls"),
            func.count(completed_flag).label("completed_calls"),
            func.count(abandoned_flag).label("abandoned_calls"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            CallSession.status == "completed",
                            CallSession.duration_seconds,
                        )
                    )
                ),
                0.0,
            ).label("total_duration_seconds"),
            func.coalesce(
                func.avg(
                    case(
                        (
                            CallSession.status == "completed",
                            CallSession.duration_seconds,
                        )
                    )
                ),
                0.0,
            ).label("average_duration_seconds"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            CallSession.status == "completed",
                            CallSession.billable_minutes,
                        )
                    )
                ),
                0,
            ).label("total_billable_minutes"),
        )
        .where(CallSession.client_id == client_id)
        .where(
            CallSession.merged_into_session_id.is_(
                None
            )  # exclude merged siblings (Issue #22)
        )
    )

    if lead_id is not None:
        stmt = stmt.where(CallSession.lead_id == lead_id)
    if date_from is not None:
        stmt = stmt.where(CallSession.started_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(CallSession.started_at <= date_to)

    result = await session.execute(stmt)
    row = result.one()
    return {
        "total_calls": row.total_calls,
        "completed_calls": row.completed_calls,
        "abandoned_calls": row.abandoned_calls,
        "total_duration_seconds": float(row.total_duration_seconds),
        "average_duration_seconds": float(row.average_duration_seconds),
        "total_billable_minutes": int(row.total_billable_minutes),
    }


async def list_sessions_for_client(
    session: AsyncSession,
    client_id: str,
    lead_id: str | None = None,
) -> list[CallSession]:
    """Return all call sessions for a client, ordered by started_at DESC.

    Args:
        session: Active async DB session.
        client_id: Tenant client id — scopes all results.
        lead_id: Optional lead filter. If provided, returns only sessions for this lead.

    Returns:
        List of CallSession instances ordered by started_at descending (most recent first).
    """
    q = select(CallSession).where(CallSession.client_id == client_id)
    if lead_id is not None:
        q = q.where(CallSession.lead_id == lead_id)
    # Exclude merged sessions — they are absorbed into authoritative sessions (Issue #22)
    q = q.where(CallSession.merged_into_session_id.is_(None))
    q = q.order_by(CallSession.started_at.desc())
    result = await session.execute(q)
    return list(result.scalars().all())


async def get_sessions_for_lead(
    session: AsyncSession,
    lead_id: str,
    *,
    status_filter: list[str] | None = None,
    limit: int = 3,
) -> list[CallSession]:
    """Return the most recent call sessions for a lead.

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.
        status_filter: If provided, only return sessions with these statuses.
        limit: Maximum number of sessions to return.

    Returns:
        List of CallSession instances ordered by ended_at descending.
    """
    q = select(CallSession).where(CallSession.lead_id == lead_id)
    if status_filter:
        q = q.where(CallSession.status.in_(status_filter))
    q = q.order_by(CallSession.ended_at.desc()).limit(limit)
    result = await session.execute(q)
    return list(result.scalars().all())


async def get_session_by_elevenlabs_id(
    session: AsyncSession, elevenlabs_conversation_id: str
) -> CallSession | None:
    """Fetch a CallSession by ElevenLabs conversation ID.

    Returns:
        CallSession instance or None if not found.
    """
    result = await session.execute(
        select(CallSession).where(
            CallSession.elevenlabs_conversation_id == elevenlabs_conversation_id
        )
    )
    return result.scalar_one_or_none()


async def _merge_sibling_sessions(
    session: AsyncSession,
    *,
    completed_session: CallSession,
) -> list[str]:
    """Re-assign transcript turns from sibling sessions into the completed one.

    Sibling criteria (ALL must match):
    - same client_id and lead_id as completed_session
    - id != completed_session.id
    - status IN ('initiated', 'abandoned')
    - elevenlabs_conversation_id IS NULL
    - started_at within ±RECONCILIATION_WINDOW_SECONDS of completed_session.started_at
    - merged_into_session_id IS NULL (prevent double-merge)

    Returns list of merged sibling session IDs (empty if none found).
    Caller MUST flush after — this function does NOT flush.
    """
    if completed_session.started_at is None:
        return []

    started = completed_session.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    window_start = started - timedelta(seconds=RECONCILIATION_WINDOW_SECONDS)
    window_end = started + timedelta(seconds=RECONCILIATION_WINDOW_SECONDS)

    result = await session.execute(
        select(CallSession)
        .where(CallSession.client_id == completed_session.client_id)
        .where(CallSession.lead_id == completed_session.lead_id)
        .where(CallSession.id != completed_session.id)
        .where(CallSession.status.in_(["initiated", "abandoned"]))
        .where(CallSession.elevenlabs_conversation_id.is_(None))
        .where(CallSession.started_at >= window_start)
        .where(CallSession.started_at <= window_end)
        .where(CallSession.merged_into_session_id.is_(None))
    )
    siblings = list(result.scalars().all())

    if not siblings:
        return []

    sibling_ids = [s.id for s in siblings]

    # Bulk-reassign transcript turns from all siblings to completed session
    await session.execute(
        update(TranscriptTurn)
        .where(TranscriptTurn.session_id.in_(sibling_ids))
        .values(session_id=completed_session.id)
    )

    # Mark each sibling as merged
    for sibling in siblings:
        sibling.merged_into_session_id = completed_session.id

    # Recount turns on completed session using existing count_turns()
    user_turns, agent_turns = await count_turns(session, completed_session.id)
    completed_session.total_user_turns = user_turns
    completed_session.total_agent_turns = agent_turns

    return sibling_ids


async def _reconcile_session(
    session: AsyncSession,
    *,
    conversation_id: str,
    client_id: str,
    lead_id: str,
    closed_reason: str,
    update_lead_counters: bool,
) -> CallSession | None:
    """Reconciliation fallback: find and close an orphan initiated session.

    Queries for the most recent initiated session matching (client_id, lead_id)
    with no elevenlabs_conversation_id within RECONCILIATION_WINDOW_SECONDS.

    Args:
        session: Active async DB session.
        conversation_id: The unknown conversation_id from /end (to assign).
        client_id: Tenant hint from request body.
        lead_id: Lead hint from request body.
        closed_reason: Reason for closing.
        update_lead_counters: Whether to increment Lead.call_count.

    Returns:
        Reconciled CallSession, or None if no match found.
    """
    from app.leads.models import Lead  # avoid circular import

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=RECONCILIATION_WINDOW_SECONDS
    )

    result = await session.execute(
        select(CallSession)
        .where(CallSession.client_id == client_id)
        .where(CallSession.lead_id == lead_id)
        .where(CallSession.status == "initiated")
        .where(CallSession.elevenlabs_conversation_id.is_(None))
        .where(CallSession.started_at >= cutoff)
        .order_by(CallSession.started_at.desc())
        .limit(1)
    )
    cs = result.scalar_one_or_none()

    if cs is None:
        return None

    now = datetime.now(timezone.utc)

    # Compute age for the log
    started = cs.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age_seconds = int((now - started).total_seconds())

    # Update the session in-place
    cs.elevenlabs_conversation_id = conversation_id
    cs.status = "completed"
    cs.closed_reason = closed_reason
    cs.ended_at = now
    delta = int((now - started).total_seconds())
    cs.duration_seconds = delta
    cs.billable_minutes = math.ceil(delta / 60)

    # Update turn counts
    user_turns, agent_turns = await count_turns(session, cs.id)
    cs.total_user_turns = user_turns
    cs.total_agent_turns = agent_turns

    # Increment Lead counters
    if update_lead_counters and cs.lead_id:
        lead_result = await session.execute(select(Lead).where(Lead.id == cs.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead is not None:
            lead.call_count = (lead.call_count or 0) + 1
            lead.last_called_at = now

    # Merge sibling sessions BEFORE flush (Issue #22)
    merged_ids = await _merge_sibling_sessions(session, completed_session=cs)

    await session.flush()

    if merged_ids:
        structlog.get_logger().info(
            "reconcile_session_merged_siblings",
            reconciled_session_id=cs.id,
            merged_sibling_ids=merged_ids,
        )

    # Emit reconciliation log
    structlog.get_logger().info(
        "end_session_reconciled",
        reconciled_session_id=cs.id,
        client_id=client_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        age_seconds=age_seconds,
    )

    # Fire-and-forget summary generation
    _schedule_summarize(cs.id)

    return cs


async def close_session(
    session: AsyncSession,
    *,
    session_id: str,
    closed_reason: str,
    update_lead_counters: bool = True,
    reconcile_client_id: str | None = None,
    reconcile_lead_id: str | None = None,
) -> tuple[CallSession, bool]:
    """Close a call session idempotently.

    Sets status="completed", ended_at, duration_seconds, closed_reason.
    Increments Lead.call_count and Lead.last_called_at — only on first close.

    Args:
        session: Active async DB session.
        session_id: ElevenLabs conversation ID or internal UUID of the session to close.
        closed_reason: One of the valid end reasons.
        update_lead_counters: If True, increment lead counters (only on first close).
        reconcile_client_id: Optional client_id hint for reconciliation fallback.
        reconcile_lead_id: Optional lead_id hint for reconciliation fallback.

    Returns:
        Tuple of (CallSession, was_already_closed) where was_already_closed=True
        means it was idempotent (already completed).

    Raises:
        ValueError: If session not found (and reconciliation also fails).
    """
    from app.leads.models import Lead  # avoid circular import at module level

    cs = await get_session(session, session_id)
    if cs is None:
        # Reconciliation fallback: attempt to find an orphan session matching hints
        if reconcile_client_id and reconcile_lead_id:
            cs = await _reconcile_session(
                session,
                conversation_id=session_id,
                client_id=reconcile_client_id,
                lead_id=reconcile_lead_id,
                closed_reason=closed_reason,
                update_lead_counters=update_lead_counters,
            )
            if cs is None:
                raise ValueError(f"CallSession not found: {session_id!r}")
            return cs, False
        raise ValueError(f"CallSession not found: {session_id!r}")

    # Idempotency: already completed → return early without re-incrementing
    if cs.status == "completed":
        return cs, True

    now = datetime.now(timezone.utc)
    cs.status = "completed"
    cs.ended_at = now
    cs.closed_reason = closed_reason

    if cs.started_at is not None:
        # SQLite returns naive datetimes even for timezone=True columns.
        # Normalize to UTC-aware if needed before computing delta.
        started = cs.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        delta = int((now - started).total_seconds())
        cs.duration_seconds = delta
        cs.billable_minutes = math.ceil(delta / 60)

    # Update turn counts
    user_turns, agent_turns = await count_turns(session, session_id)
    cs.total_user_turns = user_turns
    cs.total_agent_turns = agent_turns

    # Increment Lead counters — only on first close
    if update_lead_counters and cs.lead_id:
        lead_result = await session.execute(select(Lead).where(Lead.id == cs.lead_id))
        lead = lead_result.scalar_one_or_none()
        if lead is not None:
            lead.call_count = (lead.call_count or 0) + 1
            lead.last_called_at = now

    # Merge sibling sessions BEFORE flush so summarizer sees full transcript (Issue #22)
    merged_ids = await _merge_sibling_sessions(session, completed_session=cs)

    await session.flush()

    if merged_ids:
        structlog.get_logger().info(
            "close_session_merged_siblings",
            session_id=session_id,
            merged_sibling_ids=merged_ids,
        )

    # Fire-and-forget summary generation (CAP-4)
    # Non-blocking — MUST NOT delay session close response.
    # Uses a new independent DB session via asyncio.create_task.
    _schedule_summarize(session_id)

    return cs, False


# ---------------------------------------------------------------------------
# Fire-and-forget summary scheduling (CAP-4)
# ---------------------------------------------------------------------------


def _schedule_summarize(session_id: str) -> None:
    """Fire-and-forget: schedule summary + fact extraction for a session.

    Creates an asyncio background task that opens its own DB session.
    MUST NOT be called from outside an async context.

    Args:
        session_id: UUID of the call session to summarize.
    """
    asyncio.create_task(_summarize_in_background(session_id))


async def _summarize_in_background(session_id: str) -> None:
    """Background task: run summarizer in an independent DB session.

    Args:
        session_id: UUID of the call session to summarize.
    """
    from app.core.database import get_session as db_session
    from app.summarizer import generate_summary_and_facts

    try:
        async with db_session() as db:
            await generate_summary_and_facts(session_id, db)
    except Exception as exc:
        structlog.get_logger().warning(
            "background_summarize_failed",
            session_id=session_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Fire-and-forget user turn persistence (CAP-1)
# ---------------------------------------------------------------------------


_USER_TURN_RETRY_BACKOFF_SECONDS: float = 0.5


async def _persist_user_turn(session_id: str, content: str) -> None:
    """Persist a user transcript turn in a new DB session (background task).

    Retries exactly once after a 0.5s backoff on transient failure.
    Successful retry → warning log.
    Both attempts fail → error log (not warning). No exception propagated.
    """
    from app.core.database import get_session as db_session

    logger = structlog.get_logger()

    try:
        async with db_session() as db:
            await add_transcript_turn(db, session_id, "user", content)
        return  # Success on first attempt — no retry needed
    except Exception as exc:
        logger.warning(
            "user_turn_persist_retrying",
            session_id=session_id,
            error=str(exc),
        )

    # Retry once after backoff
    await asyncio.sleep(_USER_TURN_RETRY_BACKOFF_SECONDS)

    try:
        async with db_session() as db:
            await add_transcript_turn(db, session_id, "user", content)
        logger.warning(
            "user_turn_persist_retry_succeeded",
            session_id=session_id,
        )
    except Exception as exc:
        logger.error(
            "user_turn_persist_failed",
            session_id=session_id,
            error=str(exc),
        )


def schedule_user_turn_persist(session_id: str, messages: list[dict]) -> None:
    """Fire-and-forget: persist the latest user message from ElevenLabs messages.

    Scans messages from the end to find the last message with role="user".
    Schedules persistence as an asyncio background task — MUST NOT block the SSE stream.

    Args:
        session_id: UUID of the call session.
        messages: Full messages list from the custom LLM request body.
    """
    if not messages:
        return

    # Scan from end to find last user message (AD-6: last user message is the new utterance)
    user_content: str | None = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if content:
                user_content = content
                break

    if not user_content:
        return

    asyncio.create_task(_persist_user_turn(session_id, user_content))
