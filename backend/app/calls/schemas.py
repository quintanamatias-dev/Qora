"""QORA Calls — Pydantic request/response schemas for call session endpoints.

Phase 2a: End session and ElevenLabs post-call webhook models.
Transcript storage improvements: TranscriptTurnResponse, SessionTranscriptResponse.
Call detail view: CallAnalysisResponse (all 12 analysis dimensions).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class EndSessionRequest(BaseModel):
    """Request body for POST /api/v1/calls/{conversation_id}/end."""

    reason: Literal[
        "agent_goodbye",
        "user_hangup",
        "network_drop",
        "timeout",
        "reconnect_attempt",
    ]
    client_id: str | None = None  # Reconciliation hint (CAP-4)
    lead_id: str | None = None  # Reconciliation hint (CAP-4)
    conversation_id: str | None = (
        None  # Optional — must match path param (T30 / REQ-2.2)
    )
    # provider_call_id: Optional ElevenLabs call identifier for fallback linkage.
    # When provided, enables link_outbound_session_by_webhook() to find the outbound
    # CallSession by provider_call_id if conversation_id lookup fails (first-time linkage).
    # WU2 fix: wires the fallback provider_call_id path through the real /end route.
    provider_call_id: str | None = None


class EndSessionResponse(BaseModel):
    """Response from POST /api/v1/calls/{conversation_id}/end."""

    id: str
    status: str
    duration_seconds: int | None
    closed_reason: str | None


class TranscriptTurnResponse(BaseModel):
    """A single transcript turn returned from GET /calls/{session_id}/transcript."""

    id: str
    role: str
    content: str
    timestamp: datetime
    filler_detected: bool


class SessionTranscriptResponse(BaseModel):
    """Full transcript response for GET /calls/{session_id}/transcript."""

    session_id: str
    turn_count: int
    turns: list[TranscriptTurnResponse]


class MetricsPeriod(BaseModel):
    """Period applied to the metrics query — echoes supplied date_from/date_to."""

    date_from: datetime | None = None
    date_to: datetime | None = None


class CallMetricsResponse(BaseModel):
    """Aggregated call metrics for a client over an optional time window."""

    total_calls: int
    completed_calls: int
    abandoned_calls: int
    total_duration_seconds: float
    average_duration_seconds: float
    total_billable_minutes: int
    period: MetricsPeriod


class ElevenLabsPostCallData(BaseModel):
    """Inner data object of the ElevenLabs post-call webhook payload.

    ElevenLabs wraps the conversation data inside a top-level envelope.
    This model represents the ``data`` field of that envelope.

    Minimum required fields. Extra fields allowed and ignored.
    Transcript format: [{role: str, message: str}]
    """

    conversation_id: str
    agent_id: str | None = None
    transcript: list[dict] | None = None  # [{role, message}]
    metadata: dict | None = None
    # provider_call_id: Optional ElevenLabs call identifier.
    # When present in the webhook payload, passed to link_outbound_session_by_webhook()
    # to enable provider_call_id fallback linkage (WU2 fix B1).
    provider_call_id: str | None = None
    # client_id: Optional tenant identifier.
    # When present, passed to link_outbound_session_by_webhook() to scope the
    # provider_call_id fallback lookup to this tenant only — preventing cross-tenant
    # session linkage (WU2 re-review RE2). When absent, provider_call_id fallback
    # is NOT attempted (safe no-match preferred over cross-tenant risk).
    client_id: str | None = None
    # New optional fields sent by ElevenLabs in the post_call_transcription event.
    status: str | None = None
    analysis: dict | None = None
    conversation_initiation_client_data: dict | None = None

    model_config = {"extra": "allow"}


class ElevenLabsPostCallPayload(BaseModel):
    """ElevenLabs post-call webhook envelope.

    ElevenLabs sends a two-level structure:
        {
          "type": "post_call_transcription",
          "event_timestamp": 1739537297,
          "data": { <conversation data> }
        }

    The actual conversation data lives in ``data`` (see ElevenLabsPostCallData).
    Extra top-level fields are allowed and ignored.
    """

    type: str
    event_timestamp: int | None = None
    data: ElevenLabsPostCallData

    model_config = {"extra": "allow"}


class CallAnalysisResponse(BaseModel):
    """Full analysis response for GET /calls/{session_id}/analysis.

    JSON text columns (objections, products, pain_points, service_issues,
    misc_notes, data_corrections, profile_facts, commitment_signals,
    specific_needs, extra_axes_data) are returned as parsed Python objects.
    All analysis fields are Optional since analysis can be partial.
    """

    session_id: str

    # Scalar analysis fields
    summary: str | None = None
    interest_level: int | None = None
    classification: str | None = None
    outcome_reason: str | None = None
    urgency: str | None = None
    primary_need: str | None = None
    next_action_suggested: str | None = None
    current_insurance: str | None = None

    # JSON columns — returned as parsed Python objects (list or dict)
    objections: list[Any] | None = None
    products: list[Any] | None = None
    pain_points: list[Any] | None = None
    service_issues: list[Any] | None = None
    profile_facts: list[Any] | None = None
    commitment_signals: list[Any] | None = None
    specific_needs: list[Any] | None = None
    misc_notes: dict[str, Any] | list[Any] | None = None
    data_corrections: list[Any] | None = None
    extra_axes_data: dict[str, Any] | None = None

    # Abandonment
    was_abrupt: bool | None = None
    abandonment_trigger: str | None = None

    # Audit metadata
    analysis_status: str
    analysis_error: str | None = None
    analyzed_at: datetime
