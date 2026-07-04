"""C2 WU2 — Add session_end_received to call_sessions for FAS-safe sweep evidence.

Adds:
  1. call_sessions.session_end_received — nullable Boolean

Rationale (FAS safety contract):
  The reconciliation sweep previously used elevenlabs_conversation_id IS NOT NULL
  as completion evidence. This was too broad: conversation_id can be set when the
  outbound linkage webhook fires, but the session-end (the actual termination signal)
  may never arrive. Using conversation_id presence would incorrectly promote sessions
  to 'completed' without true session-end evidence.

  session_end_received=True is set ONLY by:
    - link_outbound_session_by_webhook() (the Custom LLM session-end webhook path)
    - update_telephony_status_on_session_end() (called from close_session())

  The sweep checks session_end_received=True before setting telephony_status='completed'.
  Sessions with conversation_id set but session_end_received=False → 'stale_in_call'.

All existing rows are unaffected: NULL on read (inbound/pre-C2 sessions stay NULL).
Downgrade drops the column cleanly.

Design: openspec/changes/phase-c2-outbound-call-trigger/design.md — WU2 Fix Batch
Spec:   openspec/changes/phase-c2-outbound-call-trigger/specs/outbound-call-trigger/spec.md

Revision ID: 20260703_0005
Revises: 20260702_0004
Create Date: 2026-07-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260703_0005"
down_revision: Union[str, None] = "20260702_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add session_end_received column to call_sessions."""

    with op.batch_alter_table("call_sessions") as batch_op:
        # session_end_received: True only when the Custom LLM session-end webhook confirmed
        # the call ended. NULL for inbound/pre-C2 rows. False for outbound awaiting end.
        # FAS contract: sweep uses this as completion evidence, NOT conversation_id presence.
        batch_op.add_column(
            sa.Column(
                "session_end_received",
                sa.Boolean(),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Remove session_end_received from call_sessions."""

    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("session_end_received")
