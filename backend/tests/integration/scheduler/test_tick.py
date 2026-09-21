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
            phone="+5491100000001",
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


# ---------------------------------------------------------------------------
# Phase C6b Slice 1 — RED: run_scheduler_cycle dial loop + flag-off parity
#
# No test places a real call: app.outbound.service.dial_outbound_call is
# patched directly (runner seam, unit-only per design.md — Testing Strategy).
# The tick_db fixture provides a real (migrated) DB so claim + status writes
# are exercised for real; only the provider-adjacent dial call is faked.
# ---------------------------------------------------------------------------


def _auto_dialer_settings(tmp_path_db_url: str, *, enable_auto_dialer: bool):
    from app.core.config import Settings

    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=tmp_path_db_url,
        enable_auto_dialer=enable_auto_dialer,
        enable_outbound_calls=enable_auto_dialer,
        qora_webhook_auth_enabled=enable_auto_dialer,
        qora_webhook_secret=SecretStr("test-webhook-secret") if enable_auto_dialer else None,
        auto_dialer_max_concurrent_dials=1,
    )


from types import SimpleNamespace
from unittest.mock import AsyncMock, patch as _patch
from zoneinfo import ZoneInfo
import structlog.testing as _structlog_testing
from app.scheduler.service import (
    create_scheduled_call,
    mark_due_calls_in_progress,
    _dial_claimed_scheduled_call,
    calculate_scheduled_at,
    run_scheduler_cycle,
)
from app.leads.service import create_lead

_IN_WINDOW_UTC = datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc)  # inside default allowed hours (F2)


async def _mk_call(sess, lead_id, scheduled_at, **overrides):
    kwargs = dict(
        client_id="quintana-seguros", lead_id=lead_id, scheduled_at=scheduled_at,
        trigger_reason="manual", source_session_id=None, attempt_number=1,
        max_attempts=3, notes=None,
    )
    kwargs.update(overrides)
    return await create_scheduled_call(sess, **kwargs)


# Phase C6b Slice 1 — BOUNDED CORRECTION: F1, F2, F3, F4


async def test_mark_due_calls_in_progress_same_lead_conflict_skips_without_wedging(tick_db):
    """F1: same-lead conflict is skipped (not wedged); other leads still promote same cycle."""
    now = datetime.now(timezone.utc)
    async with tick_db.async_session_factory() as sess:
        a = await _mk_call(sess, "tick-lead-001", now - timedelta(minutes=10))
        b = await _mk_call(sess, "tick-lead-001", now - timedelta(minutes=5), trigger_reason="tech_retry", max_attempts=2)
        await create_lead(sess, client_id="quintana-seguros", name="Other", phone="+5491100000002", lead_id="tick-lead-002")
        other = await _mk_call(sess, "tick-lead-002", now - timedelta(minutes=1))
        await sess.commit()

        count = await mark_due_calls_in_progress(sess)
        await sess.commit()
        assert count == 2, f"Expected 2 promotions (1 conflict skipped), got {count}"

        for sc in (a, b, other):
            await sess.refresh(sc)
        assert sorted([a.status, b.status]) == ["in_progress", "pending"]
        assert other.status == "in_progress"


async def test_dial_claimed_scheduled_call_outside_allowed_hours_releases_to_pending():
    """F2: overdue row outside allowed hours is released to pending, not dialed."""
    tz = ZoneInfo("America/Argentina/Buenos_Aires")
    now_utc = datetime(2026, 7, 20, 3, 0, tzinfo=tz).astimezone(timezone.utc)  # 03:00 local
    expected_next = calculate_scheduled_at(now_utc, 0, 9, 20, "America/Argentina/Buenos_Aires")
    sc = SimpleNamespace(id="sc-1", lead_id="l-1", client_id="c-1", scheduled_at=now_utc - timedelta(days=1))
    client = SimpleNamespace(scheduler_allowed_hours_start=9, scheduler_allowed_hours_end=20, scheduler_timezone=str(tz))
    fake_dial = AsyncMock()

    with _patch("app.tenants.service.get_client", AsyncMock(return_value=client)), \
            _patch("app.outbound.service.dial_outbound_call", fake_dial), \
            _structlog_testing.capture_logs() as cap:
        await _dial_claimed_scheduled_call(AsyncMock(), sc, None, now_utc=now_utc)

    fake_dial.assert_not_called()
    assert "auto_dialer_dial_outside_allowed_hours" in [e.get("event") for e in cap]
    assert sc.status == "pending"
    assert sc.scheduled_at == expected_next


async def test_dial_claimed_scheduled_call_skips_do_not_call_lead():
    """F3: do_not_call set after scheduling blocks the dial and cancels the row."""
    sc = SimpleNamespace(id="sc-1", lead_id="l-1", client_id="c-1")
    lead = SimpleNamespace(do_not_call=True)
    fake_dial = AsyncMock()

    with _patch("app.tenants.service.get_client", AsyncMock(return_value=None)), \
            _patch("app.leads.service.get_lead", AsyncMock(return_value=lead)), \
            _patch("app.outbound.service.dial_outbound_call", fake_dial), \
            _structlog_testing.capture_logs() as cap:
        await _dial_claimed_scheduled_call(AsyncMock(), sc, None)

    fake_dial.assert_not_called()
    assert "auto_dialer_dial_skipped_do_not_call" in [e.get("event") for e in cap]
    assert sc.status == "cancelled"


