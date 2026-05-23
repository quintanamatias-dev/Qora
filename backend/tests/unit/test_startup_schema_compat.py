"""Unit tests for _ensure_startup_schema_compat() — idempotent startup migration.

Spec: sdd/unify-qora-agent-runtime-config/spec
Requirement: Migration backfills existing agents

Verifies:
- tts_speed, tts_stability, tts_similarity_boost columns are added to `agents`
  when they do not exist (old DB).
- Running the migration twice is idempotent (no error on second run).
- Existing rows get DEFAULT values from the ALTER TABLE statement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixture: fresh isolated SQLite DB (empty — no ORM init so we can simulate
# an "old" DB without TTS columns)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def old_agents_db(tmp_path: Path):
    """Create a minimal agents table WITHOUT tts_* columns (simulates old DB).

    Returns (engine, conn_str) so tests can run _ensure_startup_schema_compat on it.
    """
    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/old_agents.db"
    engine = create_async_engine(db_url, echo=False)

    # Create minimal tables WITHOUT tts_* columns (clients needed by schema compat check)
    async with engine.begin() as conn:
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                broker_name TEXT NOT NULL,
                analysis_language TEXT NOT NULL DEFAULT 'Spanish',
                created_at TEXT NOT NULL
            )
        """))
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                system_prompt TEXT,
                knowledge_base TEXT,
                model TEXT NOT NULL DEFAULT 'gpt-4o',
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 300,
                tools_enabled TEXT NOT NULL DEFAULT '[]',
                elevenlabs_agent_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """))
        # Insert a test row to verify DEFAULT backfill
        await conn.execute(sqlalchemy.text("""
            INSERT INTO agents (id, client_id, slug, name, voice_id, is_active, is_default, created_at)
            VALUES ('test-id-1', 'client-a', 'main-agent', 'Main Agent', 'v1', 1, 1, '2024-01-01T00:00:00')
        """))

    yield engine

    await engine.dispose()


# ---------------------------------------------------------------------------
# Fake db_module to pass into _ensure_startup_schema_compat
# ---------------------------------------------------------------------------


class _FakeDbModule:
    def __init__(self, engine):
        self.engine = engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_compat_adds_tts_columns_to_existing_agents_table(old_agents_db):
    """_ensure_startup_schema_compat() adds tts_speed/stability/similarity_boost when absent.

    GIVEN an existing agents table WITHOUT tts_* columns
    WHEN _ensure_startup_schema_compat() is called
    THEN the three columns MUST be added with their default values
    """
    import sqlalchemy
    from app.main import _ensure_startup_schema_compat

    fake_module = _FakeDbModule(old_agents_db)
    await _ensure_startup_schema_compat(fake_module)

    # Verify columns exist
    async with old_agents_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(agents)"))
        columns = {row[1] for row in result.fetchall()}

    assert "tts_speed" in columns, f"tts_speed not added. Got: {columns}"
    assert "tts_stability" in columns, f"tts_stability not added. Got: {columns}"
    assert "tts_similarity_boost" in columns, f"tts_similarity_boost not added. Got: {columns}"


@pytest.mark.asyncio
async def test_startup_compat_backfills_existing_row_with_defaults(old_agents_db):
    """Existing rows get DEFAULT values when TTS columns are added.

    GIVEN an existing agent row in the old table
    WHEN _ensure_startup_schema_compat() runs
    THEN the existing row MUST have tts_speed=0.95, tts_stability=0.4, tts_similarity_boost=0.75
    """
    import sqlalchemy
    from app.main import _ensure_startup_schema_compat

    fake_module = _FakeDbModule(old_agents_db)
    await _ensure_startup_schema_compat(fake_module)

    async with old_agents_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT tts_speed, tts_stability, tts_similarity_boost FROM agents WHERE id='test-id-1'"
        ))
        row = result.fetchone()

    assert row is not None
    assert row[0] == 0.95, f"Expected tts_speed=0.95, got {row[0]}"
    assert row[1] == 0.4, f"Expected tts_stability=0.4, got {row[1]}"
    assert row[2] == 0.75, f"Expected tts_similarity_boost=0.75, got {row[2]}"


@pytest.mark.asyncio
async def test_startup_compat_is_idempotent(old_agents_db):
    """Running _ensure_startup_schema_compat() twice does NOT raise an error.

    GIVEN the migration has already been applied
    WHEN _ensure_startup_schema_compat() is called a second time
    THEN no exception is raised (idempotent)
    """
    from app.main import _ensure_startup_schema_compat

    fake_module = _FakeDbModule(old_agents_db)

    # First run
    await _ensure_startup_schema_compat(fake_module)
    # Second run — must not raise
    await _ensure_startup_schema_compat(fake_module)


@pytest.mark.asyncio
async def test_startup_compat_does_not_touch_existing_tts_values(tmp_path: Path):
    """If TTS columns already exist with values, the migration leaves them untouched.

    GIVEN an agents table that ALREADY has tts_speed=1.2 for an existing agent
    WHEN _ensure_startup_schema_compat() runs
    THEN the tts_speed value MUST remain 1.2 (not overwritten to 0.95)
    """
    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.main import _ensure_startup_schema_compat

    db_url = f"sqlite+aiosqlite:///{tmp_path}/already_migrated.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        # Clients table needed by _ensure_startup_schema_compat
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                broker_name TEXT NOT NULL,
                analysis_language TEXT NOT NULL DEFAULT 'Spanish',
                created_at TEXT NOT NULL
            )
        """))
        # Agents table already has tts columns
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                voice_id TEXT NOT NULL,
                system_prompt TEXT,
                knowledge_base TEXT,
                model TEXT NOT NULL DEFAULT 'gpt-4o',
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 300,
                tools_enabled TEXT NOT NULL DEFAULT '[]',
                elevenlabs_agent_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                tts_speed REAL NOT NULL DEFAULT 0.95,
                tts_stability REAL NOT NULL DEFAULT 0.4,
                tts_similarity_boost REAL NOT NULL DEFAULT 0.75
            )
        """))
        await conn.execute(sqlalchemy.text("""
            INSERT INTO agents (id, client_id, slug, name, voice_id, is_active, is_default,
                                created_at, tts_speed, tts_stability, tts_similarity_boost)
            VALUES ('test-id-2', 'client-b', 'aria', 'Aria', 'v2', 1, 1,
                    '2024-01-01T00:00:00', 1.2, 0.5, 0.8)
        """))

    fake_module = _FakeDbModule(engine)
    await _ensure_startup_schema_compat(fake_module)

    async with engine.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT tts_speed, tts_stability, tts_similarity_boost FROM agents WHERE id='test-id-2'"
        ))
        row = result.fetchone()

    await engine.dispose()

    assert row[0] == 1.2, f"tts_speed must remain 1.2, got {row[0]}"
    assert row[1] == 0.5, f"tts_stability must remain 0.5, got {row[1]}"
    assert row[2] == 0.8, f"tts_similarity_boost must remain 0.8, got {row[2]}"
