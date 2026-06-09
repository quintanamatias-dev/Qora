"""Startup migration tests for lead_custom_fields table and data copy.

Spec: dynamic-lead-fields — CF-10, CF-11
Test layer: Unit (isolated SQLite, _FakeDbModule pattern)

TDD RED phase: tests must fail until _ensure_startup_schema_compat
creates the lead_custom_fields table and copies legacy column data.

Coverage:
- CF-10: CREATE TABLE IF NOT EXISTS lead_custom_fields (idempotent)
- CF-11: One-time data copy from legacy columns, guarded by migration marker
- AC-3: Migration runs exactly once per DB
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDbModule:
    """Minimal db_module substitute accepted by _ensure_startup_schema_compat."""

    def __init__(self, engine):
        self.engine = engine


# Legacy columns we must copy to lead_custom_fields
LEGACY_COLUMNS = ["car_make", "car_model", "car_year", "current_insurance", "age", "zona"]


# ---------------------------------------------------------------------------
# Fixture: DB that has leads with legacy column data, no lead_custom_fields table
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def legacy_db(tmp_path: Path):
    """SQLite DB with existing leads table (legacy columns) but NO lead_custom_fields.

    Simulates a DB created before WU-1 — the state that the startup migration must handle.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/legacy.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        # clients (FK target)
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                analysis_language TEXT NOT NULL DEFAULT 'Spanish',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))
        await conn.execute(sqlalchemy.text(
            "INSERT INTO clients (id, name) VALUES ('quintana-seguros', 'Quintana Seguros')"
        ))

        # agents (required by _ensure_startup_schema_compat PRAGMA loop)
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                slug TEXT NOT NULL DEFAULT 'main',
                name TEXT NOT NULL,
                voice_id TEXT NOT NULL DEFAULT 'v1',
                system_prompt TEXT,
                knowledge_base TEXT,
                model TEXT NOT NULL DEFAULT 'gpt-4o',
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 300,
                tools_enabled TEXT NOT NULL DEFAULT '[]',
                elevenlabs_agent_id TEXT,
                tts_speed REAL NOT NULL DEFAULT 0.95,
                tts_stability REAL NOT NULL DEFAULT 0.4,
                tts_similarity_boost REAL NOT NULL DEFAULT 0.75,
                soft_timeout_seconds REAL DEFAULT NULL,
                soft_timeout_message TEXT DEFAULT NULL,
                soft_timeout_use_llm INTEGER DEFAULT NULL,
                tts_model TEXT NOT NULL DEFAULT 'eleven_flash_v2_5',
                elevenlabs_sync_status TEXT DEFAULT NULL,
                elevenlabs_last_synced_at DATETIME DEFAULT NULL,
                tool_config TEXT DEFAULT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))

        # leads with legacy columns
        await conn.execute(sqlalchemy.text("""
            CREATE TABLE leads (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                call_count INTEGER NOT NULL DEFAULT 0,
                car_make TEXT DEFAULT NULL,
                car_model TEXT DEFAULT NULL,
                car_year INTEGER DEFAULT NULL,
                current_insurance TEXT DEFAULT NULL,
                age INTEGER DEFAULT NULL,
                zona TEXT DEFAULT NULL,
                external_crm_id TEXT DEFAULT NULL,
                external_lead_id INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))

        # Insert a lead with all legacy fields populated
        await conn.execute(sqlalchemy.text("""
            INSERT INTO leads (id, client_id, name, phone, car_make, car_model, car_year, current_insurance, age, zona)
            VALUES ('lead-1', 'quintana-seguros', 'Ana García', '+5491100000001',
                    'Toyota', 'Corolla', 2021, 'Mapfre', 35, 'Norte')
        """))

        # Insert a lead with only some legacy fields
        await conn.execute(sqlalchemy.text("""
            INSERT INTO leads (id, client_id, name, phone, car_make, car_year)
            VALUES ('lead-2', 'quintana-seguros', 'Carlos López', '+5491100000002',
                    'Ford', 2019)
        """))

        # Insert a lead with NO legacy fields (all NULL)
        await conn.execute(sqlalchemy.text("""
            INSERT INTO leads (id, client_id, name, phone)
            VALUES ('lead-3', 'quintana-seguros', 'María Pérez', '+5491100000003')
        """))

    yield engine

    await engine.dispose()


# ---------------------------------------------------------------------------
# CF-10: Table creation is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_compat_creates_lead_custom_fields_table(legacy_db):
    """CF-10: _ensure_startup_schema_compat creates lead_custom_fields if absent.

    GIVEN a DB without lead_custom_fields table
    WHEN _ensure_startup_schema_compat() runs
    THEN the lead_custom_fields table MUST exist
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lead_custom_fields'"
        ))
        row = result.fetchone()

    assert row is not None, "lead_custom_fields table must be created by startup migration"


