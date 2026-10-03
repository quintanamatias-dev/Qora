"""Task 3.1 — list_leads / get_lead."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_leads_requires_client_id(db_session):
    from app.mcp.tools.leads import list_leads

    with pytest.raises(ValueError):
        await list_leads(db_session, "")


@pytest.mark.asyncio
async def test_list_leads_paginates_with_hard_max(db_session):
    from app.leads import service as leads_service
    from app.mcp.schemas import MAX_PAGE_SIZE
    from app.mcp.tools.leads import list_leads
    from app.tenants import service as tenant_service

    client = await tenant_service.create_client(
        db_session, id="acme", name="Acme Co", voice_id="voice-1"
    )
    for i in range(5):
        await leads_service.create_lead(
            db_session,
            client_id=client.id,
            name=f"Lead {i}",
            phone=f"+549110000{i:04d}",
        )
    await db_session.commit()

    results = await list_leads(db_session, client.id, limit=MAX_PAGE_SIZE + 500)

    assert len(results) <= MAX_PAGE_SIZE
    assert len(results) == 5  # fewer leads than the max exist


@pytest.mark.asyncio
async def test_get_lead_requires_client_id(db_session):
    from app.mcp.tools.leads import get_lead

    with pytest.raises(ValueError):
        await get_lead(db_session, "", "some-lead-id")


@pytest.mark.asyncio
async def test_get_lead_scopes_to_client(db_session):
    from app.leads import service as leads_service
    from app.mcp.tools.leads import get_lead
    from app.tenants import service as tenant_service

    client_a = await tenant_service.create_client(
        db_session, id="client-a", name="Client A", voice_id="voice-1"
    )
    client_b = await tenant_service.create_client(
        db_session, id="client-b", name="Client B", voice_id="voice-2"
    )
    lead = await leads_service.create_lead(
        db_session, client_id=client_a.id, name="Jane Doe", phone="+5491100000000"
    )
    await db_session.commit()

    same_tenant = await get_lead(db_session, client_a.id, lead.id)
    cross_tenant = await get_lead(db_session, client_b.id, lead.id)

    assert same_tenant is not None
    assert same_tenant.lead_id == lead.id
    assert cross_tenant is None
