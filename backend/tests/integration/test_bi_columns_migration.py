"""Integration tests for scripts/migrate_bi_columns.py.

TDD RED → GREEN → TRIANGULATE → REFACTOR

Covers (task 2.1):
- 5 nullable columns created on call_analyses
- 2 indexes created (primary_objection_category, primary_pain_category)
- Idempotent: double-run produces no errors, columns/indexes still present
- Backfill: existing rows with JSON objections/pain_points/service_issues get
  denormalized columns populated correctly
- Backfill: rows with empty JSON arrays get 0 count / null primary category

Acceptance criteria: call-analysis-storage denormalized column scenarios.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixture: isolated DB with pre-existing call_analyses rows
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def migration_db(tmp_path: Path):
    """DB with call_analyses rows containing JSON objections/pain_points/service_issues."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/bi_migration_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.service import create_session
        from app.calls.models import CallAnalysis

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead A",
            phone="+5411000001",
            lead_id="lead-bi-a",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead B",
            phone="+5411000002",
            lead_id="lead-bi-b",
        )

        cs1 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-bi-a",
            session_id="sess-bi-1",
        )
        cs2 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-bi-b",
            session_id="sess-bi-2",
        )
        cs3 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-bi-a",
            session_id="sess-bi-3",
        )

        # Row 1: 2 objections (price=primary), 1 pain point (service_quality=primary), 2 service issues
        ca1 = CallAnalysis(
            id="ca-bi-1",
            session_id="sess-bi-1",
            lead_id="lead-bi-a",
            client_id="quintana-seguros",
            objections=json.dumps(
                [
                    {"category": "price", "is_primary": True, "strength": "hard"},
                    {"category": "current_provider", "is_primary": False, "strength": "soft"},
                ]
            ),
            pain_points=json.dumps(
                [
                    {"category": "service_quality", "is_primary": True, "description": "Bad service"},
                ]
            ),
            service_issues=json.dumps(
                [
                    {"category": "billing", "description": "Wrong amount"},
                    {"category": "response_time", "description": "Too slow"},
                ]
            ),
        )

        # Row 2: empty arrays
        ca2 = CallAnalysis(
            id="ca-bi-2",
            session_id="sess-bi-2",
            lead_id="lead-bi-b",
            client_id="quintana-seguros",
        )

        # Row 3: 1 objection (no primary flag), no pain points, 1 service issue
        ca3 = CallAnalysis(
            id="ca-bi-3",
            session_id="sess-bi-3",
            lead_id="lead-bi-a",
            client_id="quintana-seguros",
            objections=json.dumps(
                [
                    {"category": "price", "is_primary": False, "strength": "soft"},
                ]
            ),
            service_issues=json.dumps(
                [
                    {"category": "billing", "description": "Overcharged"},
                ]
            ),
        )

        sess.add_all([ca1, ca2, ca3])
        await sess.commit()

    yield db_module, str(settings.database_url)

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Fixture: TRUE old-schema DB (call_analyses WITHOUT the 5 BI columns/indexes)
# ---------------------------------------------------------------------------
#
# The `migration_db` fixture above uses init_db()/Base.metadata.create_all, so
# the ORM model (which already declares the 5 BI columns + 2 indexes) creates a
# table that ALREADY has them. That proves backfill, but it never exercises the
# migration's column/index *creation* path — every ADD COLUMN is a no-op skip.
#
# This fixture builds the pre-PR2 schema by hand with raw SQL: a call_analyses
# table that genuinely lacks the 5 BI columns and 2 indexes. Running the
# migration against it forces the real ALTER TABLE ADD COLUMN + CREATE INDEX
# paths, proving old-schema upgrades work end to end.


