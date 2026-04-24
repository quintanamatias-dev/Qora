"""Unit/integration tests for leads admin router.

Tests cover:
- GET /api/v1/leads?client_id={id} — list leads for a client
- GET /api/v1/leads/{id} — get single lead
- POST /api/v1/leads — create lead
- PATCH /api/v1/leads/{id}/status — transition status
- GET /api/v1/leads/{id}/history — call history for lead

Covers: T2.4 AC — GET/PATCH endpoints scope queries by client_id.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def leads_client(tmp_path: Path):
    """Test app with leads router + seeded Quintana data."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/leads_router_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    from app.leads.router import router as leads_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# GET /api/v1/leads?client_id={id}
# ---------------------------------------------------------------------------


async def test_list_leads_returns_all_for_client(leads_client: AsyncClient):
    """GET /leads?client_id=quintana-seguros returns 5 seeded leads."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5


async def test_list_leads_requires_client_id(leads_client: AsyncClient):
    """GET /leads without client_id returns 422."""
    response = await leads_client.get("/api/v1/leads")
    assert response.status_code == 422


async def test_list_leads_unknown_client_returns_empty(leads_client: AsyncClient):
    """GET /leads?client_id=unknown returns empty list (no 404 — just no data)."""
    response = await leads_client.get("/api/v1/leads?client_id=unknown-client")
    assert response.status_code == 200
    data = response.json()
    assert data == []


async def test_list_leads_scoped_to_client(leads_client: AsyncClient):
    """GET /leads?client_id=quintana-seguros only returns Quintana leads."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    data = response.json()
    for lead in data:
        assert lead["client_id"] == "quintana-seguros"