async def test_run_scheduler_cycle_dial_failed_marks_scheduled_call_failed(tick_db):
    """DialResult.status='failed' (or 'recurrent_error') -> claimed row -> failed."""
    from unittest.mock import AsyncMock, patch
    from app.scheduler.service import create_scheduled_call, run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from app.outbound.service import DialResult
    from sqlalchemy import select

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

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)

    fake_dial = AsyncMock(
        return_value=DialResult(status="failed", call_session_id=None, error="boom")
    )
    async with tick_db.async_session_factory() as sess:
        with patch("app.outbound.service.dial_outbound_call", fake_dial):
            await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)  # F2: stay in-window

    async with tick_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        updated = result.scalar_one()
        assert updated.status == "failed"


async def test_run_scheduler_cycle_dial_dialing_stays_in_progress_with_session(
    tick_db,
):
    """DialResult.status='dialing' -> stays in_progress, outcome_session_id set."""
    from unittest.mock import AsyncMock, patch
    from app.scheduler.service import create_scheduled_call, run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from app.outbound.service import DialResult
    from sqlalchemy import select

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

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)

    fake_dial = AsyncMock(
        return_value=DialResult(status="dialing", call_session_id="cs-fake-001")
    )
    async with tick_db.async_session_factory() as sess:
        with patch("app.outbound.service.dial_outbound_call", fake_dial):
            await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)  # F2: stay in-window

    async with tick_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        updated = result.scalar_one()
        assert updated.status == "in_progress"
        assert updated.outcome_session_id == "cs-fake-001"


async def test_run_scheduler_cycle_flag_off_only_promotes_no_auto_dialer_events(
    tick_db,
):
    """enable_auto_dialer=False -> only mark_due_calls_in_progress runs.

    Proposal decision 6 / design.md byte-for-byte guarantee: when the flag is
    off, the tick does not even query for dial candidates — no auto_dialer_*
    events are emitted, only the existing scheduler_tick_promoted event.
    """
    import structlog.testing
    from app.scheduler.service import create_scheduled_call, run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

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

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=False)

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings)
            await sess.commit()

    events = [e.get("event") for e in cap]
    assert "scheduler_tick_promoted" in events
    assert not any(e.startswith("auto_dialer_") for e in events if e), (
        f"No auto_dialer_* events must fire when enable_auto_dialer=False, got: {events}"
    )

    async with tick_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        updated = result.scalar_one()
        assert updated.status == "in_progress"


async def test_run_scheduler_cycle_dials_sequentially_survives_one_failure(tick_db):
    """F4: dials run sequentially on the shared session; one raising doesn't
    stop siblings from reaching a terminal status."""
    from app.scheduler import service as svc
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with tick_db.async_session_factory() as sess:
        for i in range(3):
            await create_lead(sess, client_id="quintana-seguros", name=f"F4-{i}", phone=f"+549110000000{i + 3}", lead_id=f"f4-lead-{i}")
        sc_ids = [(await _mk_call(sess, f"f4-lead-{i}", past + timedelta(seconds=i))).id for i in range(3)]
        await sess.commit()

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)
    settings.auto_dialer_max_concurrent_dials = 3
    order = []

    async def fake_dial(db, sc, settings, *, now_utc=None):
        order.append(("enter", sc.id))
        if sc.id == sc_ids[1]:
            raise RuntimeError("boom")
        await svc._set_scheduled_call_status(db, sc, "failed")
        await db.commit()
        order.append(("exit", sc.id))

    async with tick_db.async_session_factory() as sess:
        with _patch.object(svc, "_dial_claimed_scheduled_call", fake_dial):
            await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)

    # Sequential: row 2's "enter" never appears before row 1's "exit" — proves
    # no two dials touched the shared session concurrently.
    assert order == [
        ("enter", sc_ids[0]), ("exit", sc_ids[0]),
        ("enter", sc_ids[1]),
        ("enter", sc_ids[2]), ("exit", sc_ids[2]),
    ]

    async with tick_db.async_session_factory() as sess:
        rows = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id.in_([sc_ids[0], sc_ids[2]]))
        )).scalars().all()
    assert all(r.status == "failed" for r in rows), rows


# ---------------------------------------------------------------------------
# Phase C6b Slice 2 — task 2.4.1: end-to-end completion + Decision 8 wiring
#
# due row -> claimed -> dialed (fake_dial stands in for the real dial;
# dial_outbound_call's own accepted-path behavior is already covered by
# Slice 1's tests) -> close_session -> ScheduledCall.status == "completed";
# a second pending tech_retry for the same lead is cancelled by the same
# close_session() call (D9). No test places a real call.
# ---------------------------------------------------------------------------


