"""QORA Agents — Pydantic schemas for request/response validation.

Slug validation: ^[a-z0-9][a-z0-9-]*[a-z0-9]?$ (no leading/trailing hyphens).
Single-char slugs (all lowercase letters or digits) are also valid.

tools_enabled validation: must be list[str] containing only keys from
TOOL_DEFINITIONS in app.tools.registry.

The service layer is responsible for serializing list[str] → JSON string before
persisting to the DB, and deserializing JSON string → list[str] when returning
responses.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, field_validator, Field

# Slug must be all lowercase alphanumeric + hyphens, no leading/trailing hyphen.
# Allows single alphanumeric chars (e.g. "a", "1").
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Derive known tool names from the canonical TOOL_DEFINITIONS dict.
# This avoids duplicating tool names — single source of truth in app.tools.registry.
from app.tools.registry import TOOL_DEFINITIONS as _TOOL_DEFS  # noqa: E402

QORA_TOOL_NAMES: frozenset[str] = frozenset(_TOOL_DEFS.keys())

_DEFAULT_TOOLS: list[str] = list(_TOOL_DEFS.keys())


def _validate_tools_list(v: list[str] | None) -> list[str] | None:
    """Validate that tools_enabled is a list containing only known tool names."""
    if v is None:
        return v

    if not isinstance(v, list):
        raise ValueError(
            f"tools_enabled must be a list of tool name strings, got {type(v).__name__}."
        )

    invalid = [item for item in v if item not in QORA_TOOL_NAMES]
    if invalid:
        raise ValueError(
            f"tools_enabled contains unknown tool names: {invalid}. "
            f"Valid tools are: {sorted(QORA_TOOL_NAMES)}."
        )
    return v


class AgentCreate(BaseModel):
    """Request body for POST /api/v1/clients/{client_id}/agents/."""

    slug: str
    name: str
    voice_id: str
    system_prompt: str | None = None
    knowledge_base: str | None = None
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 300
    tools_enabled: list[str] = _DEFAULT_TOOLS
    is_default: bool = False
    elevenlabs_agent_id: str | None = None
    # TTS runtime config — per-agent ElevenLabs voice synthesis parameters
    # ElevenLabs Conversational AI valid range: speed=[0.7, 1.2], stability=[0.0, 1.0],
    # similarity_boost=[0.0, 1.0]. Values outside these ranges are rejected with 1008.
    tts_speed: float = Field(default=0.95, ge=0.7, le=1.2)
    tts_stability: float = Field(default=0.4, ge=0.0, le=1.0)
    tts_similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not v or not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be a lowercase slug: only letters, digits, and "
                "hyphens, with no leading or trailing hyphens. "
                f"Got: {v!r}"
            )
        return v

    @field_validator("tools_enabled")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        result = _validate_tools_list(v)
        return result  # type: ignore[return-value]


class AgentUpdate(BaseModel):
    """Request body for PATCH /api/v1/clients/{client_id}/agents/{agent_id}.

    All fields are optional. slug is NOT updatable.
    """

    name: str | None = None
    voice_id: str | None = None
    system_prompt: str | None = None
    knowledge_base: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools_enabled: list[str] = []
    elevenlabs_agent_id: str | None = None
    # TTS runtime config — optional per-agent overrides
    # ElevenLabs Conversational AI valid range: speed=[0.7, 1.2]
    tts_speed: float | None = Field(default=None, ge=0.7, le=1.2)
    tts_stability: float | None = Field(default=None, ge=0.0, le=1.0)
    tts_similarity_boost: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("tools_enabled")
    @classmethod
    def validate_tools(cls, v: list[str]) -> list[str]:
        result = _validate_tools_list(v)
        return result  # type: ignore[return-value]


class AgentResponse(BaseModel):
    """Response shape for all agent endpoints."""

    agent_id: str
    client_id: str
    slug: str
    name: str
    voice_id: str
    system_prompt: str | None
    knowledge_base: str | None
    model: str
    temperature: float
    max_tokens: int
    tools_enabled: list[str]
    is_active: bool
    is_default: bool
    created_at: datetime
    # ElevenLabs binding (qora-agent-studio-demo)
    elevenlabs_agent_id: str | None = None
    custom_llm_url: str = ""
    # Readiness metadata (computed by router)
    is_conversation_ready: bool = False
    has_prompt: bool = False
    has_elevenlabs_agent_id: bool = False
    # TTS runtime config — per-agent ElevenLabs voice synthesis parameters
    tts_speed: float = 0.95
    tts_stability: float = 0.4
    tts_similarity_boost: float = 0.75

    model_config = {"from_attributes": True}
