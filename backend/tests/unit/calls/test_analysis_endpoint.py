"""TDD tests for GET /api/v1/calls/{session_id}/analysis endpoint.

Layer 1 — Backend:
  - CallAnalysisResponse schema (JSON text → Python objects)
  - get_call_analysis service function
  - GET /{session_id}/analysis router endpoint

Strict TDD: RED → GREEN → TRIANGULATE → REFACTOR
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/analysis_test.db",
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
            name="Analysis Lead",
            phone="+5411888888",
            lead_id="analysis-lead",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _seed_session(db_module, *, lead_id: str = "analysis-lead") -> str:
    """Insert a completed CallSession and return its id."""
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession

        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="completed",
            started_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


async def _seed_analysis(
    db_module,
    *,
    session_id: str,
    summary: str | None = "Great call",
    interest_level: int | None = 75,
    classification: str | None = "completed_positive",
    outcome_reason: str | None = "Lead is interested",
    urgency: str | None = "high",
    primary_need: str | None = "Full coverage",
    next_action_suggested: str | None = "Send quote",
    current_insurance: str | None = "None",
    objections: list | None = None,
    products: list | None = None,
    pain_points: list | None = None,
    service_issues: list | None = None,
    profile_facts: list | None = None,
    commitment_signals: list | None = None,
    specific_needs: list | None = None,
    misc_notes: list | None = None,
    data_corrections: list | None = None,
    was_abrupt: bool | None = False,
    abandonment_trigger: str | None = None,
    extra_axes_data: dict | None = None,
    analysis_status: str = "ok",
    analysis_error: str | None = None,
) -> str:
    """Insert a CallAnalysis row and return its id."""
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallAnalysis

        analysis = CallAnalysis(
            id=str(uuid.uuid4()),
            session_id=session_id,
            lead_id="analysis-lead",
            client_id="quintana-seguros",
            summary=summary,
            interest_level=interest_level,
            classification=classification,
            outcome_reason=outcome_reason,
            urgency=urgency,
            primary_need=primary_need,
            next_action_suggested=next_action_suggested,
            current_insurance=current_insurance,
            objections=json.dumps(objections or [{"text": "Too expensive", "severity": "medium"}]),
            products=json.dumps(products or ["todo_riesgo"]),
            pain_points=json.dumps(pain_points or [{"category": "cost", "description": "High premium"}]),
            service_issues=json.dumps(service_issues or []),
            profile_facts=json.dumps(profile_facts or [{"key": "age", "value": "35"}]),
            commitment_signals=json.dumps(commitment_signals or []),
            specific_needs=json.dumps(specific_needs or ["cobertura_amplia"]),
            misc_notes=json.dumps(misc_notes or ["Lead mentioned car is brand new"]),
            data_corrections=json.dumps(data_corrections or []),
            was_abrupt=was_abrupt,
            abandonment_trigger=abandonment_trigger,
            extra_axes_data=json.dumps(extra_axes_data) if extra_axes_data else None,
            analysis_status=analysis_status,
            analysis_error=analysis_error,
            analyzed_at=datetime.now(timezone.utc),
        )
        sess.add(analysis)
        await sess.commit()
        return analysis.id


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
# Tests: CallAnalysisResponse schema (pure unit tests)
# ---------------------------------------------------------------------------


def test_call_analysis_response_parses_json_text_columns():
    """CallAnalysisResponse correctly deserializes JSON text columns into lists."""
    from app.calls.schemas import CallAnalysisResponse

    response = CallAnalysisResponse(
        session_id="test-session",
        summary="Test summary",
        interest_level=80,
        classification="completed_positive",
        outcome_reason="Lead agreed",
        urgency="high",
        primary_need="Full coverage",
        next_action_suggested="Send quote",
        current_insurance="Sancor",
        objections=[{"text": "Too expensive", "severity": "medium"}],
        products=["todo_riesgo"],
        pain_points=[{"category": "cost", "description": "High premium"}],
        service_issues=[],
        profile_facts=[{"key": "age", "value": "35"}],
        commitment_signals=[],
        specific_needs=["cobertura_amplia"],
        misc_notes=["Lead mentioned car is brand new"],
        data_corrections=[],
        was_abrupt=False,
        abandonment_trigger=None,
        extra_axes_data=None,
        analysis_status="ok",
        analysis_error=None,
        analyzed_at=datetime.now(timezone.utc),
    )

    assert response.session_id == "test-session"
    assert response.interest_level == 80
    assert response.products == ["todo_riesgo"]
    assert response.pain_points == [{"category": "cost", "description": "High premium"}]
    assert response.misc_notes == ["Lead mentioned car is brand new"]


def test_call_analysis_response_handles_all_nulls():
    """CallAnalysisResponse can be instantiated with all optional fields as None."""
    from app.calls.schemas import CallAnalysisResponse

    response = CallAnalysisResponse(
        session_id="no-analysis-session",
        summary=None,
        interest_level=None,
        classification=None,
        outcome_reason=None,
        urgency=None,
        primary_need=None,
        next_action_suggested=None,
        current_insurance=None,
        objections=None,
        products=None,
        pain_points=None,
        service_issues=None,
        profile_facts=None,
        commitment_signals=None,
        specific_needs=None,
        misc_notes=None,
        data_corrections=None,
        was_abrupt=None,
        abandonment_trigger=None,
        extra_axes_data=None,
        analysis_status="pending",
        analysis_error=None,
        analyzed_at=datetime.now(timezone.utc),
    )

    assert response.session_id == "no-analysis-session"
    assert response.interest_level is None
    assert response.products is None


# ---------------------------------------------------------------------------
# Tests: get_call_analysis service function
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_call_analysis_returns_none_when_no_analysis(seeded_db):
    """get_call_analysis returns None when no CallAnalysis row exists for the session."""
    session_id = await _seed_session(seeded_db)

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as db:
        from app.calls.service import get_call_analysis

        result = await get_call_analysis(db, session_id)

    assert result is None


@pytest.mark.asyncio
async def test_get_call_analysis_returns_analysis_when_exists(seeded_db):
    """get_call_analysis returns the CallAnalysis row when it exists."""
    session_id = await _seed_session(seeded_db)
    await _seed_analysis(seeded_db, session_id=session_id)

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as db:
        from app.calls.service import get_call_analysis

        result = await get_call_analysis(db, session_id)

    assert result is not None
    assert result.session_id == session_id
    assert result.classification == "completed_positive"
    assert result.interest_level == 75


# ---------------------------------------------------------------------------
# Tests: GET /{session_id}/analysis endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_404_for_unknown_session(app_client):
    """GET /api/v1/calls/{unknown}/analysis returns 404 when session doesn't exist."""
    client, _ = app_client
    response = await client.get("/api/v1/calls/nonexistent-session/analysis")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_404_when_no_analysis_exists(app_client):
    """GET /api/v1/calls/{session_id}/analysis returns 404 when session exists but has no analysis."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)

    response = await client.get(f"/api/v1/calls/{session_id}/analysis")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_200_with_analysis_data(app_client):
    """GET /api/v1/calls/{session_id}/analysis returns 200 with all parsed analysis fields."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)
    await _seed_analysis(db_module, session_id=session_id)

    response = await client.get(f"/api/v1/calls/{session_id}/analysis")
    assert response.status_code == 200

    data = response.json()
    assert data["session_id"] == session_id
    assert data["classification"] == "completed_positive"
    assert data["interest_level"] == 75
    assert data["summary"] == "Great call"
    assert data["analysis_status"] == "ok"


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_parsed_json_columns(app_client):
    """GET /api/v1/calls/{session_id}/analysis returns JSON columns as parsed lists (not strings)."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)
    await _seed_analysis(
        db_module,
        session_id=session_id,
        products=["todo_riesgo", "terceros"],
        objections=[{"text": "Too expensive", "severity": "medium"}],
        pain_points=[{"category": "cost", "description": "High premium"}],
    )

    response = await client.get(f"/api/v1/calls/{session_id}/analysis")
    assert response.status_code == 200

    data = response.json()
    # JSON text columns must be returned as lists, not raw JSON strings
    assert isinstance(data["products"], list)
    assert "todo_riesgo" in data["products"]
    assert isinstance(data["objections"], list)
    assert data["objections"][0]["text"] == "Too expensive"
    assert isinstance(data["pain_points"], list)
    assert data["pain_points"][0]["category"] == "cost"


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_null_columns_as_none(app_client):
    """GET /api/v1/calls/{session_id}/analysis returns null for optional columns that are absent."""
    client, db_module = app_client
    session_id = await _seed_session(db_module)
    await _seed_analysis(
        db_module,
        session_id=session_id,
        abandonment_trigger=None,
        extra_axes_data=None,
        was_abrupt=None,
    )

    response = await client.get(f"/api/v1/calls/{session_id}/analysis")
    assert response.status_code == 200

    data = response.json()
    assert data["abandonment_trigger"] is None
    assert data["extra_axes_data"] is None
    assert data["was_abrupt"] is None
