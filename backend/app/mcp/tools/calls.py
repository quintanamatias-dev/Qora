"""list_calls / get_call (design.md M-D1) — client_id is required and
non-optional on every call, same rationale as leads.py."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallAnalysis, CallSession
from app.mcp.schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CallAnalysisSummary,
    CallDetail,
    CallSummary,
)


def _to_summary(call: CallSession) -> CallSummary:
    return CallSummary(
        call_id=call.id,
        client_id=call.client_id,
        lead_id=call.lead_id,
        status=call.status,
        outcome=call.outcome,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_seconds=call.duration_seconds,
    )


def _analysis_to_summary(analysis: CallAnalysis) -> CallAnalysisSummary:
    return CallAnalysisSummary(
        summary=analysis.summary,
        interest_level=analysis.interest_level,
        classification=analysis.classification,
        outcome_reason=analysis.outcome_reason,
        urgency=analysis.urgency,
        primary_need=analysis.primary_need,
        next_action_suggested=analysis.next_action_suggested,
        objections=json.loads(analysis.objections or "[]"),
        products=json.loads(analysis.products or "[]"),
        pain_points=json.loads(analysis.pain_points or "[]"),
    )


async def list_calls(
    session: AsyncSession,
    client_id: str,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[CallSummary]:
    """List call sessions scoped to exactly one client. Rejected before any
    query if client_id is missing."""
    if not client_id:
        raise ValueError("client_id is required")
    bounded_limit = min(limit, MAX_PAGE_SIZE)
    query = (
        select(CallSession)
        .where(CallSession.client_id == client_id)
        .order_by(CallSession.started_at.desc())
        .offset(offset)
        .limit(bounded_limit)
    )
    result = await session.execute(query)
    return [_to_summary(c) for c in result.scalars().all()]


async def get_call(
    session: AsyncSession, client_id: str, call_id: str
) -> CallDetail | None:
    """Return a single call session, scoped to client_id, including its
    post-call analysis summary when one exists."""
    if not client_id:
        raise ValueError("client_id is required")
    call = await session.get(CallSession, call_id)
    if call is None or call.client_id != client_id:
        return None

    analysis_result = await session.execute(
        select(CallAnalysis).where(CallAnalysis.session_id == call_id)
    )
    analysis = analysis_result.scalar_one_or_none()

    return CallDetail(
        call_id=call.id,
        client_id=call.client_id,
        lead_id=call.lead_id,
        status=call.status,
        outcome=call.outcome,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_seconds=call.duration_seconds,
        summary=call.summary,
        analysis=_analysis_to_summary(analysis) if analysis is not None else None,
    )
