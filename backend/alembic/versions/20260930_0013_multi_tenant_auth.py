"""Multi-tenant auth: WorkOS AuthKit login sessions.

Changes:
  1. clients.workos_organization_id — VARCHAR NULL, UNIQUE. Links a Qora
     client (tenant) to exactly one WorkOS organization.
  2. auth_sessions — new table. Opaque server-side session rows created at
     WorkOS AuthKit callback. Only the SHA-256 hash of the session token is
     stored — the raw token never touches the database.

Design: openspec/changes/multi-tenant-auth/design.md §3.

Rollback plan:
  1. Run: alembic downgrade -1
  2. auth_sessions is dropped and clients.workos_organization_id is removed.
     Every WorkOS-authenticated user is logged out; the QORA_API_KEY path is
     unaffected.

Revision ID: 20260930_0013
Revises: 20260927_0012
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260930_0013"
down_revision: Union[str, None] = "20260927_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add clients.workos_organization_id and create auth_sessions."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("workos_organization_id", sa.String(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_clients_workos_organization_id", ["workos_organization_id"]
        )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("workos_user_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("client_ids", sa.Text(), nullable=False),
        sa.Column("workos_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True
    )


def downgrade() -> None:
    """Drop auth_sessions and clients.workos_organization_id."""
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_constraint("uq_clients_workos_organization_id", type_="unique")
        batch_op.drop_column("workos_organization_id")
