"""Integration tests for scripts/migrate_analysis_v2.py.

TDD Phase 2 — RED → GREEN → TRIANGULATE → REFACTOR

Covers:
- Task 2.1 RED:  Fresh migration, idempotent re-run, malformed JSON skip, null lead_id
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixture: isolated DB seeded with call_sessions containing extracted_facts
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def migration_db(tmp_path: Path):
    """DB with 3 call sessions (valid facts), 1 malformed, 1 with null lead_id."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/migration_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.service import create_session

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead A",
            phone="+5411000001",
            lead_id="lead-a",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead B",
            phone="+5411000002",
            lead_id="lead-b",
        )

        # Session 1: valid facts, lead-a
        cs1 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-a",
            session_id="sess-migration-1",
        )
        cs1.extracted_facts = _valid_facts(interest_level=70)

        # Session 2: valid facts, lead-b
        cs2 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-b",
            session_id="sess-migration-2",
        )
        cs2.extracted_facts = _valid_facts(interest_level=55)

        # Session 3: valid facts, lead-a (second call)
        cs3 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-a",
            session_id="sess-migration-3",
        )
        cs3.extracted_facts = _valid_facts(interest_level=85)

        # Session 4: null lead_id + valid facts (orphan session)
        cs4 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id=None,
            session_id="sess-migration-4",
        )
        cs4.extracted_facts = _valid_facts(interest_level=40)

        await sess.commit()

    # Yield the db_url so migration script can connect directly
    yield settings.database_url, db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def migration_db_malformed(tmp_path: Path):
    """DB with 2 valid sessions + 1 malformed JSON session."""
    from app.core.config import Settings
    from app.core import database as db_module
    from sqlalchemy import text

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/migration_malformed_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.service import create_session

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead A",
            phone="+5411000001",
            lead_id="lead-a",
        )

        # Session 1: valid
        cs1 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-a",
            session_id="sess-valid-1",
        )
        cs1.extracted_facts = _valid_facts(interest_level=70)

        # Session 2: valid
        cs2 = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-a",
            session_id="sess-valid-2",
        )
        cs2.extracted_facts = _valid_facts(interest_level=80)

        await sess.commit()

    # Inject malformed JSON via raw SQL (bypasses ORM type coercion)
    async with db_module.async_session_factory() as sess:
        from app.calls.service import create_session

        await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-a",
            session_id="sess-bad-json",
        )
        await sess.commit()

    # Set extracted_facts to raw malformed string using raw SQL
    engine = db_module.engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE call_sessions SET extracted_facts = :val WHERE id = :sid"),
            {"val": "not-valid-json", "sid": "sess-bad-json"},
        )

    yield settings.database_url, db_module

    await db_module.close_db()


def _valid_facts(interest_level: int = 70) -> dict:
    """Build a minimal valid extracted_facts dict matching PostCallAnalysis shape."""
    return {
        "summary": "Lead was interested.",
        "objections": ["precio alto"],
        "interest_level": interest_level,
        "current_insurance": "La Caja",
        "next_action_suggested": "send_quote",
        "misc_notes": "",
        "data_corrections": "",
        "call_outcome": {
            "classification": "completed_positive",
            "reason": "Lead asked for quote.",
            "confidence": "high",
        },
        "detected_interests": {
            "products": ["todo_riesgo"],
            "specific_needs": [],
            "buying_signals": ["asked about price"],
        },
        "identified_problem": {
            "primary_need": "Cobertura total.",
            "pain_points": [],
            "urgency": "high",
        },
    }


# ===========================================================================
# Task 2.1 RED — Fresh migration populates new tables
# ===========================================================================


