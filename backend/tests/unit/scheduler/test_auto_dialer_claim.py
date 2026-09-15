"""Unit tests for the CAS claim primitives — Phase C6b Slice 1 (task 1.3).

Covers:
- _claim_one: atomic conditional UPDATE, True once per row, False for the loser.
- _claim_one: a second lead-row claim hits uq_scheduled_calls_active_lead and
  raises IntegrityError, caught and logged as auto_dialer_claim_conflict, False.
- claim_due_scheduled_calls: bounded candidate SELECT + wraps _claim_one,
  returns only the rows this process actually won.

No test places a real call — these exercise only the DB-level claim primitive
against a real (migrated) SQLite DB. dial_outbound_call is never invoked here.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio
from pydantic import SecretStr


@pytest_asyncio.fixture
async def claim_db(tmp_path: Path):
    """Isolated DB with quintana-seguros + a test lead for claim tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/auto_dialer_claim_test.db",
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
            name="Claim Test Lead",
            phone="+5491155550101",
            lead_id="claim-lead-001",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Claim Test Lead Two",
            phone="+5493415550101",
            lead_id="claim-lead-002",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_claim_one_returns_true_once_and_false_for_the_loser(claim_db):
    """_claim_one wins exactly once on a single row — the second call loses
    the race (status is no longer 'pending')."""
    from app.scheduler.service import _claim_one, create_scheduled_call

    now = datetime.now(timezone.utc)
    async with claim_db.async_session_factory() as sess:
        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="claim-lead-001",
            scheduled_at=now - timedelta(minutes=5),
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        sc_id = sc.id

    async with claim_db.async_session_factory() as sess:
        won = await _claim_one(sess, sc_id, now)
    assert won is True, "First claim on a pending row must win"

    async with claim_db.async_session_factory() as sess:
        lost = await _claim_one(sess, sc_id, now)
    assert lost is False, "Second claim on the same (now in_progress) row must lose"


async def test_claim_one_second_lead_row_hits_unique_index_conflict(claim_db):
    """Two pending rows for the SAME lead: claiming both hits
    uq_scheduled_calls_active_lead on the second — IntegrityError is caught,
    logged as auto_dialer_claim_conflict, and _claim_one returns False.

    This is the D1-confirmed reachable state: an in_progress auto_retry row
    plus a pending tech_retry row for the same lead — both eligible to be
    claimed, but only one may become in_progress at a time.
    """
    from app.scheduler.service import _claim_one, create_scheduled_call

    now = datetime.now(timezone.utc)
    async with claim_db.async_session_factory() as sess:
        sc_a = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="claim-lead-002",
            scheduled_at=now - timedelta(minutes=5),
            trigger_reason="auto_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        sc_b = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="claim-lead-002",
            scheduled_at=now - timedelta(minutes=3),
            trigger_reason="tech_retry",
            source_session_id=None,
            attempt_number=1,
            max_attempts=2,
            notes=None,
        )
        await sess.commit()
        sc_a_id, sc_b_id = sc_a.id, sc_b.id

    # Claim the first row — wins cleanly.
    async with claim_db.async_session_factory() as sess:
        won_a = await _claim_one(sess, sc_a_id, now)
    assert won_a is True

    # Claiming the second row for the SAME lead must hit the unique index.
    from app.scheduler import service as scheduler_service

    with patch.object(scheduler_service.logger, "warning") as mock_warning:
        async with claim_db.async_session_factory() as sess:
            won_b = await _claim_one(sess, sc_b_id, now)

    assert won_b is False, (
        "Second claim for a lead that already has an in_progress row must lose "
        "to the unique index, not silently succeed."
    )
    conflict_calls = [
        c for c in mock_warning.call_args_list if c.args and c.args[0] == "auto_dialer_claim_conflict"
    ]
    assert conflict_calls, (
        f"Expected an 'auto_dialer_claim_conflict' warning log, "
        f"got calls: {mock_warning.call_args_list}"
    )


async def test_claim_due_scheduled_calls_returns_only_won_rows(claim_db):
    """claim_due_scheduled_calls selects due pending rows (bounded by limit)
    and returns only the ones this process actually claimed."""
    from app.scheduler.service import claim_due_scheduled_calls, create_scheduled_call

    now = datetime.now(timezone.utc)
    async with claim_db.async_session_factory() as sess:
        due = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="claim-lead-001",
            scheduled_at=now - timedelta(minutes=5),
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        future = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="claim-lead-002",
            scheduled_at=now + timedelta(hours=1),
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        await sess.commit()
        due_id, future_id = due.id, future.id

    async with claim_db.async_session_factory() as sess:
        claimed = await claim_due_scheduled_calls(sess, limit=5)
        await sess.commit()

    claimed_ids = {sc.id for sc in claimed}
    assert due_id in claimed_ids, "The due pending row must be claimed"
    assert future_id not in claimed_ids, "A future scheduled row must not be claimed"
    for sc in claimed:
        assert sc.status == "in_progress"


async def test_claim_due_scheduled_calls_respects_limit(claim_db):
    """claim_due_scheduled_calls never claims more than `limit` rows per call."""
    from app.scheduler.service import claim_due_scheduled_calls, create_scheduled_call

    now = datetime.now(timezone.utc)
    async with claim_db.async_session_factory() as sess:
        for idx in range(3):
            await create_scheduled_call(
                sess,
                client_id="quintana-seguros",
                lead_id="claim-lead-001" if idx % 2 == 0 else "claim-lead-002",
                scheduled_at=now - timedelta(minutes=idx + 1),
                trigger_reason="manual",
                source_session_id=None,
                attempt_number=1,
                max_attempts=3,
                notes=f"row-{idx}",
            )
        await sess.commit()

    async with claim_db.async_session_factory() as sess:
        claimed = await claim_due_scheduled_calls(sess, limit=1)
        await sess.commit()

    assert len(claimed) == 1, f"Expected exactly 1 claimed row, got {len(claimed)}"


async def test_claimed_invalid_phone_uses_real_shared_guard_without_session(claim_db):
    """A scheduled legacy number fails before any CallSession or provider creation."""
    from unittest.mock import MagicMock

    from sqlalchemy import select

    from app.calls.models import CallSession
    from app.leads.models import Lead
    from app.scheduler.models import ScheduledCall
    from app.scheduler.service import _dial_claimed_scheduled_call, create_scheduled_call

    now = datetime.now(timezone.utc)
    async with claim_db.async_session_factory() as sess:
        lead = await sess.get(Lead, "claim-lead-001")
        lead.phone = "011 5555-0101"
        scheduled = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id=lead.id,
            scheduled_at=now,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes=None,
        )
        scheduled.status = "in_progress"
        await sess.commit()
        scheduled_id = scheduled.id

    settings = MagicMock(enable_outbound_calls=True)
    with (
        patch("app.scheduler.service.calculate_scheduled_at", return_value=now),
        patch("app.outbound.service.ElevenLabsService") as provider,
    ):
        async with claim_db.async_session_factory() as sess:
            scheduled = await sess.get(ScheduledCall, scheduled_id)
            await _dial_claimed_scheduled_call(sess, scheduled, settings, now_utc=now)

    async with claim_db.async_session_factory() as sess:
        scheduled = await sess.get(ScheduledCall, scheduled_id)
        sessions = (await sess.execute(select(CallSession))).scalars().all()

    assert scheduled.status == "failed"
    assert scheduled.outcome_session_id is None
    assert sessions == []
    provider.assert_not_called()
