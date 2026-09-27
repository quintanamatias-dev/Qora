"""Multi-tenant readiness: per-client plan and entitlement overrides.

Changes:
  1. clients.plan                  — VARCHAR NOT NULL DEFAULT 'pilot'
  2. clients.entitlement_overrides — TEXT NULL (JSON: {"features": {...}, "limits": {...}})

Design decisions:
  - server_default 'pilot' gives every existing client the unrestricted plan,
    so no current behaviour changes until a superadmin assigns a paid plan.
  - Plans themselves live in code (app/entitlements/catalog.py); only the
    assignment and the per-client exceptions are data.
  - batch_alter_table: required for SQLite ADD COLUMN compatibility.

Rollback plan:
  1. Run: alembic downgrade -1
  2. Both columns are dropped; plan assignments and overrides are lost
     (entitlement enforcement must be reverted together with this migration).

Revision ID: 20260927_0012
Revises: 20260727_0011
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260927_0012"
down_revision: Union[str, None] = "20260727_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add plan and entitlement_overrides to clients."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column("plan", sa.String(), nullable=False, server_default="pilot")
        )
        batch_op.add_column(sa.Column("entitlement_overrides", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove plan and entitlement_overrides from clients."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("entitlement_overrides")
        batch_op.drop_column("plan")
