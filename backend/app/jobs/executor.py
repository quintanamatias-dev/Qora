"""Background Job Executor.

DB-backed in-process job executor that replaces fire-and-forget asyncio.create_task calls.

Responsibilities:
  - enqueue(): insert a pending row then create an asyncio task
  - _run_job(): manage the pending→running→completed|failed|dead lifecycle
  - recover(): on startup, re-enqueue pending/running jobs (crash recovery)
  - shutdown(): cancel active tasks on graceful shutdown
  - calculate_backoff(): pure exponential+jitter backoff (module-level helper)

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/background-job-executor/spec.md
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import sentry_sdk
import structlog
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.jobs.models import BackgroundJob
from app.jobs.registry import ConfigurationError, get_handler

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# B9 — Job context binding (observability-correlation spec)
# ---------------------------------------------------------------------------


def _bind_job_context(job_id: str, job_type: str) -> None:
    """Bind job_id and job_type to structlog contextvars.

    Called at the start of each _run_job() attempt, before the handler
    executes, so all log lines emitted by the handler and any functions
    it calls automatically inherit the job context.

    Design constraint: synchronous, zero I/O latency.
    Spec: observability-correlation — Job Context Binding
    """
    structlog.contextvars.bind_contextvars(job_id=job_id, job_type=job_type)


# ---------------------------------------------------------------------------
# Pure backoff function (no side effects — pure function, easily testable)
# ---------------------------------------------------------------------------


def calculate_backoff(
    attempt: int,
    base: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 1.0,
) -> float:
    """Calculate exponential backoff with optional jitter.

    Formula: min(base * 2^attempt + random(0, jitter), max_delay)

    Args:
        attempt:   Current attempt number (1-indexed). attempt=1 → base*2, attempt=2 → base*4.
        base:      Base delay in seconds (default 1s).
        max_delay: Maximum delay cap in seconds (default 60s).
        jitter:    Maximum random jitter added to prevent retry storms (default 1s).
                   Pass 0.0 for deterministic tests.

    Returns:
        Delay in seconds (float), capped at max_delay.

    Spec: Requirement: Retry Backoff — exponential + jitter, never exceeds max_delay.
    """
    exponential = base * (2 ** attempt)
    random_jitter = random.uniform(0, jitter) if jitter > 0 else 0.0
    return min(exponential + random_jitter, max_delay)


# ---------------------------------------------------------------------------
# JobExecutor
# ---------------------------------------------------------------------------


class JobExecutor:
    """In-process job executor backed by the background_jobs DB table.

    Lifecycle per job:
      enqueue() → INSERT pending row → create_task(_run_job)
      _run_job() → UPDATE running → call handler → UPDATE completed | failed | dead
      recover() → SELECT pending/running → reset running→pending → create_task(_run_job) each

    The executor is designed as a single instance per process. A module-level
    singleton is created at the bottom of this module for use in main.py.

    Design decisions:
    - _active_job_ids: in-memory set for idempotency guard (single-process, no Redis needed)
    - Fresh get_session() per attempt: prevents poisoned session from blocking retries
    - ConfigurationError: max 1 retry then dead with operator_review=True
    - Other exceptions: transient, retry up to max_attempts with exponential backoff
    """

    def __init__(self) -> None:
        # In-memory set of job IDs currently dispatched as asyncio tasks.
        # Prevents duplicate dispatch from recovery runs.
        self._active_job_ids: set[str] = set()
        # All running asyncio tasks — used by shutdown() to cancel/await.
        self._tasks: set[asyncio.Task] = set()
        # Lifecycle flag: True once recover() has run at startup, False after
        # shutdown(). Reflects actual runtime state for health reporting rather
        # than the static ENABLE_JOB_EXECUTOR config flag.
        self._started: bool = False

    @property
    def started(self) -> bool:
        """Whether the executor has been started (recover() ran, not yet shut down)."""
        return self._started

    async def enqueue(
        self,
        job_type: str,
        payload: dict,
        max_attempts: int = 3,
        db: Optional[AsyncSession] = None,
    ) -> str:
        """Insert a pending job row and dispatch the execution coroutine.

        The row is inserted before the coroutine starts, satisfying the atomicity
        requirement. If the caller provides a db session, the INSERT happens within
        that session's transaction (same commit as the triggering action).

        Args:
            job_type:     Registered job type string. Must exist in the handler registry.
            payload:      JSON-serializable dict passed to the handler.
            max_attempts: Maximum execution attempts before dead-letter (default 3).
            db:           Optional AsyncSession to reuse for the INSERT (shares commit with caller).
                          If None, a fresh get_session() context is used.

        Returns:
            The new job's UUID4 string ID.

        Raises:
            ConfigurationError: If job_type is not registered (no row is inserted).

        Spec: Requirement: Job Enqueue — row inserted before coroutine starts.
        """
        # Validate job type BEFORE inserting to satisfy "raises and does NOT insert a row".
        get_handler(job_type)  # raises ConfigurationError if not registered

        job_id = str(uuid.uuid4())
        job = BackgroundJob(
            id=job_id,
            job_type=job_type,
            payload=json.dumps(payload),
            status="pending",
            attempts=0,
            max_attempts=max_attempts,
            created_at=datetime.now(timezone.utc),
        )

        if db is not None:
            db.add(job)
            # Flush so the row is visible within this session without committing.
            # IMPORTANT: Do NOT dispatch the asyncio task here.  _run_job() opens a
            # *fresh* session and does db.get(BackgroundJob, job_id).  If we dispatch
            # the task before the caller's transaction commits, the fresh session cannot
            # see the unflushed row, logs job_not_found, and the job is stuck pending.
            #
            # Fix: register an after_commit event on the underlying sync session so the
            # task is created only once the transaction is durable on disk.
            await db.flush()

            self._active_job_ids.add(job_id)

            # Capture loop and executor refs for the closure.
            # get_running_loop() is preferred over get_event_loop() in async context.
            loop = asyncio.get_running_loop()
            executor_self = self

            # These two listener functions are defined before registration so each can
            # reference the other for cross-removal on the alternate path.

            def _dispatch_after_commit(session):
                """Fire the asyncio task after the caller's transaction commits.

                Also removes the paired rollback listener so it does not linger
                on the session after the commit path completes.
                """
                coro = executor_self._run_job(job_id)
                task = loop.create_task(coro)
                task.add_done_callback(executor_self._tasks.discard)
                executor_self._tasks.add(task)
                # Remove the paired rollback listener — no longer needed after commit.
                # Guards against session reuse: if the caller commits for this enqueue,
                # subsequent rollbacks on the same session must not call _cleanup.
                try:
                    event.remove(session, "after_rollback", _cleanup_after_rollback)
                except Exception:
                    pass  # already removed or session closed — safe to ignore

            def _cleanup_after_rollback(session):
                """Remove job_id from active set when the caller's transaction rolls back.

                Without this listener, a rollback leaves job_id stranded in
                _active_job_ids until shutdown. The paired after_commit listener
                (once=True) is never fired on rollback, so it remains registered on
                the session. On the next commit of the same session (unrelated work),
                that stale listener would dispatch _run_job() for a row that was
                never persisted to disk.

                This cleanup:
                  1. Removes job_id from _active_job_ids (stops the memory leak).
                  2. Removes the stale _dispatch_after_commit listener (stops phantom dispatch).
                """
                executor_self._active_job_ids.discard(job_id)
                # Remove the paired commit listener — must not dispatch for a rolled-back row.
                try:
                    event.remove(session, "after_commit", _dispatch_after_commit)
                except Exception:
                    pass  # already removed or session closed — safe to ignore

            # after_commit fires on the *sync* session after each successful commit.
            # Using once=True ensures this one-shot listener is auto-removed after firing.
            event.listen(db.sync_session, "after_commit", _dispatch_after_commit, once=True)
            # after_rollback fires when the caller's transaction is rolled back.
            # once=True auto-removes this listener after it fires on rollback.
            event.listen(db.sync_session, "after_rollback", _cleanup_after_rollback, once=True)

        else:
            async with get_session() as fresh_db:
                fresh_db.add(job)
                # commit happens on context manager exit

            self._active_job_ids.add(job_id)

            task = asyncio.create_task(self._run_job(job_id))
            task.add_done_callback(self._tasks.discard)
            self._tasks.add(task)

        logger.info("job_enqueued", job_id=job_id, job_type=job_type)
        return job_id

    async def _run_job(self, job_id: str) -> None:
        """Execute a job: manage state transitions and retry/backoff loop.

        State machine:
          pending → running → completed       (happy path)
          pending → running → failed          (transient error, will retry)
          failed  → running → dead            (attempts == max_attempts or ConfigurationError)

        Each attempt uses a FRESH get_session() context independent of all others.

        Design: openspec/changes/phase-b-background-job-durability/design.md#data-flow

        Context hygiene: job_id/job_type are bound to structlog contextvars each
        attempt (see _bind_job_context below). They are unbound in the finally
        block so they never leak into the next job executed on the same worker
        task or into unrelated post-job logging. Binding happens after the
        pending→running transition; the finally is a no-op when nothing was bound.
        """
        try:
            while True:
                # Load the current job state with a fresh session
                async with get_session() as db:
                    job = await db.get(BackgroundJob, job_id)
                    if job is None:
                        logger.error("job_not_found", job_id=job_id)
                        self._active_job_ids.discard(job_id)
                        return

                    # Guard: do not run dead/completed jobs
                    if job.status in ("completed", "dead"):
                        self._active_job_ids.discard(job_id)
                        return

                    # Transition pending → running
                    job.status = "running"
                    job.started_at = datetime.now(timezone.utc)
                    job.attempts += 1
                    current_attempt = job.attempts
                    current_max = job.max_attempts
                    job_type = job.job_type
                    payload_str = job.payload
                    await db.commit()

                # B9 — Bind job context to structlog contextvars before handler runs.
                # Ensures all log lines from the handler and its callees automatically
                # include job_id and job_type without modifying individual log sites.
                # Spec: observability-correlation — Job Context Binding
                _bind_job_context(job_id=job_id, job_type=job_type)

                logger.info(
                    "job_started",
                    job_id=job_id,
                    job_type=job_type,
                    attempt=current_attempt,
                )

                # Execute handler with a FRESH session (spec: fresh session per retry)
                payload = json.loads(payload_str)
                error_obj: dict | None = None
                last_exc: BaseException | None = None  # B9 PR2: kept for Sentry dead-letter capture
                success = False
                is_config_error = False

                try:
                    # get_handler() is inside the try block so that an unregistered
                    # job_type (e.g. handler removed after job was enqueued) is treated
                    # as a ConfigurationError and captured into the error state rather
                    # than propagating as an unhandled exception that leaves the job stuck
                    # in 'running' with _active_job_ids unclean.
                    handler = get_handler(job_type)
                    async with get_session() as handler_db:
                        await handler(payload, handler_db)
                    success = True
                except ConfigurationError as exc:
                    is_config_error = True
                    last_exc = exc
                    error_obj = {
                        "message": str(exc),
                        "type": type(exc).__name__,
                        "operator_review": True,
                    }
                    logger.warning(
                        "job_config_error",
                        job_id=job_id,
                        job_type=job_type,
                        attempt=current_attempt,
                        error=str(exc),
                    )
                except Exception as exc:
                    last_exc = exc
                    error_obj = {
                        "message": str(exc),
                        "type": type(exc).__name__,
                        "operator_review": False,
                    }
                    logger.warning(
                        "job_failed",
                        job_id=job_id,
                        job_type=job_type,
                        attempt=current_attempt,
                        error=str(exc),
                    )

                # Update job state based on outcome
                async with get_session() as db:
                    job = await db.get(BackgroundJob, job_id)
                    if job is None:
                        return

                    if success:
                        job.status = "completed"
                        job.completed_at = datetime.now(timezone.utc)
                        await db.commit()
                        logger.info(
                            "job_completed",
                            job_id=job_id,
                            job_type=job_type,
                            attempts=job.attempts,
                        )
                        self._active_job_ids.discard(job_id)
                        return

                    # Failure path: persist error regardless (audit trail)
                    job.error = json.dumps(error_obj)

                    # Determine if we should retry or dead-letter
                    #
                    # ConfigurationError policy (design.md):
                    #   - attempt == 1: mark failed, allow 1 more retry
                    #   - attempt >= 2: dead + operator_review=True (already set in error_obj)
                    #
                    # Transient error policy:
                    #   - attempts < max_attempts: failed + retry
                    #   - attempts == max_attempts: dead
                    should_dead_letter = False
                    if is_config_error and current_attempt >= 2:
                        should_dead_letter = True
                    elif not is_config_error and current_attempt >= current_max:
                        should_dead_letter = True

                    if should_dead_letter:
                        job.status = "dead"
                        await db.commit()
                        logger.error(
                            "job_dead",
                            job_id=job_id,
                            job_type=job_type,
                            attempts=job.attempts,
                        )

                        # B9 PR2 — Optional Sentry capture for dead-lettered jobs.
                        # Spec: observability-sentry — Dead-Letter Job Capture.
                        # Best-effort: failure here must not interfere with normal flow.
                        # Only captures when Sentry DSN was configured at startup.
                        # CRITICAL: this is NOT in the live voice/SSE call path —
                        # it runs only in background job workers after all retries exhausted.
                        if sentry_sdk.is_initialized():
                            try:
                                with sentry_sdk.push_scope() as scope:
                                    scope.set_tag("job_id", job_id)
                                    scope.set_tag("job_type", job_type)
                                    if error_obj:
                                        scope.set_extra("error_detail", error_obj)
                                    sentry_sdk.capture_exception(last_exc)
                            except Exception:
                                logger.debug(
                                    "sentry_dead_letter_capture_failed",
                                    job_id=job_id,
                                    exc_info=True,
                                )

                        self._active_job_ids.discard(job_id)
                        return
                    else:
                        job.status = "failed"
                        await db.commit()
                        logger.info(
                            "job_will_retry",
                            job_id=job_id,
                            job_type=job_type,
                            attempt=current_attempt,
                            next_attempt=current_attempt + 1,
                        )

                # Sleep with exponential backoff before the next attempt
                delay = calculate_backoff(
                    attempt=current_attempt,
                    base=1.0,
                    max_delay=60.0,
                    jitter=1.0,
                )
                logger.debug(
                    "job_backoff",
                    job_id=job_id,
                    delay_seconds=round(delay, 2),
                    next_attempt=current_attempt + 1,
                )
                await asyncio.sleep(delay)

                # Loop continues: next iteration reads current state and retries
        finally:
            # Clear job context so it never bleeds into the next job run on
            # this worker task or into unrelated post-job logging. Safe even
            # when nothing was bound (e.g. early return before _bind_job_context).
            structlog.contextvars.unbind_contextvars("job_id", "job_type")

    async def recover(self) -> int:
        """Re-enqueue incomplete jobs on startup (crash recovery sweep).

        Finds all jobs with status IN ('pending', 'running'), resets 'running' to
        'pending' to prevent double-fire, then creates asyncio tasks for each.

        Idempotency: jobs already in _active_job_ids are skipped.

        Returns:
            Count of jobs recovered (re-enqueued).

        Spec: Requirement: Startup Recovery
        Design: openspec/changes/phase-b-background-job-durability/design.md#startup-recovery
        """
        recovered = 0
        # Mark the executor live: startup wiring invoked recover(), so the
        # in-process worker infrastructure is now active and accepting tasks.
        self._started = True

        async with get_session() as db:
            result = await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.status.in_(["pending", "running"])
                )
            )
            jobs = result.scalars().all()

            for job in jobs:
                # Idempotency guard: skip if already dispatched
                if job.id in self._active_job_ids:
                    continue

                # Reset running → pending to prevent double-fire from crash
                if job.status == "running":
                    job.status = "pending"

            await db.commit()

        # Now dispatch tasks outside the session context
        for job in jobs:
            if job.id in self._active_job_ids:
                continue
            # Re-check after reset: only enqueue pending (running already reset above)
            self._active_job_ids.add(job.id)
            task = asyncio.create_task(self._run_job(job.id))
            task.add_done_callback(self._tasks.discard)
            self._tasks.add(task)
            recovered += 1
            logger.info(
                "job_recovered",
                job_id=job.id,
                job_type=job.job_type,
                # status is 'pending' here (running jobs were reset above)
                status=job.status,
            )

        return recovered

    async def shutdown(self) -> None:
        """Cancel all active job tasks on graceful shutdown.

        Current design: cancel like existing lifespan tasks (no graceful drain).
        Drain adds complexity for MVP; future enhancement if needed.

        Spec: design.md — Open question: shutdown cancels immediately for MVP.
        """
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._active_job_ids.clear()
        self._started = False
        logger.info("job_executor_shutdown")


# ---------------------------------------------------------------------------
# Module-level singleton — shared across the process
# ---------------------------------------------------------------------------

#: Global executor instance. Imported by main.py for lifespan wiring.
executor = JobExecutor()
