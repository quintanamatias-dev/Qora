"""Durable Post-Call Summarization Job Handler.

Runs the summarizer pipeline inside the background job executor so the work
survives process restarts. Uses generate_summary_and_facts_durable() which
propagates exceptions to the executor for retry/dead-letter visibility.

Handler signature: async (payload: dict, db: AsyncSession) -> None

Payload keys:
  session_id (str): UUID of the completed CallSession to summarize.

Design note:
  The legacy generate_summary_and_facts() swallows all exceptions (fire-and-
  forget behavior). The durable handler MUST use generate_summary_and_facts_durable()
  so the executor can see failures, record them in background_jobs.error, and
  apply retry/backoff. Silently marking a failed summarization as 'completed'
  hides errors from operators and prevents retries (BLOCKER B2).

Spec:   openspec/changes/phase-b-background-job-durability/specs/durable-post-call-pipeline/spec.md
Design: openspec/changes/phase-b-background-job-durability/design.md
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def summarize_handler(payload: dict, db: AsyncSession) -> None:
    """Execute post-call summarization for a completed call session.

    Calls generate_summary_and_facts_durable(session_id, db) using the db
    session provided by the executor (one fresh session per attempt).

    Uses the durable variant (not the fire-and-forget variant) so that any
    failure propagates to the executor. This enables:
    - Executor records error in background_jobs.error (operator visibility)
    - Executor applies retry with exponential backoff (transient failures)
    - Executor dead-letters after max_attempts (persistent failures)

    Args:
        payload: Must contain 'session_id' (str) — UUID of the CallSession.
        db:      Fresh AsyncSession provided by the executor for this attempt.

    Raises:
        ValueError: If 'session_id' is missing from the payload.
        Exception:  Any exception from generate_summary_and_facts_durable
                    propagates so the executor can record it and apply
                    retry/dead-letter. MUST NOT be swallowed here.

    Spec: Requirement: Post-Call Summarization Is Durable
    """
    session_id = payload.get("session_id")
    if not session_id:
        raise ValueError(
            "summarize_handler: payload must contain 'session_id'. "
            f"Got keys: {list(payload.keys())}"
        )

    # Use the durable variant — propagates exceptions so executor sees failures.
    # Do NOT use generate_summary_and_facts() here: it swallows all exceptions
    # and always returns None, which would cause executor to mark every job
    # 'completed' regardless of whether summarization actually succeeded.
    from app.summarizer import generate_summary_and_facts_durable

    logger.info("summarize_job_started", session_id=session_id)
    await generate_summary_and_facts_durable(session_id, db)
    logger.info("summarize_job_completed", session_id=session_id)
