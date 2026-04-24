"""QORA Agents — Pydantic schemas for request/response validation.

Slug validation: ^[a-z0-9][a-z0-9-]*[a-z0-9]?$ (no leading/trailing hyphens).
Single-char slugs (all lowercase letters or digits) are also valid.

tools_enabled validation: must be a JSON list containing only keys from
QORA_TOOL_DEFINITIONS in app.voice.webhook.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, field_validator

# Slug must be all lowercase alphanumeric + hyphens, no leading/trailing hyphen.
# Allows single alphanumeric chars (e.g. "a", "1").
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Known tool names from QORA_TOOL_DEFINITIONS (voice/webhook.py).
# Kept as a module-level constant to avoid circular imports at validation time.
QORA_TOOL_NAMES: frozenset[str] = frozenset(
    [
        "get_lead_details",
        "register_interest",
        "mark_not_interested",
        "schedule_followup",
    ]
)

_DEFAULT_TOOLS = (
    '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]'
)


def _validate_tools_enabled(v: str | None) -> str | None:
    """Validate that tools_enabled is a JSON list of known tool names."""
    if v is None:
        return v
    try:
        parsed = json.loads(v)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"tools_enabled must be a valid JSON array of tool names, got {v!r}."
        ) from exc

    if not isinstance(parsed, list):
        raise ValueError(
            f"tools_enabled must be a JSON array, got {type(parsed).__name__}."
        )

    invalid = [item for item in parsed if item not in QORA_TOOL_NAMES]
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
    tools_enabled: str = _DEFAULT_TOOLS
    is_default: bool = False

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
    def validate_tools(cls, v: str) -> str:
        result = _validate_tools_enabled(v)
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
    tools_enabled: str | None = None

    @field_validator("tools_enabled")
    @classmethod
    def validate_tools(cls, v: str | None) -> str | None:
        return _validate_tools_enabled(v)


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
    tools_enabled: str
    is_active: bool
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}
