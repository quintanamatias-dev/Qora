"""Pytest configuration and shared fixtures for QORA backend tests.

Provides:
- Async SQLite engine (isolated per test, schema created via Alembic migrations)
- App factory with QORA lifespan
- QORA Settings fixture (no Twilio dependencies)
- respx mocks for OpenAI/ElevenLabs
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Backup gate bypass for test environments
# ---------------------------------------------------------------------------
# scripts/migrate.py requires a today's backup before touching any existing DB
# (spec: Baseline Backup and Verification). Test environments use ephemeral
# tmp_path DBs with no real data, so the backup gate must be bypassed globally.
# Production workflows and the smoke_stamped_db fixture set this explicitly.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_backup_check_in_tests(monkeypatch):
    """Bypass the migrate.py backup gate for all tests.

    Test DBs are ephemeral (tmp_path) and never need a backup. Without this,
    any test that calls run_migrations() against an existing DB path would
    receive sys.exit(1) because no today's backup exists at the tmp_path.
    """
    monkeypatch.setenv("QORA_SKIP_BACKUP_CHECK", "1")


# ---------------------------------------------------------------------------
# Session store isolation — VSC-8 Fix A
# ---------------------------------------------------------------------------
# The module-level session_store singleton is shared across all tests in a process.
# Without cleanup between tests, find_by_client_lead() can find leftover sessions
# from earlier tests and skip creating new DB sessions — breaking tests that expect
# a new CallSession to be created on every request.
#
# This autouse fixture clears the singleton before every test automatically.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_session_store_between_tests():
    """Clear the global session_store before each test to prevent state leakage."""
    from app.voice.session import session_store

    session_store._sessions.clear()
    yield
    session_store._sessions.clear()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings(tmp_path: Path):
    """Create QORA Settings pointing at an isolated SQLite file."""
    from app.core.config import Settings

    db_url = f"sqlite+aiosqlite:///{tmp_path}/qora_test.db"
    return Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=db_url,
        debug=False,
    )


# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(test_settings):
    """Async SQLite engine with all QORA tables created via Alembic migrations.

    Uses apply_migrations() instead of Base.metadata.create_all() so that
    test DBs follow the production schema path and catch migration drift.

    Design: phase-b-db-migration-foundation/design.md — Test DB creation decision.
    """
    from app.core import database as db_module
    from tests.helpers.migrations import apply_migrations

    # 1. Run Alembic upgrade head — creates schema and stamps alembic_version
    apply_migrations(test_settings.database_url)

    # 2. Initialize the async engine and session factory (no DDL — schema already exists)
    db_module.create_engine_and_session(test_settings.database_url)

    # 3. Register all ORM models with Base.metadata (required for session queries)
    import app.tenants.models  # noqa: F401
    import app.leads.models  # noqa: F401
    import app.calls.models  # noqa: F401
    import app.scheduler.models  # noqa: F401

    # 4. Enable WAL mode for concurrent read/write support (matches production init_db)
    from sqlalchemy import text
    async with db_module.engine.connect() as raw_conn:  # type: ignore[union-attr]
        await raw_conn.execute(text("PRAGMA journal_mode=WAL"))
        await raw_conn.execute(text("PRAGMA busy_timeout=5000"))
        await raw_conn.commit()

    yield db_module
    await db_module.close_db()


@pytest_asyncio.fixture
async def db_session(test_settings, db_engine):
    """Yield a single async session for a test. Auto-commits on success."""
    assert db_engine.async_session_factory is not None, "DB not initialized"
    async with db_engine.async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# OpenAI streaming mock (SSE)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_stream():
    """Return a factory for fake OpenAI SSE chunks."""

    def make_stream(tokens: list[str]):
        """Yield fake SSE chunk objects for each token."""

        async def _gen():
            for token in tokens:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = token
                chunk.choices[0].delta.tool_calls = None
                chunk.choices[0].finish_reason = None
                yield chunk
            # Final chunk with finish_reason
            done_chunk = MagicMock()
            done_chunk.choices = [MagicMock()]
            done_chunk.choices[0].delta.content = None
            done_chunk.choices[0].delta.tool_calls = None
            done_chunk.choices[0].finish_reason = "stop"
            yield done_chunk

        return _gen()

    return make_stream
