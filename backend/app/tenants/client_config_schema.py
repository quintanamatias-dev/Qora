"""QORA Client Config — sparse client-level override schema (design.md D11, I3).

ClientConfigV1 is the validated shape stored as JSON inside every
client_config_revisions.config row. It is sparse by construction: only
fields whose FIELD_POLICY is "overridable" or "client_only" are allowed, and
every allowed field defaults to None (not set, inherit — design.md D12's
"a None value means inherit" convention, shared with agent overrides).

The allowed field set is DERIVED from FIELD_POLICY, never hand-listed: a
future field-policy change (e.g. a field moving from "overridable" to
"locked") automatically narrows what a client payload may contain, with no
edit required here. Writing a `locked` or `agent_required` field is rejected
by Pydantic's extra="forbid" as an "Extra inputs are not permitted" error
per offending field — the same mechanism that rejects any truly unregistered
field name.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import ConfigDict, create_model

from app.tenants.agent_config_schema import AgentConfigV1
from app.tenants.field_policy import FIELD_POLICY

_ALLOWED_POLICIES = {"overridable", "client_only"}

ALLOWED_CLIENT_CONFIG_FIELDS: frozenset[str] = frozenset(
    name for name, policy in FIELD_POLICY.items() if policy in _ALLOWED_POLICIES
)


def _sparse_field_definitions() -> dict[str, tuple[Any, None]]:
    """Build create_model field definitions for every allowed field, reusing
    AgentConfigV1's annotation + constraints (ge/le, etc.) but making every
    field Optional with a None default (sparse override semantics).
    """
    definitions: dict[str, tuple[Any, None]] = {}
    for name, info in AgentConfigV1.model_fields.items():
        if name not in ALLOWED_CLIENT_CONFIG_FIELDS:
            continue
        annotation = info.annotation
        is_already_optional = annotation is type(None) or (
            hasattr(annotation, "__args__") and type(None) in annotation.__args__
        )
        optional_annotation = annotation if is_already_optional else Optional[annotation]
        if info.metadata:
            optional_annotation = Annotated[tuple([optional_annotation, *info.metadata])]
        definitions[name] = (optional_annotation, None)
    return definitions


ClientConfigV1 = create_model(
    "ClientConfigV1",
    __config__=ConfigDict(extra="forbid"),
    schema_version=(Literal["v1"], "v1"),
    **_sparse_field_definitions(),
)


ClientConfigPatch = create_model(
    "ClientConfigPatch",
    __config__=ConfigDict(extra="forbid"),
    note=(Optional[str], None),
    **_sparse_field_definitions(),
)
