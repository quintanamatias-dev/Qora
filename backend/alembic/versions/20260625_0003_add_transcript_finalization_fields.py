"""Add transcript finalization audit fields to call_sessions.

Adds two nullable columns to call_sessions:
  - transcript_finalized_at: DateTime — stamped by transcript_flush_handler after call end.
  - transcript_turn_count:   Integer  — the confirmed turn count at finalization time.

Rationale: the PR3 transcript_flush handler needs an externally visible durable outcome
so B9/operators can confirm that off-call transcript reconciliation ran. NULL means the
session predates PR3 or the handler has not yet run (pending/failed job).

Migration safety:
  - Both columns are nullable — existing rows get NULL without any backfill required.
  - No FK dependencies — clean add for rollback.
  - SQLite batch mode (render_as_batch=True in env.py) handles ALTER TABLE safely.

Revision ID: 20260625_0003
Revises: 20260624_0002
Create Date: 2026-06-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260625_0003"
down_revision: Union[str, None] = "20260624_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add transcript_finalized_at and transcript_turn_count to call_sessions."""
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "transcript_finalized_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcript_turn_count",
                sa.Integer(),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Remove transcript finalization columns from call_sessions.

    Rollback plan: set ENABLE_JOB_EXECUTOR=false (so transcript_flush is not enqueued),
    then run this downgrade to remove the columns.
    """
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("transcript_turn_count")
        batch_op.drop_column("transcript_finalized_at")
