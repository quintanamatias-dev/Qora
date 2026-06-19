"""QORA — Async SQLAlchemy engine and session factory.

Reuses the pattern from the original db/engine.py but scoped to QORA models.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# Base class for all QORA models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all QORA SQLAlchemy models."""


# ---------------------------------------------------------------------------
# Module-level singletons (initialized during lifespan startup)
# ---------------------------------------------------------------------------

engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_and_session(database_url: str) -> tuple:
    """Create async engine and session factory from a DB URL.

    Returns:
        Tuple of (engine, async_session_factory).
    """
    global engine, async_session_factory

    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    return engine, async_session_factory


async def init_db(settings) -> None:
    """Initialize database engine and session factory.

    Schema creation is handled by the pre-start migration command
    (python scripts/migrate.py) via Alembic upgrade head. This function
    only creates the async engine, session factory, and enables SQLite pragmas.

    Design: phase-b-db-migration-foundation/design.md — init_db no longer
    calls create_all; the migration path guarantees the schema before startup.
    """
    global engine, async_session_factory

    create_engine_and_session(settings.database_url)

    # Import models to register them with Base.metadata (needed for ORM queries)
    import app.tenants.models  # noqa: F401
    import app.leads.models  # noqa: F401
    import app.calls.models  # noqa: F401
    import app.scheduler.models  # noqa: F401

    # Enable WAL mode for concurrent read/write support and set busy timeout.
    # Schema must already exist (from pre-start migration) before these pragmas run.
    async with engine.connect() as raw_conn:  # type: ignore[union-attr]
        await raw_conn.execute(text("PRAGMA journal_mode=WAL"))
        await raw_conn.execute(text("PRAGMA busy_timeout=5000"))
        await raw_conn.commit()


async def close_db() -> None:
    """Dispose of the engine and clean up resources."""
    global engine, async_session_factory

    if engine is not None:
        await engine.dispose()
        engine = None
        async_session_factory = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session with automatic commit/rollback.

    Usage:
        async with get_session() as session:
            session.add(obj)
            await session.commit()
    """
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
