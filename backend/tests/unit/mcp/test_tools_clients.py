"""Task 1.2 — list_clients / get_client."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_clients_returns_identity_and_config_shape(db_session):
    from app.mcp.tools.clients import list_clients
    from app.tenants import service as tenant_service

    await tenant_service.create_client(
        db_session, id="acme", name="Acme Co", voice_id="voice-1"
    )
    await db_session.commit()

    results = await list_clients(db_session)

    assert len(results) == 1
    summary = results[0]
    assert summary.client_id == "acme"
    assert summary.name == "Acme Co"
    assert summary.voice_id == "voice-1"
    assert summary.is_active is True


@pytest.mark.asyncio
async def test_get_client_returns_none_for_unknown_id(db_session):
    from app.mcp.tools.clients import get_client

    result = await get_client(db_session, "does-not-exist")

    assert result is None