async def test_migration_fresh_run_populates_call_analyses(migration_db):
    """Fresh migration: 3 sessions with valid facts → 3 rows in call_analyses."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    db_url, db_module = migration_db

    result = await run_migration(db_url)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        rows = (await sess.execute(select(CallAnalysis))).scalars().all()
        # 3 sessions with valid facts (excludes malformed — only valid here)
        # + 1 null lead_id session = 4 total sessions
        # All 4 should produce CallAnalysis rows
        assert len(rows) == 4

    assert result["processed"] == 4
    assert result["skipped"] == 0


async def test_migration_fresh_run_creates_lead_profile_facts(migration_db):
    """Fresh migration: lead-a and lead-b get LeadProfileFact rows."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    db_url, db_module = migration_db

    await run_migration(db_url)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.lead_id == "lead-a")
        )
        facts = result.scalars().all()
        assert len(facts) > 0

        result_b = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.lead_id == "lead-b")
        )
        facts_b = result_b.scalars().all()
        assert len(facts_b) > 0


async def test_migration_fresh_run_creates_lead_interest_history(migration_db):
    """Fresh migration: lead-a (2 calls) → 2 LeadInterestHistory rows."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.leads.models import LeadInterestHistory
    from sqlalchemy import select

    db_url, db_module = migration_db

    await run_migration(db_url)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadInterestHistory)
            .where(LeadInterestHistory.lead_id == "lead-a")
            .order_by(LeadInterestHistory.recorded_at)
        )
        rows = result.scalars().all()
        # lead-a had sessions 1 and 3 (interest_level 70 and 85)
        assert len(rows) == 2
        interest_levels = {r.interest_level for r in rows}
        assert 70 in interest_levels
        assert 85 in interest_levels


# ===========================================================================
# Task 2.1 RED — Idempotent re-run skips already-migrated sessions
# ===========================================================================


async def test_migration_idempotent_rerun_no_duplicates(migration_db):
    """Idempotent re-run: running migration twice → no duplicate rows."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    db_url, db_module = migration_db

    # First run
    result1 = await run_migration(db_url)
    assert result1["processed"] == 4

    # Second run — must skip all
    result2 = await run_migration(db_url)
    assert result2["skipped"] == 4
    assert result2["processed"] == 0

    # No duplicate rows
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        rows = (await sess.execute(select(CallAnalysis))).scalars().all()
        assert len(rows) == 4


# ===========================================================================
# Task 2.1 RED — Malformed JSON is skipped
# ===========================================================================


