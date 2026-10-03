"""Onboarding harness — service layer (design.md M-D2, specs/onboarding-harness).

Shared by both entrypoints (`python -m app.onboarding` and
`POST /api/v1/admin/onboarding`) so they can never diverge on what
onboarding a client means. Idempotent per entity: dry_run=True writes
nothing; a real run checks client/agent/profile/integration existence first
and reports "already_exists" rather than erroring or duplicating.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.elevenlabs.service import ElevenLabsService
from app.integrations.integration_store import get_default_store
from app.onboarding.spec import OnboardingSpec
from app.tenants import revisions_service
from app.tenants import service as tenant_service
from app.tenants.models import Agent, Client, ClientIntegration

# The genuinely-manual ElevenLabs-dashboard steps (skill Phase 1), unchanged
# by this harness — see skills/qora-client-agent-setup/SKILL.md.
MANUAL_DASHBOARD_STEPS: tuple[str, ...] = (
    "Create agent at https://elevenlabs.io/app/agents",
    "Set voice (cloned or library voice matching brand)",
    "Set Custom LLM URL: https://{host}/api/v1/voice/{client_id}/custom-llm",
    "Set API Key placeholder: dummy-key",
    "Set Model ID: gpt-4o",
    "Set initiation webhook: https://{host}/api/v1/voice/initiation"
    "?client_id={client_id}&lead_id={{lead_id}}",
    "Set first message (agent-specific greeting)",
    "Outbound only: add phone number resource (SIP trunk in Phone Numbers "
    "panel), copy the phone_number_id",
    "Set post-call webhook: https://{host}/api/v1/calls/elevenlabs-postcall "
    "+ copy webhook secret",
)


class OnboardingResult(BaseModel):
    """Checklist returned by both entrypoints for the same spec."""

    dry_run: bool
    conflicts: list[str] = []
    checklist: dict[str, dict[str, Any]] = {}
    manual_steps: list[str] = []


async def _find_agent_by_slug(
    session: AsyncSession, client_id: str, slug: str
) -> Agent | None:
    for agent in await tenant_service.list_agents_for_client(
        session, client_id, include_inactive=True
    ):
        if agent.slug == slug:
            return agent
    return None


async def _find_integration_row(
    session: AsyncSession, client_id: str, provider: str
) -> ClientIntegration | None:
    from sqlalchemy import select

    result = await session.execute(
        select(ClientIntegration).where(
            ClientIntegration.client_id == client_id,
            ClientIntegration.provider == provider,
        )
    )
    return result.scalar_one_or_none()


async def _provision_client_and_agent(
    session: AsyncSession, spec: OnboardingSpec, existing_client: Client | None
) -> tuple[Client, Agent, dict[str, dict[str, Any]]]:
    checklist: dict[str, dict[str, Any]] = {}

    if existing_client is None:
        client = await tenant_service.create_client(
            session,
            id=spec.client_id,
            name=spec.client_name,
            agent_name=spec.agent_name,
            voice_id=spec.agent_voice_id,
            system_prompt_override=spec.agent_system_prompt,
        )
        checklist["client"] = {"outcome": "created"}

        # create_client() always bootstraps a default agent (tenants/service.py
        # "every client must have one") whose slug is derived from agent_name,
        # not necessarily spec.agent_slug — reconcile it to the requested identity
        # instead of creating a second agent for the same client.
        agent = (await tenant_service.list_agents_for_client(
            session, spec.client_id, include_inactive=True
        ))[0]
        update_fields: dict[str, Any] = {}
        if agent.slug != spec.agent_slug:
            update_fields["slug"] = spec.agent_slug
        if spec.elevenlabs_agent_id is not None:
            update_fields["elevenlabs_agent_id"] = spec.elevenlabs_agent_id
        if update_fields:
            agent = await tenant_service.update_agent(
                session, agent.id, spec.client_id, **update_fields
            )
        await revisions_service.create_agent_config_revision(
            session,
            agent=agent,
            patch={"goal": spec.agent_goal},
            source="api",
            created_by="onboarding-harness",
        )
        checklist["agent"] = {"outcome": "created"}
    else:
        client = existing_client
        checklist["client"] = {"outcome": "already_exists"}
        agent = await _find_agent_by_slug(session, spec.client_id, spec.agent_slug)
        if agent is None:
            agent = await tenant_service.create_agent(
                session,
                client_id=spec.client_id,
                slug=spec.agent_slug,
                name=spec.agent_name,
                voice_id=spec.agent_voice_id,
                system_prompt=spec.agent_system_prompt,
                elevenlabs_agent_id=spec.elevenlabs_agent_id,
                goal=spec.agent_goal,
            )
            checklist["agent"] = {"outcome": "created"}
        else:
            checklist["agent"] = {"outcome": "already_exists"}

    return client, agent, checklist


async def _provision_analysis_profile(
    session: AsyncSession, spec: OnboardingSpec, client: Client
) -> dict[str, Any] | None:
    if spec.analysis_vertical is None:
        return None

    catalog = await revisions_service.resolve_client_catalog(session, client.id)
    if catalog.vertical == spec.analysis_vertical:
        return {"outcome": "already_exists", "vertical": spec.analysis_vertical}

    await revisions_service.apply_analysis_profile_template(
        session,
        client=client,
        vertical=spec.analysis_vertical,
        created_by="onboarding-harness",
    )
    return {"outcome": "attached", "vertical": spec.analysis_vertical}


async def _provision_integration(
    session: AsyncSession, spec: OnboardingSpec, client: Client
) -> dict[str, Any] | None:
    if spec.crm_integration is None:
        return None

    existing = await _find_integration_row(session, client.id, spec.crm_integration.provider)
    if existing is not None:
        return {"outcome": "already_exists", "provider": spec.crm_integration.provider}

    import json

    config_dict = {
        "base_id": spec.crm_integration.base_id,
        "table_id": spec.crm_integration.table_id,
        "match_field": spec.crm_integration.match_field,
        "field_mappings": [
            {"source": source, "target": target}
            for source, target in spec.crm_integration.field_mappings.items()
        ],
        "legacy_env_var_name": spec.crm_integration.legacy_env_var_name,
    }
    row = ClientIntegration(
        client_id=client.id,
        provider=spec.crm_integration.provider,
        enabled=True,
        config=json.dumps(config_dict),
        status="disabled" if spec.crm_integration.legacy_env_var_name is None else "degraded",
        created_by="onboarding-harness",
        updated_by="onboarding-harness",
    )
    session.add(row)
    await session.flush()
    get_default_store().invalidate(client.id)
    return {"outcome": "created", "provider": spec.crm_integration.provider}


async def _trigger_elevenlabs_sync(
    agent: Agent, settings: Settings | None
) -> dict[str, Any]:
    if agent.elevenlabs_agent_id is None:
        return {"outcome": "skipped"}

    resolved_settings = settings or Settings()
    sync_result = await ElevenLabsService(resolved_settings).sync_agent_config(agent)
    return {"outcome": sync_result.outcome}


def _config_completeness(agent: Agent) -> dict[str, Any]:
    missing = [
        field
        for field, value in (
            ("system_prompt", agent.system_prompt),
            ("voice_id", agent.voice_id),
        )
        if not value
    ]
    return {"complete": len(missing) == 0, "missing_fields": missing}


async def run_onboarding(
    spec: OnboardingSpec,
    session: AsyncSession,
    *,
    dry_run: bool,
    settings: Settings | None = None,
) -> OnboardingResult:
    """Validate (dry_run=True) or provision (dry_run=False) *spec*.

    dry_run writes nothing. A real run is idempotent per entity: an
    already-existing client/agent/profile/integration is reported, not
    re-created or erroring.
    """
    existing_client = await tenant_service.get_client(session, spec.client_id)
    existing_agent = (
        await _find_agent_by_slug(session, spec.client_id, spec.agent_slug)
        if existing_client is not None
        else None
    )

    if dry_run:
        conflicts: list[str] = []
        if existing_client is not None:
            conflicts.append(f"client '{spec.client_id}' already exists")
        if existing_agent is not None:
            conflicts.append(
                f"agent '{spec.agent_slug}' already exists for client '{spec.client_id}'"
            )
        return OnboardingResult(
            dry_run=True,
            conflicts=conflicts,
            manual_steps=list(MANUAL_DASHBOARD_STEPS),
        )

    client, agent, checklist = await _provision_client_and_agent(
        session, spec, existing_client
    )

    profile_outcome = await _provision_analysis_profile(session, spec, client)
    if profile_outcome is not None:
        checklist["analysis_profile"] = profile_outcome

    integration_outcome = await _provision_integration(session, spec, client)
    if integration_outcome is not None:
        checklist["integration"] = integration_outcome

    checklist["elevenlabs_sync"] = await _trigger_elevenlabs_sync(agent, settings)
    checklist["config_completeness"] = _config_completeness(agent)

    return OnboardingResult(
        dry_run=False,
        conflicts=[],
        checklist=checklist,
        manual_steps=list(MANUAL_DASHBOARD_STEPS),
    )
