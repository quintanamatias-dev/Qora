# DEPRECATED — This script is superseded by Alembic migrations (phase-b-db-migration-foundation).
# All schema changes are now managed via: python scripts/migrate.py (alembic upgrade head).
# This file is kept for audit trail only. Do NOT run it against production databases.
# See docs/MIGRATIONS.md for the current migration workflow.

"""QORA Data Corrections — Idempotent migration: adds email and age to leads table.

Adds:
- leads.email  TEXT (nullable, default NULL)
- leads.age    INTEGER (nullable, default NULL)

Safe to run multiple times — checks column existence before adding.

Usage:
    python scripts/migrate_data_corrections.py
    python scripts/migrate_data_corrections.py --db-url sqlite+aiosqlite:///./qora.db
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
    """Add email and age columns to leads table (idempotent)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    lead_columns = [
        ("email", "TEXT"),
        ("age", "INTEGER"),
    ]

    async with engine.begin() as conn:
        print("\nMigrating leads table (qora-data-corrections)...")
        for col_name, col_def in lead_columns:
            await add_column_if_missing(conn, "leads", col_name, col_def)

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Data Corrections — Idempotent SQLite migration"
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
