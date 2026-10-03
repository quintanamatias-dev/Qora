"""QORA agent config materialization (design.md D19).

D19 supersedes the original Phase 5 plan: instead of rewiring the voice hot
path (build_voice_context, the webhook, _build_config_payload) to call
resolve_effective_config() on every turn, Agent.* config columns are kept as
a MATERIALIZED projection of resolve_effective_config(standard, client
active revision, agent active revision). materialize_agent_config() is the
single derivation point — every write path (agents/router.py) and every
propagation path (clients/router.py's client-config propagation, the
standard resync endpoint) calls this instead of resolving/mirroring inline.
The voice hot path keeps reading columns directly: no latency or behavior
risk in the call path, and the resolver stays pure.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.config_resolver import EffectiveConfig, resolve_effective_config
from app.tenants.config_standard import STANDARD_VERSION, AgentConfigStandard
from app.tenants.models import Agent
from app.tenants import revisions_service

# Fields mirrored onto legacy Agent.* columns (design.md D19) — the subset of
# FIELD_POLICY fields that have a corresponding Agent column. Exported so
# callers that need to detect "did materialization actually change anything"
# (client-config propagation, the standard resync endpoint) can snapshot
# before/after without duplicating this list.
MIRRORED_AGENT_FIELDS: tuple[str, ...] = (
    "system_prompt",
    "voice_id",
    "tts_model",
    "tts_speed",
    "tts_stability",
    "tts_similarity_boost",
    "model",
    "temperature",
    "max_tokens",
    "tools_enabled",
    "soft_timeout_seconds",
    "soft_timeout_message",
    "soft_timeout_use_llm",
    "voicemail_detection_enabled",
    "max_call_duration_seconds",
)


def snapshot_mirrored_fields(agent: Agent) -> dict:
    """Return the current value of every column materialize_agent_config may
    overwrite, for before/after change detection.

    tools_enabled is decoded from its JSON-string column representation to a
    list before comparison: json.dumps's separator formatting (compact vs.
    spaced) differs between the raw DB default string and the resolver's
    round-tripped output for the SAME list value, which would otherwise
    register as a spurious change.
    """
    snapshot = {field: getattr(agent, field) for field in MIRRORED_AGENT_FIELDS}
    try:
        snapshot["tools_enabled"] = json.loads(snapshot["tools_enabled"] or "[]")
    except (TypeError, ValueError):
        snapshot["tools_enabled"] = []
    return snapshot


async def resolve_effective_for_agent(
    session: AsyncSession, agent: Agent
) -> EffectiveConfig:
    """Resolve *agent*'s effective config through standard -> client -> agent,
    treating a legacy V1 full-snapshot revision's present fields as
    agent-provenance overrides (design.md D13/D18).
    """
    client_overrides: dict = {}
    client_revision = await revisions_service.get_active_client_revision(
        session, agent.client_id
    )
    if client_revision is not None:
        client_overrides = json.loads(client_revision.config)
        client_overrides.pop("schema_version", None)

    agent_overrides: dict = {}
    active = await revisions_service.get_active_revision(
        session, agent.client_id, agent.id
    )
    if active is not None:
        agent_overrides = json.loads(active.config)
        agent_overrides.pop("schema_version", None)

    return resolve_effective_config(AgentConfigStandard, client_overrides, agent_overrides)


def _mirror_effective_config_to_agent(agent: Agent, effective: EffectiveConfig) -> None:
    fields = effective.fields
    agent.system_prompt = fields["system_prompt"].value or ""
    agent.voice_id = fields["voice_id"].value
    agent.tts_model = fields["tts_model"].value
    agent.tts_speed = fields["tts_speed"].value
    agent.tts_stability = fields["tts_stability"].value
    agent.tts_similarity_boost = fields["tts_similarity_boost"].value
    agent.model = fields["model"].value
    agent.temperature = fields["temperature"].value
    agent.max_tokens = fields["max_tokens"].value
    agent.tools_enabled = json.dumps(fields["tools_enabled"].value)
    agent.soft_timeout_seconds = fields["soft_timeout_seconds"].value
    agent.soft_timeout_message = fields["soft_timeout_message"].value
    agent.soft_timeout_use_llm = fields["soft_timeout_use_llm"].value
    agent.voicemail_detection_enabled = fields["voicemail_detection_enabled"].value
    agent.max_call_duration_seconds = fields["max_call_duration_seconds"].value


async def materialize_agent_config(session: AsyncSession, agent: Agent) -> EffectiveConfig:
    """Resolve *agent*'s effective config and write it onto the legacy
    Agent.* columns, stamping agent.materialized_standard_version with the
    STANDARD_VERSION used (design.md D19). Callers still own flush/commit.
    """
    effective = await resolve_effective_for_agent(session, agent)
    _mirror_effective_config_to_agent(agent, effective)
    agent.materialized_standard_version = STANDARD_VERSION
    return effective
