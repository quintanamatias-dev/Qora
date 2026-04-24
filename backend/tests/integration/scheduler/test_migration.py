"""Integration tests for call scheduler migration — Phase 6 (Task 5.1 RED).

Covers:
- Idempotent creation of scheduled_calls table
- Additive scheduler_* columns on clients table
- Running migration twice does not cause errors
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_url(tmp_path: Path) -> str:
    """Return a temporary SQLite URL for migration tests."""
    return f"sqlite+aiosqlite:///{tmp_path}/migration_test.db"


async def test_migration_creates_scheduled_calls_table(tmp_db_url: str):
    """Migration creates the scheduled_calls table if it doesn't exist."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    engine = create_async_engine(tmp_db_url, echo=False)

    # Create minimal clients table first (migration depends on it)
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Jaumpablo',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    await engine.dispose()

    # Run migration
    from scripts.migrate_call_scheduler import run_migration

    await run_migration(tmp_db_url)

    # Verify scheduled_calls table exists
    engine2 = create_async_engine(tmp_db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_calls'"
            )
        )
        row = result.fetchone()
        assert row is not None, "scheduled_calls table was not created"

    await engine2.dispose()


async def test_migration_adds_scheduler_columns_to_clients(tmp_db_url: str):
    """Migration adds scheduler_* columns to clients table."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    engine = create_async_engine(tmp_db_url, echo=False)

    # Create minimal clients table (without scheduler columns)
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Jaumpablo',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    await engine.dispose()

    # Run migration
    from scripts.migrate_call_scheduler import run_migration

    await run_migration(tmp_db_url)

    # Verify scheduler columns exist on clients
    engine2 = create_async_engine(tmp_db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(clients)"))
        columns = {row[1] for row in result.fetchall()}

    await engine2.dispose()

    expected_scheduler_columns = {
        "scheduler_enabled",
        "scheduler_max_attempts",
        "scheduler_cooldown_minutes",
        "scheduler_allowed_hours_start",
        "scheduler_allowed_hours_end",
        "scheduler_retry_on_outcomes",
        "scheduler_timezone",
    }
    for col in expected_scheduler_columns:
        assert col in columns, f"Missing scheduler column: {col}"


# ---------------------------------------------------------------------------
# Round 2 fix — Issue 5: Composite index must be created unconditionally
# ---------------------------------------------------------------------------


async def test_migration_composite_index_on_existing_table(tmp_path: Path):
    """Composite index (status, scheduled_at) must be created even when scheduled_calls
    table already exists. Simulates an existing deployment re-running the migration.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    db_url = f"sqlite+aiosqlite:///{tmp_path}/existing_table_migration_test.db"
    engine = create_async_engine(db_url, echo=False)

    # Pre-create the scheduled_calls table WITHOUT the composite index
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Jaumpablo',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        # Create the scheduled_calls table WITHOUT the composite index
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS scheduled_calls (
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
        # NO composite index yet

    await engine.dispose()

    # Run migration — the composite index must be created even though table exists
    from scripts.migrate_call_scheduler import run_migration

    await run_migration(db_url)

    # Verify the composite index now exists
    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='ix_scheduled_calls_status_scheduled_at'"
            )
        )
        row = result.fetchone()
        assert row is not None, (
            "Composite index ix_scheduled_calls_status_scheduled_at must be created "
            "even when scheduled_calls table already exists (existing deployments)"
        )

    await engine2.dispose()


async def test_migration_is_idempotent(tmp_db_url: str):
    """Running migration twice does not raise errors."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    engine = create_async_engine(tmp_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Jaumpablo',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    await engine.dispose()

    from scripts.migrate_call_scheduler import run_migration

    # First run
    await run_migration(tmp_db_url)
    # Second run — must NOT raise
    await run_migration(tmp_db_url)

    engine2 = create_async_engine(tmp_db_url, echo=False)
    async with engine2.begin() as conn:
        table_result = await conn.execute(
            sqlalchemy.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_calls'"
            )
        )
        assert table_result.fetchone() is not None

        column_result = await conn.execute(
            sqlalchemy.text("PRAGMA table_info(clients)")
        )
        columns = {row[1] for row in column_result.fetchall()}
        assert "scheduler_enabled" in columns
        assert "scheduler_timezone" in columns

    await engine2.dispose()