async def test_list_leads_response_shape(leads_client: AsyncClient):
    """Each lead in list response has expected fields."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads = response.json()
    assert len(leads) > 0
    lead = leads[0]
    assert "id" in lead
    assert "name" in lead
    assert "status" in lead
    assert "client_id" in lead
    assert "phone" in lead


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}
# ---------------------------------------------------------------------------


async def test_get_lead_by_id_returns_correct_record(leads_client: AsyncClient):
    """GET /leads/{id} returns the correct lead record."""
    response = await leads_client.get("/api/v1/leads/lead-quintana-001")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "lead-quintana-001"
    assert data["name"] == "Carlos Méndez"
    assert data["car_make"] == "Toyota"
    assert data["car_model"] == "Corolla"


async def test_get_lead_by_id_not_found(leads_client: AsyncClient):
    """GET /leads/{id} for unknown id returns 404."""
    response = await leads_client.get("/api/v1/leads/nonexistent-lead-id")
    assert response.status_code == 404


async def test_get_lead_response_has_full_fields(leads_client: AsyncClient):
    """GET /leads/{id} response includes all expected fields."""
    response = await leads_client.get("/api/v1/leads/lead-quintana-001")
    assert response.status_code == 200
    data = response.json()
    expected_fields = [
        "id",
        "client_id",
        "name",
        "phone",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "status",
        "notes",
        "call_count",
        "created_at",
        "updated_at",
    ]
    for field in expected_fields:
        assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# POST /api/v1/leads
# ---------------------------------------------------------------------------


async def test_create_lead_returns_201(leads_client: AsyncClient):
    """POST /leads creates a new lead and returns 201."""
    response = await leads_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Nuevo Lead",
            "phone": "+5411199999",
            "car_make": "Honda",
            "car_model": "Civic",
            "car_year": 2022,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Nuevo Lead"
    assert data["status"] == "new"
    assert "id" in data


async def test_create_lead_missing_required_fields_returns_422(
    leads_client: AsyncClient,
):
    """POST /leads without required fields returns 422."""
    response = await leads_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            # missing name and phone
        },
    )
    assert response.status_code == 422


async def test_create_lead_persisted_in_list(leads_client: AsyncClient):
    """Lead created via POST appears in subsequent GET list."""
    create_resp = await leads_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Test Persistencia",
            "phone": "+5411188888",
        },
    )
    assert create_resp.status_code == 201
    new_id = create_resp.json()["id"]

    list_resp = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    ids = [lead["id"] for lead in list_resp.json()]
    assert new_id in ids


# ---------------------------------------------------------------------------
# PATCH /api/v1/leads/{id}/status
# ---------------------------------------------------------------------------


async def test_patch_status_valid_transition(leads_client: AsyncClient):
    """PATCH /leads/{id}/status with valid transition updates status."""
    # lead-quintana-001 is 'new' — transition to 'called'
    response = await leads_client.patch(
        "/api/v1/leads/lead-quintana-001/status",
        json={"status": "called"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "called"


async def test_patch_status_invalid_transition_returns_409(leads_client: AsyncClient):
    """PATCH /leads/{id}/status with invalid transition returns 409."""
    # lead-quintana-001 is 'new' — cannot go directly to 'not_interested'
    response = await leads_client.patch(
        "/api/v1/leads/lead-quintana-001/status",
        json={"status": "not_interested"},
    )
    assert response.status_code == 409
    data = response.json()
    assert "error" in data["detail"]
    assert data["detail"]["from"] == "new"
    assert data["detail"]["to"] == "not_interested"


async def test_patch_status_unknown_lead_returns_404(leads_client: AsyncClient):
    """PATCH /leads/{id}/status for non-existent lead returns 404."""
    response = await leads_client.patch(
        "/api/v1/leads/ghost-lead-id/status",
        json={"status": "called"},
    )
    assert response.status_code == 404


async def test_patch_status_missing_body_returns_422(leads_client: AsyncClient):
    """PATCH /leads/{id}/status without body returns 422."""
    response = await leads_client.patch(
        "/api/v1/leads/lead-quintana-001/status",
        json={},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{id}/history
# ---------------------------------------------------------------------------


async def test_get_lead_history_returns_empty_for_new_lead(leads_client: AsyncClient):
    """GET /leads/{id}/history returns empty list for lead with no calls."""
    response = await leads_client.get("/api/v1/leads/lead-quintana-001/history")
    assert response.status_code == 200
    data = response.json()
    assert "lead_id" in data
    assert "sessions" in data
    assert isinstance(data["sessions"], list)


async def test_get_lead_history_unknown_lead_returns_404(leads_client: AsyncClient):
    """GET /leads/{id}/history for non-existent lead returns 404."""
    response = await leads_client.get("/api/v1/leads/ghost-lead/history")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Phase 2 fields — _lead_to_dict() must include all CRM summary fields
# REQ: Extend Lead Serializer with Phase 2 Fields
# ---------------------------------------------------------------------------


PHASE2_FIELDS = [
    "summary_last_call",
    "objections_heard",
    "interest_level",
    "extracted_facts",
    "do_not_call",
    "next_action",
    "next_action_at",
]


async def test_get_lead_includes_phase2_fields(leads_client: AsyncClient):
    """GET /leads/{id} response includes all 7 Phase 2 CRM fields (null-safe)."""
    response = await leads_client.get("/api/v1/leads/lead-quintana-001")
    assert response.status_code == 200
    data = response.json()
    for field in PHASE2_FIELDS:
        assert field in data, f"Missing Phase 2 field: {field!r}"


async def test_list_leads_includes_phase2_fields(leads_client: AsyncClient):
    """GET /leads list response — each lead includes all 7 Phase 2 fields."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads = response.json()
    assert len(leads) > 0
    lead = leads[0]
    for field in PHASE2_FIELDS:
        assert field in lead, f"Missing Phase 2 field in list: {field!r}"


async def test_create_lead_response_includes_phase2_fields(leads_client: AsyncClient):
    """POST /leads response includes all 7 Phase 2 fields (new leads have nulls)."""
    response = await leads_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "New Phase2 Lead",
            "phone": "+5411777777",
        },
    )
    assert response.status_code == 201
    data = response.json()
    for field in PHASE2_FIELDS:
        assert field in data, f"Missing Phase 2 field in create response: {field!r}"


