"""transcript_flush Job Handler — Off-Call Transcript Durability.

Handles off-call transcript finalization for a completed or disconnected call session.
This handler runs ONLY at call boundaries (normal end or cut/disconnect), never inside
live user-turn handlers.

Durable outcome (PR3 blocker fix):
  Stamps two fields on the CallSession row that are externally visible and inspectable
  by B9/operators after the job completes:
    - transcript_finalized_at: UTC timestamp when finalization ran
    - transcript_turn_count:   Confirmed count of transcript_turns rows at finalization

  These fields are NULL on sessions that predate PR3 or whose flush job has not yet run.
  B9 can query WHERE transcript_finalized_at IS NULL to find sessions needing review.

Design constraint (PR 3 gate):
  - MUST NOT be called from schedule_user_turn_persist or _persist_user_turn.
  - MUST NOT be enqueued during live SSE streaming.
  - Enqueued by close_session() and _reconcile_session() AFTER the call ends.

Retry policy:
  - max_attempts=2 (caller responsibility; set by call-boundary enqueue sites).
  - Transient DB failures are retried by the executor with exponential backoff.
  - After both attempts fail, the job becomes 'dead' (accepted loss, not operator-review).
  - The session_id in payload allows dead jobs to be identified and diagnosed.

Spec: openspec/changes/phase-b-background-job-durability/specs/durable-transcript-persistence/spec.md
Design: openspec/changes/phase-b-background-job-durability/design.md
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession, TranscriptTurn

logger = structlog.get_logger(__name__)


async def transcript_flush_handler(payload: dict, db: AsyncSession) -> None:
    """Finalize and verify transcript state for a completed call session.

    Responsibilities:
      1. Validate that the session exists (raise if not found — executor retries).
      2. Count transcript turns persisted for the session.
      3. Stamp transcript_finalized_at and transcript_turn_count on the CallSession row.
         This is the externally visible durable outcome — operators and B9 can inspect
         these fields to confirm finalization ran.
      4. Log the finalized turn count for observability.

    The durable stamp (step 3) is the key PR3 outcome. Without it, the handler only
    verified state without producing any durable record of that verification, making CI
    able to pass with no observable finalization effect.

    Idempotent: re-running on an already-finalized session updates the timestamp and
    reconfirms the turn count. Safe for executor retries.

    Args:
        payload: Must contain 'session_id' (str, UUID of the call session).
        db: Fresh async DB session provided by the executor per attempt.

    Raises:
        ValueError: If 'session_id' is missing or empty in payload.
        RuntimeError: If the call session is not found in the DB (caller should retry).
        Any DB exception propagates — executor applies retry/backoff/dead-letter.

    Spec: Requirement: Off-Call Transcript Durability Uses Bounded Retries
    """
    session_id: str = payload["session_id"]  # raises KeyError if missing — executor dead-letters

    if not session_id:
        raise ValueError("transcript_flush_handler: payload 'session_id' must be non-empty")

    # Verify the session exists
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()

    if session is None:
        # Session not found — could be a transient replication lag or a real miss.
        # Raise so the executor retries. After max_attempts the job becomes dead
        # (not operator_review — this is accepted bounded loss, per spec).
        raise RuntimeError(
            f"transcript_flush: CallSession not found. Will retry if attempts remain."
        )

    # Count persisted transcript turns (off-call durability confirmation)
    turns_result = await db.execute(
        select(TranscriptTurn).where(TranscriptTurn.session_id == session_id)
    )
    turns = list(turns_result.scalars().all())
    turn_count = len(turns)

    # --- Durable finalization write (PR3 blocker fix) ---
    # Stamp the session with finalization timestamp and confirmed turn count.
    # This is the externally visible outcome that proves finalization ran.
    # Idempotent: repeatable on retry — just updates the timestamp.
    finalized_at = datetime.now(timezone.utc)
    session.transcript_finalized_at = finalized_at
    session.transcript_turn_count = turn_count
    # db.flush() writes the UPDATE to the DB within the current transaction.
    # The executor's get_session() context manager commits on exit, making it durable.
    await db.flush()

    logger.info(
        "transcript_flush_completed",
        session_id=session_id,
        turn_count=turn_count,
        session_status=session.status,
        finalized_at=finalized_at.isoformat(),
    )
