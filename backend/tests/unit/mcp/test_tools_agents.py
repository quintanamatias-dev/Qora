"""Task 2.1 — list_agents / get_agent with provenance."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_agents_returns_identity_shape(db_session):
    from app.mcp.tools.agents import list_agents
    from app.tenants import service as tenant_service

    client = await tenant_service.create_client(
        db_session, id="acme", name="Acme Co", voice_id="voice-1"
    )
    await db_session.commit()

    results = await list_agents(db_session, client.id)

    assert len(results) == 1
    assert results[0].client_id == client.id
    assert results[0].slug


@pytest.mark.asyncio
async def test_get_agent_returns_provenance_per_field(db_session):
    from app.mcp.tools.agents import get_agent
    from app.tenants import revisions_service
    from app.tenants import service as tenant_service

    client = await tenant_service.create_client(
        db_session, id="acme", name="Acme Co", voice_id="voice-1"
    )
    agents = await tenant_service.list_agents_for_client(db_session, client.id)
    agent = agents[0]

    # Override one field at the agent level. The agent's bootstrap revision
    # is a full V1 snapshot (every field starts as an agent-provenance
    # override) — explicitly nulling tts_model removes that override so it
    # falls through to the Qora standard, giving a genuine inherited field
    # to assert provenance against.
    await revisions_service.create_agent_config_revision(
        db_session,
        agent=agent,
        patch={"temperature": 0.9, "tts_model": None},
        source="api",
        created_by="test",
    )
    await db_session.commit()

    result = await get_agent(db_session, client.id, agent.id)

    assert result is not None
    assert result.config["temperature"].source_layer == "agent"
    assert result.config["temperature"].value == 0.9
    assert result.config["tts_model"].source_layer == "standard"
    assert result.agent_active_revision_number is not None


@pytest.mark.asyncio
async def test_get_agent_returns_none_for_cross_tenant_lookup(db_session):
    from app.mcp.tools.agents import get_agent
    from app.tenants import service as tenant_service

    client_a = await tenant_service.create_client(
        db_session, id="client-a", name="Client A", voice_id="voice-1"
    )
    client_b = await tenant_service.create_client(
        db_session, id="client-b", name="Client B", voice_id="voice-2"
    )
    await db_session.commit()
    agents_a = await tenant_service.list_agents_for_client(db_session, client_a.id)

    result = await get_agent(db_session, client_b.id, agents_a[0].id)

    assert result is None
