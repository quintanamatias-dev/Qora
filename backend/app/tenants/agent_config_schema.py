"""QORA Agent Config — versioned configuration schema (design.md D5).

AgentConfigV1 is the validated shape stored as JSON inside every
agent_config_revisions.config row. It is the single source of truth for
what a "configuration" is in this system: the write path (API PATCH), the
rollback path, and the one-time import migration all validate against it
before a revision is persisted.

AgentConfigPatch mirrors every AgentConfigV1 field as optional, used by the
PATCH /agents/{agent_id}/config endpoint: the request body is merged over
the active revision's config, then the merged result is validated against
AgentConfigV1 before a new revision is created.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentConfigV1(BaseModel):
    """Full, validated agent configuration snapshot (design.md D5).

    system_prompt and voice_id are the only fields with no safe default —
    every other field already has a NOT NULL column default on Agent, so
    they are required here too (goal is the one field genuinely optional
    in phase 1a, per design.md D5).
    """

    schema_version: Literal["v1"] = "v1"
    system_prompt: str
    goal: str | None = None
    voice_id: str
    tts_model: str
    tts_speed: float = Field(ge=0.7, le=1.2)
    tts_stability: float = Field(ge=0.0, le=1.0)
    tts_similarity_boost: float = Field(ge=0.0, le=1.0)
    model: str
    temperature: float
    max_tokens: int
    tools_enabled: list[str]
    first_message: str | None = None
    language: str | None = None
    turn_eagerness: str | None = None
    soft_timeout_seconds: float | None = Field(default=None, ge=0.5, le=8.0)
    soft_timeout_message: str | None = None
    soft_timeout_use_llm: bool | None = None
    voicemail_detection_enabled: bool | None = None
    max_call_duration_seconds: int | None = Field(default=None, ge=30, le=7200)


class AgentConfigPatch(BaseModel):
    """Partial AgentConfigV1 — every field optional, for PATCH request bodies.

    Never persisted directly: the write path merges this over the active
    revision's config dict, then re-validates the merged result against
    AgentConfigV1 before creating a new revision.
    """

    schema_version: Literal["v1"] | None = None
    system_prompt: str | None = None
    goal: str | None = None
    voice_id: str | None = None
    tts_model: str | None = None
    tts_speed: float | None = Field(default=None, ge=0.7, le=1.2)
    tts_stability: float | None = Field(default=None, ge=0.0, le=1.0)
    tts_similarity_boost: float | None = Field(default=None, ge=0.0, le=1.0)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools_enabled: list[str] | None = None
    first_message: str | None = None
    language: str | None = None
    turn_eagerness: str | None = None
    soft_timeout_seconds: float | None = Field(default=None, ge=0.5, le=8.0)
    soft_timeout_message: str | None = None
    soft_timeout_use_llm: bool | None = None
    voicemail_detection_enabled: bool | None = None
    max_call_duration_seconds: int | None = Field(default=None, ge=30, le=7200)
    note: str | None = None
