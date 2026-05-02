"""QORA Extraction v2 — Idempotent migration: add new axes columns to call_analyses + clients.

Issue #35 — Enhanced Per-Call Extraction

Adds to `call_analyses`:
  - service_issues    TEXT NOT NULL DEFAULT '[]'
  - profile_facts     TEXT NOT NULL DEFAULT '[]'
  - commitment_signals TEXT NOT NULL DEFAULT '[]'
  - abandonment_reason TEXT (nullable)
  - extra_axes_data    TEXT (nullable)

Adds to `clients`:
  - extraction_config  TEXT (nullable)

All new columns are nullable or have defaults — backward compatible.
Existing rows are unaffected. Safe to run multiple times (idempotent).

Usage:
    python scripts/migrate_extraction_v2.py
    python scripts/migrate_extraction_v2.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


# ---------------------------------------------------------------------------
# Column addition helpers
# ---------------------------------------------------------------------------

# call_analyses new columns: (column_name, DDL_type_and_default)
_CALL_ANALYSES_NEW_COLUMNS = [
    ("service_issues", "TEXT NOT NULL DEFAULT '[]'"),
    ("profile_facts", "TEXT NOT NULL DEFAULT '[]'"),
    ("commitment_signals", "TEXT NOT NULL DEFAULT '[]'"),
    ("abandonment_reason", "TEXT"),
    ("extra_axes_data", "TEXT"),
]

# clients new columns: (column_name, DDL_type_and_default)
_CLIENTS_NEW_COLUMNS = [
    ("extraction_config", "TEXT"),
]


async def _column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column already exists on the table (SQLite PRAGMA)."""
    import sqlalchemy

    result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    return any(row[1] == column for row in rows)


async def _add_columns_if_missing(
    conn,
    table: str,
    columns: list[tuple[str, str]],
) -> dict[str, str]:
    """Add each column to the table if it doesn't already exist.

    Returns dict of {column_name: 'added' | 'skipped'}.
    """
    import sqlalchemy

    results: dict[str, str] = {}
    for col_name, col_ddl in columns:
        if await _column_exists(conn, table, col_name):
            results[col_name] = "skipped"
            print(f"  [skip] {table}.{col_name} already exists")
        else:
            await conn.execute(
                sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}")
            )
            results[col_name] = "added"
            print(f"  [ok] {table}.{col_name} added")
    return results


# ---------------------------------------------------------------------------
# Core migration function
# ---------------------------------------------------------------------------


async def run_migration(database_url: str) -> dict:
    """Run the extraction v2 migration idempotently.

    Adds 5 new columns to call_analyses and 1 new column to clients.
    All columns are nullable or defaulted — zero downtime, backward compatible.

    Args:
        database_url: SQLAlchemy async database URL.

    Returns:
        Dict with per-table column statuses.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    call_analyses_results: dict[str, str] = {}
    clients_results: dict[str, str] = {}

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1. Add new columns to call_analyses
        # ------------------------------------------------------------------
        print("\nAdding new axes columns to call_analyses...")
        call_analyses_results = await _add_columns_if_missing(
            conn, "call_analyses", _CALL_ANALYSES_NEW_COLUMNS
        )

        # ------------------------------------------------------------------
        # 2. Add extraction_config to clients
        # ------------------------------------------------------------------
        print("\nAdding extraction_config to clients...")
        clients_results = await _add_columns_if_missing(
            conn, "clients", _CLIENTS_NEW_COLUMNS
        )

    await engine.dispose()

    summary = {
        "call_analyses": call_analyses_results,
        "clients": clients_results,
    }
    added = sum(1 for v in call_analyses_results.values() if v == "added") + sum(
        1 for v in clients_results.values() if v == "added"
    )
    skipped = sum(1 for v in call_analyses_results.values() if v == "skipped") + sum(
        1 for v in clients_results.values() if v == "skipped"
    )
    print(f"\nMigration complete: added={added}, skipped={skipped}")
    return summary


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Extraction v2 — Add new axis columns to call_analyses and clients"
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
