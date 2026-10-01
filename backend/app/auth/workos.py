"""QORA Auth — thin async wrapper around the WorkOS API.

Design: openspec/changes/multi-tenant-auth/design.md §7, §8.

Every call goes through ``httpx.AsyncClient`` against ``https://api.workos.com``
with a 10 second timeout and ``Authorization: Bearer <api key>``. Tests mock
this module's HTTP calls with respx — no real network call is ever made in
tests. Tokens, authorization codes and the API key are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings

WORKOS_BASE_URL = "https://api.workos.com"
_TIMEOUT_SECONDS = 10.0


class WorkosError(Exception):
    """Raised when a WorkOS API call fails (network error or non-2xx response)."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class WorkosUser:
    id: str
    email: str
    email_verified: bool
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class AuthenticateResult:
    user: WorkosUser
    organization_id: str | None
    session_id: str | None = None


@dataclass(frozen=True)
class WorkosOrganization:
    id: str
    name: str
    external_id: str | None = None


@dataclass(frozen=True)
class WorkosInvitation:
    id: str
    email: str
    state: str
    expires_at: str
    organization_id: str | None = None


@dataclass(frozen=True)
class WorkosMember:
    user_id: str
    email: str
    name: str | None = None


def build_authorize_url(settings: Settings, *, state: str) -> str:
    """Build the AuthKit hosted-login authorize URL (design §7)."""
    params = {
        "response_type": "code",
        "provider": "authkit",
        "client_id": settings.workos_client_id,
        "redirect_uri": settings.qora_auth_redirect_uri,
        "state": state,
    }
    return f"{WORKOS_BASE_URL}/user_management/authorize?{urlencode(params)}"


def build_logout_url(workos_session_id: str) -> str:
    """Build the WorkOS-hosted logout URL for a known WorkOS session id."""
    params = {"session_id": workos_session_id}
    return f"{WORKOS_BASE_URL}/user_management/sessions/logout?{urlencode(params)}"


class WorkosClient:
    """Async WorkOS API client. One instance is created per request."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        api_key = self._settings.workos_api_key
        return {"Authorization": f"Bearer {api_key.get_secret_value() if api_key else ''}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(base_url=WORKOS_BASE_URL, timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise WorkosError(f"WorkOS request failed: {type(exc).__name__}") from exc

        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            code = None
            try:
                body = resp.json()
                code = body.get("code") or body.get("error")
            except Exception:
                pass
            raise WorkosError(
                f"WorkOS API returned {resp.status_code}",
                status_code=resp.status_code,
                code=code,
            )
        if not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------------
    # user_management: authenticate
    # ------------------------------------------------------------------

    async def authenticate_with_code(self, code: str) -> AuthenticateResult:
        api_key = self._settings.workos_api_key
        body = await self._request(
            "POST",
            "/user_management/authenticate",
            json_body={
                "client_id": self._settings.workos_client_id,
                "client_secret": api_key.get_secret_value() if api_key else "",
                "grant_type": "authorization_code",
                "code": code,
            },
        )
        assert body is not None
        user_body = body["user"]
        user = WorkosUser(
            id=user_body["id"],
            email=user_body["email"],
            email_verified=bool(user_body.get("email_verified", False)),
            first_name=user_body.get("first_name"),
            last_name=user_body.get("last_name"),
        )
        session_id = _extract_session_id(body.get("access_token"))
        return AuthenticateResult(
            user=user,
            organization_id=body.get("organization_id"),
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # user_management: organizations
    # ------------------------------------------------------------------

    async def get_organization_by_external_id(self, external_id: str) -> WorkosOrganization | None:
        try:
            body = await self._request("GET", f"/organizations/external_id/{external_id}")
        except WorkosError as exc:
            if exc.status_code == 404:
                return None
            raise
        assert body is not None
        return WorkosOrganization(id=body["id"], name=body["name"], external_id=body.get("external_id"))

    async def create_organization(self, *, name: str, external_id: str) -> WorkosOrganization:
        body = await self._request(
            "POST", "/organizations", json_body={"name": name, "external_id": external_id}
        )
        assert body is not None
        return WorkosOrganization(id=body["id"], name=body["name"], external_id=body.get("external_id"))

    # ------------------------------------------------------------------
    # user_management: users / invitations
    # ------------------------------------------------------------------

    async def list_organization_members(self, organization_id: str) -> list[WorkosMember]:
        body = await self._request(
            "GET",
            "/user_management/users",
            params={"organization_id": organization_id, "limit": 100},
        )
        assert body is not None
        members: list[WorkosMember] = []
        for row in body.get("data", []):
            first = row.get("first_name") or ""
            last = row.get("last_name") or ""
            full_name = f"{first} {last}".strip() or None
            members.append(WorkosMember(user_id=row["id"], email=row["email"], name=full_name))
        return members

    async def list_organization_invitations(self, organization_id: str) -> list[WorkosInvitation]:
        body = await self._request(
            "GET",
            "/user_management/invitations",
            params={"organization_id": organization_id, "limit": 100},
        )
        assert body is not None
        return [
            WorkosInvitation(
                id=row["id"],
                email=row["email"],
                state=row["state"],
                expires_at=row["expires_at"],
                organization_id=row.get("organization_id"),
            )
            for row in body.get("data", [])
        ]

    async def create_invitation(self, *, email: str, organization_id: str) -> WorkosInvitation:
        body = await self._request(
            "POST",
            "/user_management/invitations",
            json_body={"email": email, "organization_id": organization_id},
        )
        assert body is not None
        return WorkosInvitation(
            id=body["id"],
            email=body["email"],
            state=body["state"],
            expires_at=body["expires_at"],
            organization_id=body.get("organization_id"),
        )

    async def get_invitation(self, invitation_id: str) -> WorkosInvitation | None:
        try:
            body = await self._request("GET", f"/user_management/invitations/{invitation_id}")
        except WorkosError as exc:
            if exc.status_code == 404:
                return None
            raise
        assert body is not None
        return WorkosInvitation(
            id=body["id"],
            email=body["email"],
            state=body["state"],
            expires_at=body["expires_at"],
            organization_id=body.get("organization_id"),
        )

    async def revoke_invitation(self, invitation_id: str) -> None:
        await self._request("POST", f"/user_management/invitations/{invitation_id}/revoke")


def _extract_session_id(access_token: str | None) -> str | None:
    """Read the ``sid`` claim of the access token without verifying its signature.

    Safe because the token came straight from the WorkOS API over TLS in the
    same request/response cycle — it is never accepted from client input.
    """
    if not access_token:
        return None
    try:
        import base64
        import json

        parts = access_token.split(".")
        if len(parts) != 3:
            return None
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        sid = payload.get("sid")
        return str(sid) if sid else None
    except Exception:
        return None