# Minimal pre-PR2 call_analyses schema: the columns the migration reads
# (objections, pain_points, service_issues) plus id, deliberately WITHOUT the
# 5 denormalized BI columns and their 2 indexes.
_OLD_SCHEMA_DDL = """
CREATE TABLE call_analyses (
    id VARCHAR NOT NULL PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    lead_id VARCHAR,
    client_id VARCHAR NOT NULL,
    objections TEXT NOT NULL DEFAULT '[]',
    pain_points TEXT NOT NULL DEFAULT '[]',
    service_issues TEXT NOT NULL DEFAULT '[]'
)
"""

_BI_COLUMNS = {
    "primary_objection_category",
    "primary_pain_category",
    "objections_count",
    "pain_points_count",
    "service_issues_count",
}

_BI_INDEXES = {
    "ix_ca_primary_objection_category",
    "ix_ca_primary_pain_category",
}


@pytest_asyncio.fixture
async def old_schema_db(tmp_path: Path):
    """DB whose call_analyses table predates PR2 — no BI columns, no BI indexes.

    Built with raw DDL (NOT Base.metadata.create_all) so the migration's
    column/index creation path is genuinely exercised.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/bi_old_schema_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(text(_OLD_SCHEMA_DDL))

        # Row 1: 2 objections (price=primary), 1 pain point (service_quality=primary),
        # 2 service issues — mirrors ca-bi-1 in migration_db.
        await conn.execute(
            text(
                "INSERT INTO call_analyses "
                "(id, session_id, lead_id, client_id, objections, pain_points, service_issues) "
                "VALUES (:id, :sid, :lid, :cid, :obj, :pain, :svc)"
            ),
            {
                "id": "old-ca-1",
                "sid": "old-sess-1",
                "lid": "old-lead-a",
                "cid": "quintana-seguros",
                "obj": json.dumps(
                    [
                        {"category": "price", "is_primary": True, "strength": "hard"},
                        {"category": "current_provider", "is_primary": False, "strength": "soft"},
                    ]
                ),
                "pain": json.dumps(
                    [{"category": "service_quality", "is_primary": True, "description": "Bad service"}]
                ),
                "svc": json.dumps(
                    [
                        {"category": "billing", "description": "Wrong amount"},
                        {"category": "response_time", "description": "Too slow"},
                    ]
                ),
            },
        )

        # Row 2: all empty arrays — mirrors ca-bi-2.
        await conn.execute(
            text(
                "INSERT INTO call_analyses "
                "(id, session_id, lead_id, client_id) "
                "VALUES (:id, :sid, :lid, :cid)"
            ),
            {
                "id": "old-ca-2",
                "sid": "old-sess-2",
                "lid": "old-lead-b",
                "cid": "quintana-seguros",
            },
        )

    await engine.dispose()

    yield db_url


# ---------------------------------------------------------------------------
# Helper: read PRAGMA table_info to check columns
# ---------------------------------------------------------------------------


async def _get_columns(engine, table: str) -> set[str]:
    """Return the set of column names for the given table."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(engine, echo=False)
    async with eng.connect() as conn:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        rows = result.fetchall()
    await eng.dispose()
    return {row[1] for row in rows}


async def _get_indexes(engine, table: str) -> set[str]:
    """Return index names for the given table."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(engine, echo=False)
    async with eng.connect() as conn:
        result = await conn.execute(text(f"PRAGMA index_list({table})"))
        rows = result.fetchall()
    await eng.dispose()
    return {row[1] for row in rows}


async def _get_ca_row(db_module, ca_id: str) -> dict:
    """Fetch a call_analyses row as a dict."""
    from sqlalchemy import text

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            text("SELECT * FROM call_analyses WHERE id = :id"),
            {"id": ca_id},
        )
        row = result.mappings().fetchone()
        assert row is not None, f"call_analyses row {ca_id!r} not found"
        return dict(row)


async def _get_ca_row_by_url(db_url: str, ca_id: str) -> dict:
    """Fetch a call_analyses row as a dict using a standalone engine (no init_db)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(db_url, echo=False)
    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM call_analyses WHERE id = :id"),
            {"id": ca_id},
        )
        row = result.mappings().fetchone()
    await eng.dispose()
    assert row is not None, f"call_analyses row {ca_id!r} not found"
    return dict(row)


