"""Unit tests for _upsert_call_analysis() — denormalized BI column population.

TDD RED → GREEN → TRIANGULATE → REFACTOR

Covers (task 2.3):
- Primary objection category derived from objection with is_primary=True
- Primary pain category derived from pain point with is_primary=True
- objections_count, pain_points_count, service_issues_count populated atomically
- Empty objections → primary_objection_category=None, objections_count=0
- Multiple objections without primary flag → primary_objection_category=None

Acceptance criteria: call-analysis-storage atomic population scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixture: isolated DB with quintana + one test lead
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db_bi(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead for BI column tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/summarizer_bi_test.db",
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
            name="BI Lead",
            phone="+5411000099",
            lead_id="test-lead-bi-001",
        )
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-bi-001",
            session_id="sess-bi-test-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Task 2.3 tests — directly test _upsert_call_analysis BI columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_sets_primary_objection_and_counts(seeded_db_bi):
    """_upsert_call_analysis populates primary_objection_category and counts.

    Given facts with 2 objections (price=primary) + 1 pain point (service_quality=primary):
    - primary_objection_category = 'price'
    - primary_pain_category = 'service_quality'
    - objections_count = 2, pain_points_count = 1

    Acceptance: call-analysis-storage scenario — call with objections and pain points.
    """
    from app.summarizer import _upsert_call_analysis
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    facts = {
        "interest_level": 60,
        "next_action_suggested": "follow_up",
        "data_corrections": [],
        "misc_notes": {},
        "objections": {
            "objections": [
                {"category": "price", "is_primary": True, "strength": "hard", "evidence": "Too expensive", "resolution_status": "unresolved"},
                {"category": "current_provider", "is_primary": False, "strength": "soft", "evidence": "Happy with current", "resolution_status": "unresolved"},
            ]
        },
        "identified_problem": {
            "pain_points": [
                {"category": "service_quality", "is_primary": True, "description": "Bad service", "evidence": "Had bad experience", "urgency": "medium", "confidence": "high"},
            ]
        },
        "service_issues": {
            "issues": []
        },
        "call_outcome": {"classification": "callback_requested", "reason": "Lead said call back", "confidence": "medium"},
        "detected_interests": {},
        "profile_facts": {},
        "commitments": {},
    }

    assert seeded_db_bi.async_session_factory is not None
    async with seeded_db_bi.async_session_factory() as db:
        async with db.begin_nested():
            await _upsert_call_analysis(
                db,
                session_id="sess-bi-test-001",
                lead_id="test-lead-bi-001",
                client_id="quintana-seguros",
                summary="Test summary.",
                facts=facts,
            )

    async with seeded_db_bi.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == "sess-bi-test-001")
        )
        ca = result.scalar_one()

    assert ca.primary_objection_category == "price", (
        f"Expected primary_objection_category='price', got {ca.primary_objection_category!r}"
    )
    assert ca.objections_count == 2, (
        f"Expected objections_count=2, got {ca.objections_count!r}"
    )
    assert ca.primary_pain_category == "service_quality", (
        f"Expected primary_pain_category='service_quality', got {ca.primary_pain_category!r}"
    )
    assert ca.pain_points_count == 1, (
        f"Expected pain_points_count=1, got {ca.pain_points_count!r}"
    )
    assert ca.service_issues_count == 0, (
        f"Expected service_issues_count=0, got {ca.service_issues_count!r}"
    )


@pytest.mark.asyncio
async def test_upsert_empty_objections_gives_null_primary_and_zero_count(seeded_db_bi):
    """Empty objections list → primary_objection_category=None and objections_count=0.

    Acceptance: call-analysis-storage scenario — call with no objections.
    """
    from app.summarizer import _upsert_call_analysis
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    facts = {
        "interest_level": 80,
        "next_action_suggested": "send_quote",
        "data_corrections": [],
        "misc_notes": {},
        "objections": {"objections": []},
        "identified_problem": {"pain_points": []},
        "service_issues": {"issues": []},
        "call_outcome": {"classification": "completed_positive", "reason": "Interested", "confidence": "high"},
        "detected_interests": {},
        "profile_facts": {},
        "commitments": {},
    }

    assert seeded_db_bi.async_session_factory is not None
    async with seeded_db_bi.async_session_factory() as db:
        async with db.begin_nested():
            await _upsert_call_analysis(
                db,
                session_id="sess-bi-test-001",
                lead_id="test-lead-bi-001",
                client_id="quintana-seguros",
                summary="Short call, no objections.",
                facts=facts,
            )

    async with seeded_db_bi.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == "sess-bi-test-001")
        )
        ca = result.scalar_one()

    assert ca.primary_objection_category is None, (
        f"Expected None for empty objections, got {ca.primary_objection_category!r}"
    )
    assert ca.objections_count == 0, (
        f"Expected objections_count=0, got {ca.objections_count!r}"
    )
    assert ca.primary_pain_category is None
    assert ca.pain_points_count == 0
    assert ca.service_issues_count == 0


@pytest.mark.asyncio
async def test_upsert_service_issues_count_populated(seeded_db_bi):
    """_upsert_call_analysis populates service_issues_count correctly.

    Triangulation: separate test for service issues to force real count logic.
    """
    from app.summarizer import _upsert_call_analysis
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    facts = {
        "interest_level": 55,
        "next_action_suggested": "follow_up",
        "data_corrections": [],
        "misc_notes": {},
        "objections": {"objections": []},
        "identified_problem": {"pain_points": []},
        "service_issues": {
            "issues": [
                {"category": "billing", "description": "Wrong charge", "evidence": "Said wrong charge"},
                {"category": "response_time", "description": "Slow", "evidence": "They were slow"},
                {"category": "claims_process", "description": "Complex", "evidence": "Process is complex"},
            ]
        },
        "call_outcome": {"classification": "callback_requested", "reason": "Issues noted", "confidence": "medium"},
        "detected_interests": {},
        "profile_facts": {},
        "commitments": {},
    }

    assert seeded_db_bi.async_session_factory is not None
    async with seeded_db_bi.async_session_factory() as db:
        async with db.begin_nested():
            await _upsert_call_analysis(
                db,
                session_id="sess-bi-test-001",
                lead_id="test-lead-bi-001",
                client_id="quintana-seguros",
                summary="Service issues call.",
                facts=facts,
            )

    async with seeded_db_bi.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == "sess-bi-test-001")
        )
        ca = result.scalar_one()

    assert ca.service_issues_count == 3, (
        f"Expected service_issues_count=3, got {ca.service_issues_count!r}"
    )
    assert ca.objections_count == 0
    assert ca.pain_points_count == 0