@pytest.mark.asyncio
async def test_startup_compat_table_creation_idempotent(legacy_db):
    """CF-10: Running _ensure_startup_schema_compat() twice does not raise.

    Second run must be a no-op (CREATE TABLE IF NOT EXISTS).
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)
    # Second run — must not raise
    await _ensure_startup_schema_compat(fake)


@pytest.mark.asyncio
async def test_lead_custom_fields_table_has_correct_schema(legacy_db):
    """CF-10: lead_custom_fields has the required columns after creation."""
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(lead_custom_fields)"))
        columns = {row[1] for row in result.fetchall()}

    required = {"id", "lead_id", "client_id", "field_key", "field_value", "field_type", "created_at", "updated_at"}
    missing = required - columns
    assert not missing, f"lead_custom_fields missing columns: {missing}"


# ---------------------------------------------------------------------------
# CF-11: One-time data copy from legacy columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_migration_copies_legacy_columns_to_custom_fields(legacy_db):
    """CF-11: Existing lead column data is copied to lead_custom_fields on first run.

    GIVEN lead-1 has car_make='Toyota', car_model='Corolla', car_year=2021,
          current_insurance='Mapfre', age=35, zona='Norte'
    WHEN _ensure_startup_schema_compat() runs
    THEN lead_custom_fields rows exist for each non-null legacy column
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT field_key, field_value FROM lead_custom_fields "
            "WHERE lead_id='lead-1' AND client_id='quintana-seguros' "
            "AND field_key != '_migration_v1' "
            "ORDER BY field_key"
        ))
        rows = {row[0]: row[1] for row in result.fetchall()}

    assert rows.get("car_make") == "Toyota"
    assert rows.get("car_model") == "Corolla"
    assert rows.get("car_year") == "2021"
    assert rows.get("current_insurance") == "Mapfre"
    assert rows.get("age") == "35"
    assert rows.get("zona") == "Norte"


@pytest.mark.asyncio
async def test_startup_migration_skips_null_legacy_columns(legacy_db):
    """CF-11: NULL legacy columns are NOT copied as custom fields rows.

    GIVEN lead-3 has all legacy columns as NULL
    WHEN _ensure_startup_schema_compat() runs
    THEN no custom field rows are created for lead-3 (except possibly the marker)
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT COUNT(*) FROM lead_custom_fields "
            "WHERE lead_id='lead-3' AND field_key != '_migration_v1'"
        ))
        count = result.scalar()

    assert count == 0, f"lead-3 should have no custom fields (all NULL), got {count}"


@pytest.mark.asyncio
async def test_startup_migration_sets_marker_after_copy(legacy_db):
    """CF-11/AC-3: A migration marker row is inserted after the data copy.

    GIVEN migration has not run
    WHEN _ensure_startup_schema_compat() runs
    THEN a row with field_key='_migration_v1' and field_value='done' exists
         (prevents re-running the copy)
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT field_value FROM lead_custom_fields "
            "WHERE field_key='_migration_v1' "
            "LIMIT 1"
        ))
        row = result.fetchone()

    assert row is not None, "Migration marker row must exist after migration runs"
    assert row[0] == "done", f"Migration marker value must be 'done', got {row[0]!r}"


@pytest.mark.asyncio
async def test_startup_migration_is_idempotent_no_duplicate_rows(legacy_db):
    """CF-11/AC-3: Running the migration twice must NOT duplicate custom field rows.

    GIVEN migration has already run
    WHEN _ensure_startup_schema_compat() runs again
    THEN the number of custom field rows for lead-1 is unchanged
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT COUNT(*) FROM lead_custom_fields WHERE lead_id='lead-1' AND field_key != '_migration_v1'"
        ))
        count_first = result.scalar()

    # Second run
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT COUNT(*) FROM lead_custom_fields WHERE lead_id='lead-1' AND field_key != '_migration_v1'"
        ))
        count_second = result.scalar()

    assert count_first == count_second, (
        f"Second migration run must not add duplicate rows. "
        f"First: {count_first}, Second: {count_second}"
    )


@pytest.mark.asyncio
async def test_startup_migration_partial_legacy_columns(legacy_db):
    """CF-11: Lead with only some legacy columns gets only those copied.

    GIVEN lead-2 has car_make='Ford', car_year=2019, other columns NULL
    WHEN migration runs
    THEN only car_make and car_year rows are created for lead-2
    """
    from app.main import _ensure_startup_schema_compat

    fake = _FakeDbModule(legacy_db)
    await _ensure_startup_schema_compat(fake)

    async with legacy_db.begin() as conn:
        result = await conn.execute(sqlalchemy.text(
            "SELECT field_key, field_value FROM lead_custom_fields "
            "WHERE lead_id='lead-2' AND client_id='quintana-seguros' AND field_key != '_migration_v1' "
            "ORDER BY field_key"
        ))
        rows = {row[0]: row[1] for row in result.fetchall()}

    assert rows.get("car_make") == "Ford"
    assert rows.get("car_year") == "2019"
    # NULL columns must not be copied
    assert "car_model" not in rows
    assert "current_insurance" not in rows
    assert "age" not in rows
    assert "zona" not in rows