async def test_run_scheduler_cycle_completion_resolves_and_cancels_tech_retry(tick_db):
    from app.calls.models import CallSession
    from app.calls.service import close_session
    from app.scheduler import service as svc
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    call_session_id = "cs-e2e-completion-001"

    async with tick_db.async_session_factory() as sess:
        primary = await _mk_call(sess, "tick-lead-001", past)
        stale_retry = await _mk_call(
            sess, "tick-lead-001", past + timedelta(seconds=1),
            trigger_reason="tech_retry", max_attempts=2,
        )
        await sess.commit()
        primary_id, retry_id = primary.id, stale_retry.id

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)

    async def fake_dial(db, sc, settings, *, now_utc=None):
        db.add(CallSession(
            id=call_session_id, client_id="quintana-seguros", lead_id="tick-lead-001",
            status="initiated", telephony_provider="elevenlabs", telephony_status="ringing",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=45),
        ))
        sc.outcome_session_id = call_session_id
        await db.commit()

    async with tick_db.async_session_factory() as sess:
        with _patch.object(svc, "_dial_claimed_scheduled_call", fake_dial):
            await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)

    async with tick_db.async_session_factory() as sess:
        primary_row = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == primary_id)
        )).scalar_one()
        assert primary_row.status == "in_progress"
        assert primary_row.outcome_session_id == call_session_id
        # limit=1 (default) -> tech_retry (scheduled 1s later) is never claimed.
        retry_row = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == retry_id)
        )).scalar_one()
        assert retry_row.status == "pending"

    with _patch("app.calls.service._schedule_summarize") as schedule_summarize:
        async with tick_db.async_session_factory() as sess:
            await close_session(sess, session_id=call_session_id, closed_reason="session_end")
            await sess.commit()

    schedule_summarize.assert_called_once_with(call_session_id)
    async with tick_db.async_session_factory() as sess:
        rows = {
            r.id: r
            for r in (await sess.execute(
                select(ScheduledCall).where(ScheduledCall.id.in_([primary_id, retry_id]))
            )).scalars().all()
        }
        assert rows[primary_id].status == "completed"
        assert rows[retry_id].status == "cancelled", "D9: the parked tech_retry must be cancelled"


async def test_followup_tool_to_scheduler_to_call_completion(tick_db):
    """A duplicate follow-up tool call produces one completed outbound attempt."""
    from app.calls.models import CallSession
    from app.calls.service import close_session
    from app.elevenlabs.models import OutboundCallResult
    from app.elevenlabs.service import ElevenLabsService
    from app.leads.models import Lead
    from app.leads.service import transition_lead_status
    from app.scheduler.models import ScheduledCall
    from app.scheduler.service import run_scheduler_cycle
    from app.tenants.models import Client
    from app.tenants.service import get_default_agent
    from app.tools.schedule_followup import schedule_followup
    from sqlalchemy import select

    clock = [datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc)]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    due = clock[0] - timedelta(minutes=1)
    async with tick_db.async_session_factory() as sess:
        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        agent = await get_default_agent(sess, client.id)
        agent.elevenlabs_agent_id = "el-followup-agent"
        agent.elevenlabs_phone_number_id = "el-followup-phone"
        await transition_lead_status(sess, "tick-lead-001", "called")
        agent_id = agent.id
        await sess.commit()

    for followup_date in (due.isoformat(), due.isoformat()):
        async with tick_db.async_session_factory() as sess:
            result = await schedule_followup(
                sess,
                lead_id="tick-lead-001",
                followup_date=followup_date,
                client_id="quintana-seguros",
            )
            assert "error" not in result
            await sess.commit()

    async with tick_db.async_session_factory() as sess:
        scheduled_rows = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "tick-lead-001")
        )).scalars().all()
        assert len(scheduled_rows) == 1
        scheduled_call = scheduled_rows[0]
        scheduled_call_id = scheduled_call.id
        assert (
            scheduled_call.client_id,
            scheduled_call.lead_id,
            scheduled_call.agent_id,
            scheduled_call.trigger_reason,
            scheduled_call.status,
        ) == (
            "quintana-seguros",
            "tick-lead-001",
            agent_id,
            "followup_tool",
            "pending",
        )

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)
    accepted = OutboundCallResult(
        outcome="accepted", provider_call_id="provider-followup-001"
    )
    with _patch("app.scheduler.service.datetime", FrozenDateTime), _patch.object(
        ElevenLabsService, "initiate_outbound_call", AsyncMock(return_value=accepted)
    ) as provider_call, _patch("app.outbound.service._fire_probe") as fire_probe:
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])

        # An in-progress row cannot be claimed twice on a later tick.
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])

    provider_call.assert_awaited_once()
    fire_probe.assert_called_once()
    async with tick_db.async_session_factory() as sess:
        scheduled_call = await sess.get(ScheduledCall, scheduled_call_id)
        sessions = (await sess.execute(
            select(CallSession).where(CallSession.lead_id == "tick-lead-001")
        )).scalars().all()
        assert scheduled_call.status == "in_progress"
        assert len(sessions) == 1
        call_session = sessions[0]
        call_session_id = call_session.id
        assert scheduled_call.outcome_session_id == call_session_id
        assert (
            call_session.client_id,
            call_session.lead_id,
            call_session.agent_id,
            call_session.status,
            call_session.telephony_status,
            call_session.provider_call_id,
        ) == (
            "quintana-seguros",
            "tick-lead-001",
            agent_id,
            "initiated",
            "ringing",
            "provider-followup-001",
        )

    # Isolate only the legacy background summarizer; close_session itself is real.
    with _patch("app.calls.service._schedule_summarize") as schedule_summarize:
        async with tick_db.async_session_factory() as sess:
            _, already_closed = await close_session(
                sess, session_id=call_session_id, closed_reason="session_end"
            )
            await sess.commit()
        async with tick_db.async_session_factory() as sess:
            lead = await sess.get(Lead, "tick-lead-001")
            counters_after_first_close = (lead.call_count, lead.last_called_at)
        async with tick_db.async_session_factory() as sess:
            _, repeated_close = await close_session(
                sess, session_id=call_session_id, closed_reason="session_end"
            )
            await sess.commit()

    assert already_closed is False
    assert repeated_close is True
    schedule_summarize.assert_called_once_with(call_session_id)
    async with tick_db.async_session_factory() as sess:
        scheduled_call = await sess.get(ScheduledCall, scheduled_call_id)
        sessions = (await sess.execute(
            select(CallSession).where(CallSession.lead_id == "tick-lead-001")
        )).scalars().all()
        assert scheduled_call.status == "completed"
        assert scheduled_call.outcome_session_id == call_session_id
        assert len(sessions) == 1
        assert sessions[0].status == "completed"
        # Immediate offline closure is classified as voicemail; that maps to a
        # completed ScheduledCall because the dial attempt was consumed.
        assert sessions[0].telephony_status == "voicemail"

    with _patch("app.scheduler.service.datetime", FrozenDateTime), _patch.object(
        ElevenLabsService, "initiate_outbound_call", AsyncMock()
    ) as repeated_provider_call:
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])

    repeated_provider_call.assert_not_awaited()
    async with tick_db.async_session_factory() as sess:
        sessions = (await sess.execute(
            select(CallSession).where(CallSession.lead_id == "tick-lead-001")
        )).scalars().all()
        lead = await sess.get(Lead, "tick-lead-001")
        assert len(sessions) == 1
        assert {session.id for session in sessions} == {call_session_id}
        assert (lead.call_count, lead.last_called_at) == counters_after_first_close


