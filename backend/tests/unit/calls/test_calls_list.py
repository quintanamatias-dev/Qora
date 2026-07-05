"""Unit/integration tests for GET /api/v1/calls list endpoint.

Covers:
- Missing client_id → 422
- List sessions scoped to client (client scope)
- Filter by lead_id
- Empty result
- Sort order (most-recent first)
- Response shape includes summary + extracted_facts

TDD: RED phase — tests written before implementation.
Spec: sdd/qora-basic-crm/spec — Requirement: List Call Sessions Endpoint
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite DB seeded with quintana-seguros + leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/calls_list_test.db",
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
            name="Lead Alpha",
            phone="+54111111111",
            lead_id="lead-alpha",
        )
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Lead Beta",
            phone="+54222222222",
            lead_id="lead-beta",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_session(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "lead-alpha",
    status: str = "completed",
    started_at: datetime | None = None,
    summary: str | None = None,
    extracted_facts: dict | None = None,
    telephony_status: str | None = None,
):
    """Helper: insert a CallSession with optional summary/extracted_facts."""
    import uuid
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            status=status,
            started_at=started_at or datetime.now(timezone.utc),
            summary=summary,
            extracted_facts=extracted_facts,
            telephony_status=telephony_status,
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to calls router with isolated DB."""
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
# Scenario: Missing client_id → 422
# ---------------------------------------------------------------------------


async def test_list_calls_missing_client_id_returns_422(app_client):
    """GET /calls without client_id → 422 Unprocessable Entity."""
    client, _ = app_client
    response = await client.get("/api/v1/calls")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Scenario: List sessions scoped to client
# ---------------------------------------------------------------------------


async def test_list_calls_returns_sessions_for_client(app_client):
    """GET /calls?client_id=quintana-seguros returns all sessions for that client."""
    client, seeded_db = app_client
    await _seed_session(seeded_db, client_id="quintana-seguros", lead_id="lead-alpha")
    await _seed_session(seeded_db, client_id="quintana-seguros", lead_id="lead-alpha")

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    for item in data:
        assert item["client_id"] == "quintana-seguros"


# ---------------------------------------------------------------------------
# Scenario: Filter by lead_id
# ---------------------------------------------------------------------------


