"""FastAPI dependencies that enforce plan entitlements on HTTP routes.

Design: openspec/changes/multi-tenant-readiness/design.md §3 "Enforcement"
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException

from app.core.access import require_client_access
from app.core.auth import CallerIdentity
from app.entitlements.catalog import FEATURES
from app.entitlements.service import Entitlements, resolve_entitlements


async def _load_entitlements(client_id: str) -> Entitlements | None:
    from app.core.database import get_session
    from app.tenants.service import get_client

    async with get_session() as db:
        client = await get_client(db, client_id.lower())
    return resolve_entitlements(client) if client is not None else None


def require_feature(feature: str) -> Callable[..., CallerIdentity]:
    """Dependency factory: 403 ``feature_not_in_plan`` unless the client's plan includes ``feature``.

    Runs after the tenant check, so a foreign tenant still gets
    ``tenant_forbidden`` and never learns anything about that tenant's plan.
    An unknown client passes through so the route keeps its own 404.
    """
    if feature not in FEATURES:
        raise ValueError(f"Unknown feature: {feature!r}")

    async def _dependency(
        client_id: str,
        caller: CallerIdentity = Depends(require_client_access),
    ) -> CallerIdentity:
        entitlements = await _load_entitlements(client_id)
        if entitlements is not None and not entitlements.has_feature(feature):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_not_in_plan",
                    "feature": feature,
                    "message": f"Your plan does not include '{feature}'.",
                },
            )
        return caller

    return _dependency