# ---------------------------------------------------------------------------
# Phase C6b Slice 3 — RED: reap_stranded_scheduled_calls
#
# No test places a real call. Rows are seeded directly in in_progress via the
# ORM (create_scheduled_call always starts pending — see design.md/tasks.md
# 3.1-3.5) so the exact stranded state (updated_at, outcome_session_id) is
# under test control. Clock is always injected via reap's `now=` — no sleep,
# no wall-clock dependence.
# ---------------------------------------------------------------------------


async def _mk_stranded_call(
    sess, lead_id, *, updated_at, scheduled_at=None, outcome_session_id=None, **overrides
):
    """Create a ScheduledCall already in_progress with a controlled updated_at.

    create_scheduled_call always starts a row `pending` — this bypasses that
    to seed the exact class (a)/(b) stranded state under test.
    """
    sc = await _mk_call(
        sess, lead_id, scheduled_at or updated_at, **overrides
    )
    await sess.flush()
    sc.status = "in_progress"
    sc.updated_at = updated_at
    sc.outcome_session_id = outcome_session_id
    await sess.commit()
    await sess.refresh(sc)
    return sc


async def test_reap_class_a_attempts_remaining_releases_to_pending(tick_db):
    """3.1: never-dialed row past claim timeout, attempts remaining -> pending."""
    import structlog.testing
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    stale_updated_at = now - timedelta(minutes=15)  # past the 10-min claim timeout
    scheduled_at = now - timedelta(minutes=20)  # well within the 6h age-out cap

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await reap_stranded_scheduled_calls(sess, now=now)

    events = [e for e in cap if e.get("event") == "scheduled_call_reaped_stale"]
    assert len(events) == 1, cap
    assert events[0]["requeued"] is True
    assert events[0]["scheduled_call_id"] == sc_id

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "pending"


async def test_reap_class_a_attempts_exhausted_fails(tick_db):
    """3.1: never-dialed row past claim timeout, attempts exhausted -> failed."""
    import structlog.testing
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    stale_updated_at = now - timedelta(minutes=15)
    scheduled_at = now - timedelta(minutes=20)

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=3, max_attempts=3,
        )
        sc_id = sc.id

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await reap_stranded_scheduled_calls(sess, now=now)

    events = [e for e in cap if e.get("event") == "scheduled_call_reap_exhausted"]
    assert len(events) == 1, cap
    assert events[0]["scheduled_call_id"] == sc_id

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "failed"


async def test_reap_class_a_release_outside_allowed_hours_clamps_forward(tick_db):
    """3.2: released at 02:00 local -> scheduled_at clamped to the next 09:00."""
    from app.scheduler.service import reap_stranded_scheduled_calls, calculate_scheduled_at
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = datetime(2026, 7, 21, 5, 0, tzinfo=timezone.utc)  # 02:00 ART (outside 09-20 window)
    stale_updated_at = now - timedelta(minutes=15)
    scheduled_at = now - timedelta(minutes=20)
    expected_next = calculate_scheduled_at(
        now, 0, 9, 20, "America/Argentina/Buenos_Aires"
    )

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    async with tick_db.async_session_factory() as sess:
        await reap_stranded_scheduled_calls(sess, now=now)

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "pending"
        actual = updated.scheduled_at
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=timezone.utc)
        assert actual == expected_next