async def test_list_calls_filter_by_lead_id(app_client):
    """GET /calls?client_id=X&lead_id=Y returns only sessions for lead Y."""
    client, seeded_db = app_client
    await _seed_session(seeded_db, lead_id="lead-alpha")
    await _seed_session(seeded_db, lead_id="lead-alpha")
    await _seed_session(seeded_db, lead_id="lead-beta")

    response = await client.get(
        "/api/v1/calls",
        params={"client_id": "quintana-seguros", "lead_id": "lead-alpha"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    for item in data:
        assert item["lead_id"] == "lead-alpha"


# ---------------------------------------------------------------------------
# Scenario: Empty result
# ---------------------------------------------------------------------------


async def test_list_calls_empty_result(app_client):
    """GET /calls?client_id=X with no sessions returns empty array."""
    client, _ = app_client
    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data == []


# ---------------------------------------------------------------------------
# Scenario: Sort order (most-recent first)
# ---------------------------------------------------------------------------


async def test_list_calls_sorted_most_recent_first(app_client):
    """GET /calls returns sessions ordered by started_at DESC."""
    client, seeded_db = app_client
    now = datetime.now(timezone.utc)
    old_id = await _seed_session(seeded_db, started_at=now - timedelta(hours=2))
    mid_id = await _seed_session(seeded_db, started_at=now - timedelta(hours=1))
    new_id = await _seed_session(seeded_db, started_at=now)

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # Most recent first
    assert data[0]["id"] == new_id
    assert data[1]["id"] == mid_id
    assert data[2]["id"] == old_id


# ---------------------------------------------------------------------------
# Scenario: Response shape includes summary + extracted_facts
# ---------------------------------------------------------------------------


async def test_list_calls_response_shape_includes_summary_and_facts(app_client):
    """Each session in response includes summary and extracted_facts fields."""
    client, seeded_db = app_client
    await _seed_session(
        seeded_db,
        summary="Lead showed strong interest",
        extracted_facts={"budget": "50k ARS/month"},
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]

    # Required fields from spec
    assert "id" in item
    assert "client_id" in item
    assert "lead_id" in item
    assert "status" in item
    assert "started_at" in item
    assert "summary" in item
    assert "extracted_facts" in item
    assert item["summary"] == "Lead showed strong interest"
    assert item["extracted_facts"] == {"budget": "50k ARS/month"}


async def test_list_calls_null_summary_returned_as_null(app_client):
    """Sessions without summary/extracted_facts return null values (not omitted)."""
    client, seeded_db = app_client
    await _seed_session(seeded_db, summary=None, extracted_facts=None)

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    item = data[0]
    assert item["summary"] is None
    assert item["extracted_facts"] is None


# ---------------------------------------------------------------------------
# Scenario: No cross-tenant leak
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue #22 — Merged sessions excluded from list
# Spec: Requirement: List Call Sessions Endpoint — "Merged sessions excluded from list"
# ---------------------------------------------------------------------------


async def _seed_session_with_merged_into(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "lead-alpha",
    status: str = "initiated",
    started_at=None,
    merged_into_session_id: str | None = None,
):
    """Helper: insert a CallSession with an optional merged_into_session_id."""
    import uuid
    from app.calls.models import CallSession
    import datetime as _dt

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            status=status,
            started_at=started_at or _dt.datetime.now(_dt.timezone.utc),
            merged_into_session_id=merged_into_session_id,
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


async def test_list_calls_excludes_merged_sessions(app_client):
    """Sessions with merged_into_session_id IS NOT NULL must be excluded.

    Spec: Requirement: List Call Sessions Endpoint — "Merged sessions excluded from list"
    """
    client, seeded_db = app_client

    # Seed the completed (authoritative) session
    completed_id = await _seed_session(seeded_db, status="completed")

    # Seed a merged sibling pointing to the completed session
    await _seed_session_with_merged_into(
        seeded_db,
        status="abandoned",
        merged_into_session_id=completed_id,
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()

    # Only completed session should appear — merged sibling must be hidden
    ids_returned = [item["id"] for item in data]
    assert (
        completed_id in ids_returned
    ), "Completed (authoritative) session must be returned"
    assert len(data) == 1, (
        f"Expected 1 session (merged sibling excluded), got {len(data)}. "
        f"list_sessions_for_client() must filter merged_into_session_id IS NULL."
    )


async def test_list_calls_non_merged_abandoned_remains_visible(app_client):
    """Abandoned sessions with merged_into_session_id IS NULL must still appear.

    Spec: Requirement: List Call Sessions Endpoint — "Non-merged abandoned sessions remain visible"
    """
    client, seeded_db = app_client

    # Abandoned session, NOT merged
    non_merged_id = await _seed_session_with_merged_into(
        seeded_db,
        status="abandoned",
        merged_into_session_id=None,
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()

    ids_returned = [item["id"] for item in data]
    assert (
        non_merged_id in ids_returned
    ), "Abandoned session with merged_into_session_id=NULL must remain visible"


async def test_list_calls_response_includes_merged_into_session_id(app_client):
    """Response shape includes merged_into_session_id field for debug visibility.

    Spec: Design — _session_to_dict() includes merged_into_session_id
    """
    client, seeded_db = app_client
    await _seed_session(seeded_db, status="completed")

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]
    # merged_into_session_id must be present in response (even if None)
    assert "merged_into_session_id" in item, (
        "Response must include 'merged_into_session_id' field. "
        "Update _session_to_dict() in router.py."
    )
    assert item["merged_into_session_id"] is None


async def test_list_calls_no_cross_tenant_leak(app_client):
    """lead_id from another client returns empty array (no data leak)."""
    client, seeded_db = app_client
    # Seed a session for lead-beta under quintana-seguros
    await _seed_session(seeded_db, client_id="quintana-seguros", lead_id="lead-beta")

    # Request with client_id=quintana-seguros but wrong lead_id that belongs to no sessions
    response = await client.get(
        "/api/v1/calls",
        params={"client_id": "quintana-seguros", "lead_id": "lead-alpha"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == []


# ---------------------------------------------------------------------------
# Scenario: Ghost filter — outbound sessions with telephony_status are NOT filtered
# ---------------------------------------------------------------------------


async def test_outbound_session_with_telephony_status_not_filtered_as_ghost(app_client):
    """GIVEN an outbound session with status='initiated', no turns, no duration,
         BUT telephony_status='ringing'
    WHEN GET /calls is called
    THEN the session must appear in the response — it is a real outbound call,
         not a ghost WebSocket connection attempt.

    Root cause: the ghost filter removed all status='initiated' sessions with no
    turns/duration, which included outbound sessions that hadn't completed yet.
    After the fix, a non-null telephony_status marks a real outbound call and
    exempts it from the ghost filter.
    """
    client, seeded_db = app_client

    outbound_id = await _seed_session(
        seeded_db,
        status="initiated",
        telephony_status="ringing",
        # No duration, no turns — exactly the conditions for ghost filtering
        summary=None,
        extracted_facts=None,
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()

    ids_returned = [item["id"] for item in data]
    assert outbound_id in ids_returned, (
        "Outbound session with telephony_status='ringing' must NOT be filtered as a ghost. "
        "Only sessions with telephony_status=NULL should be filtered."
    )


async def test_ghost_inbound_session_without_telephony_status_is_filtered(app_client):
    """GIVEN an inbound ghost session with status='initiated', no turns, no duration,
         AND telephony_status=None (no outbound tracking)
    WHEN GET /calls is called
    THEN the session must NOT appear in the response — it is a ghost.
    """
    client, seeded_db = app_client

    ghost_id = await _seed_session(
        seeded_db,
        status="initiated",
        telephony_status=None,  # inbound ghost — no telephony tracking
        summary=None,
        extracted_facts=None,
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()

    ids_returned = [item["id"] for item in data]
    assert ghost_id not in ids_returned, (
        "Inbound ghost session (status='initiated', no turns, no duration, "
        "telephony_status=NULL) must be filtered out of the call list."
    )


async def test_outbound_session_with_dialing_status_not_filtered(app_client):
    """GIVEN an outbound session with status='initiated', telephony_status='dialing'
    WHEN GET /calls is called
    THEN the session appears — even 'dialing' (pre-dial) counts as a real outbound call.
    """
    client, seeded_db = app_client

    dialing_id = await _seed_session(
        seeded_db,
        status="initiated",
        telephony_status="dialing",
    )

    response = await client.get(
        "/api/v1/calls", params={"client_id": "quintana-seguros"}
    )
    assert response.status_code == 200
    data = response.json()

    ids_returned = [item["id"] for item in data]
    assert dialing_id in ids_returned, (
        "Outbound session with telephony_status='dialing' must appear in call list."
    )
