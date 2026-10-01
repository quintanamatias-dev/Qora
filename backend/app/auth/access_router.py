"""QORA Auth — superadmin access API: /api/v1/clients/{client_id}/access.

Design: openspec/changes/multi-tenant-auth/design.md §8.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.access import require_superadmin
from app.core.config import Settings
from app.auth.workos import WorkosClient, WorkosError

router = APIRouter(tags=["auth-access"])


def _get_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or Settings()


async def _get_db():
    from app.core import database as db_module

    if db_module.async_session_factory is None:
        yield None
        return
    async with db_module.get_session() as session:
        yield session


class MemberResponse(BaseModel):
    user_id: str
    email: str
    name: str | None


class InvitationResponse(BaseModel):
    id: str
    email: str
    state: str
    expires_at: str


class AccessStateResponse(BaseModel):
    organization_id: str | None
    members: list[MemberResponse]
    invitations: list[InvitationResponse]


class InviteRequest(BaseModel):
    email: str


async def _get_client_or_404(db, client_id: str):
    from app.tenants.service import get_client

    client = await get_client(db, client_id.lower())
    if client is None:
        raise HTTPException(status_code=404, detail={"error": "client not found", "client_id": client_id})
    return client


def _require_login_configured(settings: Settings) -> None:
    if not settings.login_enabled:
        raise HTTPException(status_code=503, detail={"error": "auth_not_configured"})


def _workos_error_response(exc: WorkosError):
    raise HTTPException(status_code=502, detail={"error": "identity_provider_error"}) from exc


async def _build_access_state(client, ws_client: WorkosClient) -> AccessStateResponse:
    if not client.workos_organization_id:
        return AccessStateResponse(organization_id=None, members=[], invitations=[])

    try:
        members = await ws_client.list_organization_members(client.workos_organization_id)
        invitations = await ws_client.list_organization_invitations(client.workos_organization_id)
    except WorkosError as exc:
        _workos_error_response(exc)
        raise  # pragma: no cover — _workos_error_response always raises

    return AccessStateResponse(
        organization_id=client.workos_organization_id,
        members=[MemberResponse(user_id=m.user_id, email=m.email, name=m.name) for m in members],
        invitations=[
            InvitationResponse(id=i.id, email=i.email, state=i.state, expires_at=i.expires_at)
            for i in invitations
            if i.state == "pending"
        ],
    )


@router.get(
    "/clients/{client_id}/access",
    response_model=AccessStateResponse,
    dependencies=[Depends(require_superadmin)],
)
async def get_access(client_id: str, settings: Settings = Depends(_get_settings), db=Depends(_get_db)) -> AccessStateResponse:
    _require_login_configured(settings)
    client = await _get_client_or_404(db, client_id)
    return await _build_access_state(client, WorkosClient(settings))


@router.post(
    "/clients/{client_id}/access/organization",
    response_model=AccessStateResponse,
    dependencies=[Depends(require_superadmin)],
)
async def link_organization(
    client_id: str, settings: Settings = Depends(_get_settings), db=Depends(_get_db)
) -> AccessStateResponse:
    _require_login_configured(settings)
    client = await _get_client_or_404(db, client_id)
    ws_client = WorkosClient(settings)

    if not client.workos_organization_id:
        try:
            org = await ws_client.get_organization_by_external_id(client.id)
            if org is None:
                org = await ws_client.create_organization(name=client.name, external_id=client.id)
        except WorkosError as exc:
            _workos_error_response(exc)
            raise  # pragma: no cover

        client.workos_organization_id = org.id
        await db.commit()
        await db.refresh(client)

    return await _build_access_state(client, ws_client)


@router.post(
    "/clients/{client_id}/access/invitations",
    response_model=InvitationResponse,
    status_code=201,
    dependencies=[Depends(require_superadmin)],
)
async def invite_user(
    client_id: str,
    payload: InviteRequest,
    settings: Settings = Depends(_get_settings),
    db=Depends(_get_db),
) -> InvitationResponse:
    _require_login_configured(settings)
    client = await _get_client_or_404(db, client_id)
    if not client.workos_organization_id:
        raise HTTPException(status_code=409, detail={"error": "organization_not_linked"})

    ws_client = WorkosClient(settings)
    try:
        invitation = await ws_client.create_invitation(
            email=payload.email, organization_id=client.workos_organization_id
        )
    except WorkosError as exc:
        _workos_error_response(exc)
        raise  # pragma: no cover

    return InvitationResponse(
        id=invitation.id, email=invitation.email, state=invitation.state, expires_at=invitation.expires_at
    )


@router.delete(
    "/clients/{client_id}/access/invitations/{invitation_id}",
    status_code=204,
    dependencies=[Depends(require_superadmin)],
)
async def revoke_invitation(
    client_id: str,
    invitation_id: str,
    settings: Settings = Depends(_get_settings),
    db=Depends(_get_db),
):
    _require_login_configured(settings)
    client = await _get_client_or_404(db, client_id)
    if not client.workos_organization_id:
        raise HTTPException(status_code=409, detail={"error": "organization_not_linked"})
    ws_client = WorkosClient(settings)

    try:
        invitation = await ws_client.get_invitation(invitation_id)
    except WorkosError as exc:
        _workos_error_response(exc)
        raise  # pragma: no cover

    if invitation is None or invitation.organization_id != client.workos_organization_id:
        raise HTTPException(status_code=404, detail={"error": "invitation not found"})

    try:
        await ws_client.revoke_invitation(invitation_id)
    except WorkosError as exc:
        _workos_error_response(exc)
        raise  # pragma: no cover

    return None
