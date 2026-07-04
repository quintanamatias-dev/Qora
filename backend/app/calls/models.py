"""QORA Calls — SQLAlchemy models for call sessions and transcripts.

Based on design.md schema for `call_sessions` and `transcript_turns`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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
    # DEPRECATED: use call_analyses table instead. Kept for backward compat reads.
    extracted_facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Session reconciliation (Issue #22) — nullable String (no FK; SQLite limitation)
    merged_into_session_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    # Phase 7: agent_id FK (nullable for migration safety — backfilled post-migration)
    agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agents.id"), nullable=True, default=None
    )
    # PR 3: transcript finalization audit — stamped by transcript_flush_handler
    # after the call ends. NULL means not yet finalized (call still live or handler pending).
    # Operators and B9 can inspect these to confirm off-call durability ran.
    transcript_finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    transcript_turn_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # C2: Outbound telephony metadata — nullable for inbound/pre-C2 sessions.
    # provider_call_id: ElevenLabs call identifier from the outbound-call API response.
    provider_call_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # telephony_provider: always "elevenlabs" for now; stored for future multi-provider support.
    telephony_provider: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # telephony_status: provider-reported state machine.
    # dialing → ringing → in_call → completed | no_answer | failed | recurrent_error
    # NULL for inbound/pre-C2 sessions. "completed" ONLY set by webhook evidence (FAS-safe).
    telephony_status: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # telephony_error: human-readable error detail; populated on failure/retry.
    telephony_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # provider_metadata: safe/allowlisted provider metadata (cost, billed_duration_seconds, etc.).
    # Only fields in _SAFE_PROVIDER_METADATA_FIELDS are persisted — PII and routing data are stripped.
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    # session_end_received: True when the Custom LLM session-end webhook has fired for this
    # outbound session. This is the canonical "session-end evidence" used by the reconciliation
    # sweep to distinguish "completed" (session-end confirmed) from "stale_in_call" (no evidence).
    # NULL for inbound/pre-C2 sessions. False for outbound sessions awaiting session-end.
    # FAS contract: telephony_status='completed' in the sweep REQUIRES session_end_received=True.
    session_end_received: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    # C3 — SIP Observability columns (call-observability-reconciliation change)
    # All five are nullable — existing/inbound rows remain NULL (no data loss on migration).
    # Populated asynchronously by the post-dial probe or background reconciliation sweep.
    # These fields must NEVER contain raw SIP bodies, Proxy-Authorization headers,
    # digest credentials, or SIP URIs containing phone numbers (PII).
    # Only structured allowlisted fields (spec: Structured-Field-Only SIP Extraction).
    #
    # sip_call_id: ElevenLabs/Telnyx SIP Call-ID header value (e.g. "otb_...")
    sip_call_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # sip_status_code: Final SIP response status code (200, 404, 487, etc.)
    sip_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # sip_reason: Final SIP response reason phrase ("OK", "Not Found", "Request Terminated")
    sip_reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # reconciled_at: UTC timestamp when SIP evidence was successfully captured
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # reconciliation_source: Which path populated the SIP evidence
    # Values: "probe" (post-dial background probe) | "sweep" (background reconciliation sweep)
    #         "unreconcilable" (parked after hitting reconciliation_max_attempts)
    reconciliation_source: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    # reconciliation_attempts: number of reconciliation sweep attempts made for this session.
    # Incremented on each failed sweep attempt (e.g. ElevenLabs list API 404/5xx).
    # When it reaches settings.reconciliation_max_attempts, the session is parked as
    # unreconcilable: reconciled_at is set and reconciliation_source='unreconcilable'.
    # NULL for pre-C3 sessions and sessions that were reconciled on the first attempt.
    # Default 0 so new unreconciled sessions start at zero without a migration null-check.
    reconciliation_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
    # post-call-analysis-bi-friendly PR 2 — 5 denormalized BI columns (AD-1/AD-2/AD-3)
    # Populated by _upsert_call_analysis() in the same transaction as JSON arrays.
    # Migration: backend/scripts/migrate_bi_columns.py (idempotent, adds + backfills).
    primary_objection_category: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_pain_category: Mapped[str | None] = mapped_column(String, nullable=True)
    objections_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pain_points_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_issues_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    __table_args__ = (
        Index("ix_call_analyses_classification", "classification"),
        # post-call-analysis-bi-friendly PR 2: B-tree indexes for BI GROUP BY / filter (AD-2)
        Index("ix_ca_primary_objection_category", "primary_objection_category"),
        Index("ix_ca_primary_pain_category", "primary_pain_category"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CallAnalysis session={self.session_id!r} status={self.analysis_status!r}>"
