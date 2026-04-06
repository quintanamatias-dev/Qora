"""QORA Leads — SQLAlchemy models for lead CRM data.

Based on the design.md schema for the `leads` table.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadStatus(str, enum.Enum):
    """Valid states for a lead in the QORA state machine.

    Transitions:
        new → called → interested
                     → not_interested
                     → follow_up
        follow_up → called
    """

    NEW = "new"
    CALLED = "called"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    FOLLOW_UP = "follow_up"


# Valid state transitions: {from_state: set of allowed to_states}
VALID_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.NEW: {LeadStatus.CALLED},
    LeadStatus.CALLED: {
        LeadStatus.INTERESTED,
        LeadStatus.NOT_INTERESTED,
        LeadStatus.FOLLOW_UP,
    },
    LeadStatus.FOLLOW_UP: {LeadStatus.CALLED},
    LeadStatus.INTERESTED: set(),
    LeadStatus.NOT_INTERESTED: set(),
}


def is_valid_transition(
    from_status: str | LeadStatus, to_status: str | LeadStatus
) -> bool:
    """Return True if the from → to state transition is allowed.

    Accepts both string and LeadStatus enum values.
    """
    from_enum = LeadStatus(from_status) if isinstance(from_status, str) else from_status
    to_enum = LeadStatus(to_status) if isinstance(to_status, str) else to_status
    return to_enum in VALID_TRANSITIONS.get(from_enum, set())


class Lead(Base):
    """Represents a potential insurance customer in the CRM."""

    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    car_make: Mapped[str | None] = mapped_column(String, nullable=True)
    car_model: Mapped[str | None] = mapped_column(String, nullable=True)
    car_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_insurance: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*[s.value for s in LeadStatus], name="lead_status"),
        nullable=False,
        default=LeadStatus.NEW.value,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Lead id={self.id!r} name={self.name!r} status={self.status!r}>"
