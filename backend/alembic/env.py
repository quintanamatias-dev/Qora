"""Alembic migration environment for Qora backend.

Uses async SQLAlchemy with SQLite batch mode (render_as_batch=True) to handle
SQLite's limited ALTER TABLE support. Compatible with aiosqlite driver.

Design: phase-b-db-migration-foundation/design.md
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ---------------------------------------------------------------------------
# Load all ORM model modules to register them with Base.metadata BEFORE
# Alembic reads target_metadata. Order matters: models with FKs to other
# models must be imported after the tables they reference are registered.
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

# Ensure the backend/ directory is on sys.path so app.* imports resolve
# when running alembic CLI from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import app.tenants.models  # noqa: E402,F401 — registers clients + agents tables
import app.leads.models  # noqa: E402,F401 — registers leads, lead_profile_facts, lead_custom_fields, lead_interest_history
import app.calls.models  # noqa: E402,F401 — registers call_sessions, transcript_turns, call_analyses
import app.scheduler.models  # noqa: E402,F401 — registers scheduled_calls

from app.core.database import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values
# ---------------------------------------------------------------------------
config = context.config

# Interpret the alembic.ini logging section if present.
# disable_existing_loggers=False preserves loggers created before this call
# (e.g. app.* loggers already registered in long-running processes or test
# sessions). Without this, fileConfig() silently disables all pre-existing
# loggers, which breaks caplog-based tests that run after the first Alembic
# migration call in the same process.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# target_metadata is the SQLAlchemy metadata Alembic diffs against the DB
# for autogenerate (alembic revision --autogenerate).
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Allow DATABASE_URL env var to override the ini-file URL at runtime.
# scripts/migrate.py may also set the URL on the Config object before calling
# alembic.command.upgrade(); that takes precedence over this env check.
# ---------------------------------------------------------------------------
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    # Alembic CLI uses sync drivers; keep async driver for programmatic use.
    config.set_main_option("sqlalchemy.url", _db_url)


# ---------------------------------------------------------------------------
# Offline migration mode (generates SQL without connecting to the DB)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout/file.

    Useful for generating migration SQL to review or apply manually.
    Does not require a live database connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite batch mode required for ALTER TABLE operations
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration mode (async, connects to the real DB)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Execute pending migrations using the provided synchronous connection.

    Called inside asyncio via run_sync() — this is the sync callback
    that Alembic's context.run_migrations() expects.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite batch mode: handles ALTER TABLE by table rebuild.
        # Required for any column-level changes in SQLite.
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine from config and drive migrations asynchronously.

    Uses NullPool to prevent connection pooling in a migration context
    (safe for short-lived migration scripts).
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode — drives the async runner."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch: offline vs online based on Alembic context
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
