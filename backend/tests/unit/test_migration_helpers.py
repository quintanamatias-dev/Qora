"""Tests for tests/helpers/migrations.py — migration-based test DB helper.

TDD cycle:
  Task 2.4 — apply_migrations(db_url) runs alembic upgrade head against a
  given database URL and produces a schema-complete SQLite DB.

Spec scenarios:
  - apply_migrations creates all 10 Qora baseline tables
  - Schema matches production migration (broker_name NOT NULL, session_id index)
  - apply_migrations is idempotent (safe to call twice)
  - apply_migrations raises on invalid URL / connection error
"""

from __future__ import annotations

import sqlite3
from pathlib import Path



# ---------------------------------------------------------------------------
# Happy path: apply_migrations produces a valid schema
# ---------------------------------------------------------------------------


def test_apply_migrations_creates_baseline_tables(tmp_path: Path):
    """apply_migrations(db_url) MUST create all 10 baseline Qora tables.

    GIVEN an empty database URL pointing at a tmp file
    WHEN apply_migrations(db_url) is called
    THEN all 10 tables from the baseline migration must exist
    """
    from tests.helpers.migrations import apply_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    apply_migrations(db_url)

    # Verify via sqlite3 directly (sync, no async needed)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT IN ('alembic_version', 'sqlite_sequence')"
    )
    tables = {row[0] for row in cur.fetchall()}
    conn.close()

    expected_tables = {
        "clients",
        "agents",
        "leads",
        "lead_profile_facts",
        "lead_custom_fields",
        "lead_interest_history",
        "call_sessions",
        "transcript_turns",
        "call_analyses",
        "scheduled_calls",
    }
    assert expected_tables.issubset(tables), (
        f"Missing tables after apply_migrations: {expected_tables - tables}"
    )


def test_apply_migrations_creates_alembic_version_table(tmp_path: Path):
    """apply_migrations records the migration revision in alembic_version.

    GIVEN a fresh database
    WHEN apply_migrations is called
    THEN alembic_version table must exist with a valid version_num row
    """
    from tests.helpers.migrations import apply_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/versioned.db"
    apply_migrations(db_url)

    conn = sqlite3.connect(str(tmp_path / "versioned.db"))
    cur = conn.cursor()
    cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
    row = cur.fetchone()
    conn.close()

    assert row is not None, "alembic_version must have a row after apply_migrations"
    # HEAD revision advances as new migrations are added — accept any known Qora revision.
    # Baseline: 20241201_0001; Phase B10 background_jobs: 20260624_0002
    # PR3 transcript finalization fields: 20260625_0003
    _KNOWN_REVISIONS = {"20241201_0001", "20260624_0002", "20260625_0003"}
    assert row[0] in _KNOWN_REVISIONS, (
        f"Expected a known Qora migration version, got {row[0]!r}. "
        f"Known revisions: {_KNOWN_REVISIONS}"
    )


def test_apply_migrations_broker_name_not_null(tmp_path: Path):
    """apply_migrations must produce clients.broker_name as NOT NULL.

    GIVEN a migration-created DB
    WHEN PRAGMA table_info(clients) is queried
    THEN broker_name column must have notnull=1
    """
    from tests.helpers.migrations import apply_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/schema_check.db"
    apply_migrations(db_url)

    conn = sqlite3.connect(str(tmp_path / "schema_check.db"))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(clients)")
    cols = {row[1]: row for row in cur.fetchall()}
    conn.close()

    assert "broker_name" in cols, "clients.broker_name must exist"
    assert cols["broker_name"][3] == 1, (
        "clients.broker_name must be NOT NULL (notnull=1)"
    )


def test_apply_migrations_is_idempotent(tmp_path: Path):
    """Calling apply_migrations twice must not raise.

    GIVEN apply_migrations was already called on a DB
    WHEN apply_migrations is called again (same URL)
    THEN no exception is raised (idempotent upgrade head)
    """
    from tests.helpers.migrations import apply_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/idempotent.db"
    apply_migrations(db_url)
    # Second call must be a no-op (already at head)
    apply_migrations(db_url)  # must not raise
