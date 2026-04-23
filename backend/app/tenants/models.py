"""QORA Tenants — SQLAlchemy models for Client configuration and Agent entity.

Based on the design.md schema for the `clients` and `agents` tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class Agent(Base):
    """First-class Agent entity — one Client may have N Agents.

    Exactly one Agent per client has is_default=True (enforced at application layer).
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    voice_id: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    knowledge_base: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4o")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    tools_enabled: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        # Enforce that slug is unique per client (not globally)
        UniqueConstraint("client_id", "slug", name="uq_agents_client_slug"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent id={self.id!r} slug={self.slug!r} client={self.client_id!r}>"


class Client(Base):
    """Represents a tenant/broker that uses QORA.

    One client == one insurance broker (e.g., Quintana Seguros).
    id is a human-readable slug: "quintana-seguros".
    """

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    broker_name: Mapped[str] = mapped_column(String, nullable=False)
    agent_name: Mapped[str] = mapped_column(String, nullable=False, default="Jaumpablo")
    voice_id: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt_override: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    knowledge_base: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # GPT-4o config (flat on client for simplicity in Phase 0)
    model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4o")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(nullable=False, default=300)
    tools_enabled: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    )

    # ---------------------------------------------------------------------------
    # Scheduler configuration (Phase 6 — flat columns, matches existing pattern)
    # ---------------------------------------------------------------------------

    scheduler_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    scheduler_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    scheduler_cooldown_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    scheduler_allowed_hours_start: Mapped[int] = mapped_column(
        Integer, nullable=False, default=9
    )
    scheduler_allowed_hours_end: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    scheduler_retry_on_outcomes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["call_again","follow_up"]',
    )
    scheduler_timezone: Mapped[str] = mapped_column(
        String, nullable=False, default="America/Argentina/Buenos_Aires"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client id={self.id!r} name={self.name!r}>"

    # ---------------------------------------------------------------------------
    # DEPRECATED(Phase 7) — agent-specific columns moved to Agent model.
    # Kept nullable for rollback safety. Do NOT use in new code.
    # ---------------------------------------------------------------------------
    # NOTE: agent_name, voice_id, system_prompt_override, knowledge_base, model,
    # temperature, max_tokens, tools_enabled remain on Client for backward compat.
    # New code reads from Agent; these columns are only written during migration.
