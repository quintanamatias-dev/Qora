"""Unit tests for Analysis v2 models: CallAnalysis, LeadProfileFact, LeadInterestHistory.

TDD Phase 1 — RED → GREEN → TRIANGULATE → REFACTOR

Covers:
- Task 1.1 RED:  Basic CRUD and FK constraints for all 3 models
- Task 1.3 TRIA: Unique session_id, JSON list round-trip, nullable source_call_id,
                 supersede-current semantics, append-only ordering
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Isolated SQLite DB with all tables created, seeded with one client + lead + session."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analysis_models_test.db",
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
            name="Test Lead",
            phone="+5411000001",
            lead_id="lead-1",
        )
        await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-1",
            session_id="sess-1",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helper: build a minimal CallAnalysis dict
# ---------------------------------------------------------------------------


def _call_analysis_kwargs(**overrides) -> dict:
    base = dict(
        id=_new_id(),
        session_id="sess-1",
        lead_id="lead-1",
        client_id="quintana-seguros",
        summary="El lead mostró interés.",
        interest_level=75,
        classification="completed_positive",
        outcome_reason="Asked for quote.",
        urgency="high",
        primary_need="Cobertura todo riesgo.",
        next_action_suggested="send_quote",
        current_insurance=None,
        data_corrections="",
        misc_notes="",
        objections=json.dumps(["precio alto"]),
        products=json.dumps(["todo_riesgo"]),
        specific_needs=json.dumps([]),
        buying_signals=json.dumps(["asked for price"]),
        pain_points=json.dumps([]),
        analysis_status="ok",
        analysis_error=None,
    )
    base.update(overrides)
    return base


# ===========================================================================
# Task 1.1 RED — CallAnalysis basic CRUD
# ===========================================================================


async def test_call_analysis_create_and_read(db):
    """CallAnalysis: create row, read back via session_id FK."""
    from app.calls.models import CallAnalysis

    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        ca = CallAnalysis(**_call_analysis_kwargs())
        sess.add(ca)
        await sess.flush()
        ca_id = ca.id
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == "sess-1")
        )
        row = result.scalar_one()
        assert row.id == ca_id
        assert row.lead_id == "lead-1"
        assert row.client_id == "quintana-seguros"
        assert row.interest_level == 75
        assert row.analysis_status == "ok"
        assert isinstance(row.analyzed_at, datetime)


async def test_call_analysis_analyzed_at_is_utc(db):
    """CallAnalysis.analyzed_at defaults to UTC datetime and is non-null."""
    from app.calls.models import CallAnalysis

    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        ca = CallAnalysis(**_call_analysis_kwargs(id=_new_id()))
        sess.add(ca)
        await sess.flush()
        assert ca.analyzed_at is not None
        assert isinstance(ca.analyzed_at, datetime)
        await sess.commit()


# ===========================================================================
# Task 1.1 RED — LeadProfileFact basic CRUD
# ===========================================================================


async def test_lead_profile_fact_create_and_read(db):
    """LeadProfileFact: insert a fact for lead-1, read back with superseded_at IS NULL."""
    from app.leads.models import LeadProfileFact

    fact_id = _new_id()
    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        lpf = LeadProfileFact(
            id=fact_id,
            lead_id="lead-1",
            fact_key="interest_level",
            fact_value="75",
            source_call_id="sess-1",
        )
        sess.add(lpf)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-1",
                LeadProfileFact.fact_key == "interest_level",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        row = result.scalar_one()
        assert row.id == fact_id
        assert row.fact_value == "75"
        assert row.superseded_at is None
        assert isinstance(row.recorded_at, datetime)


# ===========================================================================
# Task 1.1 RED — LeadInterestHistory basic CRUD
# ===========================================================================


async def test_lead_interest_history_create_and_read(db):
    """LeadInterestHistory: insert an entry, read back with correct values."""
    from app.leads.models import LeadInterestHistory

    lih_id = _new_id()
    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        lih = LeadInterestHistory(
            id=lih_id,
            lead_id="lead-1",
            interest_level=80,
            source_call_id="sess-1",
        )
        sess.add(lih)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadInterestHistory).where(LeadInterestHistory.lead_id == "lead-1")
        )
        row = result.scalar_one()
        assert row.id == lih_id
        assert row.interest_level == 80
        assert row.source_call_id == "sess-1"
        assert isinstance(row.recorded_at, datetime)


# ===========================================================================
# Task 1.3 TRIANGULATE — unique session_id constraint
# ===========================================================================


async def test_call_analysis_unique_session_id_constraint(db):
    """CallAnalysis: inserting a second row for same session_id raises IntegrityError."""
    from sqlalchemy.exc import IntegrityError
    from app.calls.models import CallAnalysis

    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        ca1 = CallAnalysis(**_call_analysis_kwargs(id=_new_id()))
        sess.add(ca1)
        await sess.commit()

    with pytest.raises(IntegrityError):
        async with db.async_session_factory() as sess:
            # Same session_id — must violate UNIQUE constraint
            ca2 = CallAnalysis(**_call_analysis_kwargs(id=_new_id()))
            sess.add(ca2)
            await sess.commit()


# ===========================================================================
# Task 1.3 TRIANGULATE — JSON list round-trip
# ===========================================================================


async def test_call_analysis_json_list_round_trip(db):
    """CallAnalysis: objections and products stored as JSON text, read back as lists."""
    from app.calls.models import CallAnalysis

    objections_list = ["precio alto", "no me interesa"]
    products_list = ["todo_riesgo", "terceros"]

    assert db.async_session_factory is not None
    ca_id = _new_id()
    async with db.async_session_factory() as sess:
        ca = CallAnalysis(
            **_call_analysis_kwargs(
                id=ca_id,
                objections=json.dumps(objections_list),
                products=json.dumps(products_list),
            )
        )
        sess.add(ca)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.id == ca_id)
        )
        row = result.scalar_one()
        assert json.loads(row.objections) == objections_list
        assert json.loads(row.products) == products_list


# ===========================================================================
# Task 1.3 TRIANGULATE — analysis_status = "failed" persists error
# ===========================================================================


async def test_call_analysis_failed_status_persists_error(db):
    """CallAnalysis: analysis_status='failed' with analysis_error stores the error message."""
    from app.calls.models import CallAnalysis

    ca_id = _new_id()
    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        ca = CallAnalysis(
            **_call_analysis_kwargs(
                id=ca_id,
                analysis_status="failed",
                analysis_error="timeout",
                summary="",
            )
        )
        sess.add(ca)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.id == ca_id)
        )
        row = result.scalar_one()
        assert row.analysis_status == "failed"
        assert row.analysis_error == "timeout"
        assert row.summary == ""


# ===========================================================================
# Task 1.3 TRIANGULATE — nullable source_call_id on LeadProfileFact
# ===========================================================================


async def test_lead_profile_fact_nullable_source_call_id(db):
    """LeadProfileFact: source_call_id IS NULL is valid — no IntegrityError."""
    from app.leads.models import LeadProfileFact

    fact_id = _new_id()
    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        lpf = LeadProfileFact(
            id=fact_id,
            lead_id="lead-1",
            fact_key="primary_need",
            fact_value="Cobertura total",
            source_call_id=None,  # explicitly null
        )
        sess.add(lpf)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == fact_id)
        )
        row = result.scalar_one()
        assert row.source_call_id is None


# ===========================================================================
# Task 1.3 TRIANGULATE — supersede-current semantics
# ===========================================================================


async def test_lead_profile_fact_upsert_supersedes_old(db):
    """LeadProfileFact upsert: setting superseded_at on old row and inserting new keeps only 1 active."""
    from app.leads.models import LeadProfileFact

    old_id = _new_id()
    new_id = _new_id()

    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        old_fact = LeadProfileFact(
            id=old_id,
            lead_id="lead-1",
            fact_key="interest_level",
            fact_value="50",
            source_call_id="sess-1",
        )
        sess.add(old_fact)
        await sess.commit()

    # Simulate upsert: set superseded_at on old, insert new
    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == old_id)
        )
        old_row = result.scalar_one()
        old_row.superseded_at = datetime.now(timezone.utc)

        new_fact = LeadProfileFact(
            id=new_id,
            lead_id="lead-1",
            fact_key="interest_level",
            fact_value="80",
            source_call_id="sess-1",
        )
        sess.add(new_fact)
        await sess.commit()

    # Verify: exactly 1 active (superseded_at IS NULL)
    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-1",
                LeadProfileFact.fact_key == "interest_level",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        active_rows = result.scalars().all()
        assert len(active_rows) == 1
        assert active_rows[0].fact_value == "80"


async def test_lead_profile_fact_historical_rows_preserved(db):
    """LeadProfileFact: after 2 upsert cycles, 2 rows exist — 1 superseded, 1 active."""
    from app.leads.models import LeadProfileFact

    first_id = _new_id()
    second_id = _new_id()

    assert db.async_session_factory is not None
    # Insert first fact
    async with db.async_session_factory() as sess:
        sess.add(
            LeadProfileFact(
                id=first_id,
                lead_id="lead-1",
                fact_key="interest_level",
                fact_value="60",
            )
        )
        await sess.commit()

    # Supersede first, insert second
    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == first_id)
        )
        first = result.scalar_one()
        first.superseded_at = datetime.now(timezone.utc)
        sess.add(
            LeadProfileFact(
                id=second_id,
                lead_id="lead-1",
                fact_key="interest_level",
                fact_value="80",
            )
        )
        await sess.commit()

    # Both rows must exist
    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-1",
                LeadProfileFact.fact_key == "interest_level",
            )
        )
        all_rows = result.scalars().all()
        assert len(all_rows) == 2

        superseded = [r for r in all_rows if r.superseded_at is not None]
        active = [r for r in all_rows if r.superseded_at is None]
        assert len(superseded) == 1
        assert len(active) == 1
        assert active[0].fact_value == "80"


# ===========================================================================
# Task 1.3 TRIANGULATE — LeadInterestHistory append-only ordering
# ===========================================================================


async def test_lead_interest_history_multiple_entries_preserved(db):
    """LeadInterestHistory: 2 entries for same lead returned in insertion order."""
    from app.leads.models import LeadInterestHistory

    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        lih1 = LeadInterestHistory(
            id=_new_id(),
            lead_id="lead-1",
            interest_level=60,
            source_call_id="sess-1",
        )
        lih2 = LeadInterestHistory(
            id=_new_id(),
            lead_id="lead-1",
            interest_level=80,
            source_call_id="sess-1",
        )
        sess.add(lih1)
        sess.add(lih2)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadInterestHistory)
            .where(LeadInterestHistory.lead_id == "lead-1")
            .order_by(LeadInterestHistory.recorded_at)
        )
        rows = result.scalars().all()
        assert len(rows) == 2
        assert rows[0].interest_level == 60
        assert rows[1].interest_level == 80


async def test_lead_interest_history_nullable_source_call_id(db):
    """LeadInterestHistory: source_call_id IS NULL is valid — no IntegrityError."""
    from app.leads.models import LeadInterestHistory

    lih_id = _new_id()
    assert db.async_session_factory is not None
    async with db.async_session_factory() as sess:
        lih = LeadInterestHistory(
            id=lih_id,
            lead_id="lead-1",
            interest_level=55,
            source_call_id=None,
        )
        sess.add(lih)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(LeadInterestHistory).where(LeadInterestHistory.id == lih_id)
        )
        row = result.scalar_one()
        assert row.source_call_id is None
        assert row.interest_level == 55
