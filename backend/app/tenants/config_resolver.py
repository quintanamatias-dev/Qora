"""QORA config resolver (design.md D13).

resolve_effective_config is pure: no database access, no I/O, no network
calls. It is the single resolution path shared by the runtime context
builder, the ElevenLabs projection sync, and the admin effective-config API
(design.md's Data Flow diagram) — no consumer computes resolution itself.

A None value in an override dict means "not set, inherit" (D12): it is
treated identically to the field being absent from the dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.tenants.config_standard import _AgentConfigStandard
from app.tenants.field_policy import FIELD_POLICY

FieldProvenance = Literal["standard", "client", "agent"]


@dataclass(frozen=True)
class EffectiveField:
    value: Any
    provenance: FieldProvenance


@dataclass(frozen=True)
class EffectiveConfig:
    fields: dict[str, EffectiveField]
    missing_required: list[str]


def _is_set(overrides: dict[str, Any], field_name: str) -> bool:
    return field_name in overrides and overrides[field_name] is not None


def resolve_effective_config(
    standard: _AgentConfigStandard,
    client_overrides: dict[str, Any],
    agent_overrides: dict[str, Any],
) -> EffectiveConfig:
    fields: dict[str, EffectiveField] = {}
    missing_required: list[str] = []

    for field_name, policy in FIELD_POLICY.items():
        if policy == "locked":
            fields[field_name] = EffectiveField(
                value=getattr(standard, field_name), provenance="standard"
            )
        elif policy == "agent_required":
            if _is_set(agent_overrides, field_name):
                fields[field_name] = EffectiveField(
                    value=agent_overrides[field_name], provenance="agent"
                )
            else:
                fields[field_name] = EffectiveField(value=None, provenance="agent")
                missing_required.append(field_name)
        elif policy == "client_only":
            if _is_set(client_overrides, field_name):
                fields[field_name] = EffectiveField(
                    value=client_overrides[field_name], provenance="client"
                )
            else:
                fields[field_name] = EffectiveField(
                    value=getattr(standard, field_name), provenance="standard"
                )
        elif policy == "overridable":
            if _is_set(agent_overrides, field_name):
                fields[field_name] = EffectiveField(
                    value=agent_overrides[field_name], provenance="agent"
                )
            elif _is_set(client_overrides, field_name):
                fields[field_name] = EffectiveField(
                    value=client_overrides[field_name], provenance="client"
                )
            else:
                fields[field_name] = EffectiveField(
                    value=getattr(standard, field_name), provenance="standard"
                )

    return EffectiveConfig(fields=fields, missing_required=missing_required)
