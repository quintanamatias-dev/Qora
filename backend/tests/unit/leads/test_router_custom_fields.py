"""TDD tests — Lead API custom_fields contract (WU-6 task 6.1).

Spec requirements:
- Lead GET responses MUST include custom_fields: dict[str, str] populated from lead_custom_fields table.
- CreateLeadRequest MUST optionally accept custom_fields dict.
- custom_fields written to lead_custom_fields table on create.
- Legacy top-level fields (car_make, car_model, car_year, current_insurance) MUST NOT be in response.
- list and detail endpoints both load and expose custom_fields.

Scenarios covered:
- API-1: GET /leads/{id} response includes custom_fields key (dict, empty if none)
- API-2: GET /leads/{id} response includes existing custom_fields rows
- API-3: GET /leads list response — each lead includes custom_fields dict
- API-4: POST /leads with custom_fields stores values in lead_custom_fields table
- API-5: POST /leads without custom_fields creates lead with empty custom_fields
- API-6: GET /leads/{id} — custom_fields key populated from lead_custom_fields (not legacy columns)
- API-7: POST /leads custom_fields values readable via GET after create
- API-8: Legacy top-level fields (car_make etc.) absent from response — now in custom_fields only
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def custom_fields_client(tmp_path: Path):
    """Test app with leads router. No seed data — creates leads explicitly in tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/leads_cf_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana

        await seed_quintana(sess)
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


