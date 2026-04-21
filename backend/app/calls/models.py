"""QORA Calls — SQLAlchemy models for call sessions and transcripts.

Based on design.md schema for `call_sessions` and `transcript_turns`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
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
