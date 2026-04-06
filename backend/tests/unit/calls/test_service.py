"""Unit tests for call session service — lifecycle, transcript, and billing.

RED: References app.calls.service which is not yet implemented.
Covers: CAP-7 scenarios.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_session(tmp_path: Path):
    """Session with Quintana client + one lead pre-loaded."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/calls_test.db",
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
            name="Test Lead",
            phone="+5411111111",
            lead_id="test-lead-001",
        )
        await sess.commit()
        yield sess

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T3.1: Call lifecycle tests
# ---------------------------------------------------------------------------


async def test_create_session_persists_record(seeded_session: AsyncSession):
    """create_session() creates a CallSession with status=initiated."""
    from app.calls.service import create_session

    session = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    assert session is not None
    assert session.id is not None
    assert session.client_id == "quintana-seguros"
    assert session.lead_id == "test-lead-001"
    assert session.status == "initiated"
    assert session.started_at is not None
    assert session.ended_at is None
    assert session.outcome is None


async def test_end_session_updates_fields(seeded_session: AsyncSession):
    """end_session() sets ended_at, duration_seconds, outcome, and billable_minutes."""
    from app.calls.service import create_session, end_session

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    updated = await end_session(
        seeded_session,
        session_id=cs.id,
        outcome="completed",
        duration_seconds=90.0,
    )

    assert updated.status == "completed"
    assert updated.outcome == "completed"
    assert updated.ended_at is not None
    assert updated.duration_seconds == 90.0
    assert updated.billable_minutes == math.ceil(90 / 60)  # 2


async def test_billable_minutes_ceil_calculation(seeded_session: AsyncSession):
    """billable_minutes uses CEIL(duration / 60)."""
    from app.calls.service import create_session, end_session

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    # 61 seconds → 2 billable minutes
    updated = await end_session(
        seeded_session,
        session_id=cs.id,
        outcome="completed",
        duration_seconds=61.0,
    )
    assert updated.billable_minutes == 2

    # Test exact 60 → 1 minute
    cs2 = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )
    updated2 = await end_session(
        seeded_session,
        session_id=cs2.id,
        outcome="completed",
        duration_seconds=60.0,
    )
    assert updated2.billable_minutes == 1

    # Test < 60 → 1 minute
    cs3 = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )
    updated3 = await end_session(
        seeded_session,
        session_id=cs3.id,
        outcome="completed",
        duration_seconds=30.0,
    )
    assert updated3.billable_minutes == 1


async def test_end_session_abandoned_outcome(seeded_session: AsyncSession):
    """end_session() with outcome=abandoned sets correct status."""
    from app.calls.service import create_session, end_session

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    updated = await end_session(
        seeded_session,
        session_id=cs.id,
        outcome="abandoned",
        duration_seconds=45.0,
    )

    assert updated.outcome == "abandoned"
    assert updated.status == "abandoned"


async def test_add_transcript_turn_persists(seeded_session: AsyncSession):
    """add_transcript_turn() persists a turn with role and content."""
    from app.calls.service import create_session, add_transcript_turn

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    turn = await add_transcript_turn(
        seeded_session,
        session_id=cs.id,
        role="agent",
        content="A ver... Hola, ¿cómo estás?",
    )

    assert turn.id is not None
    assert turn.session_id == cs.id
    assert turn.role == "agent"
    assert turn.content == "A ver... Hola, ¿cómo estás?"
    assert turn.timestamp is not None


async def test_get_session_with_turns(seeded_session: AsyncSession):
    """get_session() returns call session, and turns can be listed separately."""
    from app.calls.service import (
        create_session,
        add_transcript_turn,
        get_session,
        get_transcript,
    )

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    await add_transcript_turn(seeded_session, cs.id, "user", "Hola")
    await add_transcript_turn(seeded_session, cs.id, "agent", "Hola, soy Jaumpablo")
    await add_transcript_turn(seeded_session, cs.id, "user", "Me interesa un seguro")
    await add_transcript_turn(
        seeded_session, cs.id, "agent", "Perfecto, te paso los detalles"
    )
    await add_transcript_turn(seeded_session, cs.id, "user", "Gracias")
    await seeded_session.flush()

    session = await get_session(seeded_session, cs.id)
    assert session is not None
    assert session.id == cs.id

    turns = await get_transcript(seeded_session, cs.id)
    assert len(turns) == 5


async def test_transcript_exact_count(seeded_session: AsyncSession):
    """A 5-turn conversation has exactly 5 transcript entries (CAP-7)."""
    from app.calls.service import create_session, add_transcript_turn, get_transcript

    cs = await create_session(
        seeded_session,
        client_id="quintana-seguros",
        lead_id="test-lead-001",
    )

    for i in range(5):
        role = "user" if i % 2 == 0 else "agent"
        await add_transcript_turn(seeded_session, cs.id, role, f"Turn {i}")
    await seeded_session.flush()

    turns = await get_transcript(seeded_session, cs.id)
    assert len(turns) == 5
    for turn in turns:
        assert turn.role in ("user", "agent")
        assert turn.content is not None
        assert turn.timestamp is not None
