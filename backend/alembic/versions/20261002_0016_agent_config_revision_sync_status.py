"""Agent config revisions: add elevenlabs_sync_status (agent-config-revisions-routing D7).

Changes:
  1. agent_config_revisions.elevenlabs_sync_status — VARCHAR NULL. Records the
     outcome ("synced", "drift", "error", "skipped") of the ElevenLabs sync
     triggered when a revision was activated via the API PATCH or rollback
     path. NULL for revisions created without a sync attempt (e.g. imports).

Purely additive: no existing column is modified.

Design: openspec/changes/agent-config-revisions-routing/design.md D7.

Rollback plan:
  1. Run: alembic downgrade -1
  2. agent_config_revisions.elevenlabs_sync_status is dropped. Safe — only
     the Phase 2 write/rollback paths read or write this column.

Revision ID: 20261002_0016
Revises: 20261002_0015
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261002_0016"
down_revision: Union[str, None] = "20261002_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agent_config_revisions.elevenlabs_sync_status."""
    with op.batch_alter_table("agent_config_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("elevenlabs_sync_status", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Drop agent_config_revisions.elevenlabs_sync_status."""
    with op.batch_alter_table("agent_config_revisions") as batch_op:
        batch_op.drop_column("elevenlabs_sync_status")
