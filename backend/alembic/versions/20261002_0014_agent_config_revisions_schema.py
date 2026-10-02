"""Agent config revisions: schema foundation (agent-config-revisions-routing D4).

Changes:
  1. agent_config_revisions — new table. Immutable, versioned agent config
     snapshots. Insert-only: revision_number is monotonic per agent_id.
  2. agents.active_revision_id — VARCHAR NULL, FK to agent_config_revisions.id.
     Single pointer to the agent's currently active revision.

This migration is purely additive: no existing column is modified, no data
is backfilled here (see 20261002_0015_import_agent_config_revision_1.py for
the one-time import). No runtime code path reads these columns yet.

Design: openspec/changes/agent-config-revisions-routing/design.md D4.

Rollback plan:
  1. Run: alembic downgrade -1
  2. agents.active_revision_id is dropped and agent_config_revisions is
     dropped. Safe — no runtime code depends on either yet.

Revision ID: 20261002_0014
Revises: 20260930_0013
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261002_0014"
down_revision: Union[str, None] = "20260930_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agent_config_revisions and add agents.active_revision_id."""
    op.create_table(
        "agent_config_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "agent_id", "revision_number", name="uq_agent_config_revisions_agent_number"
        ),
    )
    op.create_index(
        "ix_agent_config_revisions_agent_id",
        "agent_config_revisions",
        ["agent_id"],
    )

    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("active_revision_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_agents_active_revision_id",
            "agent_config_revisions",
            ["active_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop agents.active_revision_id and agent_config_revisions."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_constraint("fk_agents_active_revision_id", type_="foreignkey")
        batch_op.drop_column("active_revision_id")

    op.drop_index(
        "ix_agent_config_revisions_agent_id", table_name="agent_config_revisions"
    )
    op.drop_table("agent_config_revisions")
