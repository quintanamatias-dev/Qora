"""QORA Auth — /api/v1/auth router: config, login, callback, me, logout.

Design: openspec/changes/multi-tenant-auth/design.md §7.
"""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.auth.sessions import (
    NoAccessError,
    create_session,
    generate_state,
    hash_token,
    map_identity,
    revoke_session,
    sanitize_return_to,
)
from app.auth.workos import WorkosClient, WorkosError, build_authorize_url, build_logout_url
from app.core.auth import SESSION_COOKIE_NAME, CallerIdentity, require_api_key
from app.core.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_COOKIE_NAME = "qora_auth_state"
RETURN_COOKIE_NAME = "qora_auth_return"
_STATE_COOKIE_MAX_AGE = 600
_STATE_COOKIE_PATH = "/api/v1/auth"


def _get_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or Settings()


async def _get_db():
    from app.core import database as db_module

    if db_module.async_session_factory is None:
        yield None
        return
    async with db_module.get_session() as session:
        yield session


class LoginError(Exception):
    def __init__(self, code: str):
        self.code = code


def _login_redirect(request: Request, error_code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?error={error_code}", status_code=302)


class ConfigResponse(BaseModel):
    login_enabled: bool


@router.get("/config", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(_get_settings)) -> ConfigResponse:
    return ConfigResponse(login_enabled=settings.login_enabled)


@router.get("/login")
async def login(request: Request, return_to: str | None = None, settings: Settings = Depends(_get_settings)):
    if not settings.login_enabled:
        return _login_redirect(request, "auth_not_configured")

    state = generate_state()
    sanitized_return_to = sanitize_return_to(return_to)
    authorize_url = build_authorize_url(settings, state=state)

    response = RedirectResponse(url=authorize_url, status_code=302)
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        httponly=True,
        samesite="lax",
        path=_STATE_COOKIE_PATH,
        max_age=_STATE_COOKIE_MAX_AGE,
        secure=settings.auth_cookie_secure,
    )
    response.set_cookie(
        RETURN_COOKIE_NAME,
        sanitized_return_to,
        httponly=True,
        samesite="lax",
        path=_STATE_COOKIE_PATH,
        max_age=_STATE_COOKIE_MAX_AGE,
        secure=settings.auth_cookie_secure,
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(_get_settings),
    db=Depends(_get_db),
):
    def _clear_state_cookies(response: RedirectResponse) -> RedirectResponse:
        response.delete_cookie(STATE_COOKIE_NAME, path=_STATE_COOKIE_PATH)
        response.delete_cookie(RETURN_COOKIE_NAME, path=_STATE_COOKIE_PATH)
        return response

    # Validate state before honoring any outcome, including `error`. A mismatched
    # or missing state does not belong to this attempt — it may be a stale replay
    # or a forged callback. Do not clear the pending cookies: doing so would let
    # an attacker cancel a user's in-progress login.
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _login_redirect(request, "invalid_state")

    if error is not None:
        return _clear_state_cookies(_login_redirect(request, "login_failed"))

    if not code:
        return _clear_state_cookies(_login_redirect(request, "login_failed"))

    client = WorkosClient(settings)
    try:
        result = await client.authenticate_with_code(code)
    except WorkosError as exc:
        if exc.code == "organization_selection_required":
            return _clear_state_cookies(_login_redirect(request, "organization_selection_required"))
        return _clear_state_cookies(_login_redirect(request, "login_failed"))

    try:
        identity = await map_identity(db, settings, user=result.user, organization_id=result.organization_id)
    except NoAccessError:
        return _clear_state_cookies(_login_redirect(request, "no_access"))

    raw_token = await create_session(
        db, settings, user=result.user, identity=identity, workos_session_id=result.session_id
    )

    return_to = sanitize_return_to(request.cookies.get(RETURN_COOKIE_NAME))
    response = _clear_state_cookies(RedirectResponse(url=return_to, status_code=302))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=settings.qora_auth_session_ttl_hours * 3600,
        secure=settings.auth_cookie_secure,
    )
    return response


class MeResponse(BaseModel):
    auth_method: str
    role: str
    email: str | None
    name: str | None
    client_ids: list[str]


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    caller: CallerIdentity = Depends(require_api_key),
    settings: Settings = Depends(_get_settings),
    db=Depends(_get_db),
) -> MeResponse:
    name = None
    if caller.auth_method == "session":
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token and db is not None:
            from app.auth.sessions import lookup_session

            session_row = await lookup_session(db, session_token, settings)
            if session_row is not None:
                name = session_row.display_name

    return MeResponse(
        auth_method=caller.auth_method,
        role=caller.role,
        email=caller.email,
        name=name,
        client_ids=sorted(caller.client_ids),
    )


@router.post("/logout")
async def logout(request: Request, settings: Settings = Depends(_get_settings), db=Depends(_get_db)):
    if request.headers.get("X-Qora-Client") != "web":
        return JSONResponse(
            status_code=403,
            content={"error": "csrf_check_failed", "message": "Missing X-Qora-Client header"},
        )

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    logout_url: str | None = None
    if session_token and db is not None:
        session_row = await revoke_session(db, session_token)
        if session_row is not None and session_row.workos_session_id:
            logout_url = build_logout_url(session_row.workos_session_id)

    response = JSONResponse(content={"logout_url": logout_url})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
