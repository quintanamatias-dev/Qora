"""QORA Calls — SQLAlchemy models for call sessions and transcripts.

Based on design.md schema for `call_sessions` and `transcript_turns`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CallSession(Base):
    """Represents one ElevenLabs outbound call conversation."""

    __tablename__ = "call_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("leads.id"), nullable=True, index=True
    )
    elevenlabs_conversation_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="initiated",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    billable_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Phase 2 additions (CAP-5)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    total_user_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_agent_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extracted_facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Session reconciliation (Issue #22) — nullable String (no FK; SQLite limitation)
    merged_into_session_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    # Phase 7: agent_id FK (nullable for migration safety — backfilled post-migration)
    agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agents.id"), nullable=True, default=None
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CallSession id={self.id!r} status={self.status!r}>"


class TranscriptTurn(Base):
    """One turn in a call conversation transcript."""

    __tablename__ = "transcript_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("call_sessions.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    filler_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TranscriptTurn role={self.role!r} session={self.session_id!r}>"


class CallAnalysis(Base):
    """Flattened analysis record for one call session (1:1 with CallSession).

    Stores all GPT-extracted analysis fields in normalized columns, replacing the
    opaque JSON blob in CallSession.extracted_facts for structured queries.
    JSON arrays are stored as TEXT (json.dumps/json.loads at app level — AD1).
    """

    __tablename__ = "call_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("call_sessions.id"), nullable=False, unique=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("leads.id"), nullable=True, index=True
    )
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    # Flattened scalar analysis fields
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    urgency: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_need: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_suggested: Mapped[str | None] = mapped_column(String, nullable=True)
    current_insurance: Mapped[str | None] = mapped_column(String, nullable=True)
    data_corrections: Mapped[str] = mapped_column(Text, nullable=False, default="")
    misc_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON arrays stored as TEXT (AD1 — SQLite stores JSON as TEXT anyway)
    objections: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    products: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    specific_needs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    buying_signals: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    pain_points: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Issue #35 — 4 new universal axes (TEXT, migration-safe defaults)
    service_issues: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    profile_facts: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    commitment_signals: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # DEPRECATED (qora-abandonment AD-4): abandonment_reason kept for backward compat,
    # receives NULL going forward. New records use was_abrupt + abandonment_trigger.
    abandonment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # qora-abandonment: new columns absorb signal from deleted abandonment dimension
    was_abrupt: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    abandonment_trigger: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_axes_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Audit / metadata
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    analysis_status: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_call_analyses_classification", "classification"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CallAnalysis session={self.session_id!r} status={self.analysis_status!r}>"