async def test_patch_status_response_includes_phase2_fields(leads_client: AsyncClient):
    """PATCH /leads/{id}/status response includes all 7 Phase 2 fields."""
    response = await leads_client.patch(
        "/api/v1/leads/lead-quintana-001/status",
        json={"status": "called"},
    )
    assert response.status_code == 200
    data = response.json()
    for field in PHASE2_FIELDS:
        assert field in data, f"Missing Phase 2 field in patch response: {field!r}"


async def test_new_lead_phase2_fields_are_null_safe(leads_client: AsyncClient):
    """New leads have null for optional Phase 2 fields and False for do_not_call."""
    response = await leads_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Null Check Lead",
            "phone": "+5411666666",
        },
    )
    assert response.status_code == 201
    data = response.json()
    # Optional fields must be null, not missing
    assert data["summary_last_call"] is None
    assert data["objections_heard"] is None
    assert data["interest_level"] is None
    assert data["extracted_facts"] is None
    assert data["next_action"] is None
    assert data["next_action_at"] is None
    # do_not_call must default to False
    assert data["do_not_call"] is False


# ---------------------------------------------------------------------------
# Phase 7 — next_scheduled_call_at enrichment (Issue #27)
# REQ: Lead List API Response must include next_scheduled_call_at
# ---------------------------------------------------------------------------


