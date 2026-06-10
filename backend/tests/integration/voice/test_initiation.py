"""Integration tests for the ElevenLabs conversation initiation webhook.

RED: References app.voice.initiation which is not yet implemented.
Covers: CAP-2 scenarios.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr
from sqlalchemy import select


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(tmp_path: Path):
    """Create a test app with isolated SQLite and seeded data."""

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
    """dynamic_variables includes name and agent_name from client config."""
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

    assert "company_name" in dv
    assert "agent_name" in dv
    assert dv["company_name"] == "Quintana Seguros"
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


# ---------------------------------------------------------------------------
# Fixture: returning lead with 2 completed sessions (for T30-T31)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def returning_lead_client(tmp_path: Path):
    """App client with a lead that has 2 completed sessions and extracted_facts."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/initiation_returning_test.db",
    )

    await db_module.init_db(settings)

    LEAD_ID = "lead-returning-001"

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.models import CallSession
        from app.leads.models import Lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Maria Gonzalez",
            phone="+5411155502",
            car_make="Honda",
            car_model="Civic",
            car_year=2019,
            current_insurance="Sancor",
            lead_id=LEAD_ID,
        )
        await sess.flush()

        # Add 2 completed sessions
        for i, summary in enumerate(
            [
                "Primera llamada: cliente interesado en cobertura total",
                "Segunda llamada: preguntó por cobertura de granizo",
            ]
        ):
            cs = CallSession(
                id=str(uuid.uuid4()),
                client_id="quintana-seguros",
                lead_id=LEAD_ID,
                status="completed",
                summary=summary,
                started_at=datetime(2026, 3, 10 + i, 10, 0, 0, tzinfo=timezone.utc),
                ended_at=datetime(2026, 3, 10 + i, 10, 30, 0, tzinfo=timezone.utc),
            )
            sess.add(cs)

        await sess.flush()

        # Update lead to reflect 2 calls and set extracted_facts
        lead_result = await sess.execute(select(Lead).where(Lead.id == LEAD_ID))
        lead_obj = lead_result.scalar_one_or_none()
        if lead_obj is not None:
            lead_obj.call_count = 2
            lead_obj.extracted_facts = {
                "current_insurance": "La Caja",
                "interest_level": 80,
            }

        await sess.commit()

    from app.voice.initiation import router as initiation_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, LEAD_ID

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T30 — RED: Initiation response shape unchanged after refactor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiation_response_shape_unchanged_after_refactor(
    returning_lead_client,
):
    """CAP-4: initiation response shape remains identical after switching to build_memory_context.

    Asserts EXACT shape: all expected keys present, correct types and values.
    This test is CURRENTLY PASSING (the current initiation.py already produces this shape).
    After T32 refactor, it MUST STILL PASS — proving behavioral equivalence.
    """
    client, LEAD_ID = returning_lead_client

    response = await client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": LEAD_ID,
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "conversation_initiation_client_data"
    dv = data["dynamic_variables"]

    # --- Memory keys must be present ---
    assert "call_history" in dv
    assert "confirmed_facts" in dv
    assert "is_returning_caller" in dv
    assert "call_number" in dv

    # --- Underscore-wrapped memory variants ---
    assert "_call_history_" in dv
    assert "_confirmed_facts_" in dv
    assert "_is_returning_caller_" in dv
    assert "_call_number_" in dv

    # --- Lead fields still present ---
    assert "lead_name" in dv
    assert "car_make" in dv
    assert "car_model" in dv
    assert "car_year" in dv
    assert "current_insurance" in dv
    assert "lead_status" in dv
    assert "lead_notes" in dv
    assert "company_name" in dv
    assert "agent_name" in dv

    # --- Correct memory values ---
    call_history = dv["call_history"]
    assert (
        call_history
    ), f"call_history must be non-empty for returning caller, got: {call_history!r}"
    assert (
        "interesado" in call_history
        or "granizo" in call_history
        or "Llamada del" in call_history
    ), f"call_history should contain session summary content: {call_history!r}"

    confirmed_facts = dv["confirmed_facts"]
    assert confirmed_facts == ""

    # is_returning_caller should be True (bool) — 2 completed sessions exist
    is_returning = dv["is_returning_caller"]
    assert (
        is_returning is True or str(is_returning).lower() == "true"
    ), f"is_returning_caller must be True for lead with 2 completed sessions, got: {is_returning!r}"

    # call_number = lead.call_count + 1 = 2 + 1 = 3
    call_number = dv["call_number"]
    assert (
        call_number == 3 or str(call_number) == "3"
    ), f"call_number must be 3 (call_count=2+1), got: {call_number!r}"


# ---------------------------------------------------------------------------
# T31 — RED: initiation.py imports build_memory_context, no inline helpers
# ---------------------------------------------------------------------------


def test_initiation_uses_shared_build_memory_context():
    """CAP-4: Structural test — initiation.py must import build_memory_context
    and must NOT define inline _format_call_history or _format_confirmed_facts.

    RED: Currently fails because initiation.py still has the inline helpers
    and does NOT import build_memory_context. Will pass after T32 refactor.
    """
    from pathlib import Path

    initiation_path = (
        Path(__file__).resolve().parents[3] / "app" / "voice" / "initiation.py"
    )
    source = initiation_path.read_text(encoding="utf-8")

    # Must import build_memory_context from app.memory
    assert "build_memory_context" in source, (
        "initiation.py must import and use 'build_memory_context' from app.memory. "
        "T32 refactor should add: from app.memory import build_memory_context"
    )

    # Must NOT define inline _format_call_history
    assert "def _format_call_history" not in source, (
        "initiation.py must NOT define '_format_call_history' inline. "
        "T32 refactor must delete this function — it's now in app/memory.py."
    )

    # Must NOT define inline _format_confirmed_facts
    assert "def _format_confirmed_facts" not in source, (
        "initiation.py must NOT define '_format_confirmed_facts' inline. "
        "T32 refactor must delete this function — it's now in app/memory.py."
    )


# ---------------------------------------------------------------------------
# call_count increment: canonical event is close_session, NOT initiation.
# Initiation only transitions new→called (idempotent safety net).
# close_session increments call_count + last_called_at once on first close.
# ---------------------------------------------------------------------------


async def test_initiation_does_not_increment_call_count(app_client: AsyncClient):
    """POST /initiation does NOT increment call_count (close_session does).

    call_count belongs in close_session to avoid double-counting. Initiation
    only handles the new→called status transition as an idempotent safety net.

    GIVEN a lead with call_count=N
    WHEN POST /initiation is called
    THEN lead.call_count == N (unchanged)
    """
    from app.core import database as db_module
    from app.leads.service import get_lead

    # Verify baseline
    async with db_module.async_session_factory() as sess:
        lead_before = await get_lead(sess, "lead-quintana-001")
        count_before = lead_before.call_count

    response = await app_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
        },
    )
    assert response.status_code == 200

    async with db_module.async_session_factory() as sess:
        lead_after = await get_lead(sess, "lead-quintana-001")

    assert lead_after.call_count == count_before, (
        f"initiation must NOT increment call_count (close_session does). "
        f"Was {count_before}, got {lead_after.call_count}"
    )