async def test_migration_malformed_json_is_skipped(migration_db_malformed):
    """Malformed JSON session is logged/skipped; valid sessions still processed."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    db_url, db_module = migration_db_malformed

    result = await run_migration(db_url)

    # 2 valid processed, 1 malformed errored
    assert result["processed"] == 2
    assert result["errored"] == 1

    # Only 2 rows in call_analyses (not 3)
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        rows = (await sess.execute(select(CallAnalysis))).scalars().all()
        assert len(rows) == 2


# ===========================================================================
# Task 2.1 RED — Null lead_id skips lead tables
# ===========================================================================


async def test_migration_null_lead_id_skips_lead_tables(migration_db):
    """Session with lead_id=None: CallAnalysis created, no LeadProfileFact rows for it."""
    from scripts.migrate_analysis_v2 import run_migration
    from app.calls.models import CallAnalysis
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    db_url, db_module = migration_db

    await run_migration(db_url)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        # The orphan session MUST have a CallAnalysis row
        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == "sess-migration-4")
        )
        ca = result.scalar_one_or_none()
        assert ca is not None
        assert ca.lead_id is None

        # No LeadProfileFact with source_call_id pointing to the orphan session
        result2 = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.source_call_id == "sess-migration-4"
            )
        )
        facts = result2.scalars().all()
        assert len(facts) == 0


# ===========================================================================
# FIX: CRITICAL 3 — 0-100 interest range enforcement in migration (Issue #34)
# ===========================================================================


def test_migration_build_interest_history_row_clamps_above_100():
    """CRITICAL 3: _build_interest_history_row clamps interest_level > 100 to 100."""
    from scripts.migrate_analysis_v2 import _build_interest_history_row

    row = _build_interest_history_row(
        lead_id="lead-a",
        session_id="sess-1",
        facts={"interest_level": 101},
    )

    assert row is not None
    assert (
        row["interest_level"] == 100
    ), f"CRITICAL 3 FAIL: interest_level=101 was not clamped to 100, got {row['interest_level']}"


def test_migration_build_interest_history_row_clamps_below_0():
    """CRITICAL 3: _build_interest_history_row clamps interest_level < 0 to 0."""
    from scripts.migrate_analysis_v2 import _build_interest_history_row

    row = _build_interest_history_row(
        lead_id="lead-a",
        session_id="sess-1",
        facts={"interest_level": -5},
    )

    assert row is not None
    assert (
        row["interest_level"] == 0
    ), f"CRITICAL 3 FAIL: interest_level=-5 was not clamped to 0, got {row['interest_level']}"


def test_migration_build_interest_history_row_valid_value_unchanged():
    """CRITICAL 3 TRIANGULATE: valid interest_level (50) passes through unchanged."""
    from scripts.migrate_analysis_v2 import _build_interest_history_row

    row = _build_interest_history_row(
        lead_id="lead-a",
        session_id="sess-1",
        facts={"interest_level": 50},
    )

    assert row is not None
    assert row["interest_level"] == 50


# ===========================================================================
# qora-outcome: migrate_drop_engagement_quality.py tests (Task 2.3 RED → GREEN)
# ===========================================================================


@pytest_asyncio.fixture
async def fresh_db_with_engagement_quality(tmp_path: Path):
    """DB that starts with call_analyses.engagement_quality column present."""
    from app.core.config import Settings
    from app.core import database as db_module
    from sqlalchemy import text

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/drop_eq_test.db",
    )
    await db_module.init_db(settings)

    # Add engagement_quality column back (simulates pre-migration state)
    engine = db_module.engine
    assert engine is not None
    async with engine.begin() as conn:
        # Check if column already exists (from old schema); if not, add it
        result = await conn.execute(text("PRAGMA table_info(call_analyses)"))
        cols = [row[1] for row in result.fetchall()]
        if "engagement_quality" not in cols:
            await conn.execute(
                text("ALTER TABLE call_analyses ADD COLUMN engagement_quality TEXT")
            )

    yield settings.database_url, db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def fresh_db_without_engagement_quality(tmp_path: Path):
    """DB that does NOT have call_analyses.engagement_quality column."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/no_eq_test.db",
    )
    await db_module.init_db(settings)

    # Verify column doesn't exist (post-migration state from updated model)
    from sqlalchemy import text

    engine = db_module.engine
    assert engine is not None
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(call_analyses)"))
        cols = [row[1] for row in result.fetchall()]
        assert "engagement_quality" not in cols, (
            "Test setup error: engagement_quality should not exist in new schema"
        )

    yield settings.database_url, db_module

    await db_module.close_db()


async def test_drop_engagement_quality_migration_drops_column(
    fresh_db_with_engagement_quality,
):
    """qora-outcome: migration drops engagement_quality column from call_analyses."""
    from scripts.migrate_drop_engagement_quality import run_migration
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url, db_module = fresh_db_with_engagement_quality

    # Run migration
    result = await run_migration(db_url)
    assert result["engagement_quality"] == "dropped"

    # Verify column no longer exists
    engine = create_async_engine(db_url, echo=False)
    async with engine.connect() as conn:
        rows = await conn.execute(text("PRAGMA table_info(call_analyses)"))
        col_names = [row[1] for row in rows.fetchall()]
    await engine.dispose()

    assert "engagement_quality" not in col_names, (
        "engagement_quality column must be dropped after migration"
    )


async def test_drop_engagement_quality_migration_is_idempotent(
    fresh_db_without_engagement_quality,
):
    """qora-outcome: running migration when column doesn't exist is a no-op."""
    from scripts.migrate_drop_engagement_quality import run_migration

    db_url, db_module = fresh_db_without_engagement_quality

    # Run migration on DB that already doesn't have the column
    result = await run_migration(db_url)
    assert result["engagement_quality"] == "skipped"


# ===========================================================================
# qora-abandonment Task 3.2 — migrate_abandonment_to_outcome.py
# ===========================================================================


