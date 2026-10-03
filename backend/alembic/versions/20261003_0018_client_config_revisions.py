"""Client config revisions: schema + empty import revision 1 (agent-config-inheritance D11).

Changes:
  1. client_config_revisions — new table. Immutable, versioned client-level
     config override snapshots. Insert-only: revision_number is monotonic
     per client_id.
  2. clients.active_config_revision_id — VARCHAR NULL, FK to
     client_config_revisions.id. Single pointer to the client's currently
     active config revision.
  3. One-time import: for every existing client, creates an EMPTY
     source="import" revision ({"schema_version": "v1"}, no overrides) and
     activates it, so every client has an active_config_revision_id and
     resolution behavior is unchanged (every field falls through to the
     standard or the agent, exactly as before this migration).

This migration deliberately does NOT import any `app.*` module (same
precedent as 20261002_0015): the schema it writes (the empty sparse config
shape) must stay stable regardless of future application code changes.

Design: openspec/changes/agent-config-inheritance/design.md D11.

Rollback plan:
  1. Run: alembic downgrade -1
  2. client_config_revisions is dropped and clients.active_config_revision_id
     is dropped. Safe — no runtime code depends on either yet (task 5 wires
     the resolver/runtime consumers).

Revision ID: 20261003_0018
Revises: 20261002_0017
Create Date: 2026-10-03
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0018"
down_revision: Union[str, None] = "20261002_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_CONFIG_JSON = '{"schema_version": "v1"}'


def upgrade() -> None:
    """Create client_config_revisions, add clients.active_config_revision_id,
    and import an empty, activated revision 1 per existing client."""
    op.create_table(
        "client_config_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "client_id", "revision_number", name="uq_client_config_revisions_client_number"
        ),
    )
    op.create_index(
        "ix_client_config_revisions_client_id",
        "client_config_revisions",
        ["client_id"],
    )

    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column("active_config_revision_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_clients_active_config_revision_id",
            "client_config_revisions",
            ["active_config_revision_id"],
            ["id"],
        )

    bind = op.get_bind()
    client_ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM clients WHERE active_config_revision_id IS NULL")
        ).fetchall()
    ]
    now = datetime.now(timezone.utc)
    for client_id in client_ids:
        revision_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO client_config_revisions "
                "(id, client_id, revision_number, config, schema_version, source, "
                "created_by, created_at, note) "
                "VALUES (:id, :client_id, 1, :config, 'v1', 'import', 'system', "
                ":created_at, 'empty import revision 1 — no client overrides yet')"
            ),
            {
                "id": revision_id,
                "client_id": client_id,
                "config": _EMPTY_CONFIG_JSON,
                "created_at": now,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE clients SET active_config_revision_id = :rev_id WHERE id = :client_id"
            ),
            {"rev_id": revision_id, "client_id": client_id},
        )


def downgrade() -> None:
    """Drop clients.active_config_revision_id and client_config_revisions."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_constraint(
            "fk_clients_active_config_revision_id", type_="foreignkey"
        )
        batch_op.drop_column("active_config_revision_id")

    op.drop_index(
        "ix_client_config_revisions_client_id", table_name="client_config_revisions"
    )
    op.drop_table("client_config_revisions")
