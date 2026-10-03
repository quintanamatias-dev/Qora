"""Standard version tracking: materialized-config and call-session provenance.

Changes:
  1. agents.materialized_standard_version — VARCHAR NULL. Stamped by
     materialize_agent_config() (design.md D19) with the STANDARD_VERSION
     active when the agent's Agent.* columns were last derived from
     resolve_effective_config(). NULL for agents never materialized by the
     1b write/propagation paths.
  2. call_sessions.standard_version — VARCHAR NULL. Stamped by
     calls/service.py create_session() from the resolved agent's
     materialized_standard_version (falling back to the current
     STANDARD_VERSION when the agent has never been materialized).
  3. call_sessions.client_config_revision_id — VARCHAR NULL, FK to
     client_config_revisions.id. Stamped by create_session() from the
     client's active_config_revision_id at creation time.

Purely additive: no existing column is modified or backfilled.

Design: openspec/changes/agent-config-inheritance/design.md D19.

Rollback plan:
  1. Run: alembic downgrade -1
  2. agents.materialized_standard_version, call_sessions.standard_version,
     and call_sessions.client_config_revision_id are dropped. Safe — these
     are read-only provenance columns with no other runtime dependency.

Revision ID: 20261003_0019
Revises: 20261003_0018
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0019"
down_revision: Union[str, None] = "20261003_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agents.materialized_standard_version and the two call_sessions
    provenance columns (all nullable, additive)."""
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column("materialized_standard_version", sa.String(), nullable=True)
        )

    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(sa.Column("standard_version", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("client_config_revision_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_call_sessions_client_config_revision_id",
            "client_config_revisions",
            ["client_config_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop the three columns added by upgrade()."""
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_constraint(
            "fk_call_sessions_client_config_revision_id", type_="foreignkey"
        )
        batch_op.drop_column("client_config_revision_id")
        batch_op.drop_column("standard_version")

    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("materialized_standard_version")