@pytest_asyncio.fixture
async def fresh_db_for_abandonment_migration(tmp_path: Path):
    """DB without was_abrupt / abandonment_trigger columns (pre-migration state)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/abandonment_migration_test.db",
    )
    await db_module.init_db(settings)

    yield settings.database_url, db_module

    await db_module.close_db()


async def test_abandonment_migration_adds_was_abrupt_column(
    fresh_db_for_abandonment_migration,
):
    """qora-abandonment: migration adds was_abrupt column to call_analyses."""
    from scripts.migrate_abandonment_to_outcome import run_migration
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url, _db_module = fresh_db_for_abandonment_migration

    result = await run_migration(db_url)
    assert result["was_abrupt"] in ("added", "skipped")

    engine = create_async_engine(db_url, echo=False)
    async with engine.connect() as conn:
        rows = await conn.execute(text("PRAGMA table_info(call_analyses)"))
        col_names = [row[1] for row in rows.fetchall()]
    await engine.dispose()

    assert "was_abrupt" in col_names, "was_abrupt column must exist after migration"


async def test_abandonment_migration_adds_abandonment_trigger_column(
    fresh_db_for_abandonment_migration,
):
    """qora-abandonment: migration adds abandonment_trigger column to call_analyses."""
    from scripts.migrate_abandonment_to_outcome import run_migration
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url, _db_module = fresh_db_for_abandonment_migration

    result = await run_migration(db_url)
    assert result["abandonment_trigger"] in ("added", "skipped")

    engine = create_async_engine(db_url, echo=False)
    async with engine.connect() as conn:
        rows = await conn.execute(text("PRAGMA table_info(call_analyses)"))
        col_names = [row[1] for row in rows.fetchall()]
    await engine.dispose()

    assert "abandonment_trigger" in col_names, (
        "abandonment_trigger column must exist after migration"
    )


async def test_abandonment_migration_is_idempotent(
    fresh_db_for_abandonment_migration,
):
    """qora-abandonment: running migration twice is safe (both runs succeed).

    On a DB created by init_db (SQLAlchemy), the columns already exist in the schema.
    The migration must be safe in BOTH cases:
    - Columns don't exist → adds them
    - Columns already exist → skips them (idempotent)
    """
    from scripts.migrate_abandonment_to_outcome import run_migration

    db_url, _db_module = fresh_db_for_abandonment_migration

    # First run: either adds or skips depending on init_db schema
    result1 = await run_migration(db_url)
    assert result1["was_abrupt"] in ("added", "skipped")
    assert result1["abandonment_trigger"] in ("added", "skipped")

    # Second run: always skips (columns now exist)
    result2 = await run_migration(db_url)
    assert result2["was_abrupt"] == "skipped"
    assert result2["abandonment_trigger"] == "skipped"


# ===========================================================================
# qora-abandonment Task 3.1 — migrate_analysis_v2 DDL includes new columns
# ===========================================================================


def test_migration_build_call_analysis_row_does_not_include_abandonment_reason_field():
    """qora-abandonment: _build_call_analysis_row must include was_abrupt + abandonment_trigger."""
    from scripts.migrate_analysis_v2 import _build_call_analysis_row

    facts = {
        "call_outcome": {
            "classification": "hostile",
            "reason": "Lead hung up.",
            "confidence": "high",
            "was_abrupt": True,
            "abandonment_trigger": "lost_patience",
        },
        "interest_level": 20,
    }
    row = _build_call_analysis_row("sess-1", "lead-1", "client-1", facts)

    assert "was_abrupt" in row, "Row must include was_abrupt from call_outcome"
    assert "abandonment_trigger" in row, "Row must include abandonment_trigger from call_outcome"
    assert row["was_abrupt"] is True
    assert row["abandonment_trigger"] == "lost_patience"


def test_migration_build_call_analysis_row_was_abrupt_null_for_completed():
    """qora-abandonment: was_abrupt + abandonment_trigger are None when call completed."""
    from scripts.migrate_analysis_v2 import _build_call_analysis_row

    facts = {
        "call_outcome": {
            "classification": "completed_positive",
            "reason": "Lead agreed.",
            "confidence": "high",
            "was_abrupt": None,
            "abandonment_trigger": None,
        },
        "interest_level": 90,
    }
    row = _build_call_analysis_row("sess-2", "lead-2", "client-2", facts)

    assert row["was_abrupt"] is None
    assert row["abandonment_trigger"] is None
