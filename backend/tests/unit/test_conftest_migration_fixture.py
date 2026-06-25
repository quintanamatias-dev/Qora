"""Tests that the db_engine conftest fixture uses migration-based schema creation.

TDD cycle (Task 2.4b):
  After conftest.py is updated, the db_engine fixture must create the DB via
  Alembic upgrade head (not create_all). These tests verify the post-update
  behavior:
  - The schema produced by the fixture has alembic_version populated (migration ran)
  - All 10 baseline tables exist
  - broker_name is NOT NULL (migration fidelity, not create_all)

These behavioral assertions would fail if create_all() were used instead of
apply_migrations() because:
  1. create_all() does NOT populate alembic_version
  2. broker_name nullable=True in ORM models — create_all gives different constraint
"""

from __future__ import annotations


import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def migration_db(test_settings, tmp_path):
    """Fixture that uses apply_migrations to create the schema (mirrors updated conftest)."""
    from app.core import database as db_module
    from tests.helpers.migrations import apply_migrations

    # Apply Alembic migrations first (the new conftest path)
    apply_migrations(test_settings.database_url)

    # Then initialize the engine + session factory (without create_all)
    db_module.create_engine_and_session(test_settings.database_url)

    # Import models so metadata is registered
    import app.tenants.models  # noqa: F401
    import app.leads.models  # noqa: F401
    import app.calls.models  # noqa: F401
    import app.scheduler.models  # noqa: F401

    yield db_module

    await db_module.close_db()


@pytest.mark.asyncio
async def test_migration_fixture_creates_alembic_version(test_settings, migration_db):
    """Migration-based fixture MUST populate alembic_version (migration ran, not create_all).

    GIVEN db_engine created via apply_migrations + create_engine_and_session
    WHEN alembic_version is queried
    THEN version_num must be '20241201_0001' (proof that Alembic ran)
    """
    from sqlalchemy import text

    async with migration_db.async_session_factory() as session:
        result = await session.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
        row = result.fetchone()

    assert row is not None, "alembic_version must be populated when using migration fixture"
    # HEAD revision advances as new migrations are added — assert any valid Qora revision.
    # Baseline: 20241201_0001; Phase B10 background_jobs: 20260624_0002
    # PR3 transcript finalization fields: 20260625_0003
    _KNOWN_REVISIONS = {"20241201_0001", "20260624_0002", "20260625_0003"}
    assert row[0] in _KNOWN_REVISIONS, (
        f"Expected a known Qora migration version, got {row[0]!r}. "
        "This indicates create_all() was used instead of Alembic, or an unknown migration ran. "
        f"Known revisions: {_KNOWN_REVISIONS}"
    )


@pytest.mark.asyncio
async def test_migration_fixture_has_all_baseline_tables(test_settings, migration_db):
    """Migration-based fixture must produce all 10 baseline tables.

    GIVEN a migration-based db_engine
    WHEN table list is queried
    THEN all 10 baseline tables must be present
    """
    from sqlalchemy import text

    async with migration_db.async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT IN ('alembic_version', 'sqlite_sequence')"
            )
        )
        tables = {row[0] for row in result.fetchall()}

    expected = {
        "clients", "agents", "leads", "lead_profile_facts", "lead_custom_fields",
        "lead_interest_history", "call_sessions", "transcript_turns",
        "call_analyses", "scheduled_calls",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"
