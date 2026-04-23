"""QORA Scheduler — Pydantic schemas for request/response validation (Phase 6)."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator


def _require_aware(v: datetime) -> datetime:
    """Raise ValueError if the datetime is naive (no timezone info)."""
    if v.tzinfo is None:
        raise ValueError(
            "scheduled_at must be an offset-aware datetime (include timezone, e.g. "
            "'2026-06-01T15:00:00+00:00'). Naive datetimes are not accepted."
        )
    return v.astimezone(timezone.utc)


class ScheduledCallCreate(BaseModel):
    """Request body for manually creating a ScheduledCall."""

    lead_id: str
    scheduled_at: datetime
    notes: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at_aware(cls, v: datetime) -> datetime:
        return _require_aware(v)


class ScheduledCallResponse(BaseModel):
    """Response shape for ScheduledCall endpoints."""

    id: str
    client_id: str
    lead_id: str
    source_session_id: str | None
    status: str
    scheduled_at: datetime
    attempt_number: int
    max_attempts: int
    trigger_reason: str
    outcome_session_id: str | None
    notes: str | None
    agent_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduledCallReschedule(BaseModel):
    """Request body for rescheduling a ScheduledCall."""

    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at_aware(cls, v: datetime) -> datetime:
        return _require_aware(v)
