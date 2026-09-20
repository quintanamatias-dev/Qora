"""Unit tests for outcome-driven completion + Decision 8 — Phase C6b Slice 2.

Covers:
- resolve_scheduled_call_for_session(): maps a finished CallSession's terminal
  telephony_status onto the linked ScheduledCall's status; no-op for missing
  links, already-resolved rows (idempotent), and non-terminal statuses.
- Decision 8 (D9 in code): a pending tech_retry for the same lead is cancelled
  when this session resolves to "completed"; untouched on "failed"; an
  in_progress tech_retry is never matched by the pending-only lookup.

No test places a real call — these exercise only the DB-level resolution
primitive against a real (migrated) SQLite DB.

Design: openspec/changes/phase-c6b-auto-dialer/design.md — The Completion Hook.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select


@pytest_asyncio.fixture
async def completion_db(tmp_path: Path):
    """Isolated DB with quintana-seguros + a test lead for completion-hook tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/completion_hook_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db

    await _init_db(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Completion Lead",
            phone="+5411000088",
            lead_id="completion-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def _mk_in_progress_call(sess, *, session_id: str, lead_id: str = "completion-lead-001"):
    """Create a ScheduledCall pre-set to in_progress with a linked session id."""
    from app.scheduler.service import create_scheduled_call

    sc = await create_scheduled_call(
        sess,
        client_id="quintana-seguros",
        lead_id=lead_id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        trigger_reason="manual",
        source_session_id=None,
        attempt_number=1,
        max_attempts=3,
        notes=None,
    )
    sc.status = "in_progress"
    sc.outcome_session_id = session_id
    await sess.flush()
    return sc


# ---------------------------------------------------------------------------
# 2.1 — mapping table + resolve_scheduled_call_for_session
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "telephony_status,expected",
    [
        ("completed", "completed"),
        ("voicemail", "completed"),
        ("no_answer", "failed"),
        ("failed", "failed"),
        ("recurrent_error", "failed"),
        ("stale_in_call", "failed"),
    ],
)
async def test_resolve_maps_terminal_telephony_status(completion_db, telephony_status, expected):
    from app.scheduler.service import resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        sc = await _mk_in_progress_call(sess, session_id=f"cs-map-{telephony_status}")
        await sess.commit()
        sc_id = sc.id

    async with completion_db.async_session_factory() as sess:
        resolved = await resolve_scheduled_call_for_session(
            sess, call_session_id=f"cs-map-{telephony_status}", telephony_status=telephony_status
        )
        await sess.commit()

    assert resolved is not None and resolved.id == sc_id
    assert resolved.status == expected


async def test_resolve_no_linked_scheduled_call_is_noop(completion_db):
    from app.scheduler.service import resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        resolved = await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-missing-001", telephony_status="completed"
        )

    assert resolved is None


async def test_resolve_non_in_progress_row_is_idempotent_noop(completion_db):
    """A session whose linked row was already resolved must not resolve twice."""
    from app.scheduler.service import resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        sc = await _mk_in_progress_call(sess, session_id="cs-idem-001")
        sc.status = "completed"  # already resolved by a prior close
        await sess.commit()

    async with completion_db.async_session_factory() as sess:
        resolved = await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-idem-001", telephony_status="completed"
        )

    assert resolved is None


async def test_resolve_non_terminal_telephony_status_is_noop(completion_db):
    from app.scheduler.service import resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        sc = await _mk_in_progress_call(sess, session_id="cs-nonterm-001")
        await sess.commit()
        sc_id = sc.id

    async with completion_db.async_session_factory() as sess:
        resolved = await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-nonterm-001", telephony_status="ringing"
        )

    assert resolved is None

    async with completion_db.async_session_factory() as sess:
        result = await sess.execute(select(_sc()).where(_sc().id == sc_id))
        assert result.scalar_one().status == "in_progress", "Non-terminal status must not mutate the row"


def _sc():
    from app.scheduler.models import ScheduledCall

    return ScheduledCall


# ---------------------------------------------------------------------------
# 2.3 — Decision 8: cancel a parked tech_retry on successful conversation
# ---------------------------------------------------------------------------


async def test_resolve_completed_cancels_pending_tech_retry_for_lead(completion_db):
    from app.scheduler.service import create_scheduled_call, resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        await _mk_in_progress_call(sess, session_id="cs-d9-001")
        stale_retry = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="completion-lead-001",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=8),
            trigger_reason="tech_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=2,
            notes=None,
        )
        await sess.commit()
        retry_id = stale_retry.id

    async with completion_db.async_session_factory() as sess:
        await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-d9-001", telephony_status="completed"
        )
        await sess.commit()

    async with completion_db.async_session_factory() as sess:
        result = await sess.execute(select(_sc()).where(_sc().id == retry_id))
        assert result.scalar_one().status == "cancelled"


async def test_resolve_failed_does_not_cancel_pending_tech_retry(completion_db):
    from app.scheduler.service import create_scheduled_call, resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        await _mk_in_progress_call(sess, session_id="cs-d9-002")
        stale_retry = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="completion-lead-001",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=8),
            trigger_reason="tech_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=2,
            notes=None,
        )
        await sess.commit()
        retry_id = stale_retry.id

    async with completion_db.async_session_factory() as sess:
        await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-d9-002", telephony_status="failed"
        )
        await sess.commit()

    async with completion_db.async_session_factory() as sess:
        result = await sess.execute(select(_sc()).where(_sc().id == retry_id))
        assert result.scalar_one().status == "pending", "A failed resolution must NOT cancel the parked retry"


async def test_resolve_completed_no_pending_tech_retry_is_noop(completion_db):
    """No pending tech_retry for the lead -> resolution still succeeds, no error."""
    from app.scheduler.service import resolve_scheduled_call_for_session

    async with completion_db.async_session_factory() as sess:
        await _mk_in_progress_call(sess, session_id="cs-d9-003")
        await sess.commit()

    async with completion_db.async_session_factory() as sess:
        resolved = await resolve_scheduled_call_for_session(
            sess, call_session_id="cs-d9-003", telephony_status="completed"
        )
        await sess.commit()

    assert resolved is not None
    assert resolved.status == "completed"


async def test_get_pending_tech_retry_for_lead_ignores_in_progress_row(completion_db):
    """D9 scope: an in_progress tech_retry is never matched by the pending-only
    lookup — it resolves through its own dial outcome or the reaper, same as
    any other in-flight row. (An in_progress tech_retry cannot coexist with a
    second in_progress row for the same lead — uq_scheduled_calls_active_lead
    — so this is exercised directly against the lookup, not the full
    resolve_scheduled_call_for_session path.)"""
    from app.scheduler.service import create_scheduled_call, get_pending_tech_retry_for_lead

    async with completion_db.async_session_factory() as sess:
        retry = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="completion-lead-001",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=8),
            trigger_reason="tech_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=2,
            notes=None,
        )
        retry.status = "in_progress"
        await sess.commit()

    async with completion_db.async_session_factory() as sess:
        found = await get_pending_tech_retry_for_lead(
            sess, client_id="quintana-seguros", lead_id="completion-lead-001"
        )

    assert found is None
