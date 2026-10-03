"""QORA Config Revisions — service layer (design.md D4/D7, D11).

Both agent_config_revisions and client_config_revisions rows are insert-only:
no UPDATE or DELETE path exists anywhere in this module. Every lookup
function is scoped by the owning tenant id(s), so a revision belonging to
another agent/client is never readable or activatable — the lookup simply
returns None/[] as if the revision did not exist.

design.md D11: the generic private helpers below (_create_revision,
_get_revision, _list_revisions, _activate_revision, _rollback_to_revision)
are parameterized by (model, owner_id_attr, active_pointer_attr) and reused
by both the agent-level and client-level public functions — this is the
"cheap reuse at the service-layer function level" D11 calls for, without
merging the two tables into one generic schema.

Agent revisions store a FULL AgentConfigV1 snapshot (1a, unchanged). Client
revisions store SPARSE overrides only (design.md D11's "Client revision
content is sparse" requirement) — hence the two config_cls/serialize
callables threaded through the generic rollback helper instead of a single
shared `.model_dump_json()` call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.profiles.schema import AnalysisProfileConfigV1
from app.analysis.profiles.templates import generic as generic_profile_template
from app.analysis.profiles.templates import insurance as insurance_profile_template
from app.tenants.agent_config_schema import AgentConfigV1, AgentConfigV2
from app.tenants.client_config_schema import ClientConfigV1
from app.tenants.field_policy import AGENT_REQUIRED_FIELDS, FIELD_POLICY
from app.tenants.models import (
    Agent,
    AgentConfigRevision,
    Client,
    ClientAnalysisProfileRevision,
    ClientConfigRevision,
)

RevisionSource = Literal["import", "api", "rollback"]

Serializer = Callable[[BaseModel], tuple[str, str]]


def _serialize_agent_config(config: AgentConfigV1) -> tuple[str, str]:
    return config.model_dump_json(), config.schema_version


def _serialize_client_config(config: ClientConfigV1) -> tuple[str, str]:
    sparse = config.model_dump(exclude_none=True)
    return json.dumps(sparse), config.schema_version


def _serialize_agent_config_v2(config: AgentConfigV2) -> tuple[str, str]:
    sparse = config.model_dump(exclude_none=True)
    return json.dumps(sparse), config.schema_version


def _agent_serializer_for(schema_version: str) -> tuple[type[BaseModel], Serializer]:
    """Pick the (config_cls, serializer) pair matching a stored revision's
    schema_version, so rollback can copy EITHER a V1 full-snapshot or a V2
    sparse-override revision without guessing (design.md D18).
    """
    if schema_version == "v2":
        return AgentConfigV2, _serialize_agent_config_v2
    return AgentConfigV1, _serialize_agent_config


# ---------------------------------------------------------------------------
# Generic helpers (design.md D11) — parameterized by model/owner-attr, never
# called directly by anything outside this module.
# ---------------------------------------------------------------------------


async def _next_revision_number(
    session: AsyncSession, model: Any, owner_id_attr: str, owner_id: str
) -> int:
    id_column = getattr(model, owner_id_attr)
    existing_max = await session.execute(
        select(model.revision_number)
        .where(id_column == owner_id)
        .order_by(model.revision_number.desc())
        .limit(1)
    )
    return (existing_max.scalar_one_or_none() or 0) + 1


async def _create_revision(
    session: AsyncSession,
    *,
    model: Any,
    owner: Any,
    owner_id_attr: str,
    active_pointer_attr: str,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
    **fields: Any,
) -> Any:
    """Insert-only revision creation + activation.

    revision_number = max(existing for owner.id) + 1, starting at 1. Single
    pointer swap on owner.<active_pointer_attr> — no other revision row is
    touched.

    **fields are the revision's own content columns beyond
    id/revision_number/source/created_by/note/owner-id — e.g. config+
    schema_version for the JSON-blob revision tables (agent/client/analysis-
    profile), or content_md/filler_text/trigger_hint/description for
    SkillRevision (skill-packages, P4-D1's fourth owner table on this
    reuse pattern).
    """
    owner_id = owner.id
    next_number = await _next_revision_number(session, model, owner_id_attr, owner_id)

    revision = model(
        id=str(uuid.uuid4()),
        revision_number=next_number,
        source=source,
        created_by=created_by,
        note=note,
        **{owner_id_attr: owner_id},
        **fields,
    )
    session.add(revision)
    await session.flush()

    setattr(owner, active_pointer_attr, revision.id)
    await session.flush()
    return revision


async def _get_revision(
    session: AsyncSession,
    *,
    model: Any,
    owner_id_attr: str,
    owner_id: str,
    revision_id: str,
) -> Any | None:
    id_column = getattr(model, owner_id_attr)
    result = await session.execute(
        select(model).where(model.id == revision_id, id_column == owner_id)
    )
    return result.scalar_one_or_none()


async def _list_revisions(
    session: AsyncSession, *, model: Any, owner_id_attr: str, owner_id: str
) -> list[Any]:
    id_column = getattr(model, owner_id_attr)
    result = await session.execute(
        select(model)
        .where(id_column == owner_id)
        .order_by(model.revision_number.desc())
    )
    return list(result.scalars().all())


async def _activate_revision(
    session: AsyncSession,
    *,
    model: Any,
    owner: Any,
    owner_id_attr: str,
    active_pointer_attr: str,
    revision_id: str,
) -> Any | None:
    """Point owner.<active_pointer_attr> at revision_id. Single UPDATE."""
    revision = await _get_revision(
        session,
        model=model,
        owner_id_attr=owner_id_attr,
        owner_id=owner.id,
        revision_id=revision_id,
    )
    if revision is None:
        return None
    setattr(owner, active_pointer_attr, revision.id)
    await session.flush()
    return owner


async def _rollback_to_revision(
    session: AsyncSession,
    *,
    model: Any,
    owner: Any,
    owner_id_attr: str,
    active_pointer_attr: str,
    target_revision_id: str,
    config_cls: type[BaseModel],
    serializer: Serializer,
    created_by: str,
) -> Any | None:
    """Copy target_revision_id's config into a NEW revision (source="rollback"),
    then activate it. Never mutates or reactivates the old row directly.
    """
    target = await _get_revision(
        session,
        model=model,
        owner_id_attr=owner_id_attr,
        owner_id=owner.id,
        revision_id=target_revision_id,
    )
    if target is None:
        return None

    config = config_cls.model_validate_json(target.config)
    config_json, schema_version = serializer(config)
    return await _create_revision(
        session,
        model=model,
        owner=owner,
        owner_id_attr=owner_id_attr,
        active_pointer_attr=active_pointer_attr,
        config=config_json,
        schema_version=schema_version,
        source="rollback",
        created_by=created_by,
        note=f"rollback to revision {target.revision_number}",
    )


# ---------------------------------------------------------------------------
# Agent-level public functions (unchanged signatures — 1a's call sites and
# tests keep working exactly as before).
# ---------------------------------------------------------------------------


class AgentConfigWriteError(ValueError):
    """Raised when an agent config write violates field-policy rules
    (design.md D14/D18): a locked/client_only field present in the payload,
    a brand-new agent missing an agent_required field, or an existing
    agent's write removing a previously-set required field.
    """

    def __init__(self, message: str, *, fields: list[str]):
        super().__init__(message)
        self.fields = fields


def _decode_agent_overrides(revision: AgentConfigRevision | None) -> dict[str, Any]:
    """Build the sparse agent-overrides dict to merge the next patch over.

    V1 active revision (or none): promote every non-None V1 value to an
    explicit override, dropping any locked/client_only key (design.md D18's
    V1-to-V2 promotion) — guarantees no behavior change on first V2 write.
    V2 active revision: already sparse, decode as-is.
    """
    if revision is None:
        return {}
    data: dict[str, Any] = json.loads(revision.config)
    data.pop("schema_version", None)
    if revision.schema_version == "v2":
        return {k: v for k, v in data.items() if v is not None}
    return {
        k: v
        for k, v in data.items()
        if v is not None and FIELD_POLICY.get(k) not in ("locked", "client_only")
    }


def validate_agent_config_write(
    *,
    previous_overrides: dict[str, Any],
    patch: dict[str, Any],
    is_new_agent: bool,
) -> dict[str, Any]:
    """Merge *patch* over *previous_overrides*, enforcing field-policy rules.

    Grandfathering (design.md D18): an existing agent whose required field
    was already missing before this write may keep omitting it — the merged
    result simply stays missing, never force-filled or rejected for that
    reason alone. Once a required field has a value, no write may null it
    back out.
    """
    locked_in_patch = sorted(
        k
        for k, v in patch.items()
        if v is not None and FIELD_POLICY.get(k) in ("locked", "client_only")
    )
    if locked_in_patch:
        raise AgentConfigWriteError(
            f"cannot set client/locked-level field(s) on an agent revision: {locked_in_patch}",
            fields=locked_in_patch,
        )

    merged = dict(previous_overrides)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value

    if is_new_agent:
        missing = sorted(f for f in AGENT_REQUIRED_FIELDS if merged.get(f) is None)
        if missing:
            raise AgentConfigWriteError(
                f"missing required field(s) for a new agent: {missing}", fields=missing
            )
        return merged

    removed = sorted(
        f
        for f in AGENT_REQUIRED_FIELDS
        if previous_overrides.get(f) is not None and merged.get(f) is None
    )
    if removed:
        raise AgentConfigWriteError(
            f"cannot remove previously-set required field(s): {removed}", fields=removed
        )
    return merged


async def create_agent_config_revision(
    session: AsyncSession,
    *,
    agent: Agent,
    patch: dict[str, Any],
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
    is_new_agent: bool = False,
) -> AgentConfigRevision:
    """Create + activate a new sparse AgentConfigV2 revision (design.md D18).

    *patch* is the raw write payload (field -> value; an explicit null value
    removes an existing override, i.e. "inherit again"). Validated against
    FIELD_POLICY before persisting — raises AgentConfigWriteError on any
    violation, and no row is created.
    """
    patch = {k: v for k, v in patch.items() if k != "schema_version"}
    previous = await get_active_revision(session, agent.client_id, agent.id)
    previous_overrides = _decode_agent_overrides(previous)
    merged = validate_agent_config_write(
        previous_overrides=previous_overrides, patch=patch, is_new_agent=is_new_agent
    )
    validated = AgentConfigV2(**merged)
    config_json, schema_version = _serialize_agent_config_v2(validated)
    return await _create_revision(
        session,
        model=AgentConfigRevision,
        owner=agent,
        owner_id_attr="agent_id",
        active_pointer_attr="active_revision_id",
        config=config_json,
        schema_version=schema_version,
        source=source,
        created_by=created_by,
        note=note,
    )


async def create_revision(
    session: AsyncSession,
    *,
    agent: Agent,
    config: AgentConfigV1,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> AgentConfigRevision:
    config_json, schema_version = _serialize_agent_config(config)
    return await _create_revision(
        session,
        model=AgentConfigRevision,
        owner=agent,
        owner_id_attr="agent_id",
        active_pointer_attr="active_revision_id",
        config=config_json,
        schema_version=schema_version,
        source=source,
        created_by=created_by,
        note=note,
    )


async def _get_agent_in_client(
    session: AsyncSession, client_id: str, agent_id: str
) -> Agent | None:
    result = await session.execute(
        select(Agent).where(Agent.id == agent_id, Agent.client_id == client_id)
    )
    return result.scalar_one_or_none()


async def get_active_revision(
    session: AsyncSession, client_id: str, agent_id: str
) -> AgentConfigRevision | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None or agent.active_revision_id is None:
        return None
    return await session.get(AgentConfigRevision, agent.active_revision_id)


async def get_revision(
    session: AsyncSession, client_id: str, agent_id: str, revision_id: str
) -> AgentConfigRevision | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    return await _get_revision(
        session,
        model=AgentConfigRevision,
        owner_id_attr="agent_id",
        owner_id=agent.id,
        revision_id=revision_id,
    )


async def list_revisions(
    session: AsyncSession, client_id: str, agent_id: str
) -> list[AgentConfigRevision]:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return []
    return await _list_revisions(
        session, model=AgentConfigRevision, owner_id_attr="agent_id", owner_id=agent.id
    )


async def activate_revision(
    session: AsyncSession, client_id: str, agent_id: str, revision_id: str
) -> Agent | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    return await _activate_revision(
        session,
        model=AgentConfigRevision,
        owner=agent,
        owner_id_attr="agent_id",
        active_pointer_attr="active_revision_id",
        revision_id=revision_id,
    )


async def rollback_to_revision(
    session: AsyncSession,
    client_id: str,
    agent_id: str,
    target_revision_id: str,
    created_by: str,
) -> AgentConfigRevision | None:
    agent = await _get_agent_in_client(session, client_id, agent_id)
    if agent is None:
        return None
    target = await _get_revision(
        session,
        model=AgentConfigRevision,
        owner_id_attr="agent_id",
        owner_id=agent.id,
        revision_id=target_revision_id,
    )
    if target is None:
        return None
    # design.md D18: rollback preserves whichever schema_version the target
    # revision was recorded in — rolling back to a V1 full snapshot stays V1,
    # rolling back to a V2 sparse override set stays V2.
    config_cls, serializer = _agent_serializer_for(target.schema_version)
    return await _rollback_to_revision(
        session,
        model=AgentConfigRevision,
        owner=agent,
        owner_id_attr="agent_id",
        active_pointer_attr="active_revision_id",
        target_revision_id=target_revision_id,
        config_cls=config_cls,
        serializer=serializer,
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# Client-level public functions (design.md D11) — same generic helpers,
# scoped by client_id only (the client itself is the tenant boundary).
# ---------------------------------------------------------------------------


async def create_client_revision(
    session: AsyncSession,
    *,
    client: Client,
    config: ClientConfigV1,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> ClientConfigRevision:
    config_json, schema_version = _serialize_client_config(config)
    return await _create_revision(
        session,
        model=ClientConfigRevision,
        owner=client,
        owner_id_attr="client_id",
        active_pointer_attr="active_config_revision_id",
        config=config_json,
        schema_version=schema_version,
        source=source,
        created_by=created_by,
        note=note,
    )


async def get_active_client_revision(
    session: AsyncSession, client_id: str
) -> ClientConfigRevision | None:
    client = await session.get(Client, client_id)
    if client is None or client.active_config_revision_id is None:
        return None
    return await session.get(ClientConfigRevision, client.active_config_revision_id)


async def get_client_revision(
    session: AsyncSession, client_id: str, revision_id: str
) -> ClientConfigRevision | None:
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return await _get_revision(
        session,
        model=ClientConfigRevision,
        owner_id_attr="client_id",
        owner_id=client.id,
        revision_id=revision_id,
    )


async def list_client_revisions(
    session: AsyncSession, client_id: str
) -> list[ClientConfigRevision]:
    client = await session.get(Client, client_id)
    if client is None:
        return []
    return await _list_revisions(
        session, model=ClientConfigRevision, owner_id_attr="client_id", owner_id=client.id
    )


async def activate_client_revision(
    session: AsyncSession, client_id: str, revision_id: str
) -> Client | None:
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return await _activate_revision(
        session,
        model=ClientConfigRevision,
        owner=client,
        owner_id_attr="client_id",
        active_pointer_attr="active_config_revision_id",
        revision_id=revision_id,
    )


async def rollback_client_revision(
    session: AsyncSession,
    client_id: str,
    target_revision_id: str,
    created_by: str,
) -> ClientConfigRevision | None:
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return await _rollback_to_revision(
        session,
        model=ClientConfigRevision,
        owner=client,
        owner_id_attr="client_id",
        active_pointer_attr="active_config_revision_id",
        target_revision_id=target_revision_id,
        config_cls=ClientConfigV1,
        serializer=_serialize_client_config,
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# Analysis-profile-level public functions (design.md P5-D2) — same generic
# helpers, scoped by client_id only. config stores a FULL
# AnalysisProfileConfigV1 snapshot (products + need_tags), not a sparse
# override set — mirrors AgentConfigRevision's full-snapshot serializer
# rather than ClientConfigV1's sparse one.
# ---------------------------------------------------------------------------

_ANALYSIS_PROFILE_TEMPLATES = {
    "insurance": insurance_profile_template,
    "generic": generic_profile_template,
}


def _serialize_analysis_profile_config(config: AnalysisProfileConfigV1) -> tuple[str, str]:
    return config.model_dump_json(), str(config.schema_version)


async def get_active_analysis_profile_revision(
    session: AsyncSession, client_id: str
) -> ClientAnalysisProfileRevision | None:
    client = await session.get(Client, client_id)
    if client is None or client.active_analysis_profile_revision_id is None:
        return None
    return await session.get(
        ClientAnalysisProfileRevision, client.active_analysis_profile_revision_id
    )


async def resolve_client_catalog(
    session: AsyncSession, client_id: str
) -> AnalysisProfileConfigV1:
    """Loads the client's active analysis profile revision; returns its
    config. Every client has revision 1 seeded by migration 0023 (or by
    create_client for a new client), so this never returns an unset result
    for an existing client — a missing Client row, or a client with no
    active revision for any other reason, falls back to the empty generic
    config rather than raising.
    """
    revision = await get_active_analysis_profile_revision(session, client_id)
    if revision is None:
        return generic_profile_template.config
    return AnalysisProfileConfigV1.model_validate_json(revision.config)


async def create_analysis_profile_revision(
    session: AsyncSession,
    *,
    client: Client,
    config: AnalysisProfileConfigV1,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> ClientAnalysisProfileRevision:
    config_json, schema_version = _serialize_analysis_profile_config(config)
    return await _create_revision(
        session,
        model=ClientAnalysisProfileRevision,
        owner=client,
        owner_id_attr="client_id",
        active_pointer_attr="active_analysis_profile_revision_id",
        config=config_json,
        schema_version=schema_version,
        source=source,
        created_by=created_by,
        note=note,
    )


async def get_analysis_profile_revision(
    session: AsyncSession, client_id: str, revision_id: str
) -> ClientAnalysisProfileRevision | None:
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return await _get_revision(
        session,
        model=ClientAnalysisProfileRevision,
        owner_id_attr="client_id",
        owner_id=client.id,
        revision_id=revision_id,
    )


async def list_analysis_profile_revisions(
    session: AsyncSession, client_id: str
) -> list[ClientAnalysisProfileRevision]:
    client = await session.get(Client, client_id)
    if client is None:
        return []
    return await _list_revisions(
        session,
        model=ClientAnalysisProfileRevision,
        owner_id_attr="client_id",
        owner_id=client.id,
    )


async def rollback_analysis_profile_revision(
    session: AsyncSession,
    *,
    client_id: str,
    target_revision_id: str,
    created_by: str,
) -> ClientAnalysisProfileRevision | None:
    """Copy target_revision_id's config into a NEW revision (source=
    "rollback"), then activate it. Never mutates or reactivates the old row.
    Returns None when the client or the target revision (scoped to this
    client) does not exist.
    """
    client = await session.get(Client, client_id)
    if client is None:
        return None
    return await _rollback_to_revision(
        session,
        model=ClientAnalysisProfileRevision,
        owner=client,
        owner_id_attr="client_id",
        active_pointer_attr="active_analysis_profile_revision_id",
        target_revision_id=target_revision_id,
        config_cls=AnalysisProfileConfigV1,
        serializer=_serialize_analysis_profile_config,
        created_by=created_by,
    )


async def apply_analysis_profile_template(
    session: AsyncSession,
    *,
    client: Client,
    vertical: Literal["insurance", "generic"],
    created_by: str,
) -> ClientAnalysisProfileRevision:
    template = _ANALYSIS_PROFILE_TEMPLATES[vertical]
    return await create_analysis_profile_revision(
        session,
        client=client,
        config=template.config,
        source="api",
        created_by=created_by,
        note=f"applied template: {vertical}",
    )
