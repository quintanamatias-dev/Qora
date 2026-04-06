"""QORA Tenants — SQLAlchemy models for Client configuration.

Based on the design.md schema for the `clients` table.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client id={self.id!r} name={self.name!r}>"
