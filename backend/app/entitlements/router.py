"""QORA Entitlements API — plan, effective features/limits and usage per client.

Endpoints:
    GET /api/v1/clients/{client_id}/entitlements  — any principal with access to the client
    PUT /api/v1/clients/{client_id}/entitlements  — superadmin only
    GET /api/v1/entitlements/plans                — superadmin only (plan catalog for the admin editor)

Design: openspec/changes/multi-tenant-readiness/design.md §3 "API"
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.access import require_client_access, require_superadmin
from app.core.database import get_session
from app.entitlements.catalog import FEATURES, LIMITS, PLANS
from app.entitlements.service import (
    InvalidOverridesError,
    get_usage,
    resolve_entitlements,
    validate_overrides,
)

router = APIRouter(tags=["entitlements"])


class UsageResponse(BaseModel):
    period_start: datetime
    monthly_calls: int
    monthly_minutes: int
    concurrent_calls: int
    active_agents: int


class EntitlementsResponse(BaseModel):
    client_id: str
    plan: str
    features: dict[str, bool]
    limits: dict[str, int | None]
    usage: UsageResponse
    overrides: dict[str, Any]


class EntitlementsUpdate(BaseModel):
    plan: str
    overrides: dict[str, Any] = Field(default_factory=dict)


class PlanResponse(BaseModel):
    name: str
    label: str
    features: dict[str, bool]
    limits: dict[str, int | None]


class PlanCatalogResponse(BaseModel):
    features: list[str]
    limits: list[str]
    plans: list[PlanResponse]


async def _entitlements_response(db, client) -> EntitlementsResponse:
    ent = resolve_entitlements(client)
    usage = await get_usage(db, client)
    return EntitlementsResponse(
        client_id=client.id,
        plan=ent.plan,
        features=ent.features,
        limits=ent.limits,
        usage=UsageResponse(**usage.__dict__),
        overrides=ent.overrides,
    )


async def _get_client_or_404(db, client_id: str):
    from app.tenants.service import get_client

    client = await get_client(db, client_id.lower())
    if client is None:
        raise HTTPException(status_code=404, detail={"error": "client not found", "client_id": client_id})
    return client


@router.get(
    "/clients/{client_id}/entitlements",
    response_model=EntitlementsResponse,
    dependencies=[Depends(require_client_access)],
)
async def get_entitlements(client_id: str) -> EntitlementsResponse:
    async with get_session() as db:
        client = await _get_client_or_404(db, client_id)
        return await _entitlements_response(db, client)


@router.put(
    "/clients/{client_id}/entitlements",
    response_model=EntitlementsResponse,
    dependencies=[Depends(require_superadmin)],
)
async def update_entitlements(client_id: str, payload: EntitlementsUpdate) -> EntitlementsResponse:
    if payload.plan not in PLANS:
        raise HTTPException(
            status_code=422,
            detail={"error": "unknown_plan", "message": f"Unknown plan {payload.plan!r}. Valid: {list(PLANS)}"},
        )
    try:
        overrides = validate_overrides(payload.overrides)
    except InvalidOverridesError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_overrides", "message": str(exc)}) from None

    async with get_session() as db:
        client = await _get_client_or_404(db, client_id)
        client.plan = payload.plan
        client.entitlement_overrides = json.dumps(overrides) if overrides else None
        await db.commit()
        await db.refresh(client)
        return await _entitlements_response(db, client)


@router.get(
    "/entitlements/plans",
    response_model=PlanCatalogResponse,
    dependencies=[Depends(require_superadmin)],
)
async def list_plans() -> PlanCatalogResponse:
    return PlanCatalogResponse(
        features=list(FEATURES),
        limits=list(LIMITS),
        plans=[
            PlanResponse(name=p.name, label=p.label, features=dict(p.features), limits=dict(p.limits))
            for p in PLANS.values()
        ],
    )
