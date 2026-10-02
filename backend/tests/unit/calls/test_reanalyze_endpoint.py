"""Tests for POST /api/v1/calls/{session_id}/reanalyze (superadmin-only).

Allows operators to re-run post-call analysis for a completed session that
has transcript turns but is missing its call_analyses row (production race,
now fixed). No SSH, no raw SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Initialize isolated SQLite DB with quintana-seguros + one lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/reanalyze_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Reanalyze Lead",
            phone="+5491100777777",
            lead_id="reanalyze-lead",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_session(
    db_module,
    *,
    lead_id: str = "reanalyze-lead",
    status: str = "completed",
    with_turns: bool = True,
) -> str:
    """Insert a CallSession (optionally with transcript turns) and return its id."""
    from app.calls.models import CallSession
    from app.calls.service import add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status=status,
            started_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    if with_turns:
        async with db_module.async_session_factory() as sess:
            await add_transcript_turn(sess, session_id, "user", "Hello, I need a quote")
            await add_transcript_turn(sess, session_id, "agent", "Sure, let me help you")
            await sess.commit()

    return session_id


async def _seed_analysis(db_module, *, session_id: str) -> None:
    """Insert a minimal existing CallAnalysis row for a session."""
    from app.calls.models import CallAnalysis

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        analysis = CallAnalysis(
            id=str(uuid.uuid4()),
            session_id=session_id,
            lead_id="reanalyze-lead",
            client_id="quintana-seguros",
            analysis_status="ok",
            analyzed_at=datetime.now(timezone.utc),
        )
        sess.add(analysis)
        await sess.commit()


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to the calls router (superadmin via test bypass)."""
    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, seeded_db


@pytest_asyncio.fixture
async def non_superadmin_client(seeded_db):
    """Test HTTP client with a non-superadmin principal overriding require_api_key."""
    from app.calls.router import router as calls_router
    from app.core.auth import CallerIdentity, require_api_key

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")
    test_app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="t", role="client", client_ids=frozenset({"quintana-seguros"})
    )

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, seeded_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reanalyze_rejects_non_superadmin(non_superadmin_client):
    """POST /reanalyze returns 403 for a non-superadmin caller."""
    client, db_module = non_superadmin_client
    session_id = await _seed_session(db_module)

    response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reanalyze_returns_404_for_unknown_session(app_client):
    """POST /reanalyze returns 404 when the session does not exist."""
    client, _ = app_client

    response = await client.post("/api/v1/calls/nonexistent-session/reanalyze")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reanalyze_returns_409_when_analysis_already_exists(app_client):
    """POST /reanalyze returns 409 when a call_analyses row already exists."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)
    await _seed_analysis(db_module, session_id=session_id)

    response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "analysis_exists"


@pytest.mark.asyncio
async def test_reanalyze_returns_422_when_session_not_completed(app_client):
    """POST /reanalyze returns 422 when the session status is not 'completed'."""
    client, db_module = app_client
    session_id = await _seed_session(db_module, status="active")

    response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reanalyze_returns_422_when_no_transcript_turns(app_client):
    """POST /reanalyze returns 422 when the session has zero transcript turns."""
    client, db_module = app_client
    session_id = await _seed_session(db_module, with_turns=False)

    response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reanalyze_returns_200_on_success(app_client):
    """POST /reanalyze runs the durable summarizer and returns 200 on success."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)

    async def _fake_generate(sid, db):
        await _seed_analysis(db_module, session_id=sid)

    with patch(
        "app.calls.router.generate_summary_and_facts_durable",
        new=AsyncMock(side_effect=_fake_generate),
    ) as mocked:
        response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert mocked.await_count == 1
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == session_id
    assert data["status"] == "analyzed"


@pytest.mark.asyncio
async def test_reanalyze_returns_502_when_summarizer_raises(app_client):
    """POST /reanalyze returns 502 (without leaking internals) when the summarizer raises."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)

    with patch(
        "app.calls.router.generate_summary_and_facts_durable",
        new=AsyncMock(side_effect=RuntimeError("boom - internal secret detail")),
    ):
        response = await client.post(f"/api/v1/calls/{session_id}/reanalyze")

    assert response.status_code == 502
    assert "boom" not in response.text
