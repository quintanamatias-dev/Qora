"""QORA Phase 7 — Idempotent migration: add agent_id FK columns + backfill.

Steps:
1. Add nullable `agent_id` column to `call_sessions` (if not exists)
2. Add nullable `agent_id` column to `scheduled_calls` (if not exists)
3. Backfill `agent_id` for all rows where agent_id IS NULL:
   - Look up the default agent for the row's client_id
   - Update the row with that agent_id
   (Rows whose client has no default agent are left as NULL)

Note: SQLite does not support adding NOT NULL constraints via ALTER TABLE.
The NOT NULL enforcement happens at the application layer (ORM).

Safe to run multiple times — idempotent via column existence check and
NULL-only backfill query.

Usage:
    python scripts/migrate_add_agent_id_fks.py
    python scripts/migrate_add_agent_id_fks.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


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


async def column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column already exists in the table."""
    import sqlalchemy

    result = await conn.execute(
        sqlalchemy.text(f"PRAGMA table_info({table})")
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


async def count_null_agent_rows(conn, table: str) -> int:
    """Count rows in `table` where agent_id IS NULL.

    Returns:
        Number of rows with NULL agent_id.
    """
    import sqlalchemy

    result = await conn.execute(
        sqlalchemy.text(f"SELECT COUNT(*) FROM {table} WHERE agent_id IS NULL")
    )
    return result.scalar() or 0


async def backfill_agent_id(conn, table: str) -> int:
    """Backfill agent_id=NULL rows in `table` from each row's client_id default agent.

    Uses a single correlated subquery UPDATE (O(1) queries, not O(N)).

    Returns:
        Number of rows updated.
    """
    import sqlalchemy

    # Count NULL rows first to skip early if nothing to do
    null_count_result = await conn.execute(
        sqlalchemy.text(f"SELECT COUNT(*) FROM {table} WHERE agent_id IS NULL")
    )
    null_count = null_count_result.scalar() or 0

    if null_count == 0:
        print(f"  [skip] no NULL agent_id rows in {table}")
        return 0

    # Single correlated subquery UPDATE — O(1) queries regardless of row count
    result = await conn.execute(
        sqlalchemy.text(
            f"""
            UPDATE {table}
            SET agent_id = (
                SELECT id FROM agents
                WHERE client_id = {table}.client_id
                  AND is_default = 1
                  AND is_active = 1
                LIMIT 1
            )
            WHERE agent_id IS NULL
            """
        )
    )
    updated = result.rowcount

    print(f"  [backfill] {table}: updated {updated} of {null_count} rows (single correlated UPDATE)")
    return updated


async def run_migration(database_url: str) -> None:
    """Run Phase 7 agent_id FK columns and backfill migration idempotently."""
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 0. Pre-flight: agents table must exist (run migrate_add_agents.py first)
        # ------------------------------------------------------------------
        if not await table_exists(conn, "agents"):
            raise RuntimeError(
                "agents table does not exist. "
                "Run migrate_add_agents.py before migrate_add_agent_id_fks.py."
            )

        # ------------------------------------------------------------------
        # 1. Add agent_id to call_sessions
        # ------------------------------------------------------------------
        print("\nMigrating call_sessions table...")
        await add_column_if_missing(
            conn, "call_sessions", "agent_id", "TEXT REFERENCES agents(id)"
        )

        # ------------------------------------------------------------------
        # 2. Add agent_id to scheduled_calls
        # ------------------------------------------------------------------
        print("\nMigrating scheduled_calls table...")
        await add_column_if_missing(
            conn, "scheduled_calls", "agent_id", "TEXT REFERENCES agents(id)"
        )

        # ------------------------------------------------------------------
        # 3. Backfill agent_id from default agents
        # ------------------------------------------------------------------
        print("\nBackfilling agent_id for existing rows...")
        await backfill_agent_id(conn, "call_sessions")
        await backfill_agent_id(conn, "scheduled_calls")

        # ------------------------------------------------------------------
        # 4. Verify — report remaining NULL rows (cannot enforce NOT NULL
        #    via ALTER TABLE in SQLite, but we surface the count clearly)
        # ------------------------------------------------------------------
        print("\nVerifying backfill completeness...")
        null_sessions = await count_null_agent_rows(conn, "call_sessions")
        null_scheduled = await count_null_agent_rows(conn, "scheduled_calls")

        if null_sessions > 0:
            print(
                f"  [warn] {null_sessions} call_sessions row(s) still have NULL agent_id "
                "(client has no default agent — manual assignment required)"
            )
        else:
            print("  [ok]   call_sessions: 0 NULL agent_id rows")

        if null_scheduled > 0:
            print(
                f"  [warn] {null_scheduled} scheduled_calls row(s) still have NULL agent_id "
                "(client has no default agent — manual assignment required)"
            )
        else:
            print("  [ok]   scheduled_calls: 0 NULL agent_id rows")

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Phase 7 — Add agent_id FK columns to call_sessions and scheduled_calls"
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
