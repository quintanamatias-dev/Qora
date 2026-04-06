"""QORA Clients — Pydantic schemas for request/response validation.

Slug validation: ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (no leading/trailing hyphens)
Single-char slugs (all lowercase letters or digits) are also valid.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, field_validator

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


class ClientResponse(BaseModel):
    """Response shape for all client endpoints."""

    client_id: str
    broker_name: str
    agent_name: str
    voice_id: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
