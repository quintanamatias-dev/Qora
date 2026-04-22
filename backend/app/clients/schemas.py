"""QORA Clients — Pydantic schemas for request/response validation.

Slug validation: ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (no leading/trailing hyphens)
Single-char slugs (all lowercase letters or digits) are also valid.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

# Slug must be all lowercase alphanumeric + hyphens, no leading/trailing hyphen.
# Allows single alphanumeric chars (e.g. "a", "1").
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class ClientCreate(BaseModel):
    """Request body for POST /api/v1/clients."""

    client_id: str
    broker_name: str
    agent_name: str = "Jaumpablo"
    voice_id: str = "pNInz6obpgDQGcFmaJgB"  # ElevenLabs Adam voice
    system_prompt_override: str | None = None

    @field_validator("client_id")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "client_id must be a lowercase slug: only letters, digits, and "
                "hyphens, with no leading or trailing hyphens. "
                f"Got: {v!r}"
            )
        return v


class ClientUpdate(BaseModel):
    """Request body for PATCH /api/v1/clients/{client_id}.

    All fields are optional. client_id is NOT updatable.
    """

    broker_name: str | None = None
    agent_name: str | None = None
    voice_id: str | None = None
    system_prompt_override: str | None = None
    # Scheduler configuration (Phase 6)
    scheduler_enabled: bool | None = None
    scheduler_max_attempts: int | None = None
    scheduler_cooldown_minutes: int | None = None
    scheduler_allowed_hours_start: int | None = None
    scheduler_allowed_hours_end: int | None = None
    scheduler_retry_on_outcomes: str | None = None
    scheduler_timezone: str | None = None

    @field_validator("scheduler_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate that scheduler_timezone is a valid IANA timezone string."""
        if v is None:
            return v
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError):
            raise ValueError(
                f"Invalid timezone: {v!r}. Must be a valid IANA timezone string "
                "(e.g. 'America/Argentina/Buenos_Aires', 'Europe/Madrid')."
            )
        return v

    @field_validator("scheduler_max_attempts")
    @classmethod
    def validate_max_attempts(cls, v: int | None) -> int | None:
        """Validate that scheduler_max_attempts is at least 1."""
        if v is not None and v < 1:
            raise ValueError(
                f"scheduler_max_attempts must be >= 1, got {v}."
            )
        return v

    @field_validator("scheduler_cooldown_minutes")
    @classmethod
    def validate_cooldown(cls, v: int | None) -> int | None:
        """Validate that scheduler_cooldown_minutes is non-negative."""
        if v is not None and v < 0:
            raise ValueError(
                f"scheduler_cooldown_minutes must be >= 0, got {v}."
            )
        return v

    @field_validator("scheduler_allowed_hours_start", "scheduler_allowed_hours_end")
    @classmethod
    def validate_hour_range(cls, v: int | None) -> int | None:
        """Validate that hour values are in [0, 23]."""
        if v is not None and not (0 <= v <= 23):
            raise ValueError(
                f"Hour value must be between 0 and 23 (inclusive), got {v}."
            )
        return v

    @field_validator("scheduler_retry_on_outcomes")
    @classmethod
    def validate_retry_outcomes(cls, v: str | None) -> str | None:
        """Validate that scheduler_retry_on_outcomes is a valid JSON list of strings."""
        if v is None:
            return v
        try:
            parsed = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            raise ValueError(
                f"scheduler_retry_on_outcomes must be a valid JSON array, got {v!r}."
            )
        if not isinstance(parsed, list):
            raise ValueError(
                f"scheduler_retry_on_outcomes must be a JSON array, got {type(parsed).__name__}."
            )
        for item in parsed:
            if not isinstance(item, str):
                raise ValueError(
                    f"All items in scheduler_retry_on_outcomes must be strings, got {type(item).__name__}."
                )
        return v

    @model_validator(mode="after")
    def validate_hour_window(self) -> "ClientUpdate":
        """Validate that start_hour < end_hour when both are provided."""
        start = self.scheduler_allowed_hours_start
        end = self.scheduler_allowed_hours_end
        if start is not None and end is not None and start >= end:
            raise ValueError(
                f"scheduler_allowed_hours_start ({start}) must be less than "
                f"scheduler_allowed_hours_end ({end})."
            )
        return self


class ClientResponse(BaseModel):
    """Response shape for all client endpoints."""

    client_id: str
    broker_name: str
    agent_name: str
    voice_id: str
    is_active: bool
    created_at: datetime
    # Scheduler configuration (Phase 6)
    scheduler_enabled: bool = False
    scheduler_max_attempts: int = 3
    scheduler_cooldown_minutes: int = 60
    scheduler_allowed_hours_start: int = 9
    scheduler_allowed_hours_end: int = 20
    scheduler_retry_on_outcomes: str = '["call_again","follow_up"]'
    scheduler_timezone: str = "America/Argentina/Buenos_Aires"

    model_config = {"from_attributes": True}
