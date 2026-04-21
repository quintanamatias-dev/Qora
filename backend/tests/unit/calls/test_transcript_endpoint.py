"""Tests for GET /api/v1/calls/{session_id}/transcript endpoint — CAP-1.

Covers:
- 200 responses validate SessionTranscriptResponse schema
- turn_count matches seeded turns
- Unknown session returns 404 before schema validation
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/transcript_test.db",
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
            name="Transcript Test Lead",
            phone="+5411000005",
            lead_id="test-lead-transcript-001",
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


async def _create_session_with_turns(seeded_db, *, num_turns: int = 3) -> str:
    """Helper: create a CallSession with N transcript turns. Returns session_id."""
    from app.calls.service import create_session, add_transcript_turn

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-transcript-001",
        )
        session_id = cs.id
        for i in range(num_turns):
            role = "user" if i % 2 == 0 else "agent"
            await add_transcript_turn(sess, session_id, role, f"Turn {i + 1} content")
        await sess.commit()
        return session_id


# ---------------------------------------------------------------------------
# CAP-1: Schema validation on 200 response
# ---------------------------------------------------------------------------


async def test_transcript_endpoint_returns_session_transcript_response(
    seeded_db, app_client
):
    """GET /transcript returns body matching SessionTranscriptResponse schema."""
    from app.calls.schemas import SessionTranscriptResponse

    session_id = await _create_session_with_turns(seeded_db, num_turns=3)
    response = await app_client.get(f"/api/v1/calls/{session_id}/transcript")

    assert response.status_code == 200
    data = response.json()

    # Must validate against SessionTranscriptResponse
    parsed = SessionTranscriptResponse(**data)
    assert parsed.session_id == session_id
    assert parsed.turn_count == 3
    assert len(parsed.turns) == 3


async def test_transcript_endpoint_turn_count_matches_seeded_turns(
    seeded_db, app_client
):
    """turn_count in response matches the exact number of seeded transcript turns."""
    session_id = await _create_session_with_turns(seeded_db, num_turns=5)
    response = await app_client.get(f"/api/v1/calls/{session_id}/transcript")

    assert response.status_code == 200
    data = response.json()

    assert data["turn_count"] == 5
    assert len(data["turns"]) == 5


async def test_transcript_endpoint_turns_have_required_fields(seeded_db, app_client):
    """Each turn in the response has id, role, content, timestamp, filler_detected."""
    from app.calls.schemas import TranscriptTurnResponse

    session_id = await _create_session_with_turns(seeded_db, num_turns=2)
    response = await app_client.get(f"/api/v1/calls/{session_id}/transcript")

    assert response.status_code == 200
    data = response.json()
    turns = data["turns"]

    assert len(turns) == 2
    for turn_data in turns:
        # Must validate against TranscriptTurnResponse
        parsed_turn = TranscriptTurnResponse(**turn_data)
        assert isinstance(parsed_turn.id, str)
        assert parsed_turn.role in ("user", "agent")
        assert isinstance(parsed_turn.content, str)
        assert isinstance(parsed_turn.timestamp, datetime)
        assert isinstance(parsed_turn.filler_detected, bool)


# ---------------------------------------------------------------------------
# CAP-1: Unknown session returns 404
# ---------------------------------------------------------------------------


async def test_transcript_endpoint_unknown_session_returns_404(app_client):
    """GET /transcript with unknown session_id returns HTTP 404."""
    response = await app_client.get(
        "/api/v1/calls/completely-nonexistent-session-id-xyz/transcript"
    )
    assert response.status_code == 404
