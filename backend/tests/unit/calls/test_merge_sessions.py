"""Unit tests for _merge_sibling_sessions() — session reconciliation (Issue #22).

RED phase: tests written before implementation.
These tests WILL FAIL until _merge_sibling_sessions() is implemented.

Spec: sdd/qora-session-reconciliation/spec
Design: sdd/qora-session-reconciliation/design
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/merge_test.db",
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
            name="Merge Lead",
            phone="+5411000010",
            lead_id="merge-lead-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


def _make_session(
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "merge-lead-001",
    status: str = "initiated",
    elevenlabs_conversation_id: str | None = None,
    started_at: datetime | None = None,
    merged_into_session_id: str | None = None,
) -> "CallSession":  # noqa: F821
    """Build a CallSession ORM object (not yet flushed)."""
    from app.calls.models import CallSession

    return CallSession(
        id=str(uuid.uuid4()),
        client_id=client_id,
        lead_id=lead_id,
        status=status,
        elevenlabs_conversation_id=elevenlabs_conversation_id,
        started_at=started_at or datetime.now(timezone.utc),
        merged_into_session_id=merged_into_session_id,
    )


# ---------------------------------------------------------------------------
# Scenario: Two siblings within window are identified
# Spec: Requirement: Sibling detection — "Two siblings within window"
# ---------------------------------------------------------------------------


async def test_merge_finds_two_siblings_within_window(seeded_db):
    """_merge_sibling_sessions() identifies siblings within ±120s and merges their turns."""
    from app.calls.service import (
        _merge_sibling_sessions,
        add_transcript_turn,
        get_transcript,
    )

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        # Completed session
        completed = _make_session(status="completed", started_at=now)
        # Siblings A and B — same client/lead, no EL ID, within 60s
        sibling_a = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=60)
        )
        sibling_b = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=30)
        )
        sess.add_all([completed, sibling_a, sibling_b])
        await sess.flush()

        # Add 2 turns to completed, 3 to sibling_a, 0 to sibling_b
        await add_transcript_turn(sess, completed.id, "agent", "Hola")
        await add_transcript_turn(sess, completed.id, "user", "Hola de vuelta")
        await add_transcript_turn(sess, sibling_a.id, "user", "Turno sibling A 1")
        await add_transcript_turn(sess, sibling_a.id, "agent", "Turno sibling A 2")
        await add_transcript_turn(sess, sibling_a.id, "user", "Turno sibling A 3")
        await sess.flush()

        # RED: this function does not exist yet
        merged_ids = await _merge_sibling_sessions(sess, completed_session=completed)

        # Both siblings must be identified
        assert set(merged_ids) == {sibling_a.id, sibling_b.id}

        # All 5 turns must now belong to completed
        turns = await get_transcript(sess, completed.id)
        assert len(turns) == 5

        # Sibling A must have 0 turns
        sibling_a_turns = await get_transcript(sess, sibling_a.id)
        assert len(sibling_a_turns) == 0


# ---------------------------------------------------------------------------
# Scenario: Session outside time window is excluded
# Spec: Requirement: Sibling detection — "Session outside time window is excluded"
# ---------------------------------------------------------------------------


async def test_merge_excludes_session_outside_window(seeded_db):
    """Sessions started >RECONCILIATION_WINDOW_SECONDS before completed session are NOT merged."""
    from app.calls.service import _merge_sibling_sessions

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        # 700 seconds before — outside the ±600s window
        outside = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=700)
        )
        sess.add_all([completed, outside])
        await sess.flush()

        merged_ids = await _merge_sibling_sessions(sess, completed_session=completed)

    assert merged_ids == []


# ---------------------------------------------------------------------------
# Scenario: Session with EL ID is excluded
# Spec: Requirement: Sibling detection — "Session with EL ID is excluded"
# ---------------------------------------------------------------------------


async def test_merge_excludes_session_with_elevenlabs_id(seeded_db):
    """Sessions with a non-null elevenlabs_conversation_id are NOT siblings."""
    from app.calls.service import _merge_sibling_sessions

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        has_el_id = _make_session(
            status="abandoned",
            started_at=now - timedelta(seconds=30),
            elevenlabs_conversation_id="conv_xyz",
        )
        sess.add_all([completed, has_el_id])
        await sess.flush()

        merged_ids = await _merge_sibling_sessions(sess, completed_session=completed)

    assert merged_ids == []


# ---------------------------------------------------------------------------
# Scenario: Session from different lead is excluded
# Spec: Requirement: Sibling detection — "Session from different lead is excluded"
# ---------------------------------------------------------------------------


async def test_merge_excludes_session_from_different_lead(seeded_db):
    """Sessions for a different lead are NOT siblings, even if same client + window."""
    from app.calls.service import _merge_sibling_sessions
    from app.leads.service import create_lead

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        # Create a second lead
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Other Lead",
            phone="+5411000099",
            lead_id="other-lead-001",
        )
        await sess.flush()

        completed = _make_session(status="completed", started_at=now)
        diff_lead = _make_session(
            lead_id="other-lead-001",
            status="abandoned",
            started_at=now - timedelta(seconds=30),
        )
        sess.add_all([completed, diff_lead])
        await sess.flush()

        merged_ids = await _merge_sibling_sessions(sess, completed_session=completed)

    assert merged_ids == []


# ---------------------------------------------------------------------------
# Scenario: Turn ordering preserved by timestamp
# Spec: Requirement: Transcript turn re-assignment — "Turn ordering preserved by timestamp"
# ---------------------------------------------------------------------------


async def test_merge_turns_ordered_by_timestamp(seeded_db):
    """After merge, get_transcript returns turns in chronological order (by timestamp)."""
    from app.calls.service import _merge_sibling_sessions, get_transcript
    from app.calls.models import TranscriptTurn

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        sibling = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=30)
        )
        sess.add_all([completed, sibling])
        await sess.flush()

        # Sibling turns come BEFORE completed turns
        t1 = TranscriptTurn(
            id=str(uuid.uuid4()),
            session_id=sibling.id,
            role="user",
            content="Sibling turn 1",
            timestamp=now - timedelta(seconds=25),
        )
        t2 = TranscriptTurn(
            id=str(uuid.uuid4()),
            session_id=sibling.id,
            role="agent",
            content="Sibling turn 2",
            timestamp=now - timedelta(seconds=20),
        )
        t3 = TranscriptTurn(
            id=str(uuid.uuid4()),
            session_id=completed.id,
            role="user",
            content="Completed turn 1",
            timestamp=now - timedelta(seconds=10),
        )
        t4 = TranscriptTurn(
            id=str(uuid.uuid4()),
            session_id=completed.id,
            role="agent",
            content="Completed turn 2",
            timestamp=now - timedelta(seconds=5),
        )
        sess.add_all([t1, t2, t3, t4])
        await sess.flush()

        await _merge_sibling_sessions(sess, completed_session=completed)
        await sess.flush()

        turns = await get_transcript(sess, completed.id)

    # All 4 turns returned, in chronological order
    assert len(turns) == 4
    contents = [t.content for t in turns]
    assert contents[0] == "Sibling turn 1"
    assert contents[1] == "Sibling turn 2"
    assert contents[2] == "Completed turn 1"
    assert contents[3] == "Completed turn 2"


# ---------------------------------------------------------------------------
# Scenario: Turn count recount reflects merged transcript
# Spec: Requirement: Turn count recount — "Turn counts reflect merged transcript"
# ---------------------------------------------------------------------------


async def test_merge_recounts_turn_totals(seeded_db):
    """After merge, completed.total_user_turns and total_agent_turns are recounted."""
    from app.calls.service import _merge_sibling_sessions, add_transcript_turn

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        completed.total_user_turns = 1
        completed.total_agent_turns = 1

        sibling = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=30)
        )
        sess.add_all([completed, sibling])
        await sess.flush()

        # Completed: 1 user + 1 agent
        await add_transcript_turn(sess, completed.id, "user", "C user")
        await add_transcript_turn(sess, completed.id, "agent", "C agent")
        # Sibling: 2 user + 1 agent
        await add_transcript_turn(sess, sibling.id, "user", "S user 1")
        await add_transcript_turn(sess, sibling.id, "user", "S user 2")
        await add_transcript_turn(sess, sibling.id, "agent", "S agent")
        await sess.flush()

        await _merge_sibling_sessions(sess, completed_session=completed)
        await sess.commit()

    # Reload and check turn counts
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        from sqlalchemy import select
        from app.calls.models import CallSession

        result = await sess.execute(
            select(CallSession).where(CallSession.id == completed.id)
        )
        reloaded = result.scalar_one()
        assert reloaded.total_user_turns == 3
        assert reloaded.total_agent_turns == 2


# ---------------------------------------------------------------------------
# Scenario: Sibling is marked post-merge
# Spec: Requirement: Sibling marking — "Sibling is marked post-merge"
# ---------------------------------------------------------------------------


async def test_merge_marks_sibling_with_merged_into_session_id(seeded_db):
    """After merge, sibling.merged_into_session_id == completed.id."""
    from app.calls.service import _merge_sibling_sessions
    from app.calls.models import CallSession
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        sibling = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=40)
        )
        sess.add_all([completed, sibling])
        await sess.flush()

        completed_id = completed.id
        sibling_id = sibling.id

        await _merge_sibling_sessions(sess, completed_session=completed)
        await sess.commit()

    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.id == sibling_id)
        )
        sibling_reloaded = result.scalar_one()
        assert sibling_reloaded.merged_into_session_id == completed_id
        # Status must remain unchanged (still "abandoned")
        assert sibling_reloaded.status == "abandoned"


# ---------------------------------------------------------------------------
# Scenario: Idempotency — double-merge does not double-reassign
# Spec: Requirement: Idempotency guard — "Double-close does not double-merge"
# ---------------------------------------------------------------------------


async def test_merge_is_idempotent_second_run_finds_no_siblings(seeded_db):
    """Calling _merge_sibling_sessions() twice returns [] on the second call."""
    from app.calls.service import _merge_sibling_sessions

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        sibling = _make_session(
            status="abandoned", started_at=now - timedelta(seconds=30)
        )
        sess.add_all([completed, sibling])
        await sess.flush()

        # First run
        first_run = await _merge_sibling_sessions(sess, completed_session=completed)
        assert sibling.id in first_run

        await sess.flush()

        # Second run — sibling now has merged_into_session_id set → excluded
        second_run = await _merge_sibling_sessions(sess, completed_session=completed)

    assert second_run == []


# ---------------------------------------------------------------------------
# Scenario: No siblings — empty list returned
# Spec: Requirement: Merge result logging — "No siblings — empty list returned"
# ---------------------------------------------------------------------------


async def test_merge_returns_empty_list_when_no_siblings(seeded_db):
    """_merge_sibling_sessions() returns [] when no siblings match criteria."""
    from app.calls.service import _merge_sibling_sessions

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        sess.add(completed)
        await sess.flush()

        result = await _merge_sibling_sessions(sess, completed_session=completed)

    assert result == []


# ---------------------------------------------------------------------------
# Scenario: Only initiated/abandoned are merged — completed status excluded
# Spec: Requirement: Sibling detection — status IN (initiated, abandoned)
# ---------------------------------------------------------------------------


async def test_merge_excludes_already_completed_sessions(seeded_db):
    """Sessions with status='completed' are NOT merged (not in initiated/abandoned)."""
    from app.calls.service import _merge_sibling_sessions

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        completed = _make_session(status="completed", started_at=now)
        # Another completed session — same client/lead/window but wrong status
        also_completed = _make_session(
            status="completed",
            started_at=now - timedelta(seconds=30),
        )
        sess.add_all([completed, also_completed])
        await sess.flush()

        merged_ids = await _merge_sibling_sessions(sess, completed_session=completed)

    assert merged_ids == []
