"""QORA Phase 6 — Idempotent migration script for Call Scheduler.

Adds:
- `scheduled_calls` table (new)
- 7 `scheduler_*` columns on `clients` table (additive)

Safe to run multiple times — checks if column/table exists before adding.

Usage:
    python scripts/migrate_call_scheduler.py
    python scripts/migrate_call_scheduler.py --db-url sqlite+aiosqlite:///./qora.db
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


async def table_exists(conn, table: str) -> bool:
    """Return True if the table already exists in the database."""
    import sqlalchemy

    result = await conn.execute(
        sqlalchemy.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:table"
        ),
        {"table": table},
    )
    return result.fetchone() is not None


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
    """Run all Phase 6 Call Scheduler migrations idempotently."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1. Create scheduled_calls table (if not exists)
        # ------------------------------------------------------------------
        print("\nChecking scheduled_calls table...")
        if await table_exists(conn, "scheduled_calls"):
            print("  [skip] scheduled_calls table already exists")
        else:
            await conn.execute(
                sqlalchemy.text(
                    """
                    CREATE TABLE scheduled_calls (
                        id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL REFERENCES clients(id),
                        lead_id TEXT NOT NULL REFERENCES leads(id),
                        source_session_id TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        scheduled_at DATETIME NOT NULL,
                        attempt_number INTEGER NOT NULL DEFAULT 1,
                        max_attempts INTEGER NOT NULL DEFAULT 3,
                        trigger_reason TEXT NOT NULL,
                        outcome_session_id TEXT,
                        notes TEXT,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            # Create per-column indexes (only needed on fresh table)
            await conn.execute(
                sqlalchemy.text(
                    "CREATE INDEX IF NOT EXISTS ix_scheduled_calls_client_id "
                    "ON scheduled_calls(client_id)"
                )
            )
            await conn.execute(
                sqlalchemy.text(
                    "CREATE INDEX IF NOT EXISTS ix_scheduled_calls_lead_id "
                    "ON scheduled_calls(lead_id)"
                )
            )
            await conn.execute(
                sqlalchemy.text(
                    "CREATE INDEX IF NOT EXISTS ix_scheduled_calls_lead_status "
                    "ON scheduled_calls(lead_id, status)"
                )
            )
            print("  [create] scheduled_calls table + basic indexes")

        # Composite index for the scheduler tick query — created unconditionally
        # so existing deployments that already have the table also get it.
        # SELECT ... WHERE status = 'pending' AND scheduled_at <= now
        await conn.execute(
            sqlalchemy.text(
                "CREATE INDEX IF NOT EXISTS ix_scheduled_calls_status_scheduled_at "
                "ON scheduled_calls(status, scheduled_at)"
            )
        )
        print("  [ensure] ix_scheduled_calls_status_scheduled_at")

        # ------------------------------------------------------------------
        # 2. Add scheduler_* columns to clients table
        # ------------------------------------------------------------------
        print("\nMigrating clients table (scheduler config columns)...")
        scheduler_columns = [
            ("scheduler_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("scheduler_max_attempts", "INTEGER NOT NULL DEFAULT 3"),
            ("scheduler_cooldown_minutes", "INTEGER NOT NULL DEFAULT 60"),
            ("scheduler_allowed_hours_start", "INTEGER NOT NULL DEFAULT 9"),
            ("scheduler_allowed_hours_end", "INTEGER NOT NULL DEFAULT 20"),
            (
                "scheduler_retry_on_outcomes",
                'TEXT NOT NULL DEFAULT \'["call_again","follow_up"]\'',
            ),
            (
                "scheduler_timezone",
                "TEXT NOT NULL DEFAULT 'America/Argentina/Buenos_Aires'",
            ),
        ]

        for col_name, col_def in scheduler_columns:
            await add_column_if_missing(conn, "clients", col_name, col_def)

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Phase 6 — Call Scheduler idempotent migration"
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
