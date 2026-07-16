"""Phase C6 — Retry & Recontact Policy: backoff formula & tech-retry tests.

Spec:
- Backoff: delay = cooldown × (multiplier ^ (attempt - 1))
- multiplier=1.0 → flat delay (unchanged behavior)
- multiplier=2.0, cooldown=60, attempt=3 → 240min
- schedule_tech_retry: max=2, 5min delay, trigger_reason='tech_retry'
- schedule_tech_retry does NOT increment lead recontact counter
- Third tech retry returns None
- Counter isolation: auto_retry and tech_retry counts are independent
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock


# ===========================================================================
# Task 3.1: Backoff formula — pure function tests (no DB needed)
# ===========================================================================


class TestBackoffFormula:
    """Backoff delay formula: delay = cooldown × (multiplier ^ (attempt - 1))."""

    def test_multiplier_1_0_attempt_1_flat_delay(self):
        """multiplier=1.0, attempt=1 → delay = cooldown × 1.0^0 = cooldown."""
        from app.scheduler.service import calculate_backoff_delay

        result = calculate_backoff_delay(
            cooldown_minutes=60,
            backoff_multiplier=1.0,
            attempt_number=1,
        )
        assert result == 60, f"Expected 60, got {result}"

    def test_multiplier_1_0_attempt_2_flat_delay(self):
        """multiplier=1.0, attempt=2 → delay = cooldown × 1.0^1 = cooldown (flat)."""
        from app.scheduler.service import calculate_backoff_delay

        result = calculate_backoff_delay(
            cooldown_minutes=60,
            backoff_multiplier=1.0,
            attempt_number=2,
        )
        assert result == 60, f"Expected flat delay 60, got {result}"

    def test_multiplier_2_0_cooldown_60_attempt_3_is_240(self):
        """multiplier=2.0, cooldown=60, attempt=3 → 60 × 2^2 = 240 min."""
        from app.scheduler.service import calculate_backoff_delay

        result = calculate_backoff_delay(
            cooldown_minutes=60,
            backoff_multiplier=2.0,
            attempt_number=3,
        )
        assert result == 240, f"Expected 240, got {result}"

    def test_multiplier_2_0_cooldown_60_attempt_2_is_120(self):
        """multiplier=2.0, cooldown=60, attempt=2 → 60 × 2^1 = 120 min."""
        from app.scheduler.service import calculate_backoff_delay

        result = calculate_backoff_delay(
            cooldown_minutes=60,
            backoff_multiplier=2.0,
            attempt_number=2,
        )
        assert result == 120, f"Expected 120, got {result}"

    def test_multiplier_1_5_cooldown_60_attempt_3_correct(self):
        """multiplier=1.5, cooldown=60, attempt=3 → 60 × 1.5^2 = 135 min."""
        from app.scheduler.service import calculate_backoff_delay

        result = calculate_backoff_delay(
            cooldown_minutes=60,
            backoff_multiplier=1.5,
            attempt_number=3,
        )
        assert abs(result - 135.0) < 0.01, f"Expected ~135, got {result}"


# ===========================================================================
# Task 3.3 / 3.4: schedule_tech_retry — pure signature and DB tests
# ===========================================================================


class TestScheduleTechRetryPure:
    """schedule_tech_retry must be importable and have the right interface."""

    def test_schedule_tech_retry_is_importable(self):
        """schedule_tech_retry function exists in scheduler.service."""
        from app.scheduler.service import schedule_tech_retry

        assert callable(schedule_tech_retry)

    def test_tech_retry_delay_constant_is_5_minutes(self):
        """Tech retry uses exactly 5 minutes delay (hardcoded MVP)."""
        from app.scheduler import service as svc

        assert hasattr(svc, "_TECH_RETRY_DELAY_MINUTES"), (
            "Module must expose _TECH_RETRY_DELAY_MINUTES constant"
        )
        assert svc._TECH_RETRY_DELAY_MINUTES == 5, (
            f"Tech retry delay must be 5 minutes, got {svc._TECH_RETRY_DELAY_MINUTES}"
        )

    def test_tech_retry_max_constant_is_2(self):
        """Tech retry max attempts is 2 (hardcoded MVP)."""
        from app.scheduler import service as svc

        assert hasattr(svc, "_TECH_RETRY_MAX_ATTEMPTS"), (
            "Module must expose _TECH_RETRY_MAX_ATTEMPTS constant"
        )
        assert svc._TECH_RETRY_MAX_ATTEMPTS == 2, (
            f"Tech retry max must be 2, got {svc._TECH_RETRY_MAX_ATTEMPTS}"
        )


# ===========================================================================
# DB-dependent tests for tech-retry
# ===========================================================================


import pytest_asyncio
from pydantic import SecretStr


@pytest_asyncio.fixture
async def tech_retry_db(tmp_path: Path):
    """Isolated DB for tech-retry tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tech_retry_test.db",
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
            name="Tech Retry Lead",
            phone="+5411000099",
            lead_id="tech-retry-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_schedule_tech_retry_creates_scheduled_call(tech_retry_db):
    """schedule_tech_retry creates a ScheduledCall with trigger_reason='tech_retry'."""
    from app.scheduler.service import schedule_tech_retry
    from app.calls.models import CallSession
    import uuid

    # Create a source CallSession so schedule_tech_retry can reference it
    async with tech_retry_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="tech-retry-lead-001",
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="failed",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    async with tech_retry_db.async_session_factory() as sess:
        result = await schedule_tech_retry(
            sess,
            session_id=session_id,
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert result is not None, "First tech retry must create a ScheduledCall"
    assert result.trigger_reason == "tech_retry", (
        f"Expected trigger_reason='tech_retry', got {result.trigger_reason!r}"
    )


async def test_schedule_tech_retry_uses_5_minute_delay(tech_retry_db):
    """schedule_tech_retry scheduled_at is approximately now + 5 minutes."""
    from app.scheduler.service import schedule_tech_retry
    from app.calls.models import CallSession
    import uuid

    async with tech_retry_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="tech-retry-lead-001",
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="failed",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    before = datetime.now(timezone.utc)

    async with tech_retry_db.async_session_factory() as sess:
        result = await schedule_tech_retry(
            sess,
            session_id=session_id,
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    after = datetime.now(timezone.utc)

    assert result is not None
    # scheduled_at should be between (now + 4.5min) and (now + 5.5min)
    expected_min = before + timedelta(minutes=4, seconds=30)
    expected_max = after + timedelta(minutes=5, seconds=30)
    assert expected_min <= result.scheduled_at <= expected_max, (
        f"scheduled_at={result.scheduled_at} not in expected 5-minute window"
    )


async def test_schedule_tech_retry_max_2_third_returns_none(tech_retry_db):
    """Third tech retry for same lead returns None (max=2 reached)."""
    from app.scheduler.service import schedule_tech_retry
    from app.calls.models import CallSession
    import uuid

    # Create 3 session IDs
    session_ids = []
    async with tech_retry_db.async_session_factory() as sess:
        for _ in range(3):
            cs = CallSession(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="tech-retry-lead-001",
                status="initiated",
                telephony_provider="elevenlabs",
                telephony_status="failed",
                started_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            sess.add(cs)
            session_ids.append(cs.id)
        await sess.commit()

    # First retry
    async with tech_retry_db.async_session_factory() as sess:
        r1 = await schedule_tech_retry(
            sess,
            session_id=session_ids[0],
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        # Mark it completed so next retry can proceed (no active-guard conflict)
        if r1 is not None:
            r1.status = "completed"
        await sess.commit()

    assert r1 is not None, "First tech retry must succeed"

    # Second retry
    async with tech_retry_db.async_session_factory() as sess:
        r2 = await schedule_tech_retry(
            sess,
            session_id=session_ids[1],
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        if r2 is not None:
            r2.status = "completed"
        await sess.commit()

    assert r2 is not None, "Second tech retry must succeed"

    # Third retry — must return None (max=2 reached)
    async with tech_retry_db.async_session_factory() as sess:
        r3 = await schedule_tech_retry(
            sess,
            session_id=session_ids[2],
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert r3 is None, (
        f"Third tech retry must return None (max=2 exhausted), got {r3}"
    )


async def test_schedule_tech_retry_skips_when_pending_already_exists(tech_retry_db):
    """schedule_tech_retry returns None when a pending tech retry already exists for same lead.

    Warning W2: Calling schedule_tech_retry twice rapidly (before the first
    pending is executed) must NOT create duplicate pending/in_progress tech retries.
    The dedup guard checks for active (pending/in_progress) rows, not just total count.
    """
    from app.scheduler.service import schedule_tech_retry
    from app.calls.models import CallSession
    import uuid

    # Create two source sessions so we can call schedule_tech_retry twice
    session_ids = []
    async with tech_retry_db.async_session_factory() as sess:
        for _ in range(2):
            cs = CallSession(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="tech-retry-lead-001",
                status="initiated",
                telephony_provider="elevenlabs",
                telephony_status="failed",
                started_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            sess.add(cs)
            session_ids.append(cs.id)
        await sess.commit()

    # First call — must succeed and create a pending ScheduledCall
    async with tech_retry_db.async_session_factory() as sess:
        r1 = await schedule_tech_retry(
            sess,
            session_id=session_ids[0],
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert r1 is not None, "First tech retry must create a ScheduledCall"
    assert r1.status == "pending", (
        f"First tech retry must be pending, got status={r1.status!r}"
    )

    # Second call — must return None because a pending retry already exists
    async with tech_retry_db.async_session_factory() as sess:
        r2 = await schedule_tech_retry(
            sess,
            session_id=session_ids[1],
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert r2 is None, (
        f"schedule_tech_retry must return None when a pending tech retry already exists for the lead, "
        f"got {r2!r}"
    )


async def test_schedule_tech_retry_does_not_increment_recontact_counter(tech_retry_db):
    """Tech retry does not affect auto_retry (lead recontact) counter."""
    from app.scheduler.service import schedule_tech_retry, auto_schedule
    from app.calls.models import CallSession
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select
    import uuid

    async with tech_retry_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="tech-retry-lead-001",
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="recurrent_error",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    # Create a tech_retry ScheduledCall
    async with tech_retry_db.async_session_factory() as sess:
        tr = await schedule_tech_retry(
            sess,
            session_id=session_id,
            lead_id="tech-retry-lead-001",
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert tr is not None
    assert tr.trigger_reason == "tech_retry"

    # Now count tech_retry vs auto_retry rows for this lead
    async with tech_retry_db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.lead_id == "tech-retry-lead-001",
                ScheduledCall.trigger_reason == "tech_retry",
            )
        )
        tech_rows = list(result.scalars().all())

        result2 = await sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.lead_id == "tech-retry-lead-001",
                ScheduledCall.trigger_reason == "auto_retry",
            )
        )
        auto_rows = list(result2.scalars().all())

    assert len(tech_rows) == 1, "Should have exactly 1 tech_retry row"
    assert len(auto_rows) == 0, (
        "tech_retry must NOT create auto_retry rows (counters are independent)"
    )