async def test_reap_class_a_release_inside_allowed_hours_keeps_scheduled_at(tick_db):
    """3.2: released at 14:00 local (inside window) -> scheduled_at unchanged.

    Regression guard: this is what makes the 6h age-out bound a crash loop
    instead of resetting the clock every reaper pass.
    """
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC  # 14:00 ART
    stale_updated_at = now - timedelta(minutes=15)
    scheduled_at = now - timedelta(minutes=20)

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id
        original_scheduled_at = sc.scheduled_at

    async with tick_db.async_session_factory() as sess:
        await reap_stranded_scheduled_calls(sess, now=now)

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "pending"
        assert updated.scheduled_at == original_scheduled_at


async def test_reap_class_a_aged_out_fails_regardless_of_attempts(tick_db):
    """3.3: class (a) row aged past the 6h cap -> failed, even with attempts remaining."""
    import structlog.testing
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    stale_updated_at = now - timedelta(minutes=15)  # past claim timeout too
    scheduled_at = now - timedelta(hours=7)  # past the 6h age-out cap

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await reap_stranded_scheduled_calls(sess, now=now)

    events = [e for e in cap if e.get("event") == "scheduled_call_reap_exhausted"]
    assert len(events) == 1, cap

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "failed"


async def test_reap_class_a_not_yet_past_claim_timeout_is_untouched(tick_db):
    """Sanity: a row updated recently (within the claim timeout) is not reaped."""
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    recent_updated_at = now - timedelta(minutes=2)  # well inside the 10-min timeout

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=recent_updated_at,
            scheduled_at=now - timedelta(minutes=5), attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    async with tick_db.async_session_factory() as sess:
        await reap_stranded_scheduled_calls(sess, now=now)

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "in_progress"


# ---------------------------------------------------------------------------
# 3.4 — class (b): dialed, completion signal never arrived
# ---------------------------------------------------------------------------


async def test_reap_class_b_terminal_status_resolves_via_shared_mapping(tick_db):
    """3.4: linked CallSession at a terminal telephony_status -> resolved."""
    from app.calls.models import CallSession
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    call_session_id = "cs-reap-class-b-001"

    async with tick_db.async_session_factory() as sess:
        sess.add(CallSession(
            id=call_session_id, client_id="quintana-seguros", lead_id="tick-lead-001",
            status="completed", telephony_provider="elevenlabs", telephony_status="completed",
            started_at=now - timedelta(minutes=45),
        ))
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=now - timedelta(minutes=2),
            scheduled_at=now - timedelta(minutes=45),
            outcome_session_id=call_session_id, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    async with tick_db.async_session_factory() as sess:
        await reap_stranded_scheduled_calls(sess, now=now)

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "completed"


async def test_reap_class_b_non_terminal_status_is_untouched(tick_db):
    """3.4: non-terminal telephony_status is left for the 30-min sweeper."""
    from app.calls.models import CallSession
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    call_session_id = "cs-reap-class-b-002"

    async with tick_db.async_session_factory() as sess:
        sess.add(CallSession(
            id=call_session_id, client_id="quintana-seguros", lead_id="tick-lead-001",
            status="initiated", telephony_provider="elevenlabs", telephony_status="ringing",
            started_at=now - timedelta(minutes=45),
        ))
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=now - timedelta(minutes=2),
            scheduled_at=now - timedelta(minutes=45),
            outcome_session_id=call_session_id, attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    async with tick_db.async_session_factory() as sess:
        await reap_stranded_scheduled_calls(sess, now=now)

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "in_progress"


async def test_reap_class_b_missing_call_session_fails(tick_db):
    """3.4: outcome_session_id points at a CallSession that no longer exists -> failed."""
    import structlog.testing
    from app.scheduler.service import reap_stranded_scheduled_calls
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=now - timedelta(minutes=2),
            scheduled_at=now - timedelta(minutes=45),
            outcome_session_id="cs-does-not-exist", attempt_number=1, max_attempts=3,
        )
        sc_id = sc.id

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await reap_stranded_scheduled_calls(sess, now=now)

    events = [e for e in cap if e.get("event") == "scheduled_call_reap_session_missing"]
    assert len(events) == 1, cap
    assert events[0]["scheduled_call_id"] == sc_id

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "failed"


# ---------------------------------------------------------------------------
# 3.5 — tick wiring + full-cycle no-stranding proof
# ---------------------------------------------------------------------------


