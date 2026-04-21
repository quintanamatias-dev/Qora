"""Behavioral tests for Phase 2 — CAP-1 (user turn persistence) and CAP-2b (postcall webhook).

Covers:
- CAP-1: schedule_user_turn_persist fires with correct role="user" and content
- CAP-1: graceful skip when messages is empty
- CAP-2b: orphan session close — initiated → completed, call_count incremented
- CAP-2b: already-completed session stays completed, no double increment
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite with quintana-seguros + test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/phase2_test.db",
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
            name="Phase2 Lead",
            phone="+5411000004",
            lead_id="test-lead-phase2-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to calls router."""
    from fastapi import FastAPI
    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


async def _create_call_session(
    seeded_db, *, elevenlabs_id: str | None = None, status: str = "initiated"
) -> str:
    """Helper: create a CallSession with given status."""
    from app.calls.service import create_session

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-phase2-001",
            elevenlabs_conversation_id=elevenlabs_id,
        )
        if status != "initiated":
            cs.status = status
            if status == "completed":
                cs.ended_at = datetime.now(timezone.utc)
                cs.closed_reason = "user_hangup"
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# CAP-1: User turn persistence
# ---------------------------------------------------------------------------


def test_schedule_user_turn_persist_fires_with_last_user_message():
    """schedule_user_turn_persist() picks the LAST user message from messages list."""
    from app.calls.service import schedule_user_turn_persist

    messages = [
        {"role": "system", "content": "You are an agent..."},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿cómo estás?"},
        {"role": "user", "content": "Me interesa un seguro"},
    ]

    with patch("asyncio.create_task") as mock_create_task:
        # We need to capture what coroutine is passed to create_task
        schedule_user_turn_persist("session-001", messages)
        assert mock_create_task.called
        # Close the coroutine to prevent "was never awaited" RuntimeWarning.
        # The mock intercepts create_task, so the coroutine is never scheduled.
        coroutine = mock_create_task.call_args[0][0]
        coroutine.close()


def test_schedule_user_turn_persist_skips_empty_messages():
    """schedule_user_turn_persist() with empty messages → no asyncio.create_task called."""
    from app.calls.service import schedule_user_turn_persist

    with patch("asyncio.create_task") as mock_create_task:
        schedule_user_turn_persist("session-001", [])
        mock_create_task.assert_not_called()


def test_schedule_user_turn_persist_skips_no_user_role():
    """schedule_user_turn_persist() with no user-role messages → no task created."""
    from app.calls.service import schedule_user_turn_persist

    messages = [
        {"role": "system", "content": "..."},
        {"role": "assistant", "content": "Hola"},
    ]

    with patch("asyncio.create_task") as mock_create_task:
        schedule_user_turn_persist("session-001", messages)
        mock_create_task.assert_not_called()


def test_schedule_user_turn_persist_finds_last_user_message():
    """schedule_user_turn_persist() scans from end — picks LAST user message, not first."""
    from app.calls.service import schedule_user_turn_persist

    messages = [
        {"role": "user", "content": "First message"},
        {"role": "assistant", "content": "Reply"},
        {"role": "user", "content": "Latest message"},
    ]

    with patch("asyncio.create_task") as mock_create_task:
        schedule_user_turn_persist("session-001", messages)
        # Task was created — verify it got called
        assert mock_create_task.call_count == 1
        # The coroutine passed to create_task is _persist_user_turn("session-001", "Latest message")
        call_args = mock_create_task.call_args[0][0]
        # Verify the coroutine has the correct session_id and content
        # (coroutine object's cr_frame has locals with the right values)
        assert call_args.cr_frame.f_locals.get("session_id") == "session-001"
        assert call_args.cr_frame.f_locals.get("content") == "Latest message"
        # IMPORTANT: close the coroutine to prevent "was never awaited" RuntimeWarning.
        # asyncio.create_task is patched (not a real event loop), so the coroutine
        # is never scheduled — closing it explicitly suppresses the garbage-collector warning.
        call_args.close()


# ---------------------------------------------------------------------------
# CAP-2b: Postcall webhook — orphan session close
# ---------------------------------------------------------------------------


