"""Call analysis profile revision pointer (design.md P5-D6).

Adds call_analyses.analysis_profile_revision_id — nullable FK to
client_analysis_profile_revisions.id. Stamped by summarizer.py at analysis
time with the client's currently-active analysis profile revision, so a
later profile edit never changes how an already-analyzed call's
products/specific_needs should be interpreted.

Nullable because rows written before this migration have no value — they
are interpreted under the implicit assumption of catalog.py's original
constants, documented as a migration-boundary note, not backfilled.

Design: openspec/changes/analysis-profiles/design.md P5-D6.

Rollback plan:
  1. Run: alembic downgrade -1
  2. call_analyses.analysis_profile_revision_id is dropped. Safe — rollback
     means stamping stops (column stays absent), functionally degraded but
     not broken.

Revision ID: 20261003_0024
Revises: 20261003_0023
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0024"
down_revision: Union[str, None] = "20261003_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add call_analyses.analysis_profile_revision_id (nullable FK)."""
    with op.batch_alter_table("call_analyses") as batch_op:
        batch_op.add_column(
            sa.Column("analysis_profile_revision_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_call_analyses_analysis_profile_revision_id",
            "client_analysis_profile_revisions",
            ["analysis_profile_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop call_analyses.analysis_profile_revision_id."""
    with op.batch_alter_table("call_analyses") as batch_op:
        batch_op.drop_constraint(
            "fk_call_analyses_analysis_profile_revision_id", type_="foreignkey"
        )
        batch_op.drop_column("analysis_profile_revision_id")
