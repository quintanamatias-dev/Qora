"""call-state-machine: rename in_call→connected, add outcome_reason column.

Changes:
  1. UPDATE call_sessions SET telephony_status='connected'
     WHERE telephony_status='in_call' — renames the phantom state in-place.
     In production, in_call is never actually set (phantom state per exploration),
     so this UPDATE affects 0 rows. It is included for correctness and rollback
     symmetry.
  2. Add call_sessions.outcome_reason — nullable VARCHAR; set by probe/sweep on
     SIP routing failures ('sip_routing_error'). NULL for existing rows.

Design decisions (design.md):
  - SQLite stores telephony_status as VARCHAR strings; no ALTER TYPE needed.
    An op.execute(UPDATE) renames values in-place without column type changes.
  - batch_alter_table: required for SQLite ADD COLUMN compatibility.
    SQLite does not support DROP COLUMN natively; batch mode uses
    CREATE + COPY + RENAME for the downgrade DROP.
  - Downgrade: reverses both changes — renames connected→in_call (for sessions
    created between upgrade and downgrade) and drops outcome_reason.
  - No server_default: outcome_reason is NULL for pre-migration rows.

Rollback plan:
  1. Set ENABLE_OUTBOUND_CALLS=false (probe/sweep no-ops).
  2. Run: alembic downgrade -1
  3. outcome_reason column dropped; in_call restored for any 'connected' rows.

Revision ID: 20260706_0008
Revises: 20260704_0007
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260706_0008"
down_revision: Union[str, None] = "20260704_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename in_call→connected + add outcome_reason column."""

    # Step 1: Rename the phantom in_call state to connected.
    # In production in_call is never set (phantom state), so this UPDATE is a
    # no-op. Included for correctness — ensures no legacy rows remain after upgrade.
    op.execute(
        "UPDATE call_sessions SET telephony_status = 'connected' "
        "WHERE telephony_status = 'in_call'"
    )

    # Step 2: Add outcome_reason column (nullable, no default).
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("outcome_reason", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Reverse: drop outcome_reason + rename connected→in_call.

    WARNING: Any 'connected' rows created after the upgrade will be renamed back
    to 'in_call'. This is acceptable for a rollback scenario; the code that was
    using 'connected' would also be rolled back simultaneously.
    """

    # Step 1: Drop outcome_reason column.
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("outcome_reason")

    # Step 2: Rename connected→in_call for any rows upgraded to connected.
    op.execute(
        "UPDATE call_sessions SET telephony_status = 'in_call' "
        "WHERE telephony_status = 'connected'"
    )
