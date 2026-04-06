"""SQLAlchemy async engine and session factory for V1-CallCenter."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

# Module-level singletons, initialized during lifespan startup
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine_and_session(settings: Settings) -> tuple:
    """Create the async engine and session factory from settings.

    Returns:
        Tuple of (engine, async_session_factory).
    """
    global engine, async_session_factory

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    return engine, async_session_factory


async def init_db(settings: Settings) -> None:
    """Initialize database engine, session factory, and create all tables."""
    global engine, async_session_factory

    create_engine_and_session(settings)

    # Import models so they are registered with Base.metadata
    from app.db.models import Base  # noqa: F401

    async with engine.begin() as conn:  # type: ignore[union-attr]
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the engine and clean up resources."""
    global engine, async_session_factory

    if engine is not None:
        await engine.dispose()
        engine = None
        async_session_factory = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session with automatic cleanup.

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
