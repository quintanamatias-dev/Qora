"""Unit tests for scheduler service — Phase 6 (Task 2.1 RED).

Covers:
- calculate_scheduled_at: UTC/TZ clamping (within window, after end, before start)
- create_scheduled_call: copies config-at-creation-time, persists with pending status
- auto_schedule: disabled-client skip, duplicate guard, do_not_call skip,
  ineligible outcome skip, eligible scenario creates ScheduledCall
- list_scheduled_calls / get_scheduled_call helpers
- cancel_scheduled_call: pending → cancelled
- reschedule_call: updates scheduled_at (only if pending)
- mark_due_calls_in_progress: promotes pending due records
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch


import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Pure function tests — calculate_scheduled_at (no DB needed)
# ---------------------------------------------------------------------------


def test_calculate_within_allowed_window():
    """Time within allowed window → no clamping."""
    from app.scheduler.service import calculate_scheduled_at

    # now_local = 14:00, cooldown=60 → candidate=15:00, window=[9,20) → no clamp
    # Use UTC-3 (Buenos Aires) — 14:00 local = 17:00 UTC
    tz_str = "America/Argentina/Buenos_Aires"
    now_utc = datetime(2026, 5, 1, 17, 0, 0, tzinfo=timezone.utc)  # 14:00 local
    result = calculate_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=60,
        start_hour=9,
        end_hour=20,
        tz_str=tz_str,
    )
    # candidate local = 15:00 → within [9,20) → no clamp
    # expected result ≈ 18:00 UTC (15:00 local BsAs = UTC-3)
    assert result.tzinfo is not None
    # Result should be exactly 60 minutes after now_utc (no clamping)
    expected = now_utc + timedelta(minutes=60)
    assert abs((result - expected).total_seconds()) < 2


def test_calculate_after_end_of_window_clamps_to_next_day():
    """Time after end of window → clamp to next day start_hour."""
    from app.scheduler.service import calculate_scheduled_at

    tz_str = "America/Argentina/Buenos_Aires"
    # now_local = 19:30 BsAs → UTC = 22:30
    now_utc = datetime(2026, 5, 1, 22, 30, 0, tzinfo=timezone.utc)  # 19:30 local
    result = calculate_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=60,
        start_hour=9,
        end_hour=20,
        tz_str=tz_str,
    )
    # candidate local = 20:30 → after end(20) → clamp to 09:00 next day
    # 09:00 BsAs next day (2026-05-02) = 12:00 UTC
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_str)
    result_local = result.astimezone(tz)
    assert result_local.hour == 9
    assert result_local.minute == 0
    assert result_local.date().day == 2  # next day


def test_calculate_before_start_of_window_clamps_same_day():
    """Time before start of window → clamp to start_hour same day."""
    from app.scheduler.service import calculate_scheduled_at

    tz_str = "America/Argentina/Buenos_Aires"
    # now_local = 07:00 BsAs → UTC = 10:00
    now_utc = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)  # 07:00 local
    result = calculate_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=60,
        start_hour=9,
        end_hour=20,
        tz_str=tz_str,
    )
    # candidate local = 08:00 → before start(9) → clamp to 09:00 same day
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_str)
    result_local = result.astimezone(tz)
    assert result_local.hour == 9
    assert result_local.minute == 0
    assert result_local.date().day == 1  # same day


def test_calculate_returns_utc_datetime():
    """calculate_scheduled_at always returns a UTC-aware datetime."""
    from app.scheduler.service import calculate_scheduled_at

    now_utc = datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)
    result = calculate_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=30,
        start_hour=9,
        end_hour=20,
        tz_str="America/Argentina/Buenos_Aires",
    )
    assert result.tzinfo is not None
    # Should be convertible to UTC
    utc_result = result.astimezone(timezone.utc)
    assert utc_result is not None


# ---------------------------------------------------------------------------
# DB-dependent tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sched_db(tmp_path: Path):
    """Isolated DB with quintana-seguros (scheduler_enabled=True) + test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/scheduler_service_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Sched Lead",
            phone="+5411000099",
            lead_id="sched-lead-001",
        )
        await sess.commit()

    # Enable scheduler on quintana
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_cooldown_minutes = 60
        client.scheduler_allowed_hours_start = 9
        client.scheduler_allowed_hours_end = 20
        client.scheduler_retry_on_outcomes = (
            '["busy","no_answer","follow_up","call_again"]'
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_create_scheduled_call_defaults(sched_db):
    """create_scheduled_call persists record with status=pending, attempt=1."""
    from app.scheduler.service import create_scheduled_call

    now = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sched_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()

    assert sc.status == "pending"
    assert sc.attempt_number == 1
    assert sc.trigger_reason == "manual"
    assert sc.client_id == "quintana-seguros"


async def test_create_scheduled_call_copies_max_attempts(sched_db):
    """create_scheduled_call copies max_attempts from caller (config at creation time)."""
    from app.scheduler.service import create_scheduled_call

    now = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sched_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=now,
            trigger_reason="auto_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=5,  # custom max_attempts
            notes="Test note",
        )
        await sess.commit()

    assert sc.max_attempts == 5
    assert sc.notes == "Test note"


