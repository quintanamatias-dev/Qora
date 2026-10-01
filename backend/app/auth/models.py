"""QORA Auth — SQLAlchemy model for opaque, server-side WorkOS login sessions.

Design: openspec/changes/multi-tenant-auth/design.md §3.

The raw session token (secrets.token_urlsafe(32)) is never stored: only its
SHA-256 hex digest (token_hash) is persisted, so a stolen database dump does
not yield usable session cookies.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class AuthSession(Base):
    """A WorkOS-authenticated Qora session, keyed by the hash of its cookie token."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    workos_user_id: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # JSON array snapshot of client ids the caller may access, taken at login.
    client_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    workos_session_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthSession id={self.id!r} role={self.role!r} email={self.email!r}>"
