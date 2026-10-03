"""Analysis profiles: schema + per-client seed (design.md P5-D2/P5-D4).

Changes:
  1. client_analysis_profile_revisions — new table. Immutable, versioned
     per-client analysis profile snapshots (products + need_tags). Insert-
     only: revision_number is monotonic per client_id.
  2. clients.active_analysis_profile_revision_id — VARCHAR NULL, FK to
     client_analysis_profile_revisions.id. Single pointer to the client's
     currently active analysis profile revision.
  3. One-time seed: for every existing client, creates and activates a
     source="import" revision 1. Quintana Seguros ("quintana-seguros") gets
     the `insurance` template's data — the 9 product IDs and 10 need-tag IDs
     from catalog.py, INLINED here literally (not imported — migrations
     never import `app.*`, same house pattern as 20261003_0022). Every
     other client gets an empty `generic` revision (products=[],
     need_tags=[]).

This migration deliberately does NOT import any `app.*` module: the
insurance template's literal product/need-tag IDs below must stay stable
regardless of future application code changes. A golden regression test
(backend/tests/regression/test_analysis_profiles_golden.py, task 3.4)
asserts these inline IDs still match catalog.py's live constants.

Idempotent: re-running upgrade() does not duplicate a seeded revision for a
client that already has an active_analysis_profile_revision_id.

Design: openspec/changes/analysis-profiles/design.md P5-D2/P5-D3/P5-D4.

Rollback plan:
  1. Run: alembic downgrade -1
  2. client_analysis_profile_revisions is dropped and
     clients.active_analysis_profile_revision_id is dropped. Safe — no
     runtime code depends on either yet (task 3 wires the per-call
     resolver/consumers).

Revision ID: 20261003_0023
Revises: 20261003_0022
Create Date: 2026-10-03
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0023"
down_revision: Union[str, None] = "20261003_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_QUINTANA_CLIENT_ID = "quintana-seguros"

# Inlined literally — must stay byte-identical to catalog.py's PRODUCT_CATALOG
# list + label text sourced from frontend/src/config/dimension-labels.ts.
_INSURANCE_PRODUCTS = [
    {"id": "auto_todo_riesgo", "label_es": "Auto todo riesgo", "label_en": "Comprehensive auto", "description": None},
    {"id": "auto_terceros_completo", "label_es": "Auto terceros completo", "label_en": "Auto third-party complete", "description": None},
    {"id": "auto_terceros", "label_es": "Auto terceros", "label_en": "Auto third-party", "description": None},
    {"id": "moto", "label_es": "Moto", "label_en": "Motorcycle", "description": None},
    {"id": "hogar", "label_es": "Hogar", "label_en": "Home", "description": None},
    {"id": "vida", "label_es": "Vida", "label_en": "Life", "description": None},
    {"id": "comercio", "label_es": "Comercio", "label_en": "Commercial", "description": None},
    {"id": "art", "label_es": "ART", "label_en": "Personal accident (ART)", "description": None},
    {"id": "caucion", "label_es": "Caución", "label_en": "Surety bond", "description": None},
]

# Inlined literally — must stay byte-identical to catalog.py's NEED_TAGS list.
_INSURANCE_NEED_TAGS = [
    {"id": "precio_competitivo", "label_es": "Precio competitivo", "label_en": "Competitive price"},
    {"id": "mayor_cobertura", "label_es": "Mayor cobertura", "label_en": "More coverage"},
    {"id": "menor_franquicia", "label_es": "Menor franquicia", "label_en": "Lower deductible"},
    {"id": "atencion_personalizada", "label_es": "Atención personalizada", "label_en": "Personalized service"},
    {"id": "rapidez", "label_es": "Rapidez", "label_en": "Speed"},
    {"id": "financiacion", "label_es": "Financiación", "label_en": "Financing"},
    {"id": "comparar_con_actual", "label_es": "Comparar con actual", "label_en": "Compare with current"},
    {"id": "renovacion_proxima", "label_es": "Renovación próxima", "label_en": "Upcoming renewal"},
    {"id": "COMPARANDO_OPCIONES", "label_es": "Comparando opciones", "label_en": "Comparing options"},
    {"id": "other", "label_es": "Otro", "label_en": "Other"},
]


def _insurance_config_json() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "vertical": "insurance",
            "products": _INSURANCE_PRODUCTS,
            "need_tags": _INSURANCE_NEED_TAGS,
        }
    )


def _generic_config_json() -> str:
    return json.dumps({"schema_version": 1, "vertical": "generic", "products": [], "need_tags": []})


def upgrade() -> None:
    """Create client_analysis_profile_revisions, add
    clients.active_analysis_profile_revision_id, and seed revision 1 per
    existing client (Quintana = insurance, everyone else = generic)."""
    op.create_table(
        "client_analysis_profile_revisions",
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
            "client_id",
            "revision_number",
            name="uq_client_analysis_profile_revisions_client_number",
        ),
    )
    op.create_index(
        "ix_client_analysis_profile_revisions_client_id",
        "client_analysis_profile_revisions",
        ["client_id"],
    )

    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(
            sa.Column("active_analysis_profile_revision_id", sa.String(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_clients_active_analysis_profile_revision_id",
            "client_analysis_profile_revisions",
            ["active_analysis_profile_revision_id"],
            ["id"],
        )

    bind = op.get_bind()
    client_ids = [
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT id FROM clients WHERE active_analysis_profile_revision_id IS NULL"
            )
        ).fetchall()
    ]
    now = datetime.now(timezone.utc)
    for client_id in client_ids:
        config_json = (
            _insurance_config_json() if client_id == _QUINTANA_CLIENT_ID else _generic_config_json()
        )
        revision_id = str(uuid.uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO client_analysis_profile_revisions "
                "(id, client_id, revision_number, config, schema_version, source, "
                "created_by, created_at, note) "
                "VALUES (:id, :client_id, 1, :config, '1', 'import', 'system', "
                ":created_at, 'seeded revision 1 by migration 20261003_0023')"
            ),
            {
                "id": revision_id,
                "client_id": client_id,
                "config": config_json,
                "created_at": now,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE clients SET active_analysis_profile_revision_id = :rev_id "
                "WHERE id = :client_id"
            ),
            {"rev_id": revision_id, "client_id": client_id},
        )


def downgrade() -> None:
    """Drop clients.active_analysis_profile_revision_id and
    client_analysis_profile_revisions."""
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_constraint(
            "fk_clients_active_analysis_profile_revision_id", type_="foreignkey"
        )
        batch_op.drop_column("active_analysis_profile_revision_id")

    op.drop_index(
        "ix_client_analysis_profile_revisions_client_id",
        table_name="client_analysis_profile_revisions",
    )
    op.drop_table("client_analysis_profile_revisions")
