"""C2 Outbound Telephony — agent phone number ID and CallSession telephony metadata.

Adds:
  1. agents.elevenlabs_phone_number_id   — nullable String
  2. call_sessions.provider_call_id      — nullable String
  3. call_sessions.telephony_provider    — nullable String (default 'elevenlabs')
  4. call_sessions.telephony_status      — nullable String
  5. call_sessions.telephony_error       — nullable Text
  6. call_sessions.provider_metadata     — nullable JSON

All columns are nullable → existing rows are unaffected (NULL on read).
Downgrade drops all 6 columns cleanly.

Design: openspec/changes/phase-c2-outbound-call-trigger/design.md
Spec:   openspec/changes/phase-c2-outbound-call-trigger/specs/telephony-provider-decision/spec.md

Revision ID: 20260702_0004
Revises: 20260625_0003
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260702_0004"
down_revision: Union[str, None] = "20260625_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add outbound telephony columns to agents and call_sessions."""

    # 1. agents.elevenlabs_phone_number_id — nullable String
    #    Stores the ElevenLabs phone number resource ID for the SIP trunk outbound API.
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "elevenlabs_phone_number_id",
                sa.String(),
                nullable=True,
            )
        )

    # 2-6. call_sessions telephony metadata columns (5 new columns, all nullable)
    with op.batch_alter_table("call_sessions") as batch_op:
        # ElevenLabs call identifier returned by the outbound-call API.
        batch_op.add_column(
            sa.Column("provider_call_id", sa.String(), nullable=True)
        )
        # Provider name (always "elevenlabs" for outbound; NULL for inbound/pre-C2 rows).
        # NO server_default: existing rows must remain NULL. The application layer sets
        # telephony_provider="elevenlabs" explicitly when creating an outbound CallSession.
        # A server_default would misclassify all legacy inbound rows as outbound.
        batch_op.add_column(
            sa.Column(
                "telephony_provider",
                sa.String(),
                nullable=True,
            )
        )
        # Provider-reported telephony state machine:
        # dialing → ringing → in_call → completed | no_answer | failed | recurrent_error
        batch_op.add_column(
            sa.Column("telephony_status", sa.String(), nullable=True)
        )
        # Human-readable error detail populated on failure or retry.
        batch_op.add_column(
            sa.Column("telephony_error", sa.Text(), nullable=True)
        )
        # Safe/allowlisted provider metadata JSON: only permitted fields (cost,
        # billed_duration_seconds, call_id, status, duration_seconds) are stored.
        # 'message' is excluded — free-form provider text may contain PII (phone
        # numbers, caller names, routing annotations). PII, routing data (SIP URIs),
        # and internal provider identifiers are stripped by
        # _extract_safe_provider_metadata() before persist (WU2-RE4).
        batch_op.add_column(
            sa.Column("provider_metadata", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    """Remove outbound telephony columns from agents and call_sessions.

    Rollback plan:
      1. Set ENABLE_OUTBOUND_CALLS=false (or remove the env var) — immediate
      2. Run alembic downgrade -1 — removes the 6 columns
      3. Pre-C2 data is unaffected; all new columns are nullable additions.
    """
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("provider_metadata")
        batch_op.drop_column("telephony_error")
        batch_op.drop_column("telephony_status")
        batch_op.drop_column("telephony_provider")
        batch_op.drop_column("provider_call_id")

    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("elevenlabs_phone_number_id")
