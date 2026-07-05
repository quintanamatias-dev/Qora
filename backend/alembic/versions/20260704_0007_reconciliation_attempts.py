"""C3 resilience — add reconciliation_attempts counter to call_sessions.

Adds:
  1. call_sessions.reconciliation_attempts — Integer, NOT NULL, server default 0

Problem: Sessions whose ElevenLabs list API call always fails (e.g. 404 on the
conversations endpoint) are never marked reconciled, so they re-enter the sweep
candidate query every 5 minutes forever — an infinite retry loop that burns API
quota on known-doomed calls.

Fix: track the number of reconciliation attempts per session. When the counter
reaches settings.reconciliation_max_attempts (default 5), the sweep parks the
session by setting reconciled_at + reconciliation_source='unreconcilable', which
excludes it from future candidate queries (reconciled_at IS NULL filter).

Design decisions:
  - Integer NOT NULL with server_default='0': existing rows inherit 0, so the
    sweep starts counting from a clean baseline without a backfill script.
    server_default (SQLite DDL default) ensures ALTER TABLE ADD COLUMN sets 0
    on all pre-migration rows.
  - No FK constraint — counter lives on call_sessions alongside the other C3 columns.
  - Downgrade: DROP COLUMN. Rows parked as 'unreconcilable' will revert to
    reconciled_at=<timestamp> with no attempts column — they remain excluded from
    the sweep candidate query because reconciled_at IS NOT NULL, so no data hazard.
  - batch_alter_table: required for SQLite (ALTER TABLE ADD COLUMN works for
    nullable or defaulted additions; batch mode used for DROP in downgrade).

Rollback plan:
  1. alembic downgrade -1   → drops reconciliation_attempts column.
  2. Sessions parked as 'unreconcilable' keep reconciled_at set so they stay
     excluded from the sweep — no regression to the infinite-retry state.
  3. To re-open parked sessions: UPDATE call_sessions SET reconciled_at=NULL,
     reconciliation_source=NULL WHERE reconciliation_source='unreconcilable';
     (operator action, not required for rollback safety)

Revision ID: 20260704_0007
Revises: 20260704_0006
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260704_0007"
down_revision: Union[str, None] = "20260704_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add reconciliation_attempts INTEGER NOT NULL DEFAULT 0 to call_sessions."""

    with op.batch_alter_table("call_sessions") as batch_op:
        # NOT NULL with server_default='0': SQLite sets 0 on all existing rows
        # when the column is added via ALTER TABLE (SQLite ADD COLUMN with DEFAULT).
        # This avoids a NULL-handling branch in the sweep and a separate backfill.
        batch_op.add_column(
            sa.Column(
                "reconciliation_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """Drop reconciliation_attempts from call_sessions.

    Safe: sessions parked as 'unreconcilable' retain reconciled_at IS NOT NULL,
    so they remain excluded from the sweep candidate query after rollback.
    """
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("reconciliation_attempts")
