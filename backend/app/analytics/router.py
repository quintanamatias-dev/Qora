"""QORA Analytics — Router for analytics endpoints.

Provides:
- GET /analytics/{client_id}/overview        — aggregated call metrics
- GET /analytics/{client_id}/service-issues  — ranked service issues
- GET /analytics/{client_id}/interests       — top interests with trend
- GET /analytics/{client_id}/agent-stats     — per-agent statistics

Base path: /api/v1/analytics/{client_id}/
All endpoints require client_id (multi-tenant isolation).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.analytics.schemas import (
    AnalyticsAgentStatsResponse,
    AnalyticsInterestsResponse,
    AnalyticsOverviewResponse,
    AnalyticsServiceIssuesResponse,
    AgentStatItem,
    InterestItem,
    ServiceIssueItem,
    VALID_PERIODS,
)
from app.analytics.service import (
    get_agent_stats,
    get_interests,
    get_overview,
    get_service_issues,
    resolve_window,
)
from app.core.database import get_session as db_session
from app.tenants.models import Client

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def _validate_period(
    period: str,
    start_date: date | None,
    end_date: date | None,
) -> None:
    """Raise HTTPException 400 for invalid period values or missing custom dates."""
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period. Must be one of: {', '.join(sorted(VALID_PERIODS))}",
        )
    if period == "custom" and (start_date is None or end_date is None):
        raise HTTPException(
            status_code=400,
            detail="start_date and end_date required for custom period",
        )


async def _validate_client_exists(db, client_id: str) -> None:
    """Raise HTTPException 404 if the client does not exist."""
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=404,
            detail=f"Client '{client_id}' not found",
        )


# ---------------------------------------------------------------------------
# Overview endpoint
# ---------------------------------------------------------------------------


@router.get("/{client_id}/overview", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview(
    client_id: str,
    period: str = "month",
    start_date: date | None = None,
    end_date: date | None = None,
    agent_id: str | None = None,
):
    """Return aggregated call metrics for a client.

    Query parameters:
    - **period**: day | week | month | custom (default: month)
    - **start_date**: ISO 8601 date, required when period=custom
    - **end_date**: ISO 8601 date, required when period=custom
    - **agent_id**: optional agent filter
    """
    _validate_period(period, start_date, end_date)

    date_from, date_to = resolve_window(period, start_date, end_date)

    async with db_session() as db:
        await _validate_client_exists(db, client_id)
        data = await get_overview(
            db,
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
            agent_id=agent_id,
        )

    return AnalyticsOverviewResponse(
        **data,
        period=period,
        start_date=date_from.date(),
        end_date=date_to.date(),
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# Service Issues endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{client_id}/service-issues", response_model=AnalyticsServiceIssuesResponse
)
async def get_analytics_service_issues(
    client_id: str,
    period: str = "month",
    start_date: date | None = None,
    end_date: date | None = None,
    agent_id: str | None = None,
):
    """Return ranked service issues for a client.

    Query parameters:
    - **period**: day | week | month | custom (default: month)
    - **start_date**: required when period=custom
    - **end_date**: required when period=custom
    - **agent_id**: optional agent filter
    """
    _validate_period(period, start_date, end_date)

    date_from, date_to = resolve_window(period, start_date, end_date)

    async with db_session() as db:
        await _validate_client_exists(db, client_id)
        data = await get_service_issues(
            db,
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
            agent_id=agent_id,
        )

    return AnalyticsServiceIssuesResponse(
        issues=[ServiceIssueItem(**item) for item in data["issues"]],
        period=period,
        start_date=date_from.date(),
        end_date=date_to.date(),
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# Interests endpoint
# ---------------------------------------------------------------------------


@router.get("/{client_id}/interests", response_model=AnalyticsInterestsResponse)
async def get_analytics_interests(
    client_id: str,
    period: str = "month",
    start_date: date | None = None,
    end_date: date | None = None,
    agent_id: str | None = None,
):
    """Return top interests with trend direction for a client.

    Query parameters:
    - **period**: day | week | month | custom (default: month)
    - **start_date**: required when period=custom
    - **end_date**: required when period=custom
    - **agent_id**: optional agent filter (passed through, not used in interest query)
    """
    _validate_period(period, start_date, end_date)

    date_from, date_to = resolve_window(period, start_date, end_date)

    async with db_session() as db:
        await _validate_client_exists(db, client_id)
        data = await get_interests(
            db,
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
            agent_id=agent_id,
        )

    return AnalyticsInterestsResponse(
        interests=[InterestItem(**item) for item in data["interests"]],
        period=period,
        start_date=date_from.date(),
        end_date=date_to.date(),
        agent_id=agent_id,
    )


# ---------------------------------------------------------------------------
# Agent Stats endpoint
# ---------------------------------------------------------------------------


@router.get("/{client_id}/agent-stats", response_model=AnalyticsAgentStatsResponse)
async def get_analytics_agent_stats(
    client_id: str,
    period: str = "month",
    start_date: date | None = None,
    end_date: date | None = None,
    agent_id: str | None = None,
):
    """Return per-agent call statistics for a client.

    Query parameters:
    - **period**: day | week | month | custom (default: month)
    - **start_date**: required when period=custom
    - **end_date**: required when period=custom
    - **agent_id**: optional — if provided, returns only that agent's row
    """
    _validate_period(period, start_date, end_date)

    date_from, date_to = resolve_window(period, start_date, end_date)

    async with db_session() as db:
        await _validate_client_exists(db, client_id)
        data = await get_agent_stats(
            db,
            client_id=client_id,
            date_from=date_from,
            date_to=date_to,
        )

    agents = data["agents"]
    # Optional filter by agent_id
    if agent_id is not None:
        agents = [a for a in agents if a["agent_id"] == agent_id]

    return AnalyticsAgentStatsResponse(
        agents=[AgentStatItem(**a) for a in agents],
        period=period,
        start_date=date_from.date(),
        end_date=date_to.date(),
    )
