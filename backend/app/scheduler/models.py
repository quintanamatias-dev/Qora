"""QORA Scheduler — SQLAlchemy model for ScheduledCall (Phase 6).

Manages the lifecycle of scheduled outbound calls:
  pending → in_progress → completed | failed
  pending → cancelled
  pending → expired
  in_progress → completed | failed | cancelled
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Valid lifecycle transitions for ScheduledCall.status
# ---------------------------------------------------------------------------

#: Maps each status to the set of statuses it can transition TO.
#: Terminal states (completed, cancelled, expired, failed) have empty lists.
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["in_progress", "cancelled", "expired"],
    "in_progress": ["completed", "failed", "cancelled"],
    "completed": [],
    "failed": [],
    "cancelled": [],
    "expired": [],
}


class ScheduledCall(Base):
    """Represents one scheduled outbound call in the queue.

    Phase 6: Queue-only. Actual Twilio dialing is Phase 8.
    """

    __tablename__ = "scheduled_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # uuid4
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        String, ForeignKey("leads.id"), nullable=False, index=True
    )
    source_session_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    outcome_session_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Phase 7: agent_id FK (nullable for migration safety — backfilled post-migration)
    agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agents.id"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        # Composite index for duplicate-guard query: (lead_id, status)
        Index("ix_scheduled_calls_lead_status", "lead_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ScheduledCall id={self.id!r} lead={self.lead_id!r} "
            f"status={self.status!r} at={self.scheduled_at!r}>"
        )
