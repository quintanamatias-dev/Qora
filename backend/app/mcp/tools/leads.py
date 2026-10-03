"""list_leads / get_lead (design.md M-D1) — client_id is required and
non-optional on every call: an LLM-driven caller omitting it must get a loud
validation error, never a cross-tenant data dump (design.md M-D1 rationale)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import Lead
from app.mcp.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, LeadDetail, LeadSummary


def _to_summary(lead: Lead) -> LeadSummary:
    return LeadSummary(
        lead_id=lead.id,
        client_id=lead.client_id,
        name=lead.name,
        phone=lead.phone,
        status=lead.status,
        created_at=lead.created_at,
    )


def _to_detail(lead: Lead) -> LeadDetail:
    return LeadDetail(
        lead_id=lead.id,
        client_id=lead.client_id,
        name=lead.name,
        phone=lead.phone,
        status=lead.status,
        notes=lead.notes,
        email=lead.email,
        interest_level=lead.interest_level,
        next_action=lead.next_action,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


async def list_leads(
    session: AsyncSession,
    client_id: str,
    *,
    status: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[LeadSummary]:
    """List leads scoped to exactly one client. Rejected before any query if
    client_id is missing."""
    if not client_id:
        raise ValueError("client_id is required")
    bounded_limit = min(limit, MAX_PAGE_SIZE)
    query = select(Lead).where(Lead.client_id == client_id)
    if status is not None:
        query = query.where(Lead.status == status)
    query = query.order_by(Lead.created_at.desc()).offset(offset).limit(bounded_limit)
    result = await session.execute(query)
    return [_to_summary(lead) for lead in result.scalars().all()]


async def get_lead(
    session: AsyncSession, client_id: str, lead_id: str
) -> LeadDetail | None:
    """Return a single lead, scoped to client_id. A lead belonging to another
    client is reported as not found."""
    if not client_id:
        raise ValueError("client_id is required")
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.client_id != client_id:
        return None
    return _to_detail(lead)
