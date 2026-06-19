"""Migration-based test DB helper.

Provides apply_migrations(database_url) — a synchronous wrapper that runs
alembic upgrade head against a given database URL.

Design: phase-b-db-migration-foundation/design.md — Test DB creation decision.

Why: Tests must use the production schema path (Alembic) rather than
Base.metadata.create_all() to catch migration drift and ensure parity between
test DBs and production DBs.

Thread-safety note:
    alembic/env.py uses asyncio.run() which cannot be called while a running
    event loop exists (e.g. pytest-asyncio). When called from an async context,
    apply_migrations runs the Alembic upgrade in a separate thread via
    concurrent.futures.ThreadPoolExecutor so asyncio.run() gets a fresh loop.

Usage (sync context):
    from tests.helpers.migrations import apply_migrations
    apply_migrations("sqlite+aiosqlite:///./test.db")

Usage (async context — same API, thread-transparent):
    from tests.helpers.migrations import apply_migrations
    apply_migrations("sqlite+aiosqlite:///./test.db")
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path


def _run_alembic_upgrade(database_url: str) -> None:
    """Execute alembic upgrade head in the current thread.

    This function must run in a thread that does NOT have a running event loop
    so that alembic/env.py's asyncio.run() can create a fresh one.
    """
    from alembic.config import Config
    from alembic import command

    # Resolve alembic.ini from backend/ — two levels up from this file:
    # backend/tests/helpers/migrations.py → backend/
    backend_dir = Path(__file__).resolve().parent.parent.parent
    alembic_ini = backend_dir / "alembic.ini"

    alembic_cfg = Config(str(alembic_ini))

    # Override script_location to absolute path so it resolves correctly
    # regardless of process cwd (same pattern as scripts/migrate.py).
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # Point Alembic at the test DB URL instead of the ini-file default.
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(alembic_cfg, "head")


async def init_db_with_migrations(db_module, settings) -> None:
    """Run Alembic migrations then initialize the DB engine and session factory.

    Convenience wrapper for test fixtures that previously called db_module.init_db()
    directly. After PR 2 cutover, init_db() no longer calls create_all(). Test
    fixtures must call apply_migrations() first so the schema exists before seeding.

    This helper combines both steps safely:
      1. apply_migrations(database_url) — Alembic upgrade head (sync, thread-safe)
      2. db_module.init_db(settings) — creates engine + session factory + WAL pragmas

    Args:
        db_module: The app.core.database module (imported by the caller).
        settings: QORA Settings instance with the test database_url.

    Example:
        from tests.helpers.migrations import init_db_with_migrations
        await init_db_with_migrations(db_module, test_settings)
        # Now db_module.async_session_factory is ready for use
    """
    apply_migrations(settings.database_url)
    await db_module.init_db(settings)


def apply_migrations(database_url: str) -> None:
    """Run alembic upgrade head against the given database URL (sync wrapper).

    Creates the full Qora baseline schema (all 10 tables + alembic_version).
    Safe to call multiple times — idempotent when already at head.

    When called from a context with a running asyncio event loop (e.g. inside
    a pytest-asyncio async fixture), the upgrade runs in a ThreadPoolExecutor
    so alembic/env.py's asyncio.run() gets a fresh, non-conflicting event loop.

    Args:
        database_url: SQLAlchemy async URL, e.g.
            "sqlite+aiosqlite:////abs/path/test.db"
            "sqlite+aiosqlite:///./relative/test.db"

    Raises:
        Exception: If the migration fails (propagated from Alembic).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Running inside an active event loop (e.g. pytest-asyncio async fixture).
        # Delegate to a thread so alembic/env.py's asyncio.run() gets a fresh loop.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_alembic_upgrade, database_url)
            future.result()  # re-raise any exception from the thread
    else:
        # No running event loop — safe to run directly.
        _run_alembic_upgrade(database_url)
