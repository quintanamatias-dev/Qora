"""QORA Calls — Pydantic request/response schemas for call session endpoints.

Phase 2a: End session and ElevenLabs post-call webhook models.
Transcript storage improvements: TranscriptTurnResponse, SessionTranscriptResponse.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
