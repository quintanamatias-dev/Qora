"""Tasks 4.2, 5.1-5.3 — onboarding service: dry-run, real-run, idempotency,
analysis profile, integration row, EL sync, verification checklist."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select


def _basic_spec(**overrides):
    from app.onboarding.spec import OnboardingSpec

    base = dict(
        client_id="acme",
        client_name="Acme Co",
        client_language="Spanish",
        agent_slug="jaumpablo",
        agent_name="Jaumpablo",
        agent_goal="Sell insurance",
        agent_system_prompt="You are a helpful agent.",
        agent_voice_id="voice-1",
    )
    base.update(overrides)
    return OnboardingSpec(**base)


@pytest.mark.asyncio
async def test_dry_run_validates_without_writing(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants.models import Agent, Client

    spec = _basic_spec()
    result = await run_onboarding(spec, db_session, dry_run=True)

    assert result.dry_run is True
    assert result.conflicts == []

    clients = (await db_session.execute(select(Client))).scalars().all()
    agents = (await db_session.execute(select(Agent))).scalars().all()
    assert clients == []
    assert agents == []


@pytest.mark.asyncio
async def test_dry_run_detects_existing_client_id_conflict(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants import service as tenant_service

    await tenant_service.create_client(db_session, id="acme", name="Acme Co", voice_id="voice-1")
    await db_session.commit()

    spec = _basic_spec()
    result = await run_onboarding(spec, db_session, dry_run=True)

    assert any("acme" in conflict for conflict in result.conflicts)


@pytest.mark.asyncio
async def test_real_run_creates_client_and_agent(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants import service as tenant_service

    spec = _basic_spec()
    result = await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    assert result.dry_run is False
    assert result.checklist["client"]["outcome"] == "created"
    assert result.checklist["agent"]["outcome"] == "created"

    client = await tenant_service.get_client(db_session, "acme")
    assert client is not None
    agents = await tenant_service.list_agents_for_client(db_session, "acme")
    assert len(agents) == 1
    assert agents[0].slug == "jaumpablo"
    assert agents[0].active_revision_id is not None


@pytest.mark.asyncio
async def test_real_run_is_idempotent_on_rerun(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants.models import Agent, Client

    spec = _basic_spec()
    await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    result = await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    assert result.checklist["client"]["outcome"] == "already_exists"
    assert result.checklist["agent"]["outcome"] == "already_exists"

    clients = (await db_session.execute(select(Client))).scalars().all()
    agents = (await db_session.execute(select(Agent))).scalars().all()
    assert len(clients) == 1
    assert len(agents) == 1


@pytest.mark.asyncio
async def test_real_run_attaches_analysis_profile_from_vertical(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants import revisions_service

    spec = _basic_spec(analysis_vertical="insurance")
    result = await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    assert result.checklist["analysis_profile"]["outcome"] == "attached"
    catalog = await revisions_service.resolve_client_catalog(db_session, "acme")
    assert catalog.vertical == "insurance"


@pytest.mark.asyncio
async def test_real_run_creates_integration_row_without_secret(db_session):
    from app.onboarding.service import run_onboarding
    from app.tenants.models import ClientIntegration, ClientSecret

    spec = _basic_spec(
        crm_integration={
            "provider": "airtable",
            "base_id": "appXXXXXXXXXXXXXX",
            "table_id": "tblXXXXXXXXXXXXXX",
            "field_mappings": {"name": "Name"},
        }
    )
    result = await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    assert result.checklist["integration"]["outcome"] == "created"

    rows = (
        (
            await db_session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "acme")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].provider == "airtable"

    secrets = (await db_session.execute(select(ClientSecret))).scalars().all()
    assert secrets == []


@pytest.mark.asyncio
async def test_real_run_triggers_el_sync_only_when_agent_id_set(db_session):
    from app.onboarding.service import run_onboarding

    spec_no_el = _basic_spec(client_id="acme-no-el", client_name="Acme No EL")
    with patch(
        "app.onboarding.service.ElevenLabsService.sync_agent_config", new_callable=AsyncMock
    ) as mock_sync:
        result = await run_onboarding(spec_no_el, db_session, dry_run=False)
        await db_session.commit()
        mock_sync.assert_not_called()
    assert result.checklist["elevenlabs_sync"]["outcome"] == "skipped"

    spec_with_el = _basic_spec(
        client_id="acme-with-el", client_name="Acme With EL", elevenlabs_agent_id="el-agent-1"
    )
    with patch(
        "app.onboarding.service.ElevenLabsService.sync_agent_config", new_callable=AsyncMock
    ) as mock_sync:
        from app.elevenlabs.models import SyncResult

        mock_sync.return_value = SyncResult(outcome="synced")
        result = await run_onboarding(spec_with_el, db_session, dry_run=False)
        await db_session.commit()
        mock_sync.assert_called_once()
    assert result.checklist["elevenlabs_sync"]["outcome"] == "synced"


@pytest.mark.asyncio
async def test_verification_checklist_names_every_automated_and_manual_step(db_session):
    from app.onboarding.service import run_onboarding

    spec = _basic_spec(
        client_id="full-flow",
        client_name="Full Flow Co",
        analysis_vertical="insurance",
        crm_integration={
            "provider": "airtable",
            "base_id": "appXXXXXXXXXXXXXX",
            "table_id": "tblXXXXXXXXXXXXXX",
            "field_mappings": {"name": "Name"},
        },
    )
    result = await run_onboarding(spec, db_session, dry_run=False)
    await db_session.commit()

    for key in (
        "client",
        "agent",
        "analysis_profile",
        "integration",
        "elevenlabs_sync",
    ):
        assert key in result.checklist
        assert "outcome" in result.checklist[key]

    assert len(result.manual_steps) > 0
    assert any("voice" in step.lower() for step in result.manual_steps)
