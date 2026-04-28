"""Unit tests for n8n internal API router — Phase 4 (Fix Round).

Spec-aligned paths:
- GET  /api/v1/internal/transcript/{session_id}
- GET  /api/v1/internal/extraction-config/{client_id}
- POST /api/v1/internal/analysis-result
- GET  /api/v1/internal/analysis-status/{session_id}

Auth header: X-Internal-Secret (spec requirement).

Covers:
- 401 when X-Internal-Secret missing or wrong on all endpoints
- GET /transcript/{session_id} → 200 with plain-text transcript (text/plain)
- GET /transcript/{session_id} → 404 for unknown session
- GET /extraction-config/{client_id} → 200 with system_prompt + response_schema
- GET /extraction-config/{client_id} → 404 for unknown client
- GET /extraction-config/{client_id} → 404 when client has no ExtractionConfig
- POST /analysis-result → 200 with valid N8nCallbackPayload
- POST /analysis-result → 422 on malformed body (no DB writes)
- GET /analysis-status/{session_id} → 200 with session local_status
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SECRET = "test-internal-secret-abc"


def _build_test_app(settings):
    """Build a minimal FastAPI app with only the n8n internal router."""
    from fastapi import FastAPI, APIRouter
    from app.n8n.router import router as n8n_router

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(n8n_router)
    app.include_router(api_v1)
    return app


@pytest_asyncio.fixture
async def n8n_client(tmp_path: Path):
    """AsyncClient pointed at a minimal app with n8n router + seeded DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/n8n_router_test.db",
        n8n_enabled=True,
        n8n_internal_api_key=SecretStr(VALID_SECRET),
    )
    await db_module.init_db(settings)
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Test Lead",
            phone="+5411111111",
            lead_id="test-lead-n8n",
        )
        await sess.commit()

    app = _build_test_app(settings)

    # Override the settings inside the router dependency
    from unittest.mock import patch

    with patch("app.n8n.dependencies._get_settings", return_value=settings):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Router registration in main.py
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Verify the n8n router is registered in the main FastAPI application."""

    def test_n8n_routes_registered_in_main_app(self):
        """The real app must expose /api/v1/internal/* routes.

        Critical: fixes the missing router registration in main.py.
        Tests that the n8n router is included in api_v1_router.
        """
        # Import app module — routes are registered at module level
        import app.main as main_module

        route_paths = [route.path for route in main_module.app.routes]

        # Internal API routes must be present in the main app
        assert any(
            "/internal/transcript" in p for p in route_paths
        ), f"Expected /internal/transcript route in main app. Found: {route_paths}"
        assert any(
            "/internal/extraction-config" in p for p in route_paths
        ), f"Expected /internal/extraction-config route in main app. Found: {route_paths}"
        assert any(
            "/internal/analysis-result" in p for p in route_paths
        ), f"Expected /internal/analysis-result route in main app. Found: {route_paths}"


# ---------------------------------------------------------------------------
# Authentication tests — X-Internal-Secret header
# ---------------------------------------------------------------------------


class TestInternalApiAuth:
    """All /api/v1/internal/* endpoints require X-Internal-Secret header."""

    @pytest.mark.asyncio
    async def test_transcript_missing_secret_returns_401(self, n8n_client):
        """No X-Internal-Secret header → 401 on transcript endpoint."""
        resp = await n8n_client.get("/api/v1/internal/transcript/some-session")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_transcript_wrong_secret_returns_401(self, n8n_client):
        """Wrong X-Internal-Secret → 401 on transcript endpoint."""
        resp = await n8n_client.get(
            "/api/v1/internal/transcript/some-session",
            headers={"X-Internal-Secret": "wrong-secret"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_extraction_config_missing_secret_returns_401(self, n8n_client):
        """No X-Internal-Secret → 401 on extraction-config endpoint."""
        resp = await n8n_client.get("/api/v1/internal/extraction-config/some-client")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analysis_result_missing_secret_returns_401(self, n8n_client):
        """No X-Internal-Secret → 401 on analysis-result endpoint."""
        resp = await n8n_client.post(
            "/api/v1/internal/analysis-result",
            json={"session_id": "s1", "status": "success"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analysis_status_missing_secret_returns_401(self, n8n_client):
        """No X-Internal-Secret → 401 on analysis-status endpoint."""
        resp = await n8n_client.get("/api/v1/internal/analysis-status/some-session")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_secret_grants_access_to_transcript(self, n8n_client):
        """Valid X-Internal-Secret allows request through (non-401 response)."""
        resp = await n8n_client.get(
            "/api/v1/internal/transcript/nonexistent",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        # 404 is fine — it means auth passed and the endpoint was reached
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Transcript endpoint — text/plain response
# ---------------------------------------------------------------------------


class TestTranscriptEndpoint:
    """GET /api/v1/internal/transcript/{session_id}"""

    @pytest.mark.asyncio
    async def test_transcript_404_for_unknown_session(self, n8n_client):
        """Returns 404 when session does not exist."""
        resp = await n8n_client.get(
            "/api/v1/internal/transcript/nonexistent-session",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_transcript_returns_plain_text_for_valid_session(self, n8n_client):
        """Returns 200 with Content-Type: text/plain containing transcript lines."""
        from app.core import database as db_module
        from app.calls.service import create_session, add_transcript_turn

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="test-lead-n8n",
            )
            await add_transcript_turn(sess, cs.id, "agent", "Hello, how are you?")
            await add_transcript_turn(sess, cs.id, "user", "I'm fine, thanks.")
            await sess.commit()
            session_id = cs.id

        resp = await n8n_client.get(
            f"/api/v1/internal/transcript/{session_id}",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        # Spec: response is text/plain
        assert "text/plain" in resp.headers.get("content-type", "")
        # Spec: formatted as "role: content" lines
        body = resp.text
        assert "Hello, how are you?" in body
        assert "I'm fine, thanks." in body

    @pytest.mark.asyncio
    async def test_transcript_is_not_json(self, n8n_client):
        """Transcript endpoint returns plain text, NOT JSON."""
        from app.core import database as db_module
        from app.calls.service import create_session, add_transcript_turn

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="test-lead-n8n",
            )
            await add_transcript_turn(sess, cs.id, "agent", "Hola.")
            await sess.commit()
            session_id = cs.id

        resp = await n8n_client.get(
            f"/api/v1/internal/transcript/{session_id}",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        # Response body must be plain text, not a JSON object
        assert not resp.text.startswith("{")


# ---------------------------------------------------------------------------
# Extraction config endpoint — 404 when config missing
# ---------------------------------------------------------------------------


class TestExtractionConfigEndpoint:
    """GET /api/v1/internal/extraction-config/{client_id}"""

    @pytest.mark.asyncio
    async def test_extraction_config_404_for_unknown_client(self, n8n_client):
        """Returns 404 when client does not exist."""
        resp = await n8n_client.get(
            "/api/v1/internal/extraction-config/nonexistent-client",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_extraction_config_404_when_client_has_no_config(self, n8n_client):
        """Returns 404 when client exists but has no extraction_config set.

        Spec: 'MUST return 404 if the client or its extraction config does not exist.'
        """
        # quintana-seguros is seeded without extraction_config
        resp = await n8n_client.get(
            "/api/v1/internal/extraction-config/quintana-seguros",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_extraction_config_200_when_config_exists(self, n8n_client):
        """Returns 200 with system_prompt and response_schema when config is set."""
        from app.core import database as db_module
        from app.tenants.models import Client
        from sqlalchemy import update

        # Set extraction_config on quintana-seguros
        sample_config = json.dumps(
            {
                "fields": [
                    {
                        "name": "interest_level",
                        "type": "integer",
                        "description": "1-10 scale",
                    }
                ]
            }
        )
        async with db_module.async_session_factory() as sess:
            await sess.execute(
                update(Client)
                .where(Client.id == "quintana-seguros")
                .values(extraction_config=sample_config)
            )
            await sess.commit()

        resp = await n8n_client.get(
            "/api/v1/internal/extraction-config/quintana-seguros",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "client_id" in data
        assert "system_prompt" in data
        assert "response_schema" in data
        assert data["client_id"] == "quintana-seguros"
        assert isinstance(data["system_prompt"], str)
        assert len(data["system_prompt"]) > 0


# ---------------------------------------------------------------------------
# Analysis result callback endpoint
# ---------------------------------------------------------------------------


class TestAnalysisResultEndpoint:
    """POST /api/v1/internal/analysis-result

    Spec contract: accepts {session_id, summary, facts} — no 'status' field required.
    """

    @pytest.mark.asyncio
    async def test_spec_contract_no_status_field_required(self, n8n_client):
        """Spec: POST /api/v1/internal/analysis-result accepts {session_id, summary, facts}.

        The 'status' field is NOT part of the spec contract — the payload
        must be accepted without it.
        """
        from app.core import database as db_module
        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="test-lead-n8n",
            )
            await sess.commit()
            session_id = cs.id

        # Spec-compliant payload: {session_id, summary, facts} — no 'status'
        resp = await n8n_client.post(
            "/api/v1/internal/analysis-result",
            headers={"X-Internal-Secret": VALID_SECRET},
            json={
                "session_id": session_id,
                "summary": "The lead was very interested.",
                "facts": {"interest_level": 8},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_analysis_result_422_on_missing_session_id(self, n8n_client):
        """Returns 422 when session_id is missing — and no DB writes occur.

        Spec: 'MUST return 422 on schema validation failure AND no DB writes occur.'
        """
        from app.core import database as db_module
        from app.calls.models import CallAnalysis
        from sqlalchemy import select, func

        # Count CallAnalysis rows before the invalid request
        async with db_module.async_session_factory() as sess:
            before = (await sess.execute(select(func.count(CallAnalysis.id)))).scalar()

        resp = await n8n_client.post(
            "/api/v1/internal/analysis-result",
            headers={"X-Internal-Secret": VALID_SECRET},
            json={"summary": "no session", "facts": {}},  # missing session_id
        )
        assert resp.status_code == 422

        # Verify no DB writes occurred
        async with db_module.async_session_factory() as sess:
            after = (await sess.execute(select(func.count(CallAnalysis.id)))).scalar()
        assert after == before, (
            f"Expected no DB writes on 422, but CallAnalysis count changed: "
            f"{before} → {after}"
        )

    @pytest.mark.asyncio
    async def test_analysis_result_200_for_spec_payload_with_summary_and_facts(
        self, n8n_client
    ):
        """Returns 200 and accepted status on valid spec-contract payload."""
        from app.core import database as db_module
        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="test-lead-n8n",
            )
            await sess.commit()
            session_id = cs.id

        resp = await n8n_client.post(
            "/api/v1/internal/analysis-result",
            headers={"X-Internal-Secret": VALID_SECRET},
            json={
                "session_id": session_id,
                "summary": "The lead was interested.",
                "facts": {"interest_level": 80},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"


# ---------------------------------------------------------------------------
# Analysis status endpoint
# ---------------------------------------------------------------------------


class TestAnalysisStatusEndpoint:
    """GET /api/v1/internal/analysis-status/{session_id}"""

    @pytest.mark.asyncio
    async def test_analysis_status_404_for_unknown_session(self, n8n_client):
        """Returns 404 when session doesn't exist."""
        resp = await n8n_client.get(
            "/api/v1/internal/analysis-status/nonexistent",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_analysis_status_200_for_known_session(self, n8n_client):
        """Returns 200 with local_status for a known session."""
        from app.core import database as db_module
        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="test-lead-n8n",
            )
            await sess.commit()
            session_id = cs.id

        resp = await n8n_client.get(
            f"/api/v1/internal/analysis-status/{session_id}",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert "local_status" in data
        assert data["local_status"] == "pending"  # No analysis yet
