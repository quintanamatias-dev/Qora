"""Unit tests for memory injection at conversation initiation (CAP-6).

Covers:
- do_not_call lead → 403 before EL call
- First call → is_returning_caller=false, call_number=1
- Returning lead with summary → call_history has content, is_returning_caller=true
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite with quintana-seguros + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/memory_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana

        await seed_quintana(sess)
        await sess.commit()

    yield db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to initiation router."""
    from fastapi import FastAPI
    from app.voice.initiation import router as initiation_router

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


async def _create_lead(
    seeded_db, *, lead_id: str, do_not_call: bool = False, call_count: int = 0
):
    """Helper: create a test lead in the DB."""
    from app.leads.service import create_lead
    from app.leads.models import Lead
    from sqlalchemy import select

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Test Memory Lead",
            phone="+5411999001",
            lead_id=lead_id,
        )
        # Update do_not_call and call_count directly
        result = await sess.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one()
        lead.do_not_call = do_not_call
        lead.call_count = call_count
        await sess.commit()


async def _create_completed_session(seeded_db, *, lead_id: str, summary: str):
    """Helper: create a completed CallSession with a summary for a lead."""
    from app.calls.models import CallSession
    import uuid

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="completed",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            summary=summary,
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# CAP-6: do_not_call → 403
# ---------------------------------------------------------------------------


async def test_initiation_blocked_for_do_not_call_lead(seeded_db, app_client):
    """POST /initiation with do_not_call=True lead → 403 before ElevenLabs call."""
    await _create_lead(seeded_db, lead_id="lead-dnc-001", do_not_call=True)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-dnc-001",
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert (
        "opted out" in data["detail"].lower()
        or "do_not_call" in str(data["detail"]).lower()
    )


async def test_initiation_not_blocked_for_normal_lead(seeded_db, app_client):
    """POST /initiation with do_not_call=False → 200 (not blocked)."""
    await _create_lead(seeded_db, lead_id="lead-normal-001", do_not_call=False)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-normal-001",
        },
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# CAP-6: First call → is_returning_caller=False, call_number=1
# ---------------------------------------------------------------------------


async def test_first_call_is_not_returning_caller(seeded_db, app_client):
    """First-time call (no previous completed sessions) → is_returning_caller=false."""
    await _create_lead(seeded_db, lead_id="lead-first-001", call_count=0)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-first-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    assert dv["is_returning_caller"] is False


async def test_first_call_has_call_number_1(seeded_db, app_client):
    """First-time call → call_number=1 (call_count=0, +1 for current call)."""
    await _create_lead(seeded_db, lead_id="lead-firstnum-001", call_count=0)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-firstnum-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    assert dv["call_number"] == 1


async def test_first_call_has_empty_call_history(seeded_db, app_client):
    """First call → call_history is empty string (no previous sessions)."""
    await _create_lead(seeded_db, lead_id="lead-hist-empty-001", call_count=0)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-hist-empty-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    assert dv["call_history"] == ""


# ---------------------------------------------------------------------------
# CAP-6: Returning caller → is_returning_caller=True, call_history populated
# ---------------------------------------------------------------------------


async def test_returning_caller_is_returning(seeded_db, app_client):
    """Lead with ≥1 completed session → is_returning_caller=true."""
    await _create_lead(seeded_db, lead_id="lead-return-001", call_count=1)
    await _create_completed_session(
        seeded_db,
        lead_id="lead-return-001",
        summary="Lead mostró interés en seguro todo riesgo.",
    )

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-return-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    assert dv["is_returning_caller"] is True


async def test_returning_caller_has_call_history(seeded_db, app_client):
    """Returning lead with summary → call_history contains summary content."""
    summary_text = "Lead interesado en póliza todo riesgo para su Toyota Corolla."
    await _create_lead(seeded_db, lead_id="lead-hist-001", call_count=1)
    await _create_completed_session(
        seeded_db,
        lead_id="lead-hist-001",
        summary=summary_text,
    )

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-hist-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    call_history = dv["call_history"]
    assert len(call_history) > 0
    assert summary_text in call_history


async def test_returning_caller_call_number_incremented(seeded_db, app_client):
    """Returning lead with call_count=2 → call_number=3 (current call)."""
    await _create_lead(seeded_db, lead_id="lead-callnum-001", call_count=2)
    await _create_completed_session(
        seeded_db,
        lead_id="lead-callnum-001",
        summary="Segunda llamada, prometió revisar cotización.",
    )

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-callnum-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    # call_count=2, +1 for current call = 3
    assert dv["call_number"] == 3


# ---------------------------------------------------------------------------
# CAP-6: Memory injection also in underscore-wrapped variants
# ---------------------------------------------------------------------------


async def test_underscore_wrapped_variables_present(seeded_db, app_client):
    """Initiation response includes underscore-wrapped memory variables for EL templates."""
    await _create_lead(seeded_db, lead_id="lead-ul-001", call_count=0)

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-ul-001",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]
    assert "_call_history_" in dv
    assert "_confirmed_facts_" in dv
    assert "_is_returning_caller_" in dv
    assert "_call_number_" in dv
