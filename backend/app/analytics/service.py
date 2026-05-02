"""QORA Analytics — Async service functions for analytics endpoints.

All functions take an AsyncSession, client_id, date window, and optional agent_id.
Queries are async-first, multi-tenant-safe, and use text() for json_each() extraction.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallAnalysis, CallSession
from app.leads.models import Lead, LeadProfileFact
from app.tenants.models import Agent


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

VALID_PERIODS = frozenset({"day", "week", "month", "custom"})

_PERIOD_DAYS: dict[str, int] = {
    "day": 1,
    "week": 7,
    "month": 30,
}


def resolve_window(
    period: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[datetime, datetime]:
    """Return (date_from, date_to) as UTC datetimes for the requested period.

    Raises ValueError on invalid or incomplete custom period.
    """
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period. Must be one of: {', '.join(sorted(VALID_PERIODS))}"
        )

    if period == "custom":
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date required for custom period")
        date_from = datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
        )
        date_to = datetime(
            end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc
        )
        return date_from, date_to

    days = _PERIOD_DAYS[period]
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    return date_from, date_to


def prior_window(date_from: datetime, date_to: datetime) -> tuple[datetime, datetime]:
    """Return the equivalent window immediately before the given window."""
    duration = date_to - date_from
    prior_to = date_from
    prior_from = date_from - duration
    return prior_from, prior_to


def _compute_trend(current: int, previous: int) -> str:
    """Compute trend label based on ±10% threshold."""
    if previous == 0:
        return "up" if current > 0 else "stable"
    change = (current - previous) / previous
    if change > 0.10:
        return "up"
    if change < -0.10:
        return "down"
    return "stable"


# ---------------------------------------------------------------------------
# get_overview
# ---------------------------------------------------------------------------


async def get_overview(
    session: AsyncSession,
    *,
    client_id: str,
    date_from: datetime,
    date_to: datetime,
    agent_id: str | None,
) -> dict[str, Any]:
    """Aggregate call metrics for the given client and time window.

    Returns:
        dict with total_calls, outcome_distribution, engagement_distribution,
        avg_call_duration_seconds, conversion_rate.
    """
    # Build query: CallAnalysis JOIN CallSession for agent filter
    stmt = (
        select(
            CallAnalysis.classification,
            CallSession.duration_seconds,
        )
        .join(CallSession, CallSession.id == CallAnalysis.session_id)
        .where(CallAnalysis.client_id == client_id)
        .where(CallAnalysis.analyzed_at >= date_from)
        .where(CallAnalysis.analyzed_at <= date_to)
        .where(CallSession.merged_into_session_id.is_(None))
    )

    if agent_id is not None:
        stmt = stmt.where(CallSession.agent_id == agent_id)

    rows = (await session.execute(stmt)).fetchall()

    total_calls = len(rows)
    outcome_distribution: dict[str, int] = {}
    durations: list[float] = []
    completed_positive_count = 0

    for row in rows:
        classification = row.classification
        duration = row.duration_seconds

        if classification:
            outcome_distribution[classification] = (
                outcome_distribution.get(classification, 0) + 1
            )
            if classification == "completed_positive":
                completed_positive_count += 1

        if duration is not None:
            durations.append(float(duration))

    avg_call_duration_seconds: float | None = (
        sum(durations) / len(durations) if durations else None
    )
    conversion_rate: float | None = (
        completed_positive_count / total_calls if total_calls > 0 else None
    )

    return {
        "total_calls": total_calls,
        "outcome_distribution": outcome_distribution,
        "avg_call_duration_seconds": avg_call_duration_seconds,
        "conversion_rate": conversion_rate,
    }


# ---------------------------------------------------------------------------
# get_service_issues
# ---------------------------------------------------------------------------


async def get_service_issues(
    session: AsyncSession,
    *,
    client_id: str,
    date_from: datetime,
    date_to: datetime,
    agent_id: str | None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return ranked service issues for the given window.

    Uses json_each() to extract individual issues from CallAnalysis.service_issues
    (stored as JSON array TEXT). Combines with LeadProfileFact namespace 'service_issue:'.
    """
    # Part 1: json_each() extraction from call_analyses.service_issues
    agent_filter = ""
    params: dict[str, Any] = {
        "client_id": client_id,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }

    if agent_id is not None:
        agent_filter = "AND cs.agent_id = :agent_id"
        params["agent_id"] = agent_id

    sql = text(f"""
        SELECT CASE
                 WHEN json_valid(je.value) THEN json_extract(je.value, '$.category')
                 ELSE je.value
               END AS issue,
               COUNT(*) AS cnt
        FROM call_analyses ca
        JOIN call_sessions cs ON cs.id = ca.session_id
        JOIN json_each(ca.service_issues) je
        WHERE ca.client_id = :client_id
          AND ca.analyzed_at >= :date_from
          AND ca.analyzed_at <= :date_to
          AND cs.merged_into_session_id IS NULL
          AND ca.service_issues != '[]'
          AND ca.service_issues != ''
          {agent_filter}
        GROUP BY CASE
                   WHEN json_valid(je.value) THEN json_extract(je.value, '$.category')
                   ELSE je.value
                 END
        ORDER BY cnt DESC
        LIMIT :limit
    """)

    result = await session.execute(sql, params)
    rows = result.fetchall()

    # Combine with LeadProfileFact namespace 'service_issue:'
    # Build agent-filtered lead subquery if needed
    lpf_stmt = (
        select(
            LeadProfileFact.fact_key,
            func.count(LeadProfileFact.id).label("cnt"),
        )
        .where(LeadProfileFact.fact_key.like("service_issue:%"))
        .where(LeadProfileFact.superseded_at.is_(None))
        .where(LeadProfileFact.recorded_at >= date_from)
        .where(LeadProfileFact.recorded_at <= date_to)
        .join(Lead, Lead.id == LeadProfileFact.lead_id)
        .where(Lead.client_id == client_id)
        .group_by(LeadProfileFact.fact_key)
        .order_by(func.count(LeadProfileFact.id).desc())
        .limit(limit)
    )

    # When agent_id is provided, scope LPF results to leads that have
    # at least one call session with that agent.
    if agent_id is not None:
        lpf_stmt = lpf_stmt.join(
            CallSession,
            (CallSession.lead_id == Lead.id) & (CallSession.agent_id == agent_id),
        )

    lpf_result = await session.execute(lpf_stmt)
    lpf_rows = lpf_result.fetchall()

    # Merge counts
    issue_counts: dict[str, int] = {}

    for row in rows:
        issue = str(row.issue)
        issue_counts[issue] = issue_counts.get(issue, 0) + int(row.cnt)

    for row in lpf_rows:
        # Strip namespace prefix
        issue = str(row.fact_key).removeprefix("service_issue:")
        issue_counts[issue] = issue_counts.get(issue, 0) + int(row.cnt)

    # Sort and rank
    sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[
        :limit
    ]

    return {
        "issues": [
            {"issue": issue, "count": count, "rank": rank}
            for rank, (issue, count) in enumerate(sorted_issues, start=1)
        ]
    }


