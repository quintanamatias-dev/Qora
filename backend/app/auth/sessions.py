"""QORA Auth — session token lifecycle, identity mapping, return_to sanitizing.

Design: openspec/changes/multi-tenant-auth/design.md §4, §5.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession
from app.auth.workos import WorkosUser
from app.core.config import Settings
from app.tenants.models import Client

_MAX_RETURN_TO_LENGTH = 512


def sanitize_return_to(return_to: str | None) -> str:
    """Sanitize an untrusted ``return_to`` query param per design §5.

    Must start with ``/``, must not start with ``//`` or ``/\\`` (protocol-
    relative / backslash open-redirect tricks), must not contain control
    characters (browsers strip tab/CR/LF while parsing, so ``/\t/host``
    would become ``//host``), must not target the API surface (``/api``,
    ``/api/...``, ``/api?...`` or ``/api#...``, case-insensitive), and must
    not exceed 512 chars.
    Anything else falls back to ``/``.
    """
    if not return_to:
        return "/"
    if len(return_to) > _MAX_RETURN_TO_LENGTH:
        return "/"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in return_to):
        return "/"
    if not return_to.startswith("/"):
        return "/"
    if return_to.startswith("//") or return_to.startswith("/\\"):
        return "/"
    lowered = return_to.lower()
    if lowered == "/api" or lowered.startswith(("/api/", "/api?", "/api#")):
        return "/"
    return return_to


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class MappedIdentity:
    role: str  # "superadmin" | "client"
    client_ids: list[str]


def _superadmin_emails(settings: Settings) -> set[str]:
    return {
        e.strip().lower()
        for e in settings.qora_superadmin_emails.split(",")
        if e.strip()
    }


class NoAccessError(Exception):
    """Raised when an authenticated WorkOS user maps to no Qora role."""


async def map_identity(
    db: AsyncSession,
    settings: Settings,
    *,
    user: WorkosUser,
    organization_id: str | None,
) -> MappedIdentity:
    """Map a WorkOS-authenticated user to a Qora role (design §4).

    1. Verified email in QORA_SUPERADMIN_EMAILS -> superadmin, client_ids=[].
    2. organization_id matches an active client's workos_organization_id ->
       client, client_ids=[client.id].
    3. Otherwise -> NoAccessError.
    """
    if user.email.lower() in _superadmin_emails(settings) and user.email_verified:
        return MappedIdentity(role="superadmin", client_ids=[])

    if organization_id:
        result = await db.execute(
            select(Client).where(Client.workos_organization_id == organization_id)
        )
        client = result.scalar_one_or_none()
        if client is not None and client.is_active:
            return MappedIdentity(role="client", client_ids=[client.id])

    raise NoAccessError("No Qora client or superadmin mapping for this identity")


async def create_session(
    db: AsyncSession,
    settings: Settings,
    *,
    user: WorkosUser,
    identity: MappedIdentity,
    workos_session_id: str | None,
) -> str:
    """Create an AuthSession row and return the raw (unhashed) session token."""
    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)
    display_name = None
    if user.first_name or user.last_name:
        display_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or None

    session_row = AuthSession(
        token_hash=hash_token(raw_token),
        workos_user_id=user.id,
        email=user.email,
        display_name=display_name,
        role=identity.role,
        client_ids=json.dumps(identity.client_ids),
        workos_session_id=workos_session_id,
        created_at=now,
        expires_at=now + timedelta(hours=settings.qora_auth_session_ttl_hours),
    )
    db.add(session_row)
    await db.commit()
    return raw_token


async def lookup_session(
    db: AsyncSession, raw_token: str, settings: Settings
) -> AuthSession | None:
    """Return the AuthSession for ``raw_token`` if it is valid, revoked and expired excluded.

    Roles are re-checked against current state: a client session needs every
    client still active, and a superadmin session needs its email still in
    QORA_SUPERADMIN_EMAILS.
    """
    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
    )
    session_row = result.scalar_one_or_none()
    if session_row is None:
        return None
    if session_row.revoked_at is not None:
        return None
    expires_at = session_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    if (
        session_row.role == "superadmin"
        and session_row.email.lower() not in _superadmin_emails(settings)
    ):
        return None
    if session_row.role == "client":
        client_ids: list[str] = json.loads(session_row.client_ids)
        active_result = await db.execute(
            select(Client.id).where(Client.id.in_(client_ids), Client.is_active == True)  # noqa: E712
        )
        active_ids = {row[0] for row in active_result.all()}
        if active_ids != set(client_ids):
            return None
    return session_row


async def revoke_session(db: AsyncSession, raw_token: str) -> AuthSession | None:
    """Revoke the session for ``raw_token``. Returns the row (even if already revoked/expired)."""
    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
    )
    session_row = result.scalar_one_or_none()
    if session_row is None:
        return None
    if session_row.revoked_at is None:
        session_row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return session_row