async def test_run_scheduler_cycle_reaps_before_claim_no_row_stranded(tick_db):
    """3.5 (R3-1: reaper now also gated on enable_auto_dialer): clock advanced
    past both timeouts -> no row remains in_progress after two cycles. This
    is also the gate to flip enable_auto_dialer=true.
    """
    from app.calls.models import CallSession
    from app.scheduler.service import run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    call_session_id = "cs-e2e-reap-001"

    async with tick_db.async_session_factory() as sess:
        # class (a): never dialed, past the 10-min claim timeout, attempts
        # exhausted -> failed directly. The mark_due_calls_in_progress
        # interaction (legacy-promoted rows must stay untouched while
        # enable_auto_dialer is off) is a *different* scenario, covered by
        # test_run_scheduler_cycle_reaper_gated_off_leaves_legacy_rows_untouched
        # below; this test isolates the "no genuinely stranded row survives"
        # guarantee with the reaper actually running.
        never_dialed = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=now - timedelta(minutes=15),
            scheduled_at=now - timedelta(minutes=20), attempt_number=3, max_attempts=3,
        )
        never_dialed_id = never_dialed.id

        # class (b): dialed, linked CallSession terminal past the 30-min sweep.
        await create_lead(sess, client_id="quintana-seguros", name="Reap E2E", phone="+5491100000006", lead_id="reap-lead-002")
        sess.add(CallSession(
            id=call_session_id, client_id="quintana-seguros", lead_id="reap-lead-002",
            status="completed", telephony_provider="elevenlabs", telephony_status="stale_in_call",
            started_at=now - timedelta(minutes=45),
        ))
        dialed = await _mk_stranded_call(
            sess, "reap-lead-002", updated_at=now - timedelta(minutes=35),
            scheduled_at=now - timedelta(minutes=45),
            outcome_session_id=call_session_id, attempt_number=1, max_attempts=3,
        )
        dialed_id = dialed.id

    # R3-1: the reaper only runs when enable_auto_dialer is also true.
    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)

    async with tick_db.async_session_factory() as sess:
        await run_scheduler_cycle(sess, settings, now_utc=now)
    async with tick_db.async_session_factory() as sess:
        await run_scheduler_cycle(sess, settings, now_utc=now + timedelta(minutes=1))

    async with tick_db.async_session_factory() as sess:
        rows = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id.in_([never_dialed_id, dialed_id]))
        )).scalars().all()
        assert all(r.status != "in_progress" for r in rows), rows
        by_id = {r.id: r for r in rows}
        assert by_id[never_dialed_id].status == "failed"
        assert by_id[dialed_id].status == "failed"


# ---------------------------------------------------------------------------
# R3-1 — reaper gated on enable_auto_dialer (not just enable_outbound_calls)
#
# Before this fix, enable_auto_dialer=False + enable_outbound_calls=True (the
# exact production dry-run config above) let the reaper inspect in_progress
# rows bulk-promoted by mark_due_calls_in_progress -- a legacy path the
# reaper cannot distinguish from a stale auto-dialer claim.
# ---------------------------------------------------------------------------


async def test_run_scheduler_cycle_reaper_gated_off_leaves_legacy_rows_untouched(
    tick_db,
):
    """R3-1 bug guard: with enable_auto_dialer=False + enable_outbound_calls=True,
    a row promoted by mark_due_calls_in_progress's real code path must never be
    reaped, even long past the claim timeout.
    """
    import structlog.testing
    from app.scheduler.service import mark_due_calls_in_progress, run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select, update

    past = _IN_WINDOW_UTC - timedelta(minutes=5)
    async with tick_db.async_session_factory() as sess:
        sc = await _mk_call(
            sess, "tick-lead-001", past, attempt_number=3, max_attempts=3,
        )
        await sess.commit()
        sc_id = sc.id

    # Real code path -- not seeded directly as in_progress.
    async with tick_db.async_session_factory() as sess:
        count = await mark_due_calls_in_progress(sess)
        # mark_due_calls_in_progress stamps updated_at from real wall-clock time.
        # Pin it to `past` so staleness is measured against the injected clock
        # below, not against the calendar date this test happens to run on --
        # otherwise the class-(a) predicate never matches and the assertions
        # below pass vacuously, proving nothing about the gate.
        await sess.execute(
            update(ScheduledCall).where(ScheduledCall.id == sc_id).values(updated_at=past)
        )
        await sess.commit()
    assert count == 1

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=False)
    settings.enable_outbound_calls = True  # the exact config this finding covers

    # Advance the injected clock well past the 10-minute claim timeout.
    later = _IN_WINDOW_UTC + timedelta(minutes=15)
    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=later)

    reap_events = [e.get("event") for e in cap if str(e.get("event", "")).startswith("scheduled_call_reap")]
    assert reap_events == [], reap_events

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "in_progress"
        assert updated.attempt_number == 3


async def test_run_scheduler_cycle_reaper_still_runs_when_auto_dialer_enabled(
    tick_db,
):
    """Positive case: enable_auto_dialer=True + enable_outbound_calls=True still
    reaps a genuinely stranded row -- the R3-1 gate does not disable reaping.
    """
    import structlog.testing
    from app.scheduler.service import run_scheduler_cycle
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    now = _IN_WINDOW_UTC
    stale_updated_at = now - timedelta(minutes=15)
    scheduled_at = now - timedelta(minutes=20)

    async with tick_db.async_session_factory() as sess:
        sc = await _mk_stranded_call(
            sess, "tick-lead-001", updated_at=stale_updated_at,
            scheduled_at=scheduled_at, attempt_number=3, max_attempts=3,
        )
        sc_id = sc.id

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)

    with structlog.testing.capture_logs() as cap:
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=now)

    events = [e for e in cap if e.get("event") == "scheduled_call_reap_exhausted"]
    assert len(events) == 1, cap
    assert events[0]["scheduled_call_id"] == sc_id

    async with tick_db.async_session_factory() as sess:
        updated = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )).scalar_one()
        assert updated.status == "failed"