async def test_auto_schedule_disabled_client_skips(sched_db):
    """auto_schedule returns None when client.scheduler_enabled=False."""
    from app.scheduler.service import auto_schedule

    # Disable scheduler
    async with sched_db.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = False
        await sess.commit()

    async with sched_db.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-001",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert result is None


async def test_auto_schedule_skips_do_not_call_lead(sched_db):
    """auto_schedule skips leads with do_not_call=True."""
    from app.scheduler.service import auto_schedule

    # Mark lead as do_not_call
    async with sched_db.async_session_factory() as sess:
        from app.leads.models import Lead

        lead = await sess.get(Lead, "sched-lead-001")
        lead.do_not_call = True
        await sess.commit()

    async with sched_db.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-001",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert result is None


async def test_auto_schedule_skips_ineligible_outcome(sched_db):
    """auto_schedule skips when next_action_suggested not in retry_outcomes."""
    from app.scheduler.service import auto_schedule

    async with sched_db.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-001",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "send_quote"},  # not in retry_outcomes
        )
        await sess.commit()

    assert result is None


async def test_auto_schedule_creates_scheduled_call(sched_db):
    """auto_schedule with eligible facts creates a ScheduledCall."""
    from app.scheduler.service import auto_schedule
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    async with sched_db.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-001",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert result is not None
    assert result.trigger_reason == "auto_retry"
    assert result.status == "pending"

    # Verify it's in the DB
    async with sched_db.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.lead_id == "sched-lead-001",
                ScheduledCall.trigger_reason == "auto_retry",
            )
        )
        sc = rows.scalar_one_or_none()
        assert sc is not None


async def test_auto_schedule_uses_client_config_for_scheduled_at(sched_db):
    """auto_schedule reads cooldown and allowed-hours config when computing scheduled_at."""
    from app.scheduler.service import auto_schedule, calculate_scheduled_at

    fixed_now = datetime(2026, 5, 1, 22, 30, 0, tzinfo=timezone.utc)

    async with sched_db.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_cooldown_minutes = 120
        client.scheduler_allowed_hours_start = 9
        client.scheduler_allowed_hours_end = 20
        client.scheduler_timezone = "America/Argentina/Buenos_Aires"
        await sess.commit()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is not None else fixed_now.replace(tzinfo=None)

    with patch("app.scheduler.service.datetime", FrozenDateTime):
        async with sched_db.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-001",
                lead_id="sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "call_again"},
            )
            await sess.commit()

    expected = calculate_scheduled_at(
        now_utc=fixed_now,
        cooldown_minutes=120,
        start_hour=9,
        end_hour=20,
        tz_str="America/Argentina/Buenos_Aires",
    )

    assert result is not None
    assert result.scheduled_at == expected


async def test_auto_schedule_duplicate_guard(sched_db):
    """auto_schedule returns existing record if pending ScheduledCall exists for lead."""
    from app.scheduler.service import auto_schedule
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # First call creates it
    async with sched_db.async_session_factory() as sess:
        first = await auto_schedule(
            db=sess,
            session_id="sess-001",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert first is not None

    # Second call should NOT create a duplicate
    async with sched_db.async_session_factory() as sess:
        second = await auto_schedule(
            db=sess,
            session_id="sess-002",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    # Returns None (duplicate skipped)
    assert second is None

    # Only 1 record in DB
    async with sched_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "sched-lead-001")
        )
        all_scs = result.scalars().all()
        assert len(all_scs) == 1


