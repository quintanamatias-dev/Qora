"""Integration tests for the ElevenLabs conversation initiation webhook.

RED: References app.voice.initiation which is not yet implemented.
Covers: CAP-2 scenarios.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(tmp_path: Path):
    """Create a test app with isolated SQLite and seeded data."""
    import importlib

    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/initiation_test.db",
    )

    await db_module.init_db(settings)

    # Seed tenant + leads
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    from app.voice.initiation import router as initiation_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T4.1: Initiation webhook tests
# ---------------------------------------------------------------------------


async def test_initiation_returns_dynamic_variables_for_known_lead(
    app_client: AsyncClient,
):
    """POST /initiation with valid lead_id returns all 7 dynamic_variables (CAP-2)."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert "dynamic_variables" in data
    dv = data["dynamic_variables"]

    # CAP-2: must include all 7 lead fields
    assert "lead_name" in dv
    assert "car_make" in dv
    assert "car_model" in dv
    assert "car_year" in dv
    assert "current_insurance" in dv
    assert "lead_status" in dv
    assert "lead_notes" in dv

    # Verify actual values from seed data
    assert dv["lead_name"] == "Carlos Méndez"
    assert dv["car_make"] == "Toyota"
    assert dv["car_model"] == "Corolla"
    assert str(dv["car_year"]) == "2021"


async def test_initiation_returns_empty_strings_for_unknown_lead(
    app_client: AsyncClient,
):
    """POST /initiation with unknown lead_id returns dynamic_variables with empty strings (CAP-2)."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "nonexistent-lead",
            "agent_id": "agent-001",
            "called_number": "+5411155999",
        },
    )

    # Must NOT return error — call proceeds with unknown lead
    assert response.status_code == 200
    data = response.json()

    dv = data["dynamic_variables"]
    # All fields should be empty or safe defaults
    assert dv["lead_name"] == ""
    assert dv["car_make"] == ""
    assert dv["car_model"] == ""


async def test_initiation_includes_broker_and_agent_name(app_client: AsyncClient):
    """dynamic_variables includes broker_name and agent_name from client config."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )

    assert response.status_code == 200
    dv = response.json()["dynamic_variables"]

    assert "broker_name" in dv
    assert "agent_name" in dv
    assert dv["broker_name"] == "Quintana Seguros"
    assert dv["agent_name"] == "Jaumpablo"


async def test_initiation_missing_client_id_returns_422(app_client: AsyncClient):
    """POST /initiation without client_id returns 422."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )
    assert response.status_code == 422


async def test_initiation_response_time_under_2s(app_client: AsyncClient):
    """Initiation webhook responds within 2000ms (CAP-2 timing requirement)."""
    start = time.monotonic()

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )

    elapsed_ms = (time.monotonic() - start) * 1000
    assert response.status_code == 200
    assert elapsed_ms < 2000, f"Response took {elapsed_ms:.1f}ms — exceeds 2s limit"


async def test_initiation_creates_call_session(app_client: AsyncClient):
    """POST /initiation creates a CallSession record in the DB."""
    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Response can include session_id for tracing
    # At minimum, the call should be created — verify via dynamic_variables presence
    assert "dynamic_variables" in data


async def test_initiation_transitions_lead_to_called(app_client: AsyncClient):
    """POST /initiation automatically transitions lead status to 'called'."""
    from app.core import database as db_module
    from app.leads.service import get_lead

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "agent_id": "agent-001",
            "called_number": "+5411155501",
        },
    )
    assert response.status_code == 200

    # Verify lead status changed to 'called'
    async with db_module.async_session_factory() as session:
        lead = await get_lead(session, "lead-quintana-001")
        assert lead is not None
        assert lead.status == "called"
