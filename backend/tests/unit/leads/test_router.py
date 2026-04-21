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
