"""Add background_jobs table for durable in-process job execution.

Adds the background_jobs table with full lifecycle columns and indexes.
No FK dependencies on other tables — clean add/drop for rollback safety.

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/background-job-executor/spec.md

Revision ID: 20260624_0002
Revises: 20241201_0001
Create Date: 2026-06-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260624_0002"
down_revision: Union[str, None] = "20241201_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the background_jobs table with lifecycle columns and indexes."""
    op.create_table(
        "background_jobs",
        # Primary key: UUID4 string — consistent with all existing Qora models.
        sa.Column("id", sa.String(), nullable=False),
        # Job type string — registered in the handler registry (e.g. 'summarize', 'crm_sync').
        sa.Column("job_type", sa.String(), nullable=False),
        # JSON payload passed to the handler function.
        sa.Column("payload", sa.Text(), nullable=False),
        # Lifecycle status: pending | running | completed | failed | dead
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        # Tracks how many execution attempts have been made.
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        # Maximum allowed attempts before the job is dead-lettered.
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        # Timestamps for full audit trail and B9 duration metrics.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Structured error JSON: {"message": str, "type": str, "operator_review": bool}
        # Not cleared on successful retry — preserved as audit trail.
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Index for recovery sweep: WHERE status IN ('pending', 'running')
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    # Index for B9 per-type failure dashboards: GROUP BY job_type, status
    op.create_index(
        "ix_background_jobs_type_status", "background_jobs", ["job_type", "status"]
    )


def downgrade() -> None:
    """Drop the background_jobs table and its indexes.

    No FK dependencies — clean drop with no cascade side effects.
    Rollback plan: set ENABLE_JOB_EXECUTOR=false, then run this downgrade.
    """
    op.drop_index("ix_background_jobs_type_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_table("background_jobs")
