"""Integration tests for GET /api/v1/calls/{session_id} detail endpoint.

Verifies that the detail endpoint returns summary and extracted_facts fields
in both populated and null cases.

Spec: sdd/qora-basic-crm/spec — Requirement: Extend Call Session Detail with Summary
TDD: RED phase — tests written before any additional production code changes.
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
    """Initialize isolated SQLite DB seeded with quintana-seguros + one lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/detail_test.db",
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
            name="Detail Lead",
            phone="+5411999999",
            lead_id="detail-lead",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_session(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "detail-lead",
    status: str = "completed",
    summary: str | None = None,
    extracted_facts: dict | None = None,
) -> str:
    """Insert a CallSession and return its id."""
    import uuid
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            status=status,
            started_at=datetime.now(timezone.utc),
            summary=summary,
            extracted_facts=extracted_facts,
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to the calls router with an isolated DB."""
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
# Scenario: Detail endpoint returns 404 for unknown session
# ---------------------------------------------------------------------------


async def test_get_session_detail_404_for_unknown(app_client):
    """GET /calls/{unknown-id} returns 404."""
    client, _ = app_client
    response = await client.get("/api/v1/calls/nonexistent-session-id")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scenario: Detail endpoint returns summary and extracted_facts when populated
# ---------------------------------------------------------------------------


async def test_get_session_detail_returns_populated_summary_and_facts(app_client):
    """GET /calls/{session_id} returns summary and extracted_facts when they exist."""
    client, db_module = app_client
    session_id = await _seed_session(
        db_module,
        summary="Lead showed strong interest in full coverage policy",
        extracted_facts={"budget": "50k ARS/month", "family_size": 3},
    )

    response = await client.get(f"/api/v1/calls/{session_id}")
    assert response.status_code == 200

    data = response.json()
    # Required CRM fields
    assert data["id"] == session_id
    assert "summary" in data
    assert "extracted_facts" in data
    # Values must match what was stored
    assert data["summary"] == "Lead showed strong interest in full coverage policy"
    assert data["extracted_facts"] == {"budget": "50k ARS/month", "family_size": 3}


# ---------------------------------------------------------------------------
# Scenario: Detail endpoint returns null summary and extracted_facts when absent
# ---------------------------------------------------------------------------


async def test_get_session_detail_returns_null_summary_and_facts_when_absent(
    app_client,
):
    """GET /calls/{session_id} returns null for summary and extracted_facts when not set."""
    client, db_module = app_client
    session_id = await _seed_session(
        db_module,
        summary=None,
        extracted_facts=None,
    )

    response = await client.get(f"/api/v1/calls/{session_id}")
    assert response.status_code == 200

    data = response.json()
    # Fields must be present in response (not missing/omitted)
    assert "summary" in data
    assert "extracted_facts" in data
    # Both should be null
    assert data["summary"] is None
    assert data["extracted_facts"] is None


# ---------------------------------------------------------------------------
# Scenario: Detail endpoint includes elevenlabs_conversation_id in response
# ---------------------------------------------------------------------------


async def test_get_session_detail_includes_elevenlabs_conversation_id(app_client):
    """GET /calls/{session_id} response includes elevenlabs_conversation_id field."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)

    response = await client.get(f"/api/v1/calls/{session_id}")
    assert response.status_code == 200

    data = response.json()
    # elevenlabs_conversation_id is included (may be None for sessions
    # not originating from ElevenLabs)
    assert "elevenlabs_conversation_id" in data


# ---------------------------------------------------------------------------
# Phase 5 — Scenario: Analysis axes flow through API response
# ---------------------------------------------------------------------------


async def test_get_session_detail_returns_analysis_axes_when_present(app_client):
    """GET /calls/{session_id} returns call_outcome, detected_interests, identified_problem
    when they are present in extracted_facts."""
    client, db_module = app_client
    session_id = await _seed_session(
        db_module,
        extracted_facts={
            "interest_level": 85,
            "call_outcome": {
                "classification": "interested",
                "reason": "Lead requested a quote.",
                "engagement_quality": "high",
            },
            "detected_interests": {
                "products": ["todo_riesgo"],
                "specific_needs": ["cobertura_amplia"],
                "buying_signals": ["asked about price"],
            },
            "identified_problem": {
                "primary_need": "Needs coverage for new car.",
                "pain_points": ["no current insurance"],
                "urgency": "high",
            },
        },
    )

    response = await client.get(f"/api/v1/calls/{session_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["extracted_facts"] is not None
    facts = data["extracted_facts"]

    # All 3 axes present
    assert "call_outcome" in facts
    assert facts["call_outcome"]["classification"] == "interested"
    assert facts["call_outcome"]["engagement_quality"] == "high"

    assert "detected_interests" in facts
    assert "todo_riesgo" in facts["detected_interests"]["products"]

    assert "identified_problem" in facts
    assert facts["identified_problem"]["urgency"] == "high"


async def test_get_session_list_returns_analysis_axes_for_sessions(app_client):
    """GET /calls?client_id=x returns extracted_facts including analysis axes for each session."""
    client, db_module = app_client

    # Create a session with analysis data
    await _seed_session(
        db_module,
        extracted_facts={
            "call_outcome": {
                "classification": "not_interested",
                "reason": "Lead already has insurance.",
                "engagement_quality": "low",
            },
            "detected_interests": {
                "products": [],
                "specific_needs": [],
                "buying_signals": [],
            },
            "identified_problem": {
                "primary_need": "No need identified.",
                "pain_points": [],
                "urgency": "low",
            },
        },
    )

    response = await client.get("/api/v1/calls?client_id=quintana-seguros")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) >= 1

    # Find the session with analysis data
    analyzed = next(
        (
            s
            for s in sessions
            if s.get("extracted_facts") and "call_outcome" in s["extracted_facts"]
        ),
        None,
    )
    assert analyzed is not None
    assert (
        analyzed["extracted_facts"]["call_outcome"]["classification"]
        == "not_interested"
    )


async def test_get_session_detail_legacy_session_without_analysis(app_client):
    """GET /calls/{session_id} for a legacy session without analysis axes returns
    extracted_facts without call_outcome/detected_interests/identified_problem — no error."""
    client, db_module = app_client
    session_id = await _seed_session(
        db_module,
        extracted_facts={
            "interest_level": 50,
            "objections": ["not interested now"],
            "next_action_suggested": "wait",
        },
    )

    response = await client.get(f"/api/v1/calls/{session_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["extracted_facts"] is not None
    # Legacy fields present
    assert data["extracted_facts"]["interest_level"] == 50
    # New axes NOT present (this is a legacy session)
    assert "call_outcome" not in data["extracted_facts"]
    assert "detected_interests" not in data["extracted_facts"]
