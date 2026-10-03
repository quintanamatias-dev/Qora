"""Task 3.2 — list_calls / get_call."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_list_calls_requires_client_id(db_session):
    from app.mcp.tools.calls import list_calls

    with pytest.raises(ValueError):
        await list_calls(db_session, "")


@pytest.mark.asyncio
async def test_get_call_includes_analysis(db_session):
    from app.calls.models import CallAnalysis, CallSession
    from app.mcp.tools.calls import get_call
    from app.tenants import service as tenant_service

    client = await tenant_service.create_client(
        db_session, id="acme", name="Acme Co", voice_id="voice-1"
    )
    call = CallSession(id=str(uuid.uuid4()), client_id=client.id, status="completed")
    db_session.add(call)
    await db_session.flush()
    db_session.add(
        CallAnalysis(
            id=str(uuid.uuid4()),
            session_id=call.id,
            client_id=client.id,
            summary="Customer asked about pricing.",
            interest_level=80,
            classification="hot",
        )
    )
    await db_session.commit()

    result = await get_call(db_session, client.id, call.id)

    assert result is not None
    assert result.analysis is not None
    assert result.analysis.summary == "Customer asked about pricing."
    assert result.analysis.interest_level == 80


@pytest.mark.asyncio
async def test_get_call_requires_client_id(db_session):
    from app.mcp.tools.calls import get_call

    with pytest.raises(ValueError):
        await get_call(db_session, "", "some-call-id")


@pytest.mark.asyncio
async def test_get_call_scopes_to_client(db_session):
    from app.calls.models import CallSession
    from app.mcp.tools.calls import get_call
    from app.tenants import service as tenant_service

    client_a = await tenant_service.create_client(
        db_session, id="client-a", name="Client A", voice_id="voice-1"
    )
    client_b = await tenant_service.create_client(
        db_session, id="client-b", name="Client B", voice_id="voice-2"
    )
    call = CallSession(id=str(uuid.uuid4()), client_id=client_a.id, status="completed")
    db_session.add(call)
    await db_session.commit()

    cross_tenant = await get_call(db_session, client_b.id, call.id)

    assert cross_tenant is None
