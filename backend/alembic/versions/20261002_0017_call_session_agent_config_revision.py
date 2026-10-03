"""Call sessions record the agent config revision active at session creation.

Changes:
  1. call_sessions.agent_config_revision_id — VARCHAR NULL, FK to
     agent_config_revisions.id. Stamped by calls/service.py create_session() from
     the resolved agent's active_revision_id at creation time. NULL for sessions
     created before this migration, and for any agent that has no active revision.

Purely additive: no existing column is modified.

Design: openspec/changes/agent-config-revisions-routing/design.md D4.

Rollback plan:
  1. Run: alembic downgrade -1
  2. call_sessions.agent_config_revision_id is dropped. Safe — only the
     create_session() write path and future revision-drift reporting read it.

Revision ID: 20261002_0017
Revises: 20261002_0016
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261002_0017"
down_revision: Union[str, None] = "20261002_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add call_sessions.agent_config_revision_id (nullable FK)."""
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("agent_config_revision_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_call_sessions_agent_config_revision_id",
            "agent_config_revisions",
            ["agent_config_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop call_sessions.agent_config_revision_id."""
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_constraint(
            "fk_call_sessions_agent_config_revision_id", type_="foreignkey"
        )
        batch_op.drop_column("agent_config_revision_id")
