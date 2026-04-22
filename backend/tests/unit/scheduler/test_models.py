"""Unit tests for ScheduledCall model — Phase 6 (Task 1.1 RED).

Covers:
- ScheduledCall created with correct defaults (status=pending, attempt_number=1)
- Invalid status transition rejected (completed → pending)
- ScheduledCall persists all required fields
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Isolated SQLite DB with all tables created."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/scheduler_models_test.db",
    )
    await db_module.init_db(settings)

    # Seed a client and a lead
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Scheduler Test Lead",
            phone="+5411000099",
            lead_id="sched-test-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# REQ-SCHED-001: ScheduledCall defaults
# ---------------------------------------------------------------------------


async def test_scheduled_call_default_status_is_pending(db):
    """ScheduledCall inserted without status → status='pending' from DB default."""
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select
    import uuid

    sc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with db.async_session_factory() as sess:
        sc = ScheduledCall(
            id=sc_id,
            client_id="quintana-seguros",
            lead_id="sched-test-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            max_attempts=3,
        )
        sess.add(sc)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        retrieved = result.scalar_one()
        assert retrieved.status == "pending"


async def test_scheduled_call_default_attempt_number_is_one(db):
    """ScheduledCall inserted without attempt_number → attempt_number=1 from DB default."""
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select
    import uuid

    sc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with db.async_session_factory() as sess:
        sc = ScheduledCall(
            id=sc_id,
            client_id="quintana-seguros",
            lead_id="sched-test-lead-001",
            scheduled_at=now,
            trigger_reason="auto_retry",
            max_attempts=3,
        )
        sess.add(sc)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        retrieved = result.scalar_one()
        assert retrieved.attempt_number == 1


async def test_scheduled_call_persists_to_db(db):
    """ScheduledCall can be inserted and retrieved from the DB."""
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select
    import uuid

    sc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with db.async_session_factory() as sess:
        sc = ScheduledCall(
            id=sc_id,
            client_id="quintana-seguros",
            lead_id="sched-test-lead-001",
            scheduled_at=now,
            trigger_reason="followup_tool",
            max_attempts=3,
            notes="Test note",
        )
        sess.add(sc)
        await sess.commit()

    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == sc_id)
        )
        retrieved = result.scalar_one_or_none()
        assert retrieved is not None
        assert retrieved.status == "pending"
        assert retrieved.attempt_number == 1
        assert retrieved.trigger_reason == "followup_tool"
        assert retrieved.notes == "Test note"
        assert retrieved.client_id == "quintana-seguros"
        assert retrieved.lead_id == "sched-test-lead-001"


async def test_scheduled_call_all_status_values_accepted(db):
    """ScheduledCall accepts all valid status enum values."""
    from app.scheduler.models import ScheduledCall
    import uuid

    valid_statuses = ["pending", "in_progress", "completed", "failed", "cancelled", "expired"]
    now = datetime.now(timezone.utc)

    for status in valid_statuses:
        sc = ScheduledCall(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="sched-test-lead-001",
            scheduled_at=now,
            trigger_reason="manual",
            max_attempts=3,
            status=status,
        )
        assert sc.status == status


# ---------------------------------------------------------------------------
# REQ-SCHED-001: Invalid status transitions
# (Service-layer validation — we test the model constants here)
# ---------------------------------------------------------------------------


def test_scheduled_call_valid_transitions_defined():
    """ScheduledCall model exposes VALID_TRANSITIONS for lifecycle enforcement."""
    from app.scheduler.models import VALID_TRANSITIONS

    # completed → pending is NOT valid
    assert "pending" not in VALID_TRANSITIONS.get("completed", [])
    # pending → cancelled IS valid
    assert "cancelled" in VALID_TRANSITIONS.get("pending", [])
    # pending → in_progress IS valid
    assert "in_progress" in VALID_TRANSITIONS.get("pending", [])


def test_scheduled_call_completed_has_no_forward_transitions():
    """completed is a terminal state — no valid forward transitions."""
    from app.scheduler.models import VALID_TRANSITIONS

    assert VALID_TRANSITIONS.get("completed", []) == []


def test_scheduled_call_cancelled_is_terminal():
    """cancelled is a terminal state — no valid forward transitions."""
    from app.scheduler.models import VALID_TRANSITIONS

    assert VALID_TRANSITIONS.get("cancelled", []) == []
