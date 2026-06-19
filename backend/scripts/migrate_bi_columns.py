# DEPRECATED — This script is superseded by Alembic migrations (phase-b-db-migration-foundation).
# All schema changes are now managed via: python scripts/migrate.py (alembic upgrade head).
# This file is kept for audit trail only. Do NOT run it against production databases.
# See docs/MIGRATIONS.md for the current migration workflow.

"""QORA BI Columns — Idempotent migration: adds 5 denormalized columns to call_analyses.

Adds to call_analyses:
- primary_objection_category  VARCHAR (nullable, default NULL)
- primary_pain_category       VARCHAR (nullable, default NULL)
- objections_count            INTEGER (nullable, default NULL)
- pain_points_count           INTEGER (nullable, default NULL)
- service_issues_count        INTEGER (nullable, default NULL)

Also creates two B-tree indexes:
- ix_ca_primary_objection_category ON call_analyses(primary_objection_category)
- ix_ca_primary_pain_category      ON call_analyses(primary_pain_category)

After adding columns, backfills existing rows by parsing the JSON arrays in
objections, pain_points, and service_issues columns.

Design: AD-1 (idempotent script pattern), AD-2 (B-tree indexes), AD-3 (backfill strategy).

Safe to run multiple times — checks column/index existence before adding.
If interrupted, re-run is safe (idempotent — each row UPDATE is independent).

Usage:
    python scripts/migrate_bi_columns.py
    python scripts/migrate_bi_columns.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
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


async def index_exists(conn, index_name: str) -> bool:
    """Return True if the index already exists (any table)."""
    import sqlalchemy

    result = await conn.execute(
        sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": index_name},
    )
    row = result.fetchone()
    return row is not None


async def create_index_if_missing(conn, index_name: str, table: str, column: str) -> bool:
    """Create a B-tree index if it does not already exist.

    Returns:
        True if index was created, False if it already existed.
    """
    import sqlalchemy

    if await index_exists(conn, index_name):
        print(f"  [skip] index {index_name} already exists")
        return False

    await conn.execute(
        sqlalchemy.text(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"
        )
    )
    print(f"  [add]  index {index_name} on {table}({column})")
    return True


def _extract_primary_category(json_str: str, array_key: str) -> str | None:
    """Extract the primary item's category from a JSON array column.

    Looks for the item with is_primary=true in the list.
    Returns the category string or None if not found / empty.

    Args:
        json_str: JSON string value from the DB column.
        array_key: Key within each item dict containing the category (always 'category').
    """
    if not json_str or json_str in ("[]", "null", ""):
        return None

    try:
        items = json.loads(json_str)
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and item.get("is_primary"):
                cat = item.get(array_key)
                return str(cat) if cat is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return None


def _extract_count(json_str: str) -> int:
    """Return the length of the JSON array column, or 0 if empty/invalid."""
    if not json_str or json_str in ("[]", "null", ""):
        return 0

    try:
        items = json.loads(json_str)
        if isinstance(items, list):
            return len(items)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return 0


async def run_migration(database_url: str) -> None:
    """Add BI denormalized columns + indexes to call_analyses; backfill existing rows."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    # --- Step 1: Add 5 nullable columns ---
    new_columns = [
        ("primary_objection_category", "VARCHAR DEFAULT NULL"),
        ("primary_pain_category", "VARCHAR DEFAULT NULL"),
        ("objections_count", "INTEGER DEFAULT NULL"),
        ("pain_points_count", "INTEGER DEFAULT NULL"),
        ("service_issues_count", "INTEGER DEFAULT NULL"),
    ]

    async with engine.begin() as conn:
        print("\nAdding denormalized columns to call_analyses...")
        for col_name, col_def in new_columns:
            await add_column_if_missing(conn, "call_analyses", col_name, col_def)

        print("\nCreating indexes on call_analyses...")
        await create_index_if_missing(
            conn, "ix_ca_primary_objection_category", "call_analyses", "primary_objection_category"
        )
        await create_index_if_missing(
            conn, "ix_ca_primary_pain_category", "call_analyses", "primary_pain_category"
        )

    # --- Step 2: Backfill existing rows ---
    async with engine.begin() as conn:
        print("\nBackfilling denormalized columns from JSON arrays...")

        # Fetch rows that need backfill. We process ALL rows to be safe (idempotent).
        # For very large datasets this could be batched, but call_analyses is bounded.
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT id, objections, pain_points, service_issues FROM call_analyses"
            )
        )
        rows = result.fetchall()

        updated = 0
        skipped = 0
        for row in rows:
            row_id = row[0]
            objections_json = row[1] or "[]"
            pain_points_json = row[2] or "[]"
            service_issues_json = row[3] or "[]"

            primary_objection = _extract_primary_category(objections_json, "category")
            primary_pain = _extract_primary_category(pain_points_json, "category")
            obj_count = _extract_count(objections_json)
            pain_count = _extract_count(pain_points_json)
            svc_count = _extract_count(service_issues_json)

            await conn.execute(
                sqlalchemy.text(
                    """
                    UPDATE call_analyses SET
                        primary_objection_category = :primary_objection,
                        primary_pain_category = :primary_pain,
                        objections_count = :obj_count,
                        pain_points_count = :pain_count,
                        service_issues_count = :svc_count
                    WHERE id = :id
                    """
                ),
                {
                    "id": row_id,
                    "primary_objection": primary_objection,
                    "primary_pain": primary_pain,
                    "obj_count": obj_count,
                    "pain_count": pain_count,
                    "svc_count": svc_count,
                },
            )
            updated += 1

        print(f"  [backfill] {updated} rows updated, {skipped} skipped")

    await engine.dispose()
    print("\nBI columns migration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA BI Columns — Idempotent SQLite migration for call_analyses"
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
