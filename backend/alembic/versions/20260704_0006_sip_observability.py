"""C3 — SIP Observability: add five nullable columns to call_sessions.

Adds:
  1. call_sessions.sip_call_id          — nullable String (SIP Call-ID header value)
  2. call_sessions.sip_status_code      — nullable Integer (final SIP response code)
  3. call_sessions.sip_reason           — nullable String (final SIP reason phrase)
  4. call_sessions.reconciled_at        — nullable DateTime with timezone
  5. call_sessions.reconciliation_source — nullable String ("probe" | "sweep")

Design decisions:
  - All five columns are nullable — existing/inbound rows are unaffected (NULL on read).
  - No server_default: pre-migration rows stay NULL. The probe/sweep set values
    asynchronously after a dial attempt. Existing inbound sessions stay NULL forever.
  - batch_alter_table: required for SQLite compatibility (ALTER TABLE ADD COLUMN
    works in SQLite, but SQLite does not support ALTER COLUMN or DROP COLUMN natively —
    batch mode uses CREATE + COPY + RENAME for downgrade DROP operations).
  - Downgrade: DROP COLUMN for all five. Zero data loss to pre-migration rows.

Security constraint:
  These columns MUST NOT store raw SIP message bodies, Proxy-Authorization headers,
  digest credentials, From/To SIP URIs containing phone numbers, or any credential
  material. Only structured allowlisted fields may be persisted (enforced in the
  probe and sweep via the SipMessage Pydantic model).

Rollback plan:
  1. Set ENABLE_OUTBOUND_CALLS=false (probe + sweep are no-ops without outbound calls)
  2. Run: alembic downgrade -1
  3. The five SIP columns are dropped. Zero data loss — all were nullable additions.

Design: openspec/changes/call-observability-reconciliation/design.md
Spec:   openspec/specs/call-sip-observability/spec.md

Revision ID: 20260704_0006
Revises: 20260703_0005
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260704_0006"
down_revision: Union[str, None] = "20260703_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add five SIP observability columns to call_sessions (all nullable)."""

    with op.batch_alter_table("call_sessions") as batch_op:
        # SIP Call-ID header value (e.g. "otb_abc123..." from ElevenLabs/Telnyx)
        # Never contains phone numbers or PII — it is the SIP dialog identifier only.
        batch_op.add_column(
            sa.Column("sip_call_id", sa.String(), nullable=True)
        )
        # Final SIP response status code as an integer (200, 404, 487, 503, etc.)
        # Extracted from the last SIP response in the dialog, not the raw message.
        batch_op.add_column(
            sa.Column("sip_status_code", sa.Integer(), nullable=True)
        )
        # Final SIP response reason phrase ("OK", "Not Found", "Request Terminated", etc.)
        # Short, structured phrase — NOT a raw SIP message body.
        batch_op.add_column(
            sa.Column("sip_reason", sa.String(), nullable=True)
        )
        # UTC timestamp when SIP evidence was successfully captured by probe or sweep.
        # Serves as the idempotency guard: probe/sweep skip sessions where this is not NULL.
        batch_op.add_column(
            sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True)
        )
        # Identifies which reconciliation path populated the SIP evidence.
        # Values: "probe" | "sweep" — set by the probe/sweep at write time.
        batch_op.add_column(
            sa.Column("reconciliation_source", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Drop the five SIP observability columns from call_sessions.

    Rollback is safe: all columns were nullable additions with no FK constraints.
    Existing pre-migration row data (NULL for all five columns) is unaffected.
    """
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("reconciliation_source")
        batch_op.drop_column("reconciled_at")
        batch_op.drop_column("sip_reason")
        batch_op.drop_column("sip_status_code")
        batch_op.drop_column("sip_call_id")
