"""QORA plan catalog — the single reviewed source of plan features and limits.

Plans live in code because they are product decisions that deserve review.
Per-client exceptions live in ``clients.entitlement_overrides`` (operational
data, no deploy needed).

Source: docs/pricing.md §4 "Plan structure". Only the subset Qora can enforce
today is modelled.

Design: openspec/changes/multi-tenant-readiness/design.md §3
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

#: Boolean product capabilities, gated per client.
FEATURES: tuple[str, ...] = (
    "outbound_calls",  # manual "Call now"
    "auto_dialer",  # unattended dialing of scheduled calls
    "crm_integration",  # CRM import/runtime capability implemented here
    "analytics",  # analytics dashboard
    "live_monitor",  # live calls panel
)

#: Numeric usage caps. ``None`` means unlimited.
LIMITS: tuple[str, ...] = (
    "max_agents",  # active agents
    "max_concurrent_calls",  # calls in flight at the same time
    "max_monthly_calls",  # calls started this calendar month
    "max_monthly_minutes",  # call minutes this calendar month
)


@dataclass(frozen=True)
class Plan:
    name: str
    label: str
    features: Mapping[str, bool]
    limits: Mapping[str, int | None]


def _plan(name: str, label: str, *, features: dict[str, bool], limits: dict[str, int | None]) -> Plan:
    return Plan(
        name=name,
        label=label,
        features=MappingProxyType(dict(features)),
        limits=MappingProxyType(dict(limits)),
    )


_ALL_FEATURES = {f: True for f in FEATURES}
_NO_LIMITS: dict[str, int | None] = {limit: None for limit in LIMITS}

PLANS: Mapping[str, Plan] = MappingProxyType(
    {
        # Pilot / internal clients: everything on, no caps. Default for existing
        # and newly created clients so nothing changes until a plan is assigned.
        "pilot": _plan("pilot", "Pilot", features=_ALL_FEATURES, limits=_NO_LIMITS),
        "starter": _plan(
            "starter",
            "Starter",
            features={
                "outbound_calls": True,
                "auto_dialer": False,
                "crm_integration": False,
                "analytics": True,
                "live_monitor": False,
            },
            limits={
                "max_agents": 1,
                "max_concurrent_calls": 1,
                "max_monthly_calls": None,
                "max_monthly_minutes": 200,
            },
        ),
        "pro": _plan(
            "pro",
            "Pro",
            features=_ALL_FEATURES,
            limits={
                "max_agents": 3,
                "max_concurrent_calls": 3,
                "max_monthly_calls": None,
                "max_monthly_minutes": 1000,
            },
        ),
        "business": _plan(
            "business",
            "Business",
            features=_ALL_FEATURES,
            limits={
                "max_agents": 10,
                "max_concurrent_calls": 10,
                "max_monthly_calls": None,
                "max_monthly_minutes": 5000,
            },
        ),
    }
)

#: Plan assigned when a client has none.
DEFAULT_PLAN = "pilot"

#: Plan used when the stored plan name is unknown (manual DB edit, removed
#: plan). Fail closed to the most restrictive paid plan, never to ``pilot``.
FALLBACK_PLAN = "starter"
