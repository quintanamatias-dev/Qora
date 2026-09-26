"""Tests for GET /api/v1/calls/active (READ-ONLY "en vivo" live calls view).

Covers:
- Tenant scoping (no cross-client leak)
- Telephony status filtering (only queued/dialing/ringing/connected)
- Stale exclusion (non-terminal session started > 2h ago is hidden)
- Empty result
- Route ordering vs /calls/{session_id} (real UUID lookups still work)
- Read-only (no mutation of telephony_status or any column)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/calls_live_test.db",
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
            name="Lucia Fernandez",
            phone="+5491101111111",
            lead_id="lead-alpha",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_session(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str | None = "lead-alpha",
    agent_id: str | None = None,
    status: str = "initiated",
    telephony_status: str | None = "connected",
    started_at: datetime | None = None,
):
    import uuid as _uuid
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(_uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            agent_id=agent_id,
            status=status,
            telephony_status=telephony_status,
            started_at=started_at or datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


@pytest_asyncio.fixture
async def app_client(seeded_db):
    from fastapi import FastAPI
    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, seeded_db


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


async def test_active_calls_scoped_to_client(app_client):
    """A live session for another client must never leak into this client's response."""
    client, seeded_db = app_client
    await _seed_session(seeded_db, client_id="quintana-seguros", telephony_status="connected")
    await _seed_session(seeded_db, client_id="another-client", telephony_status="connected")

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["calls"]) == 1


# ---------------------------------------------------------------------------
# Telephony status filtering
# ---------------------------------------------------------------------------


async def test_active_calls_only_includes_non_terminal_statuses(app_client):
    """Only queued/dialing/ringing/connected sessions appear; completed/voicemail do not."""
    client, seeded_db = app_client
    live_id = await _seed_session(seeded_db, telephony_status="dialing")
    await _seed_session(seeded_db, telephony_status="completed", status="completed")
    await _seed_session(seeded_db, telephony_status="voicemail", status="completed")
    await _seed_session(seeded_db, telephony_status=None)

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    ids = [c["session_id"] for c in data["calls"]]
    assert ids == [live_id]
    assert data["calls"][0]["telephony_status"] == "dialing"


# ---------------------------------------------------------------------------
# Stale exclusion
# ---------------------------------------------------------------------------


async def test_active_calls_excludes_stale_session_without_modifying_it(app_client):
    """A non-terminal session started > 2h ago is hidden but NOT mutated."""
    client, seeded_db = app_client
    from app.calls.service import get_session

    stale_id = await _seed_session(
        seeded_db,
        telephony_status="connected",
        started_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    fresh_id = await _seed_session(seeded_db, telephony_status="connected")

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    ids = [c["session_id"] for c in data["calls"]]
    assert ids == [fresh_id]
    assert stale_id not in ids

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        stale_session = await get_session(sess, stale_id)
        assert stale_session.telephony_status == "connected"
        assert stale_session.status == "initiated"


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------


async def test_active_calls_empty_result(app_client):
    client, _ = app_client
    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["calls"] == []
    assert data["active_total"] == 0
    assert data["today"]["calls_total"] == 0
    assert data["today"]["completed"] == 0
    assert data["recent_facts"] == []
    assert data["memory_total"] == 0
    assert "server_time" in data


# ---------------------------------------------------------------------------
# Route ordering vs /calls/{session_id}
# ---------------------------------------------------------------------------


async def test_active_route_does_not_shadow_session_id_lookup(app_client):
    """GET /calls/{real_uuid} must still resolve — "active" must not be captured by it."""
    client, seeded_db = app_client
    session_id = await _seed_session(seeded_db, telephony_status="connected")

    active_response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert active_response.status_code == 200
    assert "calls" in active_response.json()

    detail_response = await client.get(f"/api/v1/calls/{session_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == session_id


# ---------------------------------------------------------------------------
# Recent memories feed (LeadProfileFact source)
# ---------------------------------------------------------------------------


async def test_active_calls_includes_recent_facts_from_lead_profile_facts(app_client):
    """recent_facts is populated from LeadProfileFact rows recorded today."""
    client, seeded_db = app_client
    from app.calls.models import CallSession
    from app.leads.models import LeadProfileFact

    completed_id = await _seed_session(
        seeded_db, status="completed", telephony_status="completed"
    )
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await sess.get(CallSession, completed_id)
        cs.duration_seconds = 160
        fact = LeadProfileFact(
            id=str(uuid.uuid4()),
            lead_id="lead-alpha",
            fact_key="channel_preference",
            fact_value="Prefiere WhatsApp",
            source_call_id=completed_id,
            recorded_at=datetime.now(timezone.utc),
        )
        sess.add(fact)
        await sess.commit()

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["recent_facts"]) == 1
    assert data["recent_facts"][0]["text"] == "Prefiere WhatsApp"
    assert data["recent_facts"][0]["lead_first_name"] == "Lucia"
    assert data["recent_facts"][0]["duration_seconds"] == 160
    assert data["memory_total"] == 1


# ---------------------------------------------------------------------------
# C2: bounded active-calls / recent-facts queries
# ---------------------------------------------------------------------------


async def test_active_calls_are_capped_at_max_active_calls(app_client):
    """More than MAX_ACTIVE_CALLS live sessions must not all come back — the
    newest ones are kept."""
    client, seeded_db = app_client
    from app.calls.live import MAX_ACTIVE_CALLS

    now = datetime.now(timezone.utc)
    newest_id = None
    for i in range(MAX_ACTIVE_CALLS + 5):
        session_id = await _seed_session(
            seeded_db,
            telephony_status="connected",
            started_at=now - timedelta(seconds=i),
        )
        if i == 0:
            newest_id = session_id

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["calls"]) == MAX_ACTIVE_CALLS
    ids = [c["session_id"] for c in data["calls"]]
    assert newest_id in ids
    # The counter stays truthful even though the list is capped.
    assert data["active_total"] == MAX_ACTIVE_CALLS + 5


async def test_recent_facts_are_capped_at_recent_facts_limit(app_client):
    """recent_facts never exceeds _RECENT_FACTS_LIMIT even when more exist today."""
    client, seeded_db = app_client
    from app.leads.models import LeadProfileFact
    from app.calls.live import _RECENT_FACTS_LIMIT

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        for i in range(_RECENT_FACTS_LIMIT + 5):
            sess.add(
                LeadProfileFact(
                    id=str(uuid.uuid4()),
                    lead_id="lead-alpha",
                    fact_key=f"fact_{i}",
                    fact_value=f"Hecho {i}",
                    recorded_at=datetime.now(timezone.utc),
                )
            )
        await sess.commit()

    response = await client.get(
        "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["recent_facts"]) == _RECENT_FACTS_LIMIT
    assert data["memory_total"] == _RECENT_FACTS_LIMIT + 5


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


async def test_active_calls_endpoint_never_mutates_sessions(app_client):
    """Calling GET /calls/active repeatedly must not change telephony_status or status."""
    client, seeded_db = app_client
    from app.calls.service import get_session

    session_id = await _seed_session(seeded_db, telephony_status="ringing")

    for _ in range(3):
        response = await client.get(
            "/api/v1/calls/active", params={"client_id": "quintana-seguros"}
        )
        assert response.status_code == 200

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await get_session(sess, session_id)
        assert cs.telephony_status == "ringing"
        assert cs.status == "initiated"