async def test_auto_schedule_skips_when_max_attempts_reached(sched_db):
    """auto_schedule stops when historical attempts already equal max_attempts."""
    from app.scheduler.service import auto_schedule, create_scheduled_call
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    async with sched_db.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_max_attempts = 3

        for idx in range(3):
            sc = await create_scheduled_call(
                sess,
                client_id="quintana-seguros",
                lead_id="sched-lead-001",
                scheduled_at=datetime.now(timezone.utc) - timedelta(days=idx + 1),
                trigger_reason="manual",
                source_session_id=None,
                attempt_number=idx + 1,
                max_attempts=3,
                notes=None,
            )
            sc.status = "completed"

        await sess.commit()

    async with sched_db.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-004",
            lead_id="sched-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    assert result is None

    async with sched_db.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "sched-lead-001")
        )
        assert len(rows.scalars().all()) == 3


async def test_mark_due_calls_in_progress(sched_db):
    """mark_due_calls_in_progress promotes pending due records to in_progress."""
    from app.scheduler.service import create_scheduled_call, mark_due_calls_in_progress
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Create a past-due scheduled call
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with sched_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=past,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    # Run tick
    async with sched_db.async_session_factory() as sess:
        count = await mark_due_calls_in_progress(sess)
        await sess.commit()

    assert count == 1

    async with sched_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        sc = result.scalar_one()
        assert sc.status == "in_progress"


async def test_mark_due_calls_future_call_untouched(sched_db):
    """mark_due_calls_in_progress leaves future pending calls untouched."""
    from app.scheduler.service import create_scheduled_call, mark_due_calls_in_progress
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Create a future scheduled call
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    async with sched_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=future,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    async with sched_db.async_session_factory() as sess:
        count = await mark_due_calls_in_progress(sess)
        await sess.commit()

    assert count == 0

    async with sched_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        sc = result.scalar_one()
        assert sc.status == "pending"


async def test_cancel_scheduled_call(sched_db):
    """cancel_scheduled_call transitions pending → cancelled."""
    from app.scheduler.service import create_scheduled_call, cancel_scheduled_call

    now = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sched_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    async with sched_db.async_session_factory() as sess:
        cancelled = await cancel_scheduled_call(sess, sc_id)
        await sess.commit()

    assert cancelled.status == "cancelled"


async def test_list_queue_returns_scheduled_calls(sched_db):
    """list_queue returns all ScheduledCalls for a client."""
    from app.scheduler.service import create_scheduled_call, list_queue

    now = datetime.now(timezone.utc) + timedelta(hours=1)
    async with sched_db.async_session_factory() as sess:
        await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="sched-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()

    async with sched_db.async_session_factory() as sess:
        items = await list_queue(sess, client_id="quintana-seguros")

    assert len(items) == 1
    assert items[0].client_id == "quintana-seguros"


# ---------------------------------------------------------------------------
# Round 2 fix — Issue 4: auto-schedule default outcome mismatch
# Default scheduler_retry_on_outcomes must include "call_again"
# ---------------------------------------------------------------------------


def test_client_default_retry_outcomes_includes_call_again():
    """Client model default scheduler_retry_on_outcomes must include 'call_again'.

    The summarizer schema emits 'call_again' as next_action_suggested.
    The default must match so auto-scheduling triggers without manual config.
    """
    import json
    from app.tenants.models import Client

    # The default value is set at the column level
    default_val = Client.__table__.c["scheduler_retry_on_outcomes"].default.arg
    outcomes = json.loads(default_val)
    assert (
        "call_again" in outcomes
    ), f"Default scheduler_retry_on_outcomes must include 'call_again', got: {outcomes}"


async def test_auto_schedule_triggers_with_call_again_on_fresh_client(tmp_path):
    """auto_schedule with 'call_again' must trigger on a client with default config.

    This verifies the default outcomes align with the summarizer's output values.
    A freshly created client should auto-schedule when next_action='call_again'.
    """
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/default_retry_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Default Retry Lead",
            phone="+54110000999",
            lead_id="default-retry-lead-001",
        )
        await sess.commit()

    # Enable scheduler but leave scheduler_retry_on_outcomes at DEFAULT
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        # Do NOT set scheduler_retry_on_outcomes — rely on default
        await sess.commit()

    from app.scheduler.service import auto_schedule

    async with db_module.async_session_factory() as sess:
        result = await auto_schedule(
            db=sess,
            session_id="sess-default-001",
            lead_id="default-retry-lead-001",
            client_id="quintana-seguros",
            facts={"next_action_suggested": "call_again"},
        )
        await sess.commit()

    await db_module.close_db()

    assert result is not None, (
        "auto_schedule should create a ScheduledCall when next_action='call_again' "
        "and default scheduler_retry_on_outcomes includes 'call_again'"
    )
