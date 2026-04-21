"""QORA — Background sweeper for stale call sessions (CAP-2c).

Runs every 60 seconds and marks `initiated` sessions older than 10 minutes
as `abandoned`. Does NOT increment Lead.call_count for abandoned sessions.

Mirrors the existing `_session_store_cleanup_task` pattern in main.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.calls.models import CallSession

logger = structlog.get_logger(__name__)

# Thresholds
_SWEEP_INTERVAL_SECONDS = 60
_STALE_THRESHOLD_MINUTES = 10


async def sweep_stale_sessions(db) -> int:
    """Find and mark stale `initiated` sessions as `abandoned`.

    A session is stale if it has status="initiated" and started_at is
    older than _STALE_THRESHOLD_MINUTES minutes ago.

    MUST NOT increment Lead.call_count — abandoned sessions do not count
    as completed calls.

    Args:
        db: Active async DB session (AsyncSession).

    Returns:
        Number of sessions marked abandoned.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STALE_THRESHOLD_MINUTES)

    result = await db.execute(
        select(CallSession).where(
            CallSession.status == "initiated",
            CallSession.started_at < cutoff,
        )
    )
    stale_sessions = list(result.scalars().all())

    if not stale_sessions:
        return 0

    now = datetime.now(timezone.utc)
    abandoned_ids: list[str] = []
    for cs in stale_sessions:
        cs.status = "abandoned"
        cs.ended_at = now
        # Populate closed_reason with the spec-defined "timeout" value
        # (CAP-2a enum: agent_goodbye | user_hangup | network_drop | timeout
        # | reconnect_attempt). Sweeper-closed sessions already have
        # status="abandoned", which distinguishes them from /end-closed
        # sessions (status="completed") — no need to invent a new enum value.
        if cs.closed_reason is None:
            cs.closed_reason = "timeout"
        # Do NOT touch Lead.call_count — spec requirement (CAP-2c)
        abandoned_ids.append(cs.id)

    await db.flush()

    logger.info(
        "sweeper_abandoned_sessions",
        count=len(stale_sessions),
        session_ids=abandoned_ids,
    )

    # Trigger summarizer for each abandoned session (CAP-4).
    # The summarizer itself skips sessions with 0 turns, so abandoned
    # sessions with no transcript produce no GPT call.
    from app.calls.service import _schedule_summarize

    for session_id in abandoned_ids:
        _schedule_summarize(session_id)

    return len(stale_sessions)


async def stale_session_sweeper() -> None:
    """Async background loop that sweeps stale sessions every 60 seconds.

    Registered in main.py lifespan as an asyncio task alongside
    the existing session_store_cleanup task.
    """
    from app.core.database import get_session as db_session

    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            async with db_session() as db:
                count = await sweep_stale_sessions(db)
                if count > 0:
                    logger.info("sweeper_run_complete", abandoned=count)
        except Exception as exc:
            logger.warning("sweeper_run_failed", error=str(exc))
