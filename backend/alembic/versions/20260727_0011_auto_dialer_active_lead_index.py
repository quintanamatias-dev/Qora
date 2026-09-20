"""Phase C6b: partial unique index on active scheduled_calls per lead.

Formalises an invariant the code already assumes (get_active_scheduled_call_for_lead
calls scalar_one_or_none(), which raises on duplicates): at most one *in_progress*
ScheduledCall may exist per lead at a time. Scoped to status='in_progress' only —
NOT ('pending', 'in_progress') — because schedule_tech_retry's dedup guard
(service.py:577-584) filters trigger_reason == 'tech_retry' only, so a lead with an
active auto_retry row AND a new pending tech_retry row is a normal, reachable state
(guaranteed on every recurrent_error from a scheduled dial). Scoping to
('pending', 'in_progress') would raise IntegrityError on that path every time.

This migration MUST ship in the same slice as the CAS claim (app/scheduler/service.py
claim_due_scheduled_calls / _claim_one): the existing bulk mark_due_calls_in_progress
promotes ALL due rows in one flush, so shipping this index alone would turn the very
first lead with two pending rows (auto_retry + tech_retry) into a permanent
scheduler_tick_failed wedge.

Changes:
  1. Pre-migration duplicate resolution (irreversible) — for any lead with more
     than one 'in_progress' row, keep the newest (by scheduled_at, then created_at,
     then id) and retire the rest to 'failed' with an explanatory note. Logs the
     retired-row count via the "alembic.runtime.migration" logger so the operator
     sees exactly what was auto-resolved.
  2. CREATE UNIQUE INDEX uq_scheduled_calls_active_lead ON scheduled_calls (lead_id)
     WHERE status = 'in_progress'. Raw op.execute — the partial-index WHERE clause
     syntax is identical on SQLite (>= 3.8, window functions >= 3.25 for step 1) and
     PostgreSQL, so one statement covers both dialects.

Design decisions:
  - Window-function UPDATE for step 1 avoids a Python-side loop over candidate rows;
    ROW_NUMBER() OVER (PARTITION BY lead_id ORDER BY scheduled_at DESC, created_at
    DESC, id DESC) ranks 1 = keep, > 1 = retire.
  - Model parity: app/scheduler/models.py.__table_args__ gets a matching
    Index(..., sqlite_where=..., postgresql_where=...) in the same commit so
    ORM-created test DBs match the Alembic-migrated schema.

Rollback plan:
  1. Run: alembic downgrade -1
  2. The unique index is dropped. Step 1's data fix is NOT reversible — retired
     rows stay 'failed'. This is intentional and safe: those rows were duplicate
     in_progress rows for one lead, i.e. unresolvable dead ends that predate this
     change's invariant. No lead loses its sole active row.

Revision ID: 20260727_0011
Revises: 20260716_0010
Create Date: 2026-07-27
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20260727_0011"
down_revision: Union[str, None] = "20260716_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deliberately NOT "alembic.*" or "sqlalchemy.*" — alembic.ini's fileConfig()
# resets every child logger of its explicitly configured loggers (level,
# handlers, propagate) on EVERY upgrade/downgrade call, regardless of
# disable_existing_loggers. A distinct top-level name survives that reset and
# still reaches the operator: propagate=True (default) carries it to the
# root logger's console handler, which alembic.ini leaves at level=NOTSET.
logger = logging.getLogger("app.migrations.auto_dialer")
logger.setLevel(logging.INFO)

_RETIRE_DUPLICATES_SQL = """
UPDATE scheduled_calls
   SET status = 'failed',
       notes  = COALESCE(notes || ' | ', '') ||
                'auto-resolved by migration 20260727_0011: duplicate in_progress row'
 WHERE id IN (
   SELECT id FROM (
     SELECT id, ROW_NUMBER() OVER (
       PARTITION BY lead_id
       ORDER BY scheduled_at DESC, created_at DESC, id DESC) AS rn
       FROM scheduled_calls WHERE status = 'in_progress'
   ) ranked WHERE ranked.rn > 1
 )
"""

_CREATE_INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_scheduled_calls_active_lead "
    "ON scheduled_calls (lead_id) WHERE status = 'in_progress'"
)

_DROP_INDEX_SQL = "DROP INDEX IF EXISTS uq_scheduled_calls_active_lead"


def upgrade() -> None:
    """Retire duplicate in_progress rows per lead, then add the unique index."""
    bind = op.get_bind()

    # Step 1 — pre-migration duplicate resolution (irreversible; see docstring).
    result = bind.execute(sa.text(_RETIRE_DUPLICATES_SQL))
    retired = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
    logger.info(
        "migration 20260727_0011: retired %d duplicate in_progress "
        "scheduled_calls row(s) (kept the newest per lead)",
        retired,
    )

    # Step 2 — partial unique index (one statement valid on SQLite and Postgres).
    op.execute(_CREATE_INDEX_SQL)


def downgrade() -> None:
    """Drop the unique index. Step 1's data fix is NOT reversible (see docstring)."""
    op.execute(_DROP_INDEX_SQL)
