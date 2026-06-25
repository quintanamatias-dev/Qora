"""Background Job Query Helpers — Minimal Operator Surface.

Provides read-only query helpers for the background_jobs table.
Intended for internal observability: surfacing failed/dead jobs and
active pipeline backlog without log parsing.

B10 owns all writes to background_jobs (via executor).
Callers of these helpers are read-only consumers (operator tools, health checks, B9).

INTERNAL USE ONLY — NOT exposed via any public API or HTTP router.
Rows returned contain raw payload and error JSON (which may include client_id,
lead_id, and structured error details). These helpers MUST NOT be wired into
a public endpoint without adding tenant-scoped filtering and auth middleware.
There is intentionally no tenant filter here: callers are trusted internal
consumers (CLI scripts, health-check tasks, admin-only tooling).

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/durable-post-call-pipeline/spec.md
        Requirement: Post-Call Pipeline Error Visibility
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import BackgroundJob


async def get_failed_jobs(
    db: AsyncSession,
    *,
    job_type: str | None = None,
    limit: int = 100,
) -> list[BackgroundJob]:
    """Return background_jobs rows with status 'failed' or 'dead'.

    'failed' rows are pending retry; 'dead' rows have exhausted all attempts.
    Both statuses surface operator-visible pipeline errors beyond raw log output.

    Args:
        db:       Active AsyncSession for the query (read-only use).
        job_type: Optional filter (e.g. 'crm_sync', 'summarize').
                  When None, returns all failed/dead jobs regardless of type.
        limit:    Maximum rows returned (default 100, prevents runaway scans).

    Returns:
        List of BackgroundJob instances, ordered by created_at DESC
        (most recent failures first — fastest path to recent errors).

    Spec: Requirement: Post-Call Pipeline Error Visibility
          "Failures MUST NOT be visible only in application logs."
    """
    stmt = (
        select(BackgroundJob)
        .where(BackgroundJob.status.in_(["failed", "dead"]))
        .order_by(BackgroundJob.created_at.desc())
        .limit(limit)
    )

    if job_type is not None:
        stmt = stmt.where(BackgroundJob.job_type == job_type)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_pending_jobs(
    db: AsyncSession,
    *,
    job_type: str | None = None,
    limit: int = 100,
) -> list[BackgroundJob]:
    """Return background_jobs rows with status 'pending' or 'running'.

    Useful for monitoring active pipeline backlog: pending rows are waiting
    to be dispatched; running rows are currently executing (or stuck if a
    crash occurred before recovery swept them).

    Args:
        db:       Active AsyncSession for the query (read-only use).
        job_type: Optional filter by job type.
        limit:    Maximum rows returned (default 100).

    Returns:
        List of BackgroundJob instances, ordered by created_at ASC
        (oldest pending first — shows queue depth at the front of the line).
    """
    stmt = (
        select(BackgroundJob)
        .where(BackgroundJob.status.in_(["pending", "running"]))
        .order_by(BackgroundJob.created_at.asc())
        .limit(limit)
    )

    if job_type is not None:
        stmt = stmt.where(BackgroundJob.job_type == job_type)

    result = await db.execute(stmt)
    return list(result.scalars().all())