@pytest_asyncio.fixture
async def lead_with_custom_fields_client(tmp_path: Path):
    """Test app with a lead that has pre-seeded custom field rows."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/leads_cf_seeded.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.leads.lead_custom_fields_service import upsert

        await seed_quintana(sess)
        lead = await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Custom Fields Lead",
            phone="+5411099999",
            lead_id="test-cf-lead-001",
        )
        # Seed custom fields directly
        await upsert(
            sess,
            lead_id=lead.id,
            client_id="quintana-seguros",
            field_key="car_make",
            field_value="Toyota",
            field_type="string",
        )
        await upsert(
            sess,
            lead_id=lead.id,
            client_id="quintana-seguros",
            field_key="zona",
            field_value="Norte",
            field_type="string",
        )
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
# API-1: GET /leads/{id} response includes custom_fields key (empty dict if no rows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_response_includes_custom_fields_key(
    custom_fields_client: AsyncClient,
):
    """API-1: GET /leads/{id} MUST include 'custom_fields' key in response.

    GIVEN a lead with no custom field rows
    WHEN GET /leads/{id} is called
    THEN response includes 'custom_fields': {} (empty dict, not null, not absent)
    """
    # Create a lead first
    resp = await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Test Lead",
            "phone": "+5411100001",
        },
    )
    assert resp.status_code == 201
    lead_id = resp.json()["id"]

    resp = await custom_fields_client.get(f"/api/v1/leads/{lead_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert "custom_fields" in data, f"Missing 'custom_fields' in response: {list(data.keys())}"
    assert isinstance(data["custom_fields"], dict), (
        f"'custom_fields' must be a dict, got: {type(data['custom_fields'])}"
    )
    assert data["custom_fields"] == {}, (
        f"Expected empty dict for lead with no custom fields, got: {data['custom_fields']}"
    )


# ---------------------------------------------------------------------------
# API-2: GET /leads/{id} includes pre-seeded custom_fields values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_response_includes_seeded_custom_fields(
    lead_with_custom_fields_client: AsyncClient,
):
    """API-2: GET /leads/{id} MUST return all custom field rows as dict.

    GIVEN lead 'test-cf-lead-001' has custom fields {car_make: Toyota, zona: Norte}
    WHEN GET /leads/test-cf-lead-001 is called
    THEN response.custom_fields == {'car_make': 'Toyota', 'zona': 'Norte'}
    """
    resp = await lead_with_custom_fields_client.get("/api/v1/leads/test-cf-lead-001")
    assert resp.status_code == 200
    data = resp.json()

    assert "custom_fields" in data
    cf = data["custom_fields"]
    assert cf.get("car_make") == "Toyota", f"Expected car_make='Toyota', got: {cf}"
    assert cf.get("zona") == "Norte", f"Expected zona='Norte', got: {cf}"


# ---------------------------------------------------------------------------
# API-3: GET /leads list — each lead includes custom_fields dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_leads_each_includes_custom_fields(
    lead_with_custom_fields_client: AsyncClient,
):
    """API-3: GET /leads list MUST include custom_fields in every lead entry.

    GIVEN at least one lead with custom fields
    WHEN GET /leads?client_id=quintana-seguros is called
    THEN each lead in the response includes 'custom_fields' dict
    """
    resp = await lead_with_custom_fields_client.get(
        "/api/v1/leads?client_id=quintana-seguros"
    )
    assert resp.status_code == 200
    leads = resp.json()
    assert len(leads) > 0

    for lead in leads:
        assert "custom_fields" in lead, (
            f"Lead {lead['id']} missing 'custom_fields' in list response"
        )
        assert isinstance(lead["custom_fields"], dict), (
            f"Lead {lead['id']}: custom_fields must be dict, got {type(lead['custom_fields'])}"
        )


# ---------------------------------------------------------------------------
# API-4: GET /leads list — custom_fields populated for leads that have them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_leads_custom_fields_populated_for_matching_lead(
    lead_with_custom_fields_client: AsyncClient,
):
    """API-4: GET /leads list — lead with custom fields returns them correctly.

    GIVEN test-cf-lead-001 has car_make and zona
    WHEN GET /leads?client_id=quintana-seguros is called
    THEN the matching lead has custom_fields == {'car_make': 'Toyota', 'zona': 'Norte'}
    """
    resp = await lead_with_custom_fields_client.get(
        "/api/v1/leads?client_id=quintana-seguros"
    )
    assert resp.status_code == 200
    leads = resp.json()

    target = next((l for l in leads if l["id"] == "test-cf-lead-001"), None)
    assert target is not None, "test-cf-lead-001 not found in list response"

    cf = target["custom_fields"]
    assert cf.get("car_make") == "Toyota"
    assert cf.get("zona") == "Norte"


# ---------------------------------------------------------------------------
# API-5: POST /leads with custom_fields stores values in lead_custom_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_lead_with_custom_fields_stores_them(
    custom_fields_client: AsyncClient,
):
    """API-5: POST /leads with custom_fields dict MUST store in lead_custom_fields.

    GIVEN POST body with custom_fields: {car_make: Ford, age: 35}
    WHEN POST /leads is called
    THEN response.custom_fields == {car_make: Ford, age: 35}
    AND GET /leads/{id} also returns those fields
    """
    resp = await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Ana Rodriguez",
            "phone": "+5411100002",
            "custom_fields": {"car_make": "Ford", "age": "35"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "custom_fields" in data
    assert data["custom_fields"].get("car_make") == "Ford", (
        f"Expected car_make=Ford in create response, got: {data['custom_fields']}"
    )
    assert data["custom_fields"].get("age") == "35", (
        f"Expected age=35 in create response, got: {data['custom_fields']}"
    )

    # Also verify via GET
    lead_id = data["id"]
    get_resp = await custom_fields_client.get(f"/api/v1/leads/{lead_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["custom_fields"].get("car_make") == "Ford"


# ---------------------------------------------------------------------------
# API-6: POST /leads without custom_fields — response has empty custom_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_lead_without_custom_fields_returns_empty_dict(
    custom_fields_client: AsyncClient,
):
    """API-6: POST /leads without custom_fields MUST return custom_fields: {}.

    GIVEN POST body without custom_fields key
    WHEN POST /leads is called
    THEN response.custom_fields == {}
    """
    resp = await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Simple Lead",
            "phone": "+5411100003",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "custom_fields" in data
    assert data["custom_fields"] == {}


@pytest.mark.asyncio
async def test_create_lead_rejects_legacy_business_fields(
    custom_fields_client: AsyncClient,
):
    """API final contract: business fields must be sent via custom_fields.

    Top-level car_make/car_model/car_year/current_insurance are not accepted by
    CreateLeadRequest anymore, preventing writes to deprecated Lead columns.
    """
    resp = await custom_fields_client.post(
        "/api/v1/leads?client_id=quintana-seguros",
        json={
            "name": "Legacy Payload Lead",
            "phone": "+5411100009",
            "car_make": "Toyota",
        },
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API-7: Legacy top-level fields are ABSENT (now in custom_fields only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_legacy_car_fields_absent_from_top_level(
    custom_fields_client: AsyncClient,
):
    """API-7 FINAL: GET /leads/{id} MUST NOT include legacy car_make, car_model,
    car_year, current_insurance as top-level fields.

    These fields are now only accessible via the custom_fields dict.
    Verifies AC-1 / WU-7 compliance — legacy ORM columns not exposed in API.
    """
    resp = await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Legacy Check Lead",
            "phone": "+5411100004",
        },
    )
    assert resp.status_code == 201
    lead_id = resp.json()["id"]

    resp = await custom_fields_client.get(f"/api/v1/leads/{lead_id}")
    assert resp.status_code == 200
    data = resp.json()

    legacy_fields = ["car_make", "car_model", "car_year", "current_insurance"]
    for field in legacy_fields:
        assert field not in data, (
            f"Legacy field '{field}' must NOT be a top-level response key — "
            f"it belongs in custom_fields only (AC-1 / WU-7)"
        )


# ---------------------------------------------------------------------------
# API-8: List endpoint also excludes legacy top-level fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_leads_legacy_car_fields_absent_from_top_level(
    custom_fields_client: AsyncClient,
):
    """API-8 FINAL: GET /leads list MUST NOT include legacy fields as top-level keys.

    Legacy fields are now only in custom_fields dict per lead.
    """
    # Create a lead so list is non-empty
    await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "List Legacy Check",
            "phone": "+5411100005",
        },
    )
    resp = await custom_fields_client.get("/api/v1/leads?client_id=quintana-seguros")
    assert resp.status_code == 200
    leads = resp.json()
    assert len(leads) > 0

    legacy_fields = ["car_make", "car_model", "car_year", "current_insurance"]
    for lead in leads:
        for field in legacy_fields:
            assert field not in lead, (
                f"Lead {lead['id']}: legacy '{field}' must NOT be a top-level key — "
                f"belongs in custom_fields only (AC-1 / WU-7)"
            )


# ---------------------------------------------------------------------------
# API-9: create response includes custom_fields key even when none provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_response_always_has_custom_fields_key(
    custom_fields_client: AsyncClient,
):
    """API-9: POST /leads response ALWAYS includes 'custom_fields' key.

    GIVEN any create request (with or without custom_fields in body)
    WHEN POST /leads returns 201
    THEN response body has 'custom_fields' key of type dict
    """
    resp = await custom_fields_client.post(
        "/api/v1/leads",
        json={
            "client_id": "quintana-seguros",
            "name": "Always Present",
            "phone": "+5411100006",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "custom_fields" in data
    assert isinstance(data["custom_fields"], dict)


# ---------------------------------------------------------------------------
# API-10: PATCH /leads/{id}/status response also includes custom_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_status_response_includes_custom_fields(
    lead_with_custom_fields_client: AsyncClient,
):
    """API-10: PATCH /leads/{id}/status response MUST include custom_fields.

    GIVEN lead test-cf-lead-001 with custom fields
    WHEN PATCH /leads/{id}/status is called
    THEN response includes 'custom_fields' dict
    """
    resp = await lead_with_custom_fields_client.patch(
        "/api/v1/leads/test-cf-lead-001/status",
        json={"status": "called"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "custom_fields" in data, (
        f"PATCH status response missing 'custom_fields': {list(data.keys())}"
    )
    assert isinstance(data["custom_fields"], dict)
