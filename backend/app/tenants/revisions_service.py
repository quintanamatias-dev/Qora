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

from app.tenants.agent_config_schema import AgentConfigV1
from app.tenants.client_config_schema import ClientConfigV1
from app.tenants.models import (
    Agent,
    AgentConfigRevision,
    Client,
    ClientConfigRevision,
)

RevisionSource = Literal["import", "api", "rollback"]

Serializer = Callable[[BaseModel], tuple[str, str]]


def _serialize_agent_config(config: AgentConfigV1) -> tuple[str, str]:
    return config.model_dump_json(), config.schema_version


def _serialize_client_config(config: ClientConfigV1) -> tuple[str, str]:
    sparse = config.model_dump(exclude_none=True)
    return json.dumps(sparse), config.schema_version


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
    config_json: str,
    schema_version: str,
    source: RevisionSource,
    created_by: str,
    note: str | None = None,
) -> Any:
    """Insert-only revision creation + activation.

    revision_number = max(existing for owner.id) + 1, starting at 1. Single
    pointer swap on owner.<active_pointer_attr> — no other revision row is
    touched.
    """
    owner_id = owner.id
    next_number = await _next_revision_number(session, model, owner_id_attr, owner_id)

    revision = model(
        id=str(uuid.uuid4()),
        revision_number=next_number,
        config=config_json,
        schema_version=schema_version,
        source=source,
        created_by=created_by,
        note=note,
        **{owner_id_attr: owner_id},
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
        config_json=config_json,
        schema_version=schema_version,
        source="rollback",
        created_by=created_by,
        note=f"rollback to revision {target.revision_number}",
    )


# ---------------------------------------------------------------------------
# Agent-level public functions (unchanged signatures — 1a's call sites and
# tests keep working exactly as before).
# ---------------------------------------------------------------------------


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
        config_json=config_json,
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
    return await _rollback_to_revision(
        session,
        model=AgentConfigRevision,
        owner=agent,
        owner_id_attr="agent_id",
        active_pointer_attr="active_revision_id",
        target_revision_id=target_revision_id,
        config_cls=AgentConfigV1,
        serializer=_serialize_agent_config,
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
        config_json=config_json,
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
