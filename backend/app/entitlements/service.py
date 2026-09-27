"""QORA entitlements — resolve what a client may use and how much it has used.

Effective entitlements = plan defaults (catalog) ⊕ per-client overrides.

Design: openspec/changes/multi-tenant-readiness/design.md §3
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entitlements.catalog import DEFAULT_PLAN, FALLBACK_PLAN, FEATURES, LIMITS, PLANS

logger = structlog.get_logger(__name__)


class InvalidOverridesError(ValueError):
    """Raised when entitlement overrides reference unknown keys or bad values."""


@dataclass(frozen=True)
class Entitlements:
    plan: str
    features: dict[str, bool]
    limits: dict[str, int | None]
    overrides: dict[str, Any] = field(default_factory=dict)

    def has_feature(self, feature: str) -> bool:
        return bool(self.features.get(feature, False))

    def limit(self, name: str) -> int | None:
        return self.limits.get(name)


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def validate_overrides(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a normalised overrides dict or raise InvalidOverridesError.

    Shape: ``{"features": {name: bool}, "limits": {name: int >= 0 | None}}``.
    Empty sections are dropped so "no overrides" is always ``{}``.
    """
    if not raw:
        return {}
    unknown_sections = set(raw) - {"features", "limits"}
    if unknown_sections:
        raise InvalidOverridesError(f"Unknown override sections: {sorted(unknown_sections)}")

    clean: dict[str, Any] = {}

    features = raw.get("features") or {}
    for name, value in features.items():
        if name not in FEATURES:
            raise InvalidOverridesError(f"Unknown feature: {name!r}")
        if not isinstance(value, bool):
            raise InvalidOverridesError(f"Feature {name!r} must be true or false")
    if features:
        clean["features"] = dict(features)

    limits = raw.get("limits") or {}
    for name, value in limits.items():
        if name not in LIMITS:
            raise InvalidOverridesError(f"Unknown limit: {name!r}")
        # bool is a subclass of int — reject it explicitly.
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise InvalidOverridesError(f"Limit {name!r} must be a non-negative integer or null")
    if limits:
        clean["limits"] = dict(limits)

    return clean


def _stored_overrides(client: Any) -> dict[str, Any]:
    raw = getattr(client, "entitlement_overrides", None)
    if not raw or not isinstance(raw, str):
        return {}
    try:
        return validate_overrides(json.loads(raw))
    except (json.JSONDecodeError, TypeError, InvalidOverridesError):
        # A corrupt row must not take the tenant down; plan defaults still apply.
        logger.warning("entitlements_invalid_overrides_ignored", client_id=getattr(client, "id", None))
        return {}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_entitlements(client: Any) -> Entitlements:
    """Merge the client's plan defaults with its overrides."""
    plan_name = getattr(client, "plan", None)
    if not isinstance(plan_name, str) or not plan_name:
        # No stored plan (column is NOT NULL in the DB, so only in-memory
        # stand-ins reach this) — same as a freshly created client.
        plan_name = DEFAULT_PLAN
    plan = PLANS.get(plan_name)
    if plan is None:
        logger.warning(
            "entitlements_unknown_plan",
            client_id=getattr(client, "id", None),
            plan=plan_name,
            fallback=FALLBACK_PLAN,
        )
        plan = PLANS[FALLBACK_PLAN]

    overrides = _stored_overrides(client)
    features = {**plan.features, **overrides.get("features", {})}
    limits = {**plan.limits, **overrides.get("limits", {})}
    return Entitlements(plan=plan.name, features=features, limits=limits, overrides=overrides)


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    period_start: datetime
    monthly_calls: int
    monthly_minutes: int
    concurrent_calls: int
    active_agents: int


def month_start_utc(tz_name: str | None, now: datetime | None = None) -> datetime:
    """First instant of the current calendar month in the client's timezone, as UTC."""
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    local_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc)


async def get_usage(db: AsyncSession, client: Any, *, now: datetime | None = None) -> Usage:
    """Current-month usage for a client.

    A call counts once it reached the provider (telephony_status set) or
    produced audio (duration > 0). Browser connection attempts that never
    became a call are excluded, matching the ghost filter in GET /calls.
    """
    from app.calls.live import count_active_calls
    from app.calls.models import CallSession
    from app.tenants.models import Agent

    start = month_start_utc(getattr(client, "scheduler_timezone", None), now)
    real_call = or_(CallSession.telephony_status.is_not(None), CallSession.duration_seconds > 0)

    calls_row = (
        await db.execute(
            select(
                func.count(CallSession.id),
                func.coalesce(func.sum(CallSession.duration_seconds), 0.0),
            ).where(
                CallSession.client_id == client.id,
                CallSession.started_at >= start,
                real_call,
            )
        )
    ).one()
    active_agents = (
        await db.execute(
            select(func.count(Agent.id)).where(
                Agent.client_id == client.id,
                Agent.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one()

    return Usage(
        period_start=start,
        monthly_calls=int(calls_row[0] or 0),
        monthly_minutes=math.ceil(float(calls_row[1] or 0.0) / 60),
        concurrent_calls=await count_active_calls(db, client.id),
        active_agents=int(active_agents or 0),
    )


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanBlock:
    failure_code: str  # "plan_feature_disabled" | "plan_limit_reached"
    detail: str  # feature or limit name
    error: str


async def check_dial_allowed(
    db: AsyncSession, client: Any, *, scheduled: bool, now: datetime | None = None
) -> PlanBlock | None:
    """Return a PlanBlock when the client's plan forbids this dial, else None.

    ``scheduled`` selects the gating feature: ``auto_dialer`` for dials driven
    by a ScheduledCall, ``outbound_calls`` for a manual trigger.
    """
    ent = resolve_entitlements(client)
    feature = "auto_dialer" if scheduled else "outbound_calls"
    if not ent.has_feature(feature):
        return PlanBlock(
            failure_code="plan_feature_disabled",
            detail=feature,
            error=f"The client's plan does not include '{feature}'.",
        )

    caps = {name: ent.limit(name) for name in ("max_concurrent_calls", "max_monthly_calls", "max_monthly_minutes")}
    if all(cap is None for cap in caps.values()):
        return None

    usage = await get_usage(db, client, now=now)
    used = {
        "max_concurrent_calls": usage.concurrent_calls,
        "max_monthly_calls": usage.monthly_calls,
        "max_monthly_minutes": usage.monthly_minutes,
    }
    for name, cap in caps.items():
        if cap is not None and used[name] >= cap:
            return _limit_block(name, used[name], cap)
    return None


async def check_agent_limit(db: AsyncSession, client: Any) -> PlanBlock | None:
    """Return a PlanBlock when the client already has ``max_agents`` active agents."""
    from app.tenants.models import Agent

    cap = resolve_entitlements(client).limit("max_agents")
    if cap is None:
        return None
    active = (
        await db.execute(
            select(func.count(Agent.id)).where(
                Agent.client_id == client.id,
                Agent.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one()
    return _limit_block("max_agents", active, cap) if active >= cap else None


def _limit_block(name: str, used: int, cap: int) -> PlanBlock:
    return PlanBlock(
        failure_code="plan_limit_reached",
        detail=name,
        error=f"Plan limit reached: {name} ({used}/{cap}).",
    )