async def test_postcall_closes_orphan_session(seeded_db, app_client):
    """POST /elevenlabs-postcall with initiated session → closes to completed."""
    from app.calls.models import CallSession
    from sqlalchemy import select

    el_conv_id = "el-orphan-001"
    internal_id = await _create_call_session(
        seeded_db, elevenlabs_id=el_conv_id, status="initiated"
    )

    # Patch _schedule_summarize to avoid background task issues in tests
    with patch("app.calls.router._schedule_summarize"):
        with patch("app.calls.service._schedule_summarize"):
            response = await app_client.post(
                "/api/v1/calls/elevenlabs-postcall",
                json={
                    "conversation_id": el_conv_id,
                    "transcript": [],
                },
            )

    assert response.status_code == 200

    # Verify session is now completed
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == internal_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


async def test_postcall_increments_call_count_for_orphan(seeded_db, app_client):
    """POST /elevenlabs-postcall with initiated session → Lead.call_count incremented."""
    from app.leads.models import Lead
    from sqlalchemy import select

    el_conv_id = "el-orphan-count-001"

    # Get initial count
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-phase2-001"))
        count_before = result.scalar_one().call_count or 0

    await _create_call_session(seeded_db, elevenlabs_id=el_conv_id, status="initiated")

    with patch("app.calls.router._schedule_summarize"):
        with patch("app.calls.service._schedule_summarize"):
            response = await app_client.post(
                "/api/v1/calls/elevenlabs-postcall",
                json={
                    "conversation_id": el_conv_id,
                    "transcript": [],
                },
            )

    assert response.status_code == 200

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-phase2-001"))
        count_after = result.scalar_one().call_count or 0

    assert count_after == count_before + 1


async def test_postcall_already_completed_stays_completed(seeded_db, app_client):
    """POST /elevenlabs-postcall with already-completed session → stays completed, no double increment."""
    from app.calls.models import CallSession
    from app.leads.models import Lead
    from sqlalchemy import select

    el_conv_id = "el-already-complete-001"
    internal_id = await _create_call_session(
        seeded_db, elevenlabs_id=el_conv_id, status="completed"
    )

    # Get initial call_count (already completed via setup, may or may not have incremented)
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-phase2-001"))
        count_before = result.scalar_one().call_count or 0

    with patch("app.calls.router._schedule_summarize"):
        response = await app_client.post(
            "/api/v1/calls/elevenlabs-postcall",
            json={
                "conversation_id": el_conv_id,
                "transcript": [],
            },
        )

    assert response.status_code == 200

    # call_count should NOT have changed (already completed = idempotent)
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-phase2-001"))
        count_after = result.scalar_one().call_count or 0

    assert count_after == count_before

    # Status stays completed
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == internal_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


async def test_postcall_unknown_conversation_id_returns_404(app_client):
    """POST /elevenlabs-postcall with unknown conversation_id → 404."""
    response = await app_client.post(
        "/api/v1/calls/elevenlabs-postcall",
        json={
            "conversation_id": "el-completely-unknown-xyz",
            "transcript": [],
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# CAP-1: Both turns persisted per conversation round
# ---------------------------------------------------------------------------


async def test_both_turns_persisted_per_round(seeded_db):
    """After a turn cycle, both role='user' AND role='agent' TranscriptTurn must exist."""
    from app.calls.service import (
        create_session,
        add_transcript_turn,
        get_transcript,
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        # Create a session
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-phase2-001",
            elevenlabs_conversation_id="el-both-turns-001",
        )
        session_id = cs.id

        # Simulate a full turn: user message followed by agent response
        await add_transcript_turn(
            sess, session_id, "user", "Me interesa un seguro de auto"
        )
        await add_transcript_turn(
            sess, session_id, "agent", "Entiendo, ¿qué marca de auto tiene?"
        )
        await sess.commit()

    # Verify both turns exist
    async with seeded_db.async_session_factory() as sess:
        turns = await get_transcript(sess, session_id)

    assert len(turns) == 2
    roles = {t.role for t in turns}
    assert "user" in roles, "A role='user' TranscriptTurn must exist after a turn cycle"
    assert (
        "agent" in roles
    ), "A role='agent' TranscriptTurn must exist after a turn cycle"


# ---------------------------------------------------------------------------
# CAP-5: Lead model persists do_not_call default
# ---------------------------------------------------------------------------


async def test_new_lead_has_do_not_call_false(seeded_db):
    """A newly created Lead must have do_not_call = False by default."""
    from app.leads.service import create_lead
    from app.leads.models import Lead
    from sqlalchemy import select

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead Default DNC",
            phone="+5411000099",
            lead_id="test-lead-dnc-default-001",
        )
        await sess.commit()
        lead_id = lead.id

    # Reload from DB to confirm persisted value
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == lead_id))
        fresh_lead = result.scalar_one()

    assert fresh_lead.do_not_call is False, (
        "Newly created Lead must default do_not_call to False — "
        "spec CAP-5: 'Lead model persists do_not_call default'"
    )


