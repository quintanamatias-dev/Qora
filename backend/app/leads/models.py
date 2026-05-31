"""QORA Leads — SQLAlchemy models for lead CRM data.

Based on the design.md schema for the `leads` table.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadStatus(str, enum.Enum):
    """Valid states for a lead in the QORA state machine.

    Transitions:
        new → called → quoted (all fields present for quoting)
                     → follow_up (positive but missing data)
                     → not_interested
        follow_up → called
    """

    NEW = "new"
    CALLED = "called"
    QUOTED = "quoted"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    FOLLOW_UP = "follow_up"


# Valid state transitions: {from_state: set of allowed to_states}
VALID_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.NEW: {LeadStatus.CALLED},
    LeadStatus.CALLED: {
        LeadStatus.QUOTED,
        LeadStatus.INTERESTED,
        LeadStatus.NOT_INTERESTED,
        LeadStatus.FOLLOW_UP,
    },
    LeadStatus.FOLLOW_UP: {LeadStatus.CALLED},
    LeadStatus.QUOTED: set(),
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
        Enum(
            *[s.value for s in LeadStatus],
            name="lead_status",
        ),
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
    # qora-data-corrections: new correctable fields
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zona: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 2 additions (CAP-5)
    summary_last_call: Mapped[str | None] = mapped_column(Text, nullable=True)
    objections_heard: Mapped[list | None] = mapped_column(JSON, nullable=True)
    interest_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    do_not_call: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_action: Mapped[str | None] = mapped_column(String, nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Generic external CRM record ID for bidirectional sync (e.g. Airtable recXXX).
    # Nullable: set only for leads imported from or synced to an external CRM.
    external_crm_id: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Lead id={self.id!r} name={self.name!r} status={self.status!r}>"


class LeadProfileFact(Base):
    """Key-value store for named facts extracted from calls for a lead.

    Append-and-supersede pattern: when a fact_key changes, the current row
    gets superseded_at set to now, and a new row is inserted.
    NULL superseded_at means the row is the current (active) value.
    """

    __tablename__ = "lead_profile_facts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"), nullable=False)
    fact_key: Mapped[str] = mapped_column(String, nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_call_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("call_sessions.id"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Composite index for efficient "current fact" queries
        Index(
            "ix_lead_profile_facts_lead_key_active",
            "lead_id",
            "fact_key",
            "superseded_at",
        ),
        # Additional indexes per spec
        Index("ix_lead_profile_facts_lead_id", "lead_id"),
        Index("ix_lead_profile_facts_source_call_id", "source_call_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<LeadProfileFact lead={self.lead_id!r} key={self.fact_key!r} "
            f"value={self.fact_value!r} active={self.superseded_at is None}>"
        )


class LeadInterestHistory(Base):
    """Append-only time series of interest_level measurements per lead.

    Rows are NEVER updated or deleted after insert — each call appends a new row.
    """

    __tablename__ = "lead_interest_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lead_id: Mapped[str] = mapped_column(
        String, ForeignKey("leads.id"), nullable=False, index=True
    )
    interest_level: Mapped[int] = mapped_column(Integer, nullable=False)
    source_call_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("call_sessions.id"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        # Composite index for time-series queries per lead
        Index("ix_lead_interest_history_lead_recorded_at", "lead_id", "recorded_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<LeadInterestHistory lead={self.lead_id!r} "
            f"level={self.interest_level!r} at={self.recorded_at!r}>"
        )
