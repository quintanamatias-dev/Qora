"""Integration tests for call scheduler migration — Phase 6 (Task 5.1 RED).

Covers:
- Idempotent creation of scheduled_calls table
- Additive scheduler_* columns on clients table
- Running migration twice does not cause errors
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_url(tmp_path: Path) -> str:
    """Return a temporary SQLite URL for migration tests."""
    return f"sqlite+aiosqlite:///{tmp_path}/migration_test.db"


class _ListLogHandler(logging.Handler):
    """Collects log records in-memory — survives alembic/env.py's fileConfig()
    reconfiguration of the root logger (see usage below for why caplog doesn't).
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


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


# ---------------------------------------------------------------------------
# Phase C6b — RED: Alembic migration 20260727_0011_auto_dialer_active_lead_index
#
# Unlike the legacy scripts.migrate_call_scheduler tests above, this exercises
# the REAL Alembic migration chain (matching tests/jobs/test_executor.py's
# TestBackgroundJobsMigration pattern) so the pre-migration duplicate-resolution
# step and the partial unique index are proven against the actual schema.
# ---------------------------------------------------------------------------


class TestAutoDialerActiveLeadIndexMigration:
    """Slice 1 (D1/D3): duplicate in_progress rows retired, unique index created.

    The index and the CAS claim ship together (D3) because the existing bulk
    mark_due_calls_in_progress promotes ALL due rows in one flush — two pending
    rows for one lead would both promote, then IntegrityError on the second
    commit if the index existed without a pre-migration cleanup. This test
    proves the migration's own upgrade step resolves any duplicates that
    predate the index (D1: in_progress-only scope).
    """

    def _make_alembic_config(self, db_path):
        from alembic.config import Config

        backend_dir = Path(__file__).resolve().parent.parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        alembic_dir = backend_dir / "alembic"

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(alembic_dir))
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
        return cfg

    def _seed_client_lead_and_duplicate_in_progress_rows(self, db_path):
        """Seed one client, one lead, and two in_progress ScheduledCall rows
        for that same lead — the exact duplicate state D1 says is reachable
        today (auto_retry + tech_retry both in_progress for one lead).

        Returns (older_id, newer_id) — the migration must keep the newer one.
        """
        import sqlite3
        import uuid
        from datetime import datetime, timedelta, timezone

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        now = datetime.now(timezone.utc)
        older_at = (now - timedelta(hours=2)).isoformat()
        newer_at = (now - timedelta(minutes=10)).isoformat()

        cur.execute(
            "INSERT INTO clients (id, name, voice_id, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            ("dup-client", "Duplicate Test Client", "voice-1", now.isoformat()),
        )
        cur.execute(
            "INSERT INTO leads (id, client_id, name, phone, created_at, updated_at) "
            "VALUES (?, 'dup-client', 'Dup Lead', '+5491100000000', ?, ?)",
            ("dup-lead", now.isoformat(), now.isoformat()),
        )

        older_id = str(uuid.uuid4())
        newer_id = str(uuid.uuid4())
        for sc_id, scheduled_at, reason, created_at in (
            (older_id, older_at, "auto_retry", older_at),
            (newer_id, newer_at, "tech_retry", newer_at),
        ):
            cur.execute(
                "INSERT INTO scheduled_calls "
                "(id, client_id, lead_id, status, scheduled_at, trigger_reason, "
                " attempt_number, max_attempts, created_at, updated_at) "
                "VALUES (?, 'dup-client', 'dup-lead', 'in_progress', ?, ?, 1, 3, ?, ?)",
                (sc_id, scheduled_at, reason, created_at, created_at),
            )

        conn.commit()
        conn.close()
        return older_id, newer_id

    def test_duplicate_in_progress_rows_retired_and_index_created(self, tmp_path):
        """Two in_progress rows for one lead → one survives, the other is
        auto-resolved to failed, and the partial unique index now exists.

        Also asserts the operator-visible log includes the retired-row count
        (design.md — Migration Plan: "The migration logs the affected row
        count so the operator sees what was retired").

        Note: uses a directly-attached logging.Handler rather than pytest's
        `caplog` fixture — alembic/env.py calls fileConfig(alembic.ini) on
        every upgrade, which unconditionally resets level/handlers/propagate
        on every CHILD logger of "alembic" and "sqlalchemy" (regardless of
        disable_existing_loggers — see logging.config._handle_existing_loggers).
        The migration logs through "app.migrations.auto_dialer" specifically
        to avoid that reset; a handler attached to it survives across upgrades.
        """
        import sqlite3

        from alembic import command

        db_file = tmp_path / "test_auto_dialer_active_lead_index.db"
        cfg = self._make_alembic_config(db_file)

        # Upgrade to just before the new migration — full baseline schema exists.
        command.upgrade(cfg, "20260716_0010")

        older_id, newer_id = self._seed_client_lead_and_duplicate_in_progress_rows(
            db_file
        )

        log_handler = _ListLogHandler()
        migration_logger = logging.getLogger("app.migrations.auto_dialer")
        migration_logger.addHandler(log_handler)
        migration_logger.setLevel(logging.INFO)
        try:
            command.upgrade(cfg, "head")
        finally:
            migration_logger.removeHandler(log_handler)

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()

        cur.execute(
            "SELECT id, status, notes FROM scheduled_calls WHERE id = ?", (older_id,)
        )
        older_row = cur.fetchone()
        cur.execute(
            "SELECT id, status FROM scheduled_calls WHERE id = ?", (newer_id,)
        )
        newer_row = cur.fetchone()

        assert older_row is not None
        assert older_row[1] == "failed", (
            f"Older duplicate in_progress row must be auto-resolved to failed, "
            f"got status={older_row[1]!r}"
        )
        assert older_row[2] is not None and "auto-resolved" in older_row[2], (
            f"Retired row must carry an auto-resolved note, got notes={older_row[2]!r}"
        )

        assert newer_row is not None
        assert newer_row[1] == "in_progress", (
            f"Newer duplicate row must survive as the sole in_progress row for "
            f"the lead, got status={newer_row[1]!r}"
        )

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_scheduled_calls_active_lead'"
        )
        assert cur.fetchone() is not None, (
            "uq_scheduled_calls_active_lead partial unique index must exist after "
            "migration 20260727_0011"
        )
        conn.close()

        assert any(
            "retired" in record.getMessage().lower() and "1" in record.getMessage()
            for record in log_handler.records
        ), (
            f"Migration must log the operator-visible retired-row count. "
            f"Got messages: {[r.getMessage() for r in log_handler.records]}"
        )

    def test_no_duplicates_migration_is_a_no_op_on_data(self, tmp_path):
        """A single in_progress row per lead is untouched by the migration."""
        import sqlite3
        import uuid
        from datetime import datetime, timezone

        from alembic import command

        db_file = tmp_path / "test_auto_dialer_no_dup.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "20260716_0010")

        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clients (id, name, voice_id, is_active, created_at) "
            "VALUES ('solo-client', 'Solo Client', 'voice-1', 1, ?)",
            (now.isoformat(),),
        )
        cur.execute(
            "INSERT INTO leads (id, client_id, name, phone, created_at, updated_at) "
            "VALUES ('solo-lead', 'solo-client', 'Solo Lead', '+5491100000001', ?, ?)",
            (now.isoformat(), now.isoformat()),
        )
        sc_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO scheduled_calls "
            "(id, client_id, lead_id, status, scheduled_at, trigger_reason, "
            " attempt_number, max_attempts, created_at, updated_at) "
            "VALUES (?, 'solo-client', 'solo-lead', 'in_progress', ?, 'manual', 1, 3, ?, ?)",
            (sc_id, now.isoformat(), now.isoformat(), now.isoformat()),
        )
        conn.commit()
        conn.close()

        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT status FROM scheduled_calls WHERE id = ?", (sc_id,))
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "in_progress", (
            f"Solo in_progress row must be untouched, got status={row[0]!r}"
        )

    def test_downgrade_drops_index_only(self, tmp_path):
        """Downgrade drops the unique index; step 1 (data fix) is irreversible
        and documented as such in the migration docstring.
        """
        import sqlite3

        from alembic import command

        db_file = tmp_path / "test_auto_dialer_downgrade.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_scheduled_calls_active_lead'"
        )
        assert cur.fetchone() is not None
        conn.close()

        cfg2 = self._make_alembic_config(db_file)
        command.downgrade(cfg2, "20260716_0010")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_scheduled_calls_active_lead'"
        )
        assert cur.fetchone() is None, "downgrade must drop the partial unique index"
        conn.close()