async def test_scheduler_cycle_rejects_cross_client_targets_before_provider_or_session(tick_db):
    """The real scheduler path rejects foreign lead/agent and missing-agent rows."""
    from app.calls.models import CallSession
    from app.elevenlabs.models import OutboundCallResult
    from app.elevenlabs.service import ElevenLabsService
    from app.scheduler.models import ScheduledCall
    from app.scheduler.service import create_scheduled_call, run_scheduler_cycle
    from app.tenants.models import Agent, Client
    from app.tenants.service import get_default_agent
    from sqlalchemy import select

    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with tick_db.async_session_factory() as sess:
        default_agent = await get_default_agent(sess, "quintana-seguros")
        default_agent.elevenlabs_agent_id = "el-quintana-agent"
        default_agent.elevenlabs_phone_number_id = "el-quintana-phone"
        sess.add(Client(id="other-client", name="Other Client", voice_id="other-voice"))
        sess.add(Agent(
            id="other-agent", client_id="other-client", slug="other", name="Other",
            voice_id="other-voice", elevenlabs_agent_id="el-other-agent",
            elevenlabs_phone_number_id="el-other-phone",
        ))
        await create_lead(
            sess, client_id="other-client", name="Foreign", phone="+5491100000007",
            lead_id="foreign-lead",
        )
        await create_lead(
            sess, client_id="quintana-seguros", name="Owned", phone="+5491100000008",
            lead_id="owned-lead",
        )
        await create_lead(
            sess, client_id="quintana-seguros", name="Missing Agent", phone="+5491100000009",
            lead_id="missing-agent-lead",
        )
        default_agent_id = default_agent.id
        foreign_lead = await create_scheduled_call(
            sess, client_id="quintana-seguros", lead_id="foreign-lead",
            scheduled_at=due - timedelta(seconds=3), trigger_reason="manual",
            source_session_id=None, attempt_number=1, max_attempts=3,
            notes=None, agent_id=default_agent_id,
        )
        foreign_agent = await create_scheduled_call(
            sess, client_id="quintana-seguros", lead_id="owned-lead",
            scheduled_at=due - timedelta(seconds=2), trigger_reason="manual",
            source_session_id=None, attempt_number=1, max_attempts=3,
            notes=None, agent_id="other-agent",
        )
        missing_agent = await create_scheduled_call(
            sess, client_id="quintana-seguros", lead_id="missing-agent-lead",
            scheduled_at=due - timedelta(seconds=1), trigger_reason="tech_retry",
            source_session_id=None, attempt_number=1, max_attempts=2,
            notes=None, agent_id="missing-agent",
        )
        await sess.commit()
        ids = foreign_lead.id, foreign_agent.id, missing_agent.id

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)
    settings.auto_dialer_max_concurrent_dials = 1
    with _patch.object(ElevenLabsService, "initiate_outbound_call", AsyncMock()) as provider_call:
        for _ in range(3):
            async with tick_db.async_session_factory() as sess:
                await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)

    provider_call.assert_not_awaited()
    async with tick_db.async_session_factory() as sess:
        rows = {
            row.id: row
            for row in (await sess.execute(
                select(ScheduledCall).where(ScheduledCall.id.in_(ids))
            )).scalars()
        }
        sessions = (await sess.execute(select(CallSession))).scalars().all()

    assert all(rows[scheduled_call_id].status == "failed" for scheduled_call_id in ids)
    assert sessions == []


async def test_dial_outbound_rejects_cross_client_objects_before_flag_check(tick_db):
    """Ownership is enforced before the flag guard without creating a session."""
    from app.calls.models import CallSession
    from app.leads.service import get_lead
    from app.outbound.service import dial_outbound_call
    from app.tenants.models import Agent, Client
    from app.tenants.service import get_default_agent
    from sqlalchemy import select

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=False)
    async with tick_db.async_session_factory() as sess:
        client = await sess.get(Client, "quintana-seguros")
        lead = await get_lead(sess, "tick-lead-001")
        agent = await get_default_agent(sess, client.id)
        foreign_client = Client(
            id="direct-other-client", name="Direct Other", voice_id="other-voice"
        )
        foreign_agent = Agent(
            id="direct-other-agent", client_id="direct-other-client", slug="other",
            name="Other", voice_id="other-voice",
        )
        sess.add_all([foreign_client, foreign_agent])
        await sess.flush()

        lead_result = await dial_outbound_call(
            sess, lead=lead, agent=agent, client=foreign_client, settings=settings
        )
        agent_result = await dial_outbound_call(
            sess, lead=lead, agent=foreign_agent, client=client, settings=settings
        )
        sessions = (await sess.execute(select(CallSession))).scalars().all()

    assert lead_result.failure_code == "ownership_mismatch"
    assert agent_result.failure_code == "ownership_mismatch"
    assert sessions == []