async def test_list_leads_includes_next_scheduled_call_at_field(
    leads_client: AsyncClient,
):
    """GET /leads list — each lead must include next_scheduled_call_at field (null-safe)."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads = response.json()
    assert len(leads) > 0
    for lead in leads:
        assert "next_scheduled_call_at" in lead, (
            f"Lead {lead['id']} missing 'next_scheduled_call_at' field"
        )


async def test_list_leads_next_scheduled_call_at_is_null_without_calls(
    leads_client: AsyncClient,
):
    """GET /leads — leads with no pending scheduled calls return next_scheduled_call_at=null."""
    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads = response.json()
    assert len(leads) > 0
    # Seeded leads have no ScheduledCalls — all must be null
    for lead in leads:
        assert lead["next_scheduled_call_at"] is None, (
            f"Lead {lead['id']} expected null but got {lead['next_scheduled_call_at']!r}"
        )


async def test_list_leads_next_scheduled_call_at_returns_earliest_pending(
    leads_client: AsyncClient, tmp_path
):
    """GET /leads — returns MIN(scheduled_at) for pending/in_progress calls."""
    from datetime import datetime, timezone, timedelta
    from app.core import database as db_module
    from app.scheduler.models import ScheduledCall
    import uuid

    lead_id = "lead-quintana-001"
    now = datetime.now(timezone.utc)
    earlier = now + timedelta(hours=1)
    later = now + timedelta(hours=5)

    async with db_module.async_session_factory() as sess:
        # Seed two pending calls — earlier one should be returned
        sc1 = ScheduledCall(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="pending",
            scheduled_at=later,
            trigger_reason="test",
        )
        sc2 = ScheduledCall(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="pending",
            scheduled_at=earlier,
            trigger_reason="test",
        )
        sess.add(sc1)
        sess.add(sc2)
        await sess.commit()

    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads_data = response.json()

    target = next(ld for ld in leads_data if ld["id"] == lead_id)
    assert target["next_scheduled_call_at"] is not None
    # Must be the earlier time — parse and compare (within 1s tolerance)
    raw = target["next_scheduled_call_at"]
    # isoformat may or may not include +00:00 — ensure aware datetime for comparison
    returned_dt = datetime.fromisoformat(raw)
    if returned_dt.tzinfo is None:
        returned_dt = returned_dt.replace(tzinfo=timezone.utc)
    earlier_naive = earlier.replace(tzinfo=None)
    returned_naive = returned_dt.replace(tzinfo=None)
    delta = abs((returned_naive - earlier_naive).total_seconds())
    assert delta < 1, f"Expected earliest time {earlier!r}, got {returned_dt!r}"


async def test_list_leads_skips_scheduled_calls_query_for_empty_list(
    leads_client: AsyncClient,
):
    """GET /leads?client_id=unknown — empty list response, no crash on empty lead_ids."""
    response = await leads_client.get("/api/v1/leads?client_id=no-such-client")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_leads_next_scheduled_call_at_skips_completed_calls(
    leads_client: AsyncClient,
):
    """GET /leads — completed/cancelled/expired calls are NOT counted as next call."""
    from datetime import datetime, timezone, timedelta
    from app.core import database as db_module
    from app.scheduler.models import ScheduledCall
    import uuid

    lead_id = "lead-quintana-002"
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=2)

    async with db_module.async_session_factory() as sess:
        # Add a completed call in the future (should be ignored)
        sc_done = ScheduledCall(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="completed",
            scheduled_at=future,
            trigger_reason="test",
        )
        sess.add(sc_done)
        await sess.commit()

    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads_data = response.json()
    target = next(ld for ld in leads_data if ld["id"] == lead_id)
    # completed call must not appear as next_scheduled_call_at
    assert target["next_scheduled_call_at"] is None


async def test_list_leads_multiple_leads_with_mixed_scheduled_calls(
    leads_client: AsyncClient,
):
    """TRIANGULATE — multiple leads, each with different scheduled call states.

    Proves no N+1: one batch query populates all leads' next_scheduled_call_at
    regardless of how many leads are returned.
    """
    from datetime import datetime, timezone, timedelta
    from app.core import database as db_module
    from app.scheduler.models import ScheduledCall
    import uuid

    now = datetime.now(timezone.utc)
    # lead-001: two pending calls → earliest returned
    future_near = now + timedelta(hours=2)
    future_far = now + timedelta(hours=8)
    # lead-002: in_progress call (also a pending-compatible status)
    future_in_progress = now + timedelta(hours=3)
    # lead-003: only completed call → null
    future_completed = now + timedelta(hours=4)
    # lead-004: overdue pending call (past)
    past = now - timedelta(hours=2)

    async with db_module.async_session_factory() as sess:
        sess.add_all([
            ScheduledCall(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="lead-quintana-001",
                status="pending",
                scheduled_at=future_near,
                trigger_reason="test-near",
            ),
            ScheduledCall(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="lead-quintana-001",
                status="pending",
                scheduled_at=future_far,
                trigger_reason="test-far",
            ),
            ScheduledCall(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="lead-quintana-002",
                status="in_progress",
                scheduled_at=future_in_progress,
                trigger_reason="test-in-progress",
            ),
            ScheduledCall(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="lead-quintana-003",
                status="completed",
                scheduled_at=future_completed,
                trigger_reason="test-completed",
            ),
            ScheduledCall(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id="lead-quintana-004",
                status="pending",
                scheduled_at=past,
                trigger_reason="test-overdue",
            ),
        ])
        await sess.commit()

    response = await leads_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert response.status_code == 200
    leads_data = response.json()

    # Index by lead_id for easy assertion
    by_id = {ld["id"]: ld for ld in leads_data}

    # lead-001: must return the nearer pending call (future_near)
    l001 = by_id["lead-quintana-001"]
    assert l001["next_scheduled_call_at"] is not None
    returned_dt = datetime.fromisoformat(l001["next_scheduled_call_at"])
    if returned_dt.tzinfo is None:
        returned_dt = returned_dt.replace(tzinfo=timezone.utc)
    delta = abs((returned_dt - future_near).total_seconds())
    assert delta < 1, f"lead-001: expected {future_near}, got {returned_dt}"

    # lead-002: in_progress call must be returned
    l002 = by_id["lead-quintana-002"]
    assert l002["next_scheduled_call_at"] is not None

    # lead-003: only completed call → null
    l003 = by_id["lead-quintana-003"]
    assert l003["next_scheduled_call_at"] is None, (
        f"lead-003 should be null, got {l003['next_scheduled_call_at']!r}"
    )

    # lead-004: overdue pending call — still returned (frontend handles display)
    l004 = by_id["lead-quintana-004"]
    assert l004["next_scheduled_call_at"] is not None, (
        "lead-004 overdue pending call should still be returned"
    )