# ---------------------------------------------------------------------------
# Task 2.1 tests (RED — columns/indexes/backfill do not exist yet)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_adds_five_columns(migration_db):
    """Migration must add 5 new nullable columns to call_analyses.

    Acceptance: call-analysis-storage denormalized column scenarios.
    """
    db_module, db_url = migration_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    columns = await _get_columns(db_url, "call_analyses")
    expected = {
        "primary_objection_category",
        "primary_pain_category",
        "objections_count",
        "pain_points_count",
        "service_issues_count",
    }
    assert expected.issubset(columns), (
        f"Missing columns after migration: {expected - columns}"
    )


@pytest.mark.asyncio
async def test_migration_creates_two_indexes(migration_db):
    """Migration must create B-tree indexes on the two primary category columns.

    Acceptance: analytics service uses indexed columns (AD-2).
    """
    db_module, db_url = migration_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    indexes = await _get_indexes(db_url, "call_analyses")
    assert "ix_ca_primary_objection_category" in indexes, (
        f"Index ix_ca_primary_objection_category not found in {indexes}"
    )
    assert "ix_ca_primary_pain_category" in indexes, (
        f"Index ix_ca_primary_pain_category not found in {indexes}"
    )


@pytest.mark.asyncio
async def test_migration_is_idempotent(migration_db):
    """Running the migration twice must not raise and must leave columns/indexes intact.

    Acceptance: idempotent double-run scenario.
    """
    db_module, db_url = migration_db

    from scripts.migrate_bi_columns import run_migration

    # First run
    await run_migration(db_url)
    # Second run — must not raise
    await run_migration(db_url)

    columns = await _get_columns(db_url, "call_analyses")
    assert "primary_objection_category" in columns
    assert "objections_count" in columns


@pytest.mark.asyncio
async def test_backfill_row_with_objections_and_pain(migration_db):
    """Backfill populates primary categories and counts from JSON arrays.

    Acceptance: call-analysis-storage scenario — call with objections and pain points.
    Row ca-bi-1 has 2 objections (price=primary), 1 pain point (service_quality=primary),
    2 service issues.
    """
    db_module, db_url = migration_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    row = await _get_ca_row(db_module, "ca-bi-1")
    assert row["primary_objection_category"] == "price", (
        f"Expected primary_objection_category='price', got {row['primary_objection_category']!r}"
    )
    assert row["primary_pain_category"] == "service_quality", (
        f"Expected primary_pain_category='service_quality', got {row['primary_pain_category']!r}"
    )
    assert row["objections_count"] == 2, (
        f"Expected objections_count=2, got {row['objections_count']!r}"
    )
    assert row["pain_points_count"] == 1, (
        f"Expected pain_points_count=1, got {row['pain_points_count']!r}"
    )
    assert row["service_issues_count"] == 2, (
        f"Expected service_issues_count=2, got {row['service_issues_count']!r}"
    )


@pytest.mark.asyncio
async def test_backfill_row_with_empty_arrays(migration_db):
    """Backfill: empty JSON arrays → counts=0 and primary categories=null.

    Acceptance: call-analysis-storage scenario — call with no objections.
    Row ca-bi-2 has all empty arrays.
    """
    db_module, db_url = migration_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    row = await _get_ca_row(db_module, "ca-bi-2")
    assert row["primary_objection_category"] is None, (
        f"Expected None for empty objections, got {row['primary_objection_category']!r}"
    )
    assert row["primary_pain_category"] is None, (
        f"Expected None for empty pain_points, got {row['primary_pain_category']!r}"
    )
    assert row["objections_count"] == 0, (
        f"Expected objections_count=0, got {row['objections_count']!r}"
    )
    assert row["pain_points_count"] == 0
    assert row["service_issues_count"] == 0