async def test_scheduler_cycle_retries_transient_provider_failure_at_due_time(tick_db):
    """A real scheduler and outbound flow creates one due technical retry."""
    from app.calls.models import CallSession
    from app.elevenlabs.models import OutboundCallResult
    from app.elevenlabs.service import ElevenLabsService
    from app.scheduler.models import ScheduledCall
    from app.scheduler.service import create_scheduled_call, run_scheduler_cycle
    from app.tenants.service import get_default_agent
    from sqlalchemy import select

    clock = [datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc)]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    async with tick_db.async_session_factory() as sess:
        agent = await get_default_agent(sess, "quintana-seguros")
        agent.elevenlabs_agent_id = "el-quintana-agent"
        agent.elevenlabs_phone_number_id = "el-quintana-phone"
        agent_id = agent.id
        original = await create_scheduled_call(
            sess, client_id="quintana-seguros", lead_id="tick-lead-001",
            scheduled_at=clock[0] - timedelta(minutes=1), trigger_reason="manual",
            source_session_id=None, attempt_number=1, max_attempts=3, notes=None,
            agent_id=agent_id,
        )
        await sess.commit()
        original_id = original.id

    settings = _auto_dialer_settings("sqlite+aiosqlite:///unused", enable_auto_dialer=True)
    outcomes = [
        OutboundCallResult(outcome="error", error_category="transient", error_detail="first"),
        OutboundCallResult(outcome="error", error_category="transient", error_detail="second"),
        OutboundCallResult(outcome="accepted", provider_call_id="provider-retry"),
    ]
    with _patch("app.scheduler.service.datetime", FrozenDateTime), _patch.object(
        ElevenLabsService, "initiate_outbound_call", AsyncMock(side_effect=outcomes)
    ) as provider_call, _patch("app.outbound.probe.probe_call_evidence", AsyncMock()):
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])

        async with tick_db.async_session_factory() as sess:
            rows = (await sess.execute(
                select(ScheduledCall).where(ScheduledCall.lead_id == "tick-lead-001")
            )).scalars().all()
            sessions = (await sess.execute(select(CallSession))).scalars().all()

        assert provider_call.await_count == 2
        assert len(rows) == 2
        assert len(sessions) == 1
        original_row = next(row for row in rows if row.id == original_id)
        retry_row = next(row for row in rows if row.trigger_reason == "tech_retry")
        first_session = sessions[0]
        first_session_id = first_session.id
        retry_id = retry_row.id
        assert original_row.status == "failed"
        assert original_row.outcome_session_id is None
        assert (first_session.client_id, first_session.lead_id, first_session.agent_id) == (
            "quintana-seguros", "tick-lead-001", agent_id,
        )
        assert first_session.telephony_status == "recurrent_error"
        assert retry_row.status == "pending"
        assert retry_row.outcome_session_id is None
        assert retry_row.source_session_id == first_session_id
        assert (retry_row.client_id, retry_row.lead_id, retry_row.agent_id) == (
            "quintana-seguros", "tick-lead-001", agent_id,
        )

        clock[0] += timedelta(minutes=4)
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])
        assert provider_call.await_count == 2
        async with tick_db.async_session_factory() as sess:
            early_rows = (await sess.execute(
                select(ScheduledCall).where(ScheduledCall.lead_id == "tick-lead-001")
            )).scalars().all()
            early_sessions = (await sess.execute(select(CallSession))).scalars().all()
        assert len(early_rows) == 2
        assert len(early_sessions) == 1
        assert early_sessions[0].id == first_session_id
        early_retry = next(row for row in early_rows if row.id == retry_id)
        assert early_retry.status == "pending"
        assert early_retry.outcome_session_id is None

        clock[0] += timedelta(minutes=1)
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=clock[0])

    assert provider_call.await_count == 3
    async with tick_db.async_session_factory() as sess:
        rows = (await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "tick-lead-001")
        )).scalars().all()
        sessions = (await sess.execute(select(CallSession))).scalars().all()

    assert len(rows) == 2
    assert len(sessions) == 2
    original_row = next(row for row in rows if row.id == original_id)
    retry_row = next(row for row in rows if row.id == retry_id)
    original_session = next(session for session in sessions if session.id == first_session_id)
    retry_session = next(session for session in sessions if session.id == retry_row.outcome_session_id)
    assert original_row.status == "failed"
    assert original_row.outcome_session_id is None
    assert retry_row.status == "in_progress"
    assert retry_row.source_session_id == first_session_id
    assert (retry_row.client_id, retry_row.lead_id, retry_row.agent_id) == (
        "quintana-seguros", "tick-lead-001", agent_id,
    )
    assert (original_session.client_id, original_session.lead_id, original_session.agent_id) == (
        "quintana-seguros", "tick-lead-001", agent_id,
    )
    assert original_session.telephony_status == "recurrent_error"
    assert retry_session.telephony_status == "ringing"
    assert (retry_session.client_id, retry_session.lead_id, retry_session.agent_id) == (
        "quintana-seguros", "tick-lead-001", agent_id,
    )


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
