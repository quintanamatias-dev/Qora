"""QORA Phase 2 — Idempotent migration script for existing SQLite databases.

Adds new Phase 2 columns to `call_sessions` and `leads` tables.
Safe to run multiple times — checks if column exists before adding.

Usage:
    python scripts/migrate_phase2.py
    python scripts/migrate_phase2.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column already exists in the table."""
    result = await conn.execute(
        __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
    )
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
    """Run all Phase 2 column additions idempotently."""
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    # --- call_sessions new columns (CAP-5) ---
    call_session_columns = [
        ("summary", "TEXT"),
        ("closed_reason", "VARCHAR"),
        ("total_user_turns", "INTEGER NOT NULL DEFAULT 0"),
        ("total_agent_turns", "INTEGER NOT NULL DEFAULT 0"),
        ("extracted_facts", "TEXT"),  # JSON stored as TEXT in SQLite
    ]

    # --- leads new columns (CAP-5) ---
    lead_columns = [
        ("summary_last_call", "TEXT"),
        ("objections_heard", "TEXT"),  # JSON stored as TEXT in SQLite
        ("interest_level", "INTEGER"),
        ("extracted_facts", "TEXT"),  # JSON stored as TEXT in SQLite
        ("do_not_call", "BOOLEAN NOT NULL DEFAULT 0"),
        ("next_action", "VARCHAR"),
        ("next_action_at", "DATETIME"),
    ]

    async with engine.begin() as conn:
        print("\nMigrating call_sessions table...")
        for col_name, col_def in call_session_columns:
            await add_column_if_missing(conn, "call_sessions", col_name, col_def)

        print("\nMigrating leads table...")
        for col_name, col_def in lead_columns:
            await add_column_if_missing(conn, "leads", col_name, col_def)

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Phase 2 — Idempotent SQLite migration"
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
