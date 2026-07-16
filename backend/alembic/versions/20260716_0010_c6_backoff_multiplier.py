"""C6 retry policy: add scheduler_backoff_multiplier to clients.

Adds scheduler_backoff_multiplier (FLOAT NOT NULL DEFAULT 1.0) to the clients
table to support per-client escalating recontact delays.

Formula: delay = cooldown_minutes × (backoff_multiplier ^ (attempt_number − 1))
Default 1.0 preserves existing flat-delay behavior for all current clients.

Changes:
  1. clients.scheduler_backoff_multiplier — FLOAT NOT NULL DEFAULT 1.0

Design decisions:
  - Safe default (1.0) means no data change for existing rows.
  - batch_alter_table: required for SQLite ADD COLUMN compatibility.
  - server_default="1.0" ensures NOT NULL works even for existing rows in PostgreSQL.

Rollback plan:
  1. Run: alembic downgrade -1
  2. Column dropped; flat-delay behavior restored (no client data loss).

Revision ID: 20260716_0010
Revises: 20260706_0009
Create Date: 2026-07-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260716_0010"
down_revision: Union[str, None] = "20260706_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add scheduler_backoff_multiplier to clients."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scheduler_backoff_multiplier",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            )
        )


def downgrade() -> None:
    """Remove scheduler_backoff_multiplier from clients."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("scheduler_backoff_multiplier")
