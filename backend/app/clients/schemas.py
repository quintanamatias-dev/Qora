"""QORA Clients — Pydantic schemas for request/response validation.

Slug validation: ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (no leading/trailing hyphens)
Single-char slugs (all lowercase letters or digits) are also valid.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.analysis.profiles.schema import NeedTagEntry, ProductEntry

# Slug must be all lowercase alphanumeric + hyphens, no leading/trailing hyphen.
# Allows single alphanumeric chars (e.g. "a", "1").
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


# ---------------------------------------------------------------------------
# Shared scheduler validator mixin
# ---------------------------------------------------------------------------


class _SchedulerValidatorMixin(BaseModel):
    """Mixin that provides scheduler field validators for both Create and Update.

    Applied to both ClientCreate and ClientUpdate so validation logic is
    never duplicated.
    """

    @field_validator("scheduler_timezone", check_fields=False)
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

    @field_validator("scheduler_max_attempts", check_fields=False)
    @classmethod
    def validate_max_attempts(cls, v: int | None) -> int | None:
        """Validate that scheduler_max_attempts is at least 1."""
        if v is not None and v < 1:
            raise ValueError(f"scheduler_max_attempts must be >= 1, got {v}.")
        return v

    @field_validator("scheduler_cooldown_minutes", check_fields=False)
    @classmethod
    def validate_cooldown(cls, v: int | None) -> int | None:
        """Validate that scheduler_cooldown_minutes is non-negative."""
        if v is not None and v < 0:
            raise ValueError(f"scheduler_cooldown_minutes must be >= 0, got {v}.")
        return v

    @field_validator(
        "scheduler_allowed_hours_start",
        "scheduler_allowed_hours_end",
        check_fields=False,
    )
    @classmethod
    def validate_hour_range(cls, v: int | None) -> int | None:
        """Validate that hour values are in [0, 23]."""
        if v is not None and not (0 <= v <= 23):
            raise ValueError(
                f"Hour value must be between 0 and 23 (inclusive), got {v}."
            )
        return v

    @field_validator("scheduler_retry_on_outcomes", check_fields=False)
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

    @field_validator("scheduler_backoff_multiplier", check_fields=False)
    @classmethod
    def validate_backoff_multiplier(cls, v: float | None) -> float | None:
        """Validate scheduler_backoff_multiplier is finite, >= 1.0, and <= 10.0.

        Rejects:
        - 0 or negative: would produce zero/shrinking delays → immediate/excess retries
        - < 1.0: delay shrinks per attempt (inverted backoff)
        - NaN / Inf: undefined or infinite delay
        - > 10.0: excessively large escalation factor

        Valid range: [1.0, 10.0] finite.
        Default 1.0 = flat delay (preserves existing behaviour exactly).
        """
        if v is None:
            return v
        if not math.isfinite(v):
            raise ValueError(
                f"scheduler_backoff_multiplier must be a finite number, got {v!r}. "
                "NaN and Inf are not valid multiplier values."
            )
        if v < 1.0:
            raise ValueError(
                f"scheduler_backoff_multiplier must be >= 1.0, got {v}. "
                "Values below 1.0 would shrink or negate the retry delay."
            )
        if v > 10.0:
            raise ValueError(
                f"scheduler_backoff_multiplier must be <= 10.0, got {v}. "
                "Values above 10.0 produce excessively large retry delays."
            )
        return v

    @model_validator(mode="after")
    def validate_hour_window(self) -> "_SchedulerValidatorMixin":
        """Validate that start_hour < end_hour when both are provided."""
        start = self.scheduler_allowed_hours_start
        end = self.scheduler_allowed_hours_end
        if start is not None and end is not None and start >= end:
            raise ValueError(
                f"scheduler_allowed_hours_start ({start}) must be less than "
                f"scheduler_allowed_hours_end ({end})."
            )
        return self


class ClientCreate(_SchedulerValidatorMixin):
    """Request body for POST /api/v1/clients."""

    client_id: str | None = None  # Optional: auto-generated from name when omitted
    name: str
    agent_name: str = "Jaumpablo"
    voice_id: str = (
        "pNInz6obpgDQGcFmaJgB"  # ElevenLabs Adam voice (default, configure per-agent)
    )
    system_prompt_override: str | None = None
    # Scheduler configuration (Phase 7 — bootstrappable at create time)
    scheduler_enabled: bool = False
    scheduler_max_attempts: int = 3
    scheduler_cooldown_minutes: int = 60
    scheduler_allowed_hours_start: int = 9
    scheduler_allowed_hours_end: int = 20
    scheduler_retry_on_outcomes: str = '["call_again","follow_up"]'
    scheduler_timezone: str = "America/Argentina/Buenos_Aires"
    # C6: Backoff multiplier for recontact delay escalation. Default 1.0 = flat delay.
    scheduler_backoff_multiplier: float = 1.0

    @field_validator("client_id")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v  # auto-generated later in router
        if not _SLUG_RE.match(v):
            raise ValueError(
                "client_id must be a lowercase slug: only letters, digits, and "
                "hyphens, with no leading or trailing hyphens. "
                f"Got: {v!r}"
            )
        return v


class ClientUpdate(_SchedulerValidatorMixin):
    """Request body for PATCH /api/v1/clients/{client_id}.

    All fields are optional. client_id is NOT updatable.
    """

    name: str | None = None
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
    # C6: Backoff multiplier for recontact delay escalation.
    scheduler_backoff_multiplier: float | None = None
    # Next Action Engine configuration (qora-next-action, Issue #47)
    next_action_max_attempts: int | None = None
    next_action_min_interest_for_followup: int | None = None
    next_action_close_on_hard_rejection: bool | None = None
    # Analysis locale configuration (qora-analysis-locale)
    analysis_language: str | None = None

    @field_validator("next_action_max_attempts", check_fields=False)
    @classmethod
    def validate_next_action_max_attempts(cls, v: int | None) -> int | None:
        """Validate that next_action_max_attempts is within [1, 20]."""
        if v is not None and not (1 <= v <= 20):
            raise ValueError(
                f"next_action_max_attempts must be between 1 and 20 (inclusive), got {v}."
            )
        return v

    @field_validator("next_action_min_interest_for_followup", check_fields=False)
    @classmethod
    def validate_next_action_min_interest_for_followup(cls, v: int | None) -> int | None:
        """Validate that next_action_min_interest_for_followup is within [0, 100]."""
        if v is not None and not (0 <= v <= 100):
            raise ValueError(
                f"next_action_min_interest_for_followup must be between 0 and 100 (inclusive), got {v}."
            )
        return v

    @field_validator("analysis_language", check_fields=False)
    @classmethod
    def validate_analysis_language(cls, v: str | None) -> str | None:
        """Validate analysis_language is a non-empty, stripped string up to 40 chars."""
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("analysis_language must not be empty.")
        if len(stripped) > 40:
            raise ValueError(
                f"analysis_language must be at most 40 characters, got {len(stripped)}."
            )
        return stripped


class ClientResponse(BaseModel):
    """Response shape for all client endpoints."""

    client_id: str
    name: str
    agent_name: str
    voice_id: str
    is_active: bool
    created_at: datetime
    agent_count: int = 0
    # Scheduler configuration (Phase 6)
    scheduler_enabled: bool = False
    scheduler_max_attempts: int = 3
    scheduler_cooldown_minutes: int = 60
    scheduler_allowed_hours_start: int = 9
    scheduler_allowed_hours_end: int = 20
    scheduler_retry_on_outcomes: str = '["follow_up","retry_call","schedule_call"]'
    scheduler_timezone: str = "America/Argentina/Buenos_Aires"
    # C6: Backoff multiplier for recontact delay escalation.
    scheduler_backoff_multiplier: float = 1.0
    # Next Action Engine configuration (qora-next-action, Issue #47)
    next_action_max_attempts: int = 5
    next_action_min_interest_for_followup: int = 40
    next_action_close_on_hard_rejection: bool = True
    # Analysis locale configuration (qora-analysis-locale)
    analysis_language: str = "Spanish"
    # Plan name (app/entitlements/catalog.py). Managed via /clients/{id}/entitlements.
    plan: str = "pilot"

    model_config = {"from_attributes": True}


class ClientConfigRevisionResponse(BaseModel):
    """Response shape for client config revision endpoints (design.md D11).

    config is returned as a dict (deserialized from the DB TEXT column), and
    is sparse — it contains only the fields this client has explicitly
    overridden, not every field from the Qora standard.
    """

    id: str
    client_id: str
    revision_number: int
    config: dict
    schema_version: str
    source: str
    created_by: str
    created_at: datetime
    note: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Analysis profile revisions (design.md P5-D2/P5-D7)
# ---------------------------------------------------------------------------


class AnalysisProfileResponse(BaseModel):
    """Response shape for analysis-profile revision endpoints (design.md P5-D7).

    config is a FULL snapshot (products + need_tags) — not sparse, unlike
    ClientConfigRevisionResponse's override-only config.
    """

    id: str
    client_id: str
    revision_number: int
    vertical: str
    products: list[ProductEntry]
    need_tags: list[NeedTagEntry]
    source: str
    created_by: str
    created_at: datetime
    note: str | None = None


class PutAnalysisProfilePayload(BaseModel):
    """Write payload for PUT /clients/{client_id}/analysis-profile.

    Validates: product ids unique within the submitted list, need-tag ids
    unique within the submitted list (every label_es/label_en non-empty is
    enforced by ProductEntry/NeedTagEntry themselves) — 422 on violation.
    """

    vertical: str
    products: list[ProductEntry] = []
    need_tags: list[NeedTagEntry] = []
    note: str | None = None

    @model_validator(mode="after")
    def _unique_ids(self) -> "PutAnalysisProfilePayload":
        product_ids = [p.id for p in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("products contains a duplicate id")
        need_tag_ids = [n.id for n in self.need_tags]
        if len(need_tag_ids) != len(set(need_tag_ids)):
            raise ValueError("need_tags contains a duplicate id")
        return self


class RollbackAnalysisProfilePayload(BaseModel):
    target_revision_id: str


class ApplyAnalysisProfileTemplatePayload(BaseModel):
    vertical: Literal["insurance", "generic"]