# ---------------------------------------------------------------------------
# get_interests
# ---------------------------------------------------------------------------


async def get_interests(
    session: AsyncSession,
    *,
    client_id: str,
    date_from: datetime,
    date_to: datetime,
    agent_id: str | None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return top interests with trend direction.

    Sources:
    - LeadProfileFact with fact_key prefix 'signal:'
    Trend: compare current window vs prior equivalent window.
    """
    prior_from, prior_to = prior_window(date_from, date_to)

    # Query current window: LeadProfileFact signal: namespace
    async def _fetch_interest_counts(
        from_dt: datetime, to_dt: datetime
    ) -> dict[str, int]:
        stmt = (
            select(
                LeadProfileFact.fact_key,
                func.count(LeadProfileFact.id).label("cnt"),
            )
            .where(LeadProfileFact.fact_key.like("signal:%"))
            .where(LeadProfileFact.recorded_at >= from_dt)
            .where(LeadProfileFact.recorded_at <= to_dt)
            .join(Lead, Lead.id == LeadProfileFact.lead_id)
            .where(Lead.client_id == client_id)
            .group_by(LeadProfileFact.fact_key)
            .order_by(func.count(LeadProfileFact.id).desc())
            .limit(limit)
        )
        # When agent_id is provided, scope interests to leads that have
        # at least one call session with that agent.
        if agent_id is not None:
            stmt = stmt.join(
                CallSession,
                (CallSession.lead_id == Lead.id) & (CallSession.agent_id == agent_id),
            )
        result = await session.execute(stmt)
        return {
            str(row.fact_key).removeprefix("signal:"): int(row.cnt)
            for row in result.fetchall()
        }

    current_counts = await _fetch_interest_counts(date_from, date_to)
    previous_counts = await _fetch_interest_counts(prior_from, prior_to)

    interests = []
    for interest, count in sorted(
        current_counts.items(), key=lambda x: x[1], reverse=True
    ):
        previous_count = previous_counts.get(interest, 0)
        trend = _compute_trend(count, previous_count)
        interests.append(
            {
                "interest": interest,
                "count": count,
                "trend": trend,
                "previous_count": previous_count,
            }
        )

    return {"interests": interests}


# ---------------------------------------------------------------------------
# get_agent_stats
# ---------------------------------------------------------------------------


async def get_agent_stats(
    session: AsyncSession,
    *,
    client_id: str,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, Any]:
    """Return per-agent call statistics for the given window.

    NULL agent_id is bucketed as 'unassigned'.
    """
    stmt = (
        select(
            CallSession.agent_id,
            Agent.name.label("agent_name"),
            CallAnalysis.classification,
        )
        .join(CallSession, CallSession.id == CallAnalysis.session_id)
        .outerjoin(Agent, Agent.id == CallSession.agent_id)
        .where(CallAnalysis.client_id == client_id)
        .where(CallAnalysis.analyzed_at >= date_from)
        .where(CallAnalysis.analyzed_at <= date_to)
        .where(CallSession.merged_into_session_id.is_(None))
    )

    rows = (await session.execute(stmt)).fetchall()

    # Group by agent
    agent_data: dict[str, dict[str, Any]] = {}

    for row in rows:
        raw_agent_id = row.agent_id
        bucket_id = raw_agent_id if raw_agent_id is not None else "unassigned"
        agent_name = row.agent_name if raw_agent_id is not None else None
        classification = row.classification

        if bucket_id not in agent_data:
            agent_data[bucket_id] = {
                "agent_id": bucket_id,
                "agent_name": agent_name,
                "total_calls": 0,
                "outcome_distribution": {},
                "completed_positive_count": 0,
            }

        entry = agent_data[bucket_id]
        entry["total_calls"] += 1

        if classification:
            entry["outcome_distribution"][classification] = (
                entry["outcome_distribution"].get(classification, 0) + 1
            )
            if classification == "completed_positive":
                entry["completed_positive_count"] += 1

    # Build response
    agents = []
    for entry in agent_data.values():
        total = entry["total_calls"]
        conversion_rate = entry["completed_positive_count"] / total if total > 0 else None

        agents.append(
            {
                "agent_id": entry["agent_id"],
                "agent_name": entry["agent_name"],
                "total_calls": total,
                "outcome_distribution": entry["outcome_distribution"],
                "conversion_rate": conversion_rate,
            }
        )

    return {"agents": agents}
