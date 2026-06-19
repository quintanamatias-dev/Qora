# DEPRECATED — This script is superseded by Alembic migrations (phase-b-db-migration-foundation).
# All schema changes are now managed via: python scripts/migrate.py (alembic upgrade head).
# This file is kept for audit trail only. Do NOT run it against production databases.
# See docs/MIGRATIONS.md for the current migration workflow.

"""QORA Abandonment → Outcome migration — Add was_abrupt + abandonment_trigger columns.

qora-abandonment (Issue #56): Absorbs the abandoned abandonment dimension into
CallOutcome. Adds two new nullable columns to call_analyses:
  - was_abrupt      BOOLEAN  (nullable)
  - abandonment_trigger TEXT (nullable)

The existing abandonment_reason column is kept as DEPRECATED (AD-4 — SQLite
compat; historical data is intentionally discarded — low analytical value).

Idempotent: safe to run multiple times. Uses PRAGMA table_info to check for
column existence before issuing ALTER TABLE.

Usage:
    python scripts/migrate_abandonment_to_outcome.py
    python scripts/migrate_abandonment_to_outcome.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


# ---------------------------------------------------------------------------
# New columns: (column_name, DDL_type)
# ---------------------------------------------------------------------------

_NEW_COLUMNS = [
    ("was_abrupt", "BOOLEAN"),
    ("abandonment_trigger", "TEXT"),
]


async def _column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column already exists on the table (SQLite PRAGMA)."""
    import sqlalchemy

    result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    return any(row[1] == column for row in rows)


async def run_migration(database_url: str) -> dict:
    """Add was_abrupt + abandonment_trigger to call_analyses idempotently.

    Args:
        database_url: SQLAlchemy async database URL.

    Returns:
        Dict of {column_name: 'added' | 'skipped'}.
    """
    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    results: dict[str, str] = {}

    async with engine.begin() as conn:
        print("\nAdding qora-abandonment columns to call_analyses...")
        for col_name, col_ddl in _NEW_COLUMNS:
            if await _column_exists(conn, "call_analyses", col_name):
                results[col_name] = "skipped"
                print(f"  [skip] call_analyses.{col_name} already exists")
            else:
                await conn.execute(
                    sqlalchemy.text(
                        f"ALTER TABLE call_analyses ADD COLUMN {col_name} {col_ddl}"
                    )
                )
                results[col_name] = "added"
                print(f"  [ok] call_analyses.{col_name} added")

    await engine.dispose()

    added = sum(1 for v in results.values() if v == "added")
    skipped = sum(1 for v in results.values() if v == "skipped")
    print(f"\nMigration complete: added={added}, skipped={skipped}")
    return results


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "QORA qora-abandonment — Add was_abrupt + abandonment_trigger "
            "columns to call_analyses"
        )
    )
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./qora.db",
        help="SQLAlchemy async database URL (default: sqlite+aiosqlite:///./qora.db)",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(run_migration(args.db_url))
        print(f"Result: {result}")
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
