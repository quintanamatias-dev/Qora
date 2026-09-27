"""QORA tenant access layer — authorization on top of authentication.

``app.core.auth`` answers "who is calling?" and returns a CallerIdentity.
This module answers "may this caller touch this tenant?".

Routers depend on these helpers instead of on a credential type, so swapping
the global API key for per-user tokens (multi-tenant-auth) needs no router
changes.

Response policy (design: openspec/changes/multi-tenant-readiness/design.md §1):
  - explicit foreign ``client_id`` in path/query → 403 ``tenant_forbidden``
  - foreign resource addressed by id → 404, identical to "does not exist",
    so ids of other tenants cannot be probed
  - superadmin-only route → 403 ``superadmin_required``
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException

from app.core.auth import CallerIdentity, require_api_key


def require_client_access(
    client_id: str,
    caller: CallerIdentity = Depends(require_api_key),
) -> CallerIdentity:
    """Allow the request only if the caller may access ``client_id``.

    FastAPI resolves ``client_id`` from the path when the route declares it,
    otherwise from the query string, so one dependency covers both styles.
    """
    if not caller.can_access(client_id):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tenant_forbidden",
                "message": "You do not have access to this client.",
            },
        )
    return caller


def require_superadmin(
    caller: CallerIdentity = Depends(require_api_key),
) -> CallerIdentity:
    """Allow the request only for Qora operators."""
    if not caller.is_superadmin:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "superadmin_required",
                "message": "This action is restricted to Qora administrators.",
            },
        )
    return caller


def ensure_resource_access(
    caller: CallerIdentity,
    resource_client_id: str | None,
    *,
    detail: Any = "Not found",
) -> None:
    """Raise 404 when a resource loaded by id belongs to another tenant.

    Callers pass the same ``detail`` they use for a genuinely missing row so
    both cases are indistinguishable to the client.
    """
    if not caller.can_access(resource_client_id):
        raise HTTPException(status_code=404, detail=detail)