# ---------------------------------------------------------------------------
# True old-schema migration tests (column/index CREATION path, not just backfill)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_old_schema_lacks_bi_columns_and_indexes_before_migration(old_schema_db):
    """Guard: the pre-PR2 table genuinely lacks the 5 BI columns and 2 indexes.

    Without this guard, a regression where the fixture accidentally pre-creates
    the columns would make the creation-path tests below pass vacuously.
    """
    db_url = old_schema_db

    columns = await _get_columns(db_url, "call_analyses")
    assert _BI_COLUMNS.isdisjoint(columns), (
        f"Old-schema fixture should NOT have BI columns, but found: {_BI_COLUMNS & columns}"
    )

    indexes = await _get_indexes(db_url, "call_analyses")
    assert _BI_INDEXES.isdisjoint(indexes), (
        f"Old-schema fixture should NOT have BI indexes, but found: {_BI_INDEXES & indexes}"
    )


@pytest.mark.asyncio
async def test_migration_adds_columns_to_old_schema(old_schema_db):
    """Migration adds the 5 BI columns to a table that truly lacked them.

    Exercises the real ALTER TABLE ADD COLUMN path (not a no-op skip).
    """
    db_url = old_schema_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    columns = await _get_columns(db_url, "call_analyses")
    assert _BI_COLUMNS.issubset(columns), (
        f"Missing columns after old-schema migration: {_BI_COLUMNS - columns}"
    )


@pytest.mark.asyncio
async def test_migration_creates_indexes_on_old_schema(old_schema_db):
    """Migration creates the 2 BI indexes on a table that truly lacked them.

    Exercises the real CREATE INDEX path (not a no-op skip).
    """
    db_url = old_schema_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    indexes = await _get_indexes(db_url, "call_analyses")
    assert _BI_INDEXES.issubset(indexes), (
        f"Missing indexes after old-schema migration: {_BI_INDEXES - indexes}"
    )


@pytest.mark.asyncio
async def test_old_schema_backfill_populates_from_json(old_schema_db):
    """Migration backfills BI columns from JSON arrays on a true old-schema DB.

    Row old-ca-1: price=primary objection, service_quality=primary pain,
    2 objections, 1 pain point, 2 service issues.
    Row old-ca-2: all empty arrays → counts=0, primary categories=NULL.
    """
    db_url = old_schema_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)

    row1 = await _get_ca_row_by_url(db_url, "old-ca-1")
    assert row1["primary_objection_category"] == "price"
    assert row1["primary_pain_category"] == "service_quality"
    assert row1["objections_count"] == 2
    assert row1["pain_points_count"] == 1
    assert row1["service_issues_count"] == 2

    row2 = await _get_ca_row_by_url(db_url, "old-ca-2")
    assert row2["primary_objection_category"] is None
    assert row2["primary_pain_category"] is None
    assert row2["objections_count"] == 0
    assert row2["pain_points_count"] == 0
    assert row2["service_issues_count"] == 0


@pytest.mark.asyncio
async def test_old_schema_migration_is_idempotent(old_schema_db):
    """Double-run on an upgraded old-schema DB must not raise and must preserve data.

    First run creates columns/indexes + backfills; second run hits the skip
    paths and re-runs the (independent) backfill UPDATEs without error.
    """
    db_url = old_schema_db

    from scripts.migrate_bi_columns import run_migration

    await run_migration(db_url)
    await run_migration(db_url)  # must not raise

    columns = await _get_columns(db_url, "call_analyses")
    assert _BI_COLUMNS.issubset(columns)

    indexes = await _get_indexes(db_url, "call_analyses")
    assert _BI_INDEXES.issubset(indexes)

    # Backfilled values survive the second run.
    row1 = await _get_ca_row_by_url(db_url, "old-ca-1")
    assert row1["primary_objection_category"] == "price"
    assert row1["objections_count"] == 2
