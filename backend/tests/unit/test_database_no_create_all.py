"""Tests that init_db() no longer calls Base.metadata.create_all().

Task 2.1 TDD — After PR 2 cutover, init_db() must:
  - Initialize the async engine and session factory
  - Enable WAL mode via PRAGMA
  - NOT call create_all (schema is guaranteed by pre-start migration)

Spec scenarios:
  - init_db() does not create tables on a bare engine (no create_all)
  - init_db() initializes engine and session factory
  - init_db() enables WAL mode (PRAGMA journal_mode=WAL)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_init_db_does_not_call_create_all(test_settings):
    """init_db() MUST NOT call Base.metadata.create_all() after cutover.

    GIVEN init_db() is called with valid settings
    WHEN the function runs
    THEN Base.metadata.create_all must NOT be invoked (schema comes from migrations)
    """
    from app.core import database as db_module

    with patch.object(db_module.Base.metadata, "create_all") as mock_create_all:
        # Also patch the engine.begin() context to check run_sync wasn't called
        called_run_sync_with_create_all = False

        class _FakeConn:
            async def run_sync(self, fn):
                nonlocal called_run_sync_with_create_all
                if fn is db_module.Base.metadata.create_all:
                    called_run_sync_with_create_all = True
                return None

            async def execute(self, stmt):
                return MagicMock(fetchall=lambda: [])

            async def commit(self):
                pass

        class _FakeBeginCtx:
            async def __aenter__(self):
                return _FakeConn()

            async def __aexit__(self, *args):
                pass

        class _FakeConnCtx:
            async def __aenter__(self):
                return _FakeConn()

            async def __aexit__(self, *args):
                pass

        class _FakeEngine:
            def begin(self):
                return _FakeBeginCtx()

            def connect(self):
                return _FakeConnCtx()

            async def dispose(self):
                pass

        # Temporarily replace create_engine_and_session to inject fake engine
        original_ces = db_module.create_engine_and_session

        def _fake_ces(url):
            db_module.engine = _FakeEngine()
            db_module.async_session_factory = MagicMock()
            return db_module.engine, db_module.async_session_factory

        db_module.create_engine_and_session = _fake_ces
        try:
            await db_module.init_db(test_settings)
        finally:
            db_module.create_engine_and_session = original_ces
            await db_module.close_db()

        # create_all must NOT have been called (neither directly nor via run_sync)
        mock_create_all.assert_not_called()
        assert not called_run_sync_with_create_all, (
            "init_db() must NOT call create_all via run_sync after PR 2 cutover"
        )


@pytest.mark.asyncio
async def test_init_db_initializes_engine_and_session(test_settings):
    """init_db() MUST still initialize the engine and session factory.

    GIVEN valid settings
    WHEN init_db() is called
    THEN db_module.engine and db_module.async_session_factory must be non-None
    """
    from app.core import database as db_module
    from tests.helpers.migrations import apply_migrations

    # Apply migrations first so the DB has a schema for WAL pragmas to work on
    apply_migrations(test_settings.database_url)

    await db_module.init_db(test_settings)

    try:
        assert db_module.engine is not None, "engine must be initialized by init_db()"
        assert db_module.async_session_factory is not None, (
            "async_session_factory must be initialized by init_db()"
        )
    finally:
        await db_module.close_db()
