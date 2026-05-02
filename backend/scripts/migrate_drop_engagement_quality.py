"""QORA — Idempotent migration: drop engagement_quality column from call_analyses.

Issue #50 (qora-outcome): The engagement_quality field was removed from the
CallOutcome schema. The corresponding DB column is no longer needed.

SQLite ≥ 3.35.0 supports ALTER TABLE ... DROP COLUMN.

Idempotency: checks PRAGMA table_info(call_analyses) before attempting the DROP.
If the column already doesn't exist, the script skips silently.

Usage:
    python scripts/migrate_drop_engagement_quality.py
    python scripts/migrate_drop_engagement_quality.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def _column_exists(conn, table: str, column: str) -> bool:
    """Return True if the column exists on the table (SQLite PRAGMA)."""
    import sqlalchemy

    result = await conn.execute(sqlalchemy.text(f"PRAGMA table_info({table})"))
    rows = result.fetchall()
    return any(row[1] == column for row in rows)


async def run_migration(database_url: str) -> dict:
    """Drop engagement_quality column from call_analyses (idempotent).

    Args:
        database_url: SQLAlchemy async database URL.

    Returns:
        Dict with {"engagement_quality": "dropped" | "skipped"}.
    """
    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    result: dict[str, str] = {}

    async with engine.begin() as conn:
        if await _column_exists(conn, "call_analyses", "engagement_quality"):
            await conn.execute(
                sqlalchemy.text(
                    "ALTER TABLE call_analyses DROP COLUMN engagement_quality"
                )
            )
            result["engagement_quality"] = "dropped"
            print("  [ok] call_analyses.engagement_quality dropped")
        else:
            result["engagement_quality"] = "skipped"
            print("  [skip] call_analyses.engagement_quality does not exist — nothing to drop")

    await engine.dispose()

    print(f"\nMigration complete: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA — Drop engagement_quality column from call_analyses"
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