# ---------------------------------------------------------------------------
# CAP-6: _format_confirmed_facts() helper
# ---------------------------------------------------------------------------


def test_format_confirmed_facts_with_insurance():
    """_format_confirmed_facts() must include insurance carrier in output string.

    Updated (CAP-4 qora-memory-in-prompt): now imports from app.memory (shared builder).
    """
    from app.memory import _format_confirmed_facts

    facts = {"current_insurance": "La Caja"}
    result = _format_confirmed_facts(facts)

    assert "La Caja" in result, (
        "confirmed_facts must contain 'La Caja' when lead.extracted_facts has "
        "current_insurance='La Caja' — spec CAP-6: 'Lead with known insurance from prior call'"
    )


def test_format_confirmed_facts_empty_when_no_facts():
    """_format_confirmed_facts() returns '' when extracted_facts is None or empty.

    Updated (CAP-4 qora-memory-in-prompt): now imports from app.memory (shared builder).
    """
    from app.memory import _format_confirmed_facts

    assert _format_confirmed_facts(None) == ""
    assert _format_confirmed_facts({}) == ""


def test_format_confirmed_facts_includes_all_known_fields():
    """_format_confirmed_facts() formats multiple known fact fields.

    Updated (CAP-4 qora-memory-in-prompt): now imports from app.memory.
    The shared builder supports fixed-order fields: current_insurance, interest_level,
    next_action_suggested. The 'objections' field is not in app.memory._format_confirmed_facts
    (it was only in the old initiation.py helper).
    """
    from app.memory import _format_confirmed_facts

    facts = {
        "current_insurance": "Sancor",
        "interest_level": 75,
    }
    result = _format_confirmed_facts(facts)

    assert "Sancor" in result
    assert "75" in result


# ---------------------------------------------------------------------------
# CAP-2b: Post-call webhook merge + re-summary re-trigger
# ---------------------------------------------------------------------------


async def test_postcall_merges_extra_turns_when_el_has_more(seeded_db, app_client):
    """POST /elevenlabs-postcall with completed session + more EL turns → extra turns persisted."""
    from app.calls.service import add_transcript_turn, get_transcript

    el_conv_id = "el-merge-turns-001"

    # Create a completed session with 2 turns already stored
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        from app.calls.service import create_session

        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-phase2-001",
            elevenlabs_conversation_id=el_conv_id,
        )
        session_id = cs.id
        await add_transcript_turn(sess, session_id, "user", "Hola")
        await add_transcript_turn(sess, session_id, "agent", "Hola, ¿cómo estás?")
        await sess.commit()

    # Close the session via /end before the postcall webhook
    with patch("app.calls.router._schedule_summarize"):
        with patch("app.calls.service._schedule_summarize"):
            close_resp = await app_client.post(
                f"/api/v1/calls/{el_conv_id}/end",
                json={"reason": "user_hangup"},
            )
    assert close_resp.status_code == 200

    # Now the postcall webhook arrives with 3 turns (1 extra vs our 2 stored)
    el_transcript = [
        {"role": "user", "message": "Hola"},
        {"role": "agent", "message": "Hola, ¿cómo estás?"},
        {"role": "user", "message": "Quiero cotizar un seguro"},  # extra turn
    ]

    with patch("app.calls.router._schedule_summarize") as mock_schedule:
        response = await app_client.post(
            "/api/v1/calls/elevenlabs-postcall",
            json={
                "conversation_id": el_conv_id,
                "transcript": el_transcript,
            },
        )

    assert response.status_code == 200

    # Verify the extra turn was merged
    async with seeded_db.async_session_factory() as sess:
        turns = await get_transcript(sess, session_id)

    assert len(turns) == 3, (
        "When ElevenLabs has 3 turns and we stored 2, the extra turn must be merged — "
        "spec CAP-2b: 'Post-call webhook arrives after frontend already closed'"
    )

    # Verify re-summary was triggered (mock should have been called)
    assert mock_schedule.called, (
        "Summary re-generation must be triggered after transcript merge — "
        "spec CAP-6: 'ElevenLabs post-call webhook merge'"
    )
