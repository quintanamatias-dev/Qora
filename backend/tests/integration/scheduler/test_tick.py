"""Integration tests for scheduler_tick background task — Phase 6 (Task 4.1).

Covers:
- scheduler_tick promotes due pending rows to in_progress
- scheduler_tick survives DB errors without crashing
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


@pytest_asyncio.fixture
async def tick_db(tmp_path: Path):
    """DB with quintana + test lead for tick tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/scheduler_tick_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Tick Test Lead",
            phone="+5411000066",
            lead_id="tick-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_scheduler_tick_promotes_due_calls(tick_db):
    """scheduler_tick promotes pending due calls to in_progress."""
    from app.scheduler.service import create_scheduled_call, mark_due_calls_in_progress
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Insert a past-due call
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with tick_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="tick-lead-001",
            scheduled_at=past,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    # Run the tick
    async with tick_db.async_session_factory() as sess:
        count = await mark_due_calls_in_progress(sess)
        await sess.commit()

    assert count == 1

    async with tick_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        updated = result.scalar_one()
        assert updated.status == "in_progress"


async def test_scheduler_tick_does_not_affect_future_calls(tick_db):
    """scheduler_tick leaves future pending calls untouched."""
    from app.scheduler.service import create_scheduled_call, mark_due_calls_in_progress
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    async with tick_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="tick-lead-001",
            scheduled_at=future,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    async with tick_db.async_session_factory() as sess:
        count = await mark_due_calls_in_progress(sess)
        await sess.commit()

    assert count == 0

    async with tick_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        sc = result.scalar_one()
        assert sc.status == "pending"


async def test_scheduler_tick_loop_survives_exception():
    """scheduler_tick catches exceptions and continues the loop (no crash)."""
    from unittest.mock import AsyncMock
    import asyncio
    from app.scheduler import service as scheduler_service

    # The tick uses asyncio.sleep(60) — we can't run the full loop.
    # Instead, test that mark_due_calls_in_progress is called safely even with DB error
    # by directly testing the error-catching pattern.

    call_count = 0

    async def failing_tick():
        nonlocal call_count
        call_count += 1
        raise Exception("Simulated DB failure")

    # Patch asyncio.sleep to exit after first iteration
    iterations = [0]

    async def controlled_sleep(seconds):
        iterations[0] += 1
        if iterations[0] >= 2:
            raise asyncio.CancelledError()

    from unittest.mock import patch as mock_patch

    with mock_patch("asyncio.sleep", side_effect=controlled_sleep):
        with mock_patch("app.core.database.get_session") as mock_gs:
            with mock_patch.object(scheduler_service.logger, "warning") as mock_warning:
                mock_ctx = AsyncMock()
                mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_gs.return_value = mock_ctx
                try:
                    await scheduler_service.scheduler_tick()
                except asyncio.CancelledError:
                    pass  # Expected controlled exit

    assert mock_gs.called
    mock_warning.assert_called_once()
    assert mock_warning.call_args.args[0] == "scheduler_tick_failed"
