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


class ElevenLabsPostCallPayload(BaseModel):
    """ElevenLabs post-call webhook payload.

    Minimum required fields. Extra fields allowed and ignored.
    Transcript format: [{role: str, message: str}]
    """

    conversation_id: str
    agent_id: str | None = None
    transcript: list[dict] | None = None  # [{role, message}]
    metadata: dict | None = None

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
