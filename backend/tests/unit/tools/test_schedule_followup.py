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
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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


# ---------------------------------------------------------------------------
# Phase 6 — ScheduledCall creation via schedule_followup tool
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_with_scheduler(tmp_path: Path):
    """DB with quintana (scheduler_enabled=True) + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/followup_sched_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    # Enable scheduler on quintana
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_schedule_followup_creates_scheduled_call(db_with_scheduler):
    """Phase 6: schedule_followup creates a ScheduledCall when scheduler_enabled=True."""
    from app.tools.schedule_followup import schedule_followup
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    async with db_with_scheduler.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-05-10",
        )
        await sess.commit()

    assert "error" not in result

    # ScheduledCall should have been created
    async with db_with_scheduler.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "lead-quintana-003")
        )
        sc = rows.scalar_one_or_none()
        assert sc is not None
        assert sc.trigger_reason == "followup_tool"
        assert sc.status == "pending"


async def test_schedule_followup_still_writes_note_with_scheduler(db_with_scheduler):
    """Phase 6: schedule_followup writes backward-compat note even when scheduler_enabled."""
    from app.tools.schedule_followup import schedule_followup
    from app.leads.service import get_lead

    followup_date = "2026-05-10"
    async with db_with_scheduler.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date=followup_date,
        )
        lead = await get_lead(sess, "lead-quintana-003")
        assert "error" not in result
        assert lead.notes is not None
        assert "Seguimiento agendado" in lead.notes
        assert followup_date in lead.notes


async def test_schedule_followup_duplicate_guard_note_only(db_with_scheduler):
    """Phase 6: If pending ScheduledCall already exists, only note is written (no duplicate)."""
    from app.tools.schedule_followup import schedule_followup
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # First call creates the ScheduledCall
    async with db_with_scheduler.async_session_factory() as sess:
        await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-05-10",
        )
        await sess.commit()

    # Second call should only update notes, NOT create duplicate
    async with db_with_scheduler.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-05-20",
        )
        await sess.commit()

    assert "error" not in result

    async with db_with_scheduler.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "lead-quintana-003")
        )
        all_scs = rows.scalars().all()
        assert len(all_scs) == 1  # only 1, no duplicate


async def test_schedule_followup_disabled_scheduler_note_only(db_with_scheduler):
    """Phase 6: When scheduler_enabled=False, only note is written, no ScheduledCall."""
    from app.tools.schedule_followup import schedule_followup
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Disable scheduler
    async with db_with_scheduler.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = False
        await sess.commit()

    async with db_with_scheduler.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="2026-05-10",
        )
        await sess.commit()

    assert "error" not in result

    async with db_with_scheduler.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "lead-quintana-003")
        )
        sc = rows.scalar_one_or_none()
        assert sc is None  # no ScheduledCall created


async def test_schedule_followup_invalid_date_returns_error(db_with_scheduler):
    """Phase 6: Unparseable date from AI returns error, notes not written."""
    from app.tools.schedule_followup import schedule_followup

    async with db_with_scheduler.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="lead-quintana-003",
            followup_date="not-a-date-at-all-xyz",
        )

    assert "error" in result


# ---------------------------------------------------------------------------
# Round 2 fix — Issue 3: ISO 8601 regression in _parse_followup_date
# Valid ISO 8601 formats that must be accepted
# ---------------------------------------------------------------------------


def test_parse_followup_date_no_seconds_accepted():
    """_parse_followup_date must accept 'YYYY-MM-DDTHH:MM' (no seconds)."""
    from app.tools.schedule_followup import _parse_followup_date

    result = _parse_followup_date("2026-06-01T14:00")
    assert result is not None, "ISO 8601 without seconds must be accepted"
    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 1


def test_parse_followup_date_fractional_seconds_accepted():
    """_parse_followup_date must accept fractional seconds like '2026-06-01T14:00:00.123456'."""
    from app.tools.schedule_followup import _parse_followup_date

    result = _parse_followup_date("2026-06-01T14:00:00.123456")
    assert result is not None, "ISO 8601 with fractional seconds must be accepted"
    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 1


def test_parse_followup_date_z_suffix_accepted():
    """_parse_followup_date must accept 'YYYY-MM-DDTHH:MM:SSZ' (Z suffix for UTC)."""
    from app.tools.schedule_followup import _parse_followup_date

    result = _parse_followup_date("2026-06-01T14:00:00Z")
    assert result is not None, "ISO 8601 with Z suffix must be accepted"
    assert result.tzinfo is not None


def test_parse_followup_date_with_tz_and_no_seconds():
    """_parse_followup_date must accept 'YYYY-MM-DDTHH:MM+HH:MM' (offset, no seconds)."""
    from app.tools.schedule_followup import _parse_followup_date

    result = _parse_followup_date("2026-06-01T14:00-03:00")
    assert result is not None, "ISO 8601 with offset and no seconds must be accepted"
    assert result.tzinfo is not None


def test_parse_followup_date_naive_no_seconds_uses_client_tz():
    """_parse_followup_date with naive 'HH:MM' must use client_timezone, not UTC."""
    from app.tools.schedule_followup import _parse_followup_date

    # New York in winter is UTC-5, so midnight New York = 05:00 UTC
    result = _parse_followup_date(
        "2026-01-15T09:00", client_timezone="America/New_York"
    )
    assert result is not None
    # 9:00 AM New York (EST, UTC-5) = 14:00 UTC
    assert result.utcoffset().total_seconds() == 0  # stored as UTC
    assert result.hour == 14  # 9AM EST = 14:00 UTC


# ---------------------------------------------------------------------------
# CRITICAL 3: schedule_followup passes agent_id to ScheduledCall
# ---------------------------------------------------------------------------


async def test_schedule_followup_passes_agent_id_when_source_session_has_agent(db):
    """schedule_followup passes agent_id from the source session to ScheduledCall."""
    from app.scheduler.service import list_queue
    from app.tenants.service import get_default_agent
    from app.calls.service import create_session
    from app.leads.service import transition_lead_status
    from sqlalchemy import select as _select
    from app.leads.models import Lead as _Lead

    # Get the default agent
    async with db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        agent_id = agent.id

    # Enable scheduler for quintana
    async with db.async_session_factory() as sess:
        from app.tenants.models import Client as _Client

        client = await sess.get(_Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_allowed_hours_start = 0  # allow all hours for test
        client.scheduler_allowed_hours_end = 24
        await sess.commit()

    # Get a lead and advance to "called" state (required before follow_up)
    async with db.async_session_factory() as sess:
        lead_row = (await sess.execute(_select(_Lead).limit(1))).scalar_one()
        lead_id = lead_row.id
        await transition_lead_status(sess, lead_id, "called")

        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id=lead_id,
            agent_id=agent_id,
        )
        source_session_id = cs.id
        await sess.commit()

    # Call schedule_followup with source_session_id
    async with db.async_session_factory() as sess:
        from app.tools.schedule_followup import schedule_followup

        result = await schedule_followup(
            session=sess,
            lead_id=lead_id,
            followup_date="2099-06-01T15:00:00",
            client_id="quintana-seguros",
            source_session_id=source_session_id,
        )
        await sess.commit()

    assert "error" not in result, f"schedule_followup failed: {result}"

    async with db.async_session_factory() as sess:
        scheduled_calls = await list_queue(sess, client_id="quintana-seguros")

    assert len(scheduled_calls) >= 1
    sc = scheduled_calls[0]
    assert (
        sc.agent_id == agent_id
    ), f"Expected agent_id={agent_id!r} on ScheduledCall, got {sc.agent_id!r}"


async def test_schedule_followup_resolves_default_agent_when_no_source_session(db):
    """schedule_followup resolves default agent when no source_session_id is provided."""
    from app.scheduler.service import list_queue
    from app.tenants.service import get_default_agent
    from app.leads.service import transition_lead_status
    from sqlalchemy import select as _select
    from app.leads.models import Lead as _Lead

    # Get the default agent
    async with db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        agent_id = agent.id

    # Enable scheduler for quintana (allow all hours)
    async with db.async_session_factory() as sess:
        from app.tenants.models import Client as _Client

        client = await sess.get(_Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_allowed_hours_start = 0
        client.scheduler_allowed_hours_end = 24
        await sess.commit()

    # Get a lead and advance to "called" state (required before follow_up)
    async with db.async_session_factory() as sess:
        lead_row = (await sess.execute(_select(_Lead).limit(1))).scalar_one()
        lead_id = lead_row.id
        await transition_lead_status(sess, lead_id, "called")
        await sess.commit()

    # schedule_followup with NO source_session_id — should use default agent
    async with db.async_session_factory() as sess:
        from app.tools.schedule_followup import schedule_followup

        result = await schedule_followup(
            session=sess,
            lead_id=lead_id,
            followup_date="2099-06-01T15:00:00",
            client_id="quintana-seguros",
            source_session_id=None,
        )
        await sess.commit()

    assert "error" not in result, f"schedule_followup failed: {result}"

    async with db.async_session_factory() as sess:
        scheduled_calls = await list_queue(sess, client_id="quintana-seguros")

    assert len(scheduled_calls) >= 1
    sc = scheduled_calls[0]
    assert (
        sc.agent_id == agent_id
    ), f"Expected default agent_id={agent_id!r} on ScheduledCall, got {sc.agent_id!r}"
