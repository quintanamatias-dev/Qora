# DEPRECATED — This script is superseded by Alembic migrations (phase-b-db-migration-foundation).
# All schema changes are now managed via: python scripts/migrate.py (alembic upgrade head).
# This file is kept for audit trail only. Do NOT run it against production databases.
# See docs/MIGRATIONS.md for the current migration workflow.

"""QORA Next Action Engine — Idempotent migration (qora-next-action, Issue #47).

Adds 3 new columns to the clients table and updates the scheduler_retry_on_outcomes
default to use the new 5-action vocabulary.

New columns:
- clients.next_action_max_attempts            INTEGER DEFAULT 5
- clients.next_action_min_interest_for_followup  INTEGER DEFAULT 40
- clients.next_action_close_on_hard_rejection  INTEGER DEFAULT 1

Updated defaults (model-level only; no data migration for existing rows):
- clients.scheduler_retry_on_outcomes: default updated to
  '["follow_up","retry_call","schedule_call"]' (was '["call_again","follow_up"]')

Safe to run multiple times — checks column existence before adding.

Usage:
    python scripts/migrate_next_action_engine.py
    python scripts/migrate_next_action_engine.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column already exists in the table."""
    import sqlalchemy

    result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    return any(row[1] == column for row in rows)


async def add_column_if_missing(conn, table: str, column: str, col_def: str) -> bool:
    """Add a column to a table only if it doesn't already exist.

    Returns:
        True if column was added, False if it already existed.
    """
    import sqlalchemy

    if await column_exists(conn, table, column):
        print(f"  [skip] {table}.{column} already exists")
        return False

    await conn.execute(
        sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    )
    print(f"  [add]  {table}.{column} ({col_def})")
    return True


async def run_migration(database_url: str) -> None:
    """Add next_action engine columns to clients table (idempotent)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    client_columns = [
        ("next_action_max_attempts", "INTEGER NOT NULL DEFAULT 5"),
        ("next_action_min_interest_for_followup", "INTEGER NOT NULL DEFAULT 40"),
        ("next_action_close_on_hard_rejection", "INTEGER NOT NULL DEFAULT 1"),
    ]

    async with engine.begin() as conn:
        print("\nMigrating clients table (qora-next-action)...")
        for col_name, col_def in client_columns:
            await add_column_if_missing(conn, "clients", col_name, col_def)

        # Note: scheduler_retry_on_outcomes default is model-level only.
        # Existing rows in the DB keep their stored values (no data migration).
        # New clients created via seed_quintana or API will get the new default
        # automatically (set at the ORM model level in Client.scheduler_retry_on_outcomes).
        print("\n  [info] scheduler_retry_on_outcomes default updated in model to")
        print('         \'["follow_up","retry_call","schedule_call"]\'')
        print(
            "  [info] Existing rows keep their stored values — no data migration needed."
        )

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Next Action Engine — Idempotent SQLite migration"
    )
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./qora.db",
        help="SQLAlchemy async database URL (default: sqlite+aiosqlite:///./qora.db)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_migration(args.db_url))
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
