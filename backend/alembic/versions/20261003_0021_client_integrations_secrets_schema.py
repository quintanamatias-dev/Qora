"""client_integrations + client_secrets schema (client-integrations-secrets, P3-D1).

Creates two new, mutable-in-place tables (no revision history — see
design.md P3-D1 rationale):

  - client_integrations: per-client, non-secret CRM integration config
    (base_id, table_id, field_mappings, custom_fields, quote_ready_fields,
    status maps, enabled), plus a computed status/status_reason column pair.
    unique(client_id, provider).

  - client_secrets: encrypted per-client credentials (Fernet/MultiFernet
    ciphertext, never plaintext). unique(client_id, name).

This is purely additive — nothing reads or writes either table yet (task 3
onward). Rollback: alembic downgrade -1 drops both tables; safe, since no
runtime code depends on them at this revision.

Design: openspec/changes/client-integrations-secrets/design.md P3-D1.

Revision ID: 20261003_0021
Revises: 20261003_0020
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0021"
down_revision: Union[str, None] = "20261003_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create client_integrations and client_secrets."""
    op.create_table(
        "client_integrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "client_id", "provider", name="uq_client_integrations_client_provider"
        ),
    )
    op.create_index(
        "ix_client_integrations_client_id", "client_integrations", ["client_id"]
    )

    op.create_table(
        "client_secrets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column(
            "integration_id",
            sa.String(),
            sa.ForeignKey("client_integrations.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.UniqueConstraint("client_id", "name", name="uq_client_secrets_client_name"),
    )
    op.create_index("ix_client_secrets_client_id", "client_secrets", ["client_id"])


def downgrade() -> None:
    """Drop client_secrets and client_integrations."""
    op.drop_index("ix_client_secrets_client_id", table_name="client_secrets")
    op.drop_table("client_secrets")
    op.drop_index("ix_client_integrations_client_id", table_name="client_integrations")
    op.drop_table("client_integrations")
