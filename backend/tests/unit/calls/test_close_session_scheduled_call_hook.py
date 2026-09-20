"""Unit tests for the resolve_scheduled_call_for_session hook wired into
close_session() — Phase C6b Slice 2, task 2.2.

Covers ordering (must run after the voicemail heuristic and before the
sibling-merge flush, design.md — The Completion Hook) and idempotency (a
second close_session() call on an already-completed session must not
re-resolve the linked ScheduledCall).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
import structlog.testing
from pydantic import SecretStr
from sqlalchemy import select


@pytest_asyncio.fixture
async def hook_db(tmp_path: Path):
    """Isolated DB with quintana-seguros + a test lead for the close_session hook."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/close_session_hook_test.db",
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
            name="Hook Lead",
            phone="+5411000090",
            lead_id="hook-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def _seed_linked_pair(sess, *, session_id: str, started_at: datetime):
    """Create a 'ringing' CallSession + its linked in_progress ScheduledCall."""
    from app.calls.models import CallSession
    from app.scheduler.service import create_scheduled_call

    cs = CallSession(
        id=session_id,
        client_id="quintana-seguros",
        lead_id="hook-lead-001",
        status="initiated",
        telephony_provider="elevenlabs",
        telephony_status="ringing",
        started_at=started_at,
    )
    sess.add(cs)
    sc = await create_scheduled_call(
        sess,
        client_id="quintana-seguros",
        lead_id="hook-lead-001",
        scheduled_at=started_at,
        trigger_reason="manual",
        source_session_id=None,
        attempt_number=1,
        max_attempts=3,
        notes=None,
    )
    sc.status = "in_progress"
    sc.outcome_session_id = session_id
    await sess.flush()
    return cs, sc


async def test_hook_reads_post_heuristic_voicemail_not_pre_heuristic_completed(hook_db):
    """Regression guard: the hook must read telephony_status AFTER the
    voicemail heuristic rewrite, not the intermediate 'completed' value set
    by update_telephony_status_on_session_end() moments earlier."""
    from app.calls.service import close_session
    from app.scheduler.models import ScheduledCall

    now = datetime.now(timezone.utc)
    async with hook_db.async_session_factory() as sess:
        # duration < 30s, zero turns -> voicemail heuristic fires
        _, sc = await _seed_linked_pair(sess, session_id="cs-hook-001", started_at=now - timedelta(seconds=10))
        await sess.commit()
        sc_id = sc.id

    with structlog.testing.capture_logs() as cap:
        async with hook_db.async_session_factory() as sess:
            await close_session(sess, session_id="cs-hook-001", closed_reason="session_end")
            await sess.commit()

    resolved_events = [e for e in cap if e.get("event") == "scheduled_call_resolved_from_session"]
    assert resolved_events, f"Expected scheduled_call_resolved_from_session, got: {cap}"
    assert resolved_events[0]["telephony_status"] == "voicemail", (
        f"Hook must read the post-heuristic value, got {resolved_events[0]}"
    )

    async with hook_db.async_session_factory() as sess:
        result = await sess.execute(select(ScheduledCall).where(ScheduledCall.id == sc_id))
        assert result.scalar_one().status == "completed"


async def test_hook_is_idempotent_on_second_close_session_call(hook_db):
    """A second close_session() call on an already-completed session hits the
    early cs.status == "completed" return (:658) and never re-invokes the hook."""
    from app.calls.service import close_session

    now = datetime.now(timezone.utc)
    async with hook_db.async_session_factory() as sess:
        await _seed_linked_pair(sess, session_id="cs-hook-002", started_at=now - timedelta(seconds=40))
        await sess.commit()

    async with hook_db.async_session_factory() as sess:
        await close_session(sess, session_id="cs-hook-002", closed_reason="session_end")
        await sess.commit()

    with structlog.testing.capture_logs() as cap:
        async with hook_db.async_session_factory() as sess:
            _cs, was_already_closed = await close_session(
                sess, session_id="cs-hook-002", closed_reason="session_end"
            )
            await sess.commit()

    assert was_already_closed is True
    assert not [e for e in cap if e.get("event") == "scheduled_call_resolved_from_session"], (
        "A second close on an already-completed session must not re-resolve the ScheduledCall"
    )
