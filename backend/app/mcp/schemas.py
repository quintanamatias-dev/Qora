"""QORA data MCP — tool I/O Pydantic shapes (design.md M-D1).

No field anywhere in this module carries a secret-shaped name (*key*,
*secret*, *token*, ciphertext) — CRM API keys and webhook secrets live in
app.tenants.models.ClientSecret, a table no tool in this package reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

# Pagination (data-mcp spec: "Every List Tool Has a Bounded Output Size").
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ClientSummary(BaseModel):
    client_id: str
    name: str
    agent_name: str
    voice_id: str
    is_active: bool
    plan: str
    analysis_language: str
    scheduler_enabled: bool
    created_at: datetime


class AgentSummary(BaseModel):
    agent_id: str
    client_id: str
    slug: str
    name: str
    voice_id: str
    is_active: bool
    is_default: bool
    elevenlabs_agent_id: str | None = None


class EffectiveFieldOut(BaseModel):
    """One resolved config field plus which layer it came from (data-mcp spec:
    "get_agent Reports Effective Config With Provenance")."""

    value: Any
    source_layer: Literal["standard", "client", "agent"]


class AgentEffectiveConfig(BaseModel):
    agent_id: str
    client_id: str
    slug: str
    config: dict[str, EffectiveFieldOut]
    missing_required: list[str]
    agent_active_revision_number: int | None = None
    client_active_revision_number: int | None = None


class LeadSummary(BaseModel):
    lead_id: str
    client_id: str
    name: str
    phone: str
    status: str
    created_at: datetime


class LeadDetail(BaseModel):
    lead_id: str
    client_id: str
    name: str
    phone: str
    status: str
    notes: str | None = None
    email: str | None = None
    interest_level: int | None = None
    next_action: str | None = None
    created_at: datetime
    updated_at: datetime


class CallSummary(BaseModel):
    call_id: str
    client_id: str
    lead_id: str | None = None
    status: str
    outcome: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = None


class CallAnalysisSummary(BaseModel):
    summary: str | None = None
    interest_level: int | None = None
    classification: str | None = None
    outcome_reason: str | None = None
    urgency: str | None = None
    primary_need: str | None = None
    next_action_suggested: str | None = None
    objections: list = []
    products: list = []
    pain_points: list = []


class CallDetail(BaseModel):
    call_id: str
    client_id: str
    lead_id: str | None = None
    status: str
    outcome: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    summary: str | None = None
    analysis: CallAnalysisSummary | None = None
