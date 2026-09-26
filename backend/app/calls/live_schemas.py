"""QORA Calls — Response schemas for the read-only "en vivo" live calls view.

These schemas back GET /api/v1/calls/active. They expose ONLY data that
already exists on CallSession / LeadProfileFact — no new columns, no writes.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LiveCallResponse(BaseModel):
    """One in-flight call session for the live canvas."""

    session_id: str
    lead_id: str | None
    lead_first_name: str | None
    agent_id: str | None
    agent_name: str | None
    telephony_status: str
    started_at: datetime


class LiveRecentFactResponse(BaseModel):
    """One recently-learned fact for the "recent memories" feed."""

    text: str
    lead_first_name: str | None
    duration_seconds: float | None


class LiveTodayResponse(BaseModel):
    """Today's aggregate counters (client-scoped, all times UTC-bounded to 'today')."""

    calls_total: int
    completed: int


class LiveCallsResponse(BaseModel):
    """Full response for GET /api/v1/calls/active."""

    server_time: datetime
    calls: list[LiveCallResponse]
    today: LiveTodayResponse
    # Sourced from LeadProfileFact (real table — see app/calls/live.py). Never
    # faked: empty list / zero count when the client genuinely has no facts yet.
    recent_facts: list[LiveRecentFactResponse]
    memory_total: int
