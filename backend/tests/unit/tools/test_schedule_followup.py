"""Unit tests for schedule_followup tool.

RED: References app.tools.schedule_followup which is not yet implemented.
Covers: CAP-4 schedule_followup scenarios.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """DB module with seeded Quintana + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/followup_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# T5.3: schedule_followup tests
# ---------------------------------------------------------------------------


async def test_schedule_followup_transitions_to_follow_up(db):
    """schedule_followup transitions lead to 'follow_up' (CAP-4)."""
    from app.tools.schedule_followup import schedule_followup

    async with db.async_session_factory() as sess:
        # lead-quintana-003 is in 'called' state
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-05-01",
        )

    assert "error" not in result
    assert result["status"] == "follow_up"


async def test_schedule_followup_persists_date_in_notes(db):
    """schedule_followup stores the followup date in notes (CAP-4)."""
    from app.tools.schedule_followup import schedule_followup
    from app.leads.service import get_lead

    followup_date = "2026-05-15"

    async with db.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date=followup_date,
            note="El cliente quiere que lo llamemos la semana próxima",
        )
        assert "error" not in result

        lead = await get_lead(sess, "lead-quintana-003")
        assert lead.notes is not None
        assert followup_date in lead.notes


async def test_schedule_followup_with_optional_note(db):
    """schedule_followup works with and without optional note."""
    from app.tools.schedule_followup import schedule_followup

    async with db.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-06-01",
            # no note
        )

    assert "error" not in result
    assert result["status"] == "follow_up"


async def test_schedule_followup_missing_date_returns_error(db):
    """schedule_followup requires followup_date — returns error if missing."""
    from app.tools.schedule_followup import schedule_followup

    async with db.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="",
        )

    assert "error" in result


async def test_schedule_followup_missing_lead_returns_error(db):
    """schedule_followup returns error for unknown lead."""
    from app.tools.schedule_followup import schedule_followup

    async with db.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="ghost-lead",
            followup_date="2026-05-01",
        )

    assert "error" in result
