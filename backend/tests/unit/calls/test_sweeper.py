"""Unit tests for the stale session sweeper (CAP-2c).

Covers:
- Stale session (> 10 min started_at) → abandoned, call_count NOT incremented
- Recent session (< 10 min started_at) → untouched
- Multiple stale sessions swept in one run
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_session(tmp_path: Path):
    """Async SQLite session with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sweeper_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Sweep Lead",
            phone="+5411000002",
            lead_id="test-lead-sweep-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _create_session_with_started_at(
    db_module, *, started_at: datetime, elevenlabs_id: str | None = None
) -> str:
    """Helper: create CallSession with specific started_at timestamp."""
    from app.calls.models import CallSession
    import uuid

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="test-lead-sweep-001",
            elevenlabs_conversation_id=elevenlabs_id,
            status="initiated",
            started_at=started_at,
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# CAP-2c: Stale session → abandoned
# ---------------------------------------------------------------------------


async def test_sweeper_abandons_stale_session(seeded_session):
    """Session older than 10 min → status becomes 'abandoned'."""
    from app.sweeper import sweep_stale_sessions
    from app.calls.models import CallSession

    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    session_id = await _create_session_with_started_at(
        seeded_session, started_at=stale_started_at
    )

    assert seeded_session.async_session_factory is not None
    async with seeded_session.async_session_factory() as db:
        count = await sweep_stale_sessions(db)
        await db.commit()

    assert count >= 1

    # Verify status changed
    async with seeded_session.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "abandoned"
        assert cs.ended_at is not None
        # Sweeper must populate closed_reason with the spec-defined "timeout"
        # enum value (CAP-2a). This enables post-mortem queries that filter
        # by closed_reason to include sweeper-closed sessions.
        assert cs.closed_reason == "timeout"


async def test_sweeper_does_not_increment_call_count(seeded_session):
    """Stale session abandoned by sweeper → Lead.call_count NOT incremented."""
    from app.sweeper import sweep_stale_sessions
    from app.leads.models import Lead

    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    await _create_session_with_started_at(seeded_session, started_at=stale_started_at)

    # Get initial call_count
    assert seeded_session.async_session_factory is not None
    async with seeded_session.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sweep-001"))
        count_before = result.scalar_one().call_count or 0

    # Run sweeper
    async with seeded_session.async_session_factory() as db:
        await sweep_stale_sessions(db)
        await db.commit()

    # Verify call_count unchanged
    async with seeded_session.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sweep-001"))
        count_after = result.scalar_one().call_count or 0

    assert count_after == count_before


# ---------------------------------------------------------------------------
# CAP-2c: Recent session → untouched
# ---------------------------------------------------------------------------


async def test_sweeper_leaves_recent_session_untouched(seeded_session):
    """Session started < 10 min ago → not swept, status stays 'initiated'."""
    from app.sweeper import sweep_stale_sessions
    from app.calls.models import CallSession

    # Recent session: 5 minutes ago
    recent_started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    session_id = await _create_session_with_started_at(
        seeded_session, started_at=recent_started_at
    )

    assert seeded_session.async_session_factory is not None
    async with seeded_session.async_session_factory() as db:
        await sweep_stale_sessions(db)
        await db.commit()

    # The recent session should NOT be swept
    async with seeded_session.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "initiated"
        assert cs.ended_at is None


async def test_sweeper_returns_zero_when_no_stale_sessions(seeded_session):
    """sweep_stale_sessions() returns 0 when there are no stale sessions."""
    from app.sweeper import sweep_stale_sessions

    # Only create a recent session (5 minutes ago)
    recent_started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _create_session_with_started_at(seeded_session, started_at=recent_started_at)

    assert seeded_session.async_session_factory is not None
    async with seeded_session.async_session_factory() as db:
        count = await sweep_stale_sessions(db)
        await db.commit()

    assert count == 0


async def test_sweeper_handles_multiple_stale_sessions(seeded_session):
    """Sweeper marks all stale sessions as abandoned in a single run."""
    from app.sweeper import sweep_stale_sessions
    from app.calls.models import CallSession

    stale_started_at = datetime.now(timezone.utc) - timedelta(minutes=12)

    assert seeded_session.async_session_factory is not None
    ids = []
    for i in range(3):
        sid = await _create_session_with_started_at(
            seeded_session, started_at=stale_started_at
        )
        ids.append(sid)

    async with seeded_session.async_session_factory() as db:
        count = await sweep_stale_sessions(db)
        await db.commit()

    assert count == 3

    # Verify all three are abandoned
    async with seeded_session.async_session_factory() as db:
        result = await db.execute(select(CallSession).where(CallSession.id.in_(ids)))
        sessions = result.scalars().all()
        assert all(cs.status == "abandoned" for cs in sessions)
