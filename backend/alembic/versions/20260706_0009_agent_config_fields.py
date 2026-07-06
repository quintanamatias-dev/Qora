"""elevenlabs-config: add voicemail_detection_enabled + max_call_duration_seconds to agents.

Adds two nullable columns to the agents table for unified ElevenLabs agent config sync
(sdd/elevenlabs-config). NULL = skip that config block in the PATCH payload.

Changes:
  1. agents.voicemail_detection_enabled — nullable BOOLEAN; NULL means skip voicemail
     detection block in ElevenLabs PATCH. True/False sends the block.
  2. agents.max_call_duration_seconds — nullable INTEGER; NULL means skip max_duration
     block in ElevenLabs PATCH.

Design decisions:
  - No backfill: both columns default to NULL for all existing rows (existing behavior
    preserved — no config blocks sent for pre-migration agents unless explicitly set).
  - batch_alter_table: required for SQLite ADD COLUMN compatibility (same pattern as
    previous migrations in this file set).
  - No server_default: SQLAlchemy model defaults handle Python-side default=None;
    DB-side NULL is the correct default for nullable columns.

Rollback plan:
  1. Run: alembic downgrade -1
  2. Both columns dropped; no data loss (new feature, no production data yet).

Revision ID: 20260706_0009
Revises: 20260706_0008
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260706_0009"
down_revision: Union[str, None] = "20260706_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add voicemail_detection_enabled and max_call_duration_seconds to agents."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column("voicemail_detection_enabled", sa.Boolean(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("max_call_duration_seconds", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """Remove voicemail_detection_enabled and max_call_duration_seconds from agents."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("max_call_duration_seconds")
        batch_op.drop_column("voicemail_detection_enabled")
