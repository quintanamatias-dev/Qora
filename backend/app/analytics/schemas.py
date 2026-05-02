"""QORA Analytics — Pydantic v2 request/response schemas.

Covers all 4 analytics endpoints:
- /overview
- /service-issues
- /interests
- /agent-stats
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

VALID_PERIODS = frozenset({"day", "week", "month", "custom"})


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class AnalyticsOverviewResponse(BaseModel):
    """Response for GET /analytics/{client_id}/overview."""

    total_calls: int
    outcome_distribution: dict[str, int]
    avg_call_duration_seconds: float | None
    conversion_rate: float | None
    period: str
    start_date: date
    end_date: date
    agent_id: str | None = None


# ---------------------------------------------------------------------------
# Service Issues
# ---------------------------------------------------------------------------


class ServiceIssueItem(BaseModel):
    """One ranked service issue entry."""

    issue: str
    count: int
    rank: int


class AnalyticsServiceIssuesResponse(BaseModel):
    """Response for GET /analytics/{client_id}/service-issues."""

    issues: list[ServiceIssueItem]
    period: str
    start_date: date
    end_date: date
    agent_id: str | None = None


# ---------------------------------------------------------------------------
# Interests
# ---------------------------------------------------------------------------


class InterestItem(BaseModel):
    """One interest/product with trend comparison."""

    interest: str
    count: int
    trend: str  # "up" | "down" | "stable"
    previous_count: int


class AnalyticsInterestsResponse(BaseModel):
    """Response for GET /analytics/{client_id}/interests."""

    interests: list[InterestItem]
    period: str
    start_date: date
    end_date: date
    agent_id: str | None = None


# ---------------------------------------------------------------------------
# Agent Stats
# ---------------------------------------------------------------------------


class AgentStatItem(BaseModel):
    """Per-agent call breakdown."""

    agent_id: str
    agent_name: str | None
    total_calls: int
    outcome_distribution: dict[str, int]
    conversion_rate: float | None


class AnalyticsAgentStatsResponse(BaseModel):
    """Response for GET /analytics/{client_id}/agent-stats."""

    agents: list[AgentStatItem]
    period: str
    start_date: date
    end_date: date
