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

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.tenants.field_policy import FIELD_POLICY


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


# ---------------------------------------------------------------------------
# AgentConfigV2 — sparse agent overrides (design.md D12/D18).
#
# Only fields whose FIELD_POLICY is "agent_required" or "overridable" are
# allowed — derived from the registry, never hand-listed, mirroring
# client_config_schema.ClientConfigV1's approach. "locked" and "client_only"
# fields are not defined here at all, so supplying one raises pydantic's
# extra="forbid" error, same mechanism as an unregistered field name.
# Every field defaults to None (not set, inherit).
# ---------------------------------------------------------------------------

_V2_ALLOWED_POLICIES = {"agent_required", "overridable"}

ALLOWED_AGENT_OVERRIDE_FIELDS: frozenset[str] = frozenset(
    name for name, policy in FIELD_POLICY.items() if policy in _V2_ALLOWED_POLICIES
)


def _v2_field_definitions() -> dict[str, tuple[Any, None]]:
    """Build create_model field definitions for every allowed field, reusing
    AgentConfigV1's annotation + constraints (ge/le, etc.) but making every
    field Optional with a None default (sparse override semantics).
    """
    definitions: dict[str, tuple[Any, None]] = {}
    for name, info in AgentConfigV1.model_fields.items():
        if name not in ALLOWED_AGENT_OVERRIDE_FIELDS:
            continue
        annotation = info.annotation
        is_already_optional = annotation is type(None) or (
            hasattr(annotation, "__args__") and type(None) in annotation.__args__
        )
        optional_annotation = annotation if is_already_optional else Optional[annotation]
        if info.metadata:
            optional_annotation = Annotated[tuple([optional_annotation, *info.metadata])]
        definitions[name] = (optional_annotation, None)
    return definitions


AgentConfigV2 = create_model(
    "AgentConfigV2",
    __config__=ConfigDict(extra="forbid"),
    schema_version=(Literal["v2"], "v2"),
    **_v2_field_definitions(),
)


AgentConfigV2Patch = create_model(
    "AgentConfigV2Patch",
    __config__=ConfigDict(extra="forbid"),
    note=(Optional[str], None),
    **_v2_field_definitions(),
)
