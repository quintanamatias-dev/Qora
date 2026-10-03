"""Skill packages: schema foundation (skill-packages, P4-D1).

Changes:
  1. skill_packages — new table. One row per Qora-owned package
     (owner_type="qora", client_id NULL) plus one per client that has
     skills (owner_type="client").
  2. skills — new table. A named slot within a package, scoped to a
     "general" or "agent" section. unique(package_id, slug, agent_id).
  3. skill_revisions — new table. Immutable, versioned skill content.
     Insert-only: revision_number is monotonic per skill_id.
  4. skills.active_revision_id — VARCHAR NULL, FK to skill_revisions.id.
     Added after skill_revisions exists (same two-step pattern as
     20261002_0014's agents.active_revision_id).

This migration is purely additive: no existing column is modified, no data
is backfilled here (see 20261003_0026_import_agent_skills.py for the
one-time import). No runtime code path reads these tables yet.

Design: openspec/changes/skill-packages/design.md P4-D1.

Rollback plan:
  1. Run: alembic downgrade -1
  2. skills.active_revision_id is dropped and all three tables are dropped.
     Safe — no runtime code depends on any of them yet.

Revision ID: 20261003_0025
Revises: 20261003_0024
Create Date: 2026-10-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0025"
down_revision: Union[str, None] = "20261003_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create skill_packages, skills, skill_revisions; add skills.active_revision_id."""
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_type", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_skill_packages_client_id", "skill_packages", ["client_id"])

    op.create_table(
        "skills",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "package_id", sa.String(), sa.ForeignKey("skill_packages.id"), nullable=False
        ),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("active_revision_id", sa.String(), nullable=True),
        sa.UniqueConstraint(
            "package_id", "slug", "agent_id", name="uq_skills_package_slug_agent"
        ),
    )
    op.create_index("ix_skills_package_id", "skills", ["package_id"])
    op.create_index("ix_skills_agent_id", "skills", ["agent_id"])

    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("skill_id", sa.String(), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("filler_text", sa.Text(), nullable=False),
        sa.Column("trigger_hint", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "skill_id", "revision_number", name="uq_skill_revisions_skill_number"
        ),
    )
    op.create_index("ix_skill_revisions_skill_id", "skill_revisions", ["skill_id"])

    with op.batch_alter_table("skills") as batch_op:
        batch_op.create_foreign_key(
            "fk_skills_active_revision_id",
            "skill_revisions",
            ["active_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    """Drop skills.active_revision_id and all three tables."""
    with op.batch_alter_table("skills") as batch_op:
        batch_op.drop_constraint("fk_skills_active_revision_id", type_="foreignkey")

    op.drop_index("ix_skill_revisions_skill_id", table_name="skill_revisions")
    op.drop_table("skill_revisions")

    op.drop_index("ix_skills_agent_id", table_name="skills")
    op.drop_index("ix_skills_package_id", table_name="skills")
    op.drop_table("skills")

    op.drop_index("ix_skill_packages_client_id", table_name="skill_packages")
    op.drop_table("skill_packages")
