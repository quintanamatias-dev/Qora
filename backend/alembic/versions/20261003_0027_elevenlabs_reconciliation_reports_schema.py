"""elevenlabs_reconciliation_reports schema (elevenlabs-reconciler, R-D1).

Additive table only — one row per ElevenLabs-linked agent, upserted by the
periodic, fetch-only reconciliation pass. No existing table or column is
touched; `Agent.elevenlabs_sync_status` keeps its distinct, write-triggered
meaning (see design.md R-D1).

Revision ID: 20261003_0027
Revises: 20261003_0026
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0027"
down_revision: Union[str, None] = "20261003_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "elevenlabs_reconciliation_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("drift_fields", sa.Text(), nullable=True),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        # Unique constraint declared inline (not via a separate
        # op.create_unique_constraint call) — SQLite cannot ALTER an existing
        # table to add a constraint outside of batch mode.
        sa.UniqueConstraint("agent_id", name="uq_elevenlabs_reconciliation_reports_agent_id"),
    )
    op.create_index(
        "ix_elevenlabs_reconciliation_reports_agent_id",
        "elevenlabs_reconciliation_reports",
        ["agent_id"],
    )
    op.create_index(
        "ix_elevenlabs_reconciliation_reports_client_id",
        "elevenlabs_reconciliation_reports",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_table("elevenlabs_reconciliation_reports")
