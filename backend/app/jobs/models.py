"""Background Job — SQLAlchemy model for durable in-process job execution.

Table: background_jobs
Lifecycle: pending → running → completed | failed | dead

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/background-job-executor/spec.md
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackgroundJob(Base):
    """Represents one durable background job with full lifecycle tracking.

    Status lifecycle:
      pending  — inserted atomically before the coroutine starts
      running  — executor picked it up and handler is executing
      completed — handler returned successfully
      failed   — handler raised an exception; retry is scheduled if attempts < max_attempts
      dead     — max_attempts exhausted or ConfigurationError reached dead-letter threshold
    """

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID4
    job_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # JSON TEXT: {"message": str, "type": str, "operator_review": bool}
    # Structured so B9 can query: operator_review flag, error type, message.
    # Not cleared on successful retry — preserved as audit trail.
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        # Fast recovery sweep: WHERE status IN ('pending', 'running')
        Index("ix_background_jobs_status", "status"),
        # B9 queries by job_type + status for per-type failure dashboards
        Index("ix_background_jobs_type_status", "job_type", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BackgroundJob id={self.id!r} type={self.job_type!r} "
            f"status={self.status!r} attempts={self.attempts}>"
        )
