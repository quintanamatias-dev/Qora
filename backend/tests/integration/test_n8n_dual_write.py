"""Integration tests for full n8n dual-write flow — Phase 8 (Fix Round).

Spec-aligned paths and headers:
- Header: X-Internal-Secret (was X-Internal-Api-Key)
- GET  /api/v1/internal/transcript/{session_id}       (was /analysis/transcript/)
- GET  /api/v1/internal/extraction-config/{client_id} (was /analysis/config/)
- POST /api/v1/internal/analysis-result               (was /analysis/callback)
- GET  /api/v1/internal/analysis-status/{session_id}  (was /analysis/status/)

Covers the end-to-end path:
1. Webhook trigger fires from _schedule_summarize
2. Internal API accepts transcript, config, callback requests
3. Callback persists analysis to CallAnalysis
4. Verification comparison is logged
5. N8N_ENABLED=false → zero behavior change to existing code
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
import respx
import httpx
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr
from unittest.mock import patch


VALID_SECRET = "integration-test-secret"


def _make_full_settings(tmp_path):
    from app.core.config import Settings

    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dual_write_test.db",
        n8n_enabled=True,
        n8n_webhook_url="http://n8n.test/webhook/analysis",
        n8n_webhook_secret=SecretStr("integration-secret"),
        n8n_internal_api_key=SecretStr(VALID_SECRET),
    )


@pytest_asyncio.fixture
async def integration_client(tmp_path: Path):
    """Full n8n internal router client with seeded DB."""
    from app.core import database as db_module

    settings = _make_full_settings(tmp_path)
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Integration Test Lead",
            phone="+5411999999",
            lead_id="integration-lead-001",
        )
        await sess.commit()

    from fastapi import FastAPI, APIRouter
    from app.n8n.router import router as n8n_router

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(n8n_router)
    app.include_router(api_v1)

    with patch("app.n8n.dependencies._get_settings", return_value=settings):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, settings, db_module

    await db_module.close_db()


class TestN8nWebhookTriggerIntegration:
    """Verify that trigger_n8n_webhook sends correct payload and signature."""

    @pytest.mark.asyncio
    async def test_trigger_sends_hmac_signed_payload(self, tmp_path):
        """End-to-end: trigger fires a POST with HMAC signature."""
        import hashlib
        import hmac

        settings = _make_full_settings(tmp_path)

        with respx.mock:
            route = respx.post("http://n8n.test/webhook/analysis").mock(
                return_value=httpx.Response(200)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                await trigger_n8n_webhook("integration-sess-001", "quintana-seguros")

        assert route.called
        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["session_id"] == "integration-sess-001"
        assert body["client_id"] == "quintana-seguros"

        # Verify HMAC
        expected_sig = hmac.new(
            b"integration-secret",
            request.content,
            hashlib.sha256,
        ).hexdigest()
        assert request.headers.get("X-Webhook-Signature") == expected_sig

    @pytest.mark.asyncio
    async def test_trigger_disabled_sends_nothing(self, tmp_path):
        """When N8N_ENABLED=False, trigger_n8n_webhook is a no-op."""
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/noop.db",
            n8n_enabled=False,
        )

        with respx.mock:
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n import client as n8n_mod

                result = await n8n_mod.trigger_n8n_webhook("sess-noop", "client-noop")

        assert result is None  # No-op


class TestInternalApiTranscriptIntegration:
    """Transcript endpoint returns plain-text transcript from DB."""

    @pytest.mark.asyncio
    async def test_transcript_endpoint_returns_plain_text_turns(
        self, integration_client, tmp_path
    ):
        """Integration: transcript endpoint returns plain-text for session turns.

        Spec: GET /api/v1/internal/transcript/{session_id} returns text/plain.
        Auth: X-Internal-Secret header.
        """
        client, settings, db_module = integration_client

        from app.calls.service import create_session, add_transcript_turn

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="integration-lead-001",
            )
            await add_transcript_turn(sess, cs.id, "agent", "Good morning!")
            await add_transcript_turn(sess, cs.id, "user", "Hello there.")
            await sess.commit()
            session_id = cs.id

        resp = await client.get(
            f"/api/v1/internal/transcript/{session_id}",
            headers={"X-Internal-Secret": VALID_SECRET},
        )
        assert resp.status_code == 200
        # Must be plain text (spec requirement)
        assert "text/plain" in resp.headers.get("content-type", "")
        body = resp.text
        assert "Good morning!" in body
        assert "Hello there." in body

    @pytest.mark.asyncio
    async def test_transcript_401_without_secret(self, integration_client):
        """Transcript endpoint without X-Internal-Secret returns 401."""
        client, settings, db_module = integration_client

        resp = await client.get("/api/v1/internal/transcript/some-session")
        assert resp.status_code == 401


class TestInternalApiCallbackIntegration:
    """Callback endpoint persists analysis to CallAnalysis table."""

    @pytest.mark.asyncio
    async def test_callback_persists_call_analysis(self, integration_client, tmp_path):
        """n8n callback (POST /analysis-result) persists a CallAnalysis record.

        Spec contract: {session_id, summary, facts} — no 'status' field.
        """
        from sqlalchemy import select
        from app.calls.models import CallAnalysis

        client, settings, db_module = integration_client

        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="integration-lead-001",
            )
            await sess.commit()
            session_id = cs.id

        # Spec-compliant payload: {session_id, summary, facts}
        resp = await client.post(
            "/api/v1/internal/analysis-result",
            headers={"X-Internal-Secret": VALID_SECRET},
            json={
                "session_id": session_id,
                "summary": "The lead was very interested in life insurance.",
                "facts": {
                    "interest_level": 85,
                    "next_action_suggested": "send_quote",
                    "current_insurance": "none",
                },
                "n8n_execution_id": "exec-integration-001",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        # Verify CallAnalysis was created in DB
        async with db_module.async_session_factory() as sess:
            ca_result = await sess.execute(
                select(CallAnalysis).where(CallAnalysis.session_id == session_id)
            )
            ca = ca_result.scalar_one_or_none()

        assert ca is not None
        assert ca.session_id == session_id
        assert ca.summary == "The lead was very interested in life insurance."
        assert ca.interest_level == 85
        assert ca.analysis_status == "ok"

    @pytest.mark.asyncio
    async def test_callback_without_summary_does_not_persist_analysis(
        self, integration_client, tmp_path
    ):
        """n8n callback without summary/facts does not persist a CallAnalysis record.

        Spec: persistence only happens when both summary and facts are provided.
        """
        from sqlalchemy import select
        from app.calls.models import CallAnalysis

        client, settings, db_module = integration_client

        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="integration-lead-001",
            )
            await sess.commit()
            session_id = cs.id

        # Payload without summary or facts — no persistence should occur
        resp = await client.post(
            "/api/v1/internal/analysis-result",
            headers={"X-Internal-Secret": VALID_SECRET},
            json={"session_id": session_id},
        )
        assert resp.status_code == 200

        # Verify CallAnalysis was NOT created (no results to persist)
        async with db_module.async_session_factory() as sess:
            ca_result = await sess.execute(
                select(CallAnalysis).where(CallAnalysis.session_id == session_id)
            )
            ca = ca_result.scalar_one_or_none()

        assert ca is None  # No summary/facts → no persistence

    @pytest.mark.asyncio
    async def test_callback_401_without_secret(self, integration_client):
        """Callback without X-Internal-Secret returns 401."""
        client, settings, db_module = integration_client

        resp = await client.post(
            "/api/v1/internal/analysis-result",
            json={"session_id": "s1"},
        )
        assert resp.status_code == 401


class TestVerificationIntegration:
    """Verification comparison is logged for dual-write flow."""

    @pytest.mark.asyncio
    async def test_compare_results_returns_verification_result(self):
        """compare_results pure function returns correct VerificationResult."""
        from app.n8n.verification import compare_results

        local = {
            "interest_level": 80,
            "next_action_suggested": "send_quote",
            "current_insurance": "mapfre",
        }
        n8n = {
            "interest_level": 80,
            "next_action_suggested": "send_quote",
            "current_insurance": "mapfre",
        }
        result = compare_results("sess-verify-001", local, n8n)

        assert result.agreement is True
        assert result.session_id == "sess-verify-001"
        assert len(result.divergent_fields) == 0

    @pytest.mark.asyncio
    async def test_compare_results_pending_returns_agreed_none(self):
        """compare_results returns agreed=None when local facts not yet available.

        Spec: 'the system logs agreed=null (pending)'.
        """
        from app.n8n.verification import compare_results

        result = compare_results("sess-pending-001", None, {"interest_level": 70})

        assert result.agreement is None
        assert "_pending" in result.details

    @pytest.mark.asyncio
    async def test_n8n_disabled_existing_code_unaffected(self, tmp_path):
        """Feature flag off → N8N trigger returns None, existing tests pass."""
        from app.core.config import Settings

        s = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/noop2.db",
            n8n_enabled=False,
        )
        assert s.n8n_enabled is False

        with respx.mock:
            with patch("app.n8n.client._get_settings", return_value=s):
                from app.n8n import client as n8n_mod

                result = await n8n_mod.trigger_n8n_webhook("sess-x", "client-x")

        assert result is None


class TestCallbackVerificationLoggingIntegration:
    """Valid callback persists results AND triggers verification comparison log.

    Partial scenario addressed: 'Analysis Result Callback Endpoint — Valid callback
    persists results'. The comparison log must be emitted in the same request
    (not fire-and-forget), so it's verifiable in an integration test.
    """

    @pytest.mark.asyncio
    async def test_callback_triggers_verification_comparison_log(
        self, integration_client, tmp_path
    ):
        """When a valid callback arrives, verification comparison is logged.

        Spec: 'The backend MUST log the comparison result as a structured event
        with event name n8n_verification_comparison'.
        This verifies that log_verification_comparison is called from the callback.
        """
        from unittest.mock import patch as test_patch

        client, settings, db_module = integration_client

        from app.calls.service import create_session

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="integration-lead-001",
            )
            await sess.commit()
            session_id = cs.id

        verification_calls: list[dict] = []

        async def mock_log_verification(**kwargs):
            verification_calls.append(kwargs)

        # Patch at the verification module level (imported inside function body in router)
        with test_patch(
            "app.n8n.verification.log_verification_comparison",
            side_effect=mock_log_verification,
        ):
            resp = await client.post(
                "/api/v1/internal/analysis-result",
                headers={"X-Internal-Secret": VALID_SECRET},
                json={
                    "session_id": session_id,
                    "summary": "Lead showed strong interest in life insurance.",
                    "facts": {
                        "interest_level": 90,
                        "next_action_suggested": "send_quote",
                        "current_insurance": "none",
                    },
                },
            )

        assert resp.status_code == 200

        # Verification comparison must have been called once
        assert (
            len(verification_calls) == 1
        ), f"Expected 1 verification comparison call, got {len(verification_calls)}"
        call = verification_calls[0]
        assert call.get("session_id") == session_id
        assert (
            call.get("n8n_summary") == "Lead showed strong interest in life insurance."
        )
        assert call.get("n8n_facts", {}).get("interest_level") == 90

    @pytest.mark.asyncio
    async def test_trigger_graceful_degradation_does_not_raise(self, tmp_path):
        """n8n trigger failure (network error) must not raise at the client level.

        Partial scenario: 'n8n unreachable — graceful degradation'.
        Verifies the degradation contract at the client boundary — exception is swallowed,
        None is returned, no re-raise propagates to _schedule_summarize.
        """
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/degrade.db",
            n8n_enabled=True,
            n8n_webhook_url="http://n8n.test/unreachable",
            n8n_webhook_secret=SecretStr("sec"),
            n8n_internal_api_key=SecretStr("key"),
        )

        with respx.mock:
            # Simulate timeout — should be swallowed
            respx.post("http://n8n.test/unreachable").mock(
                side_effect=httpx.TimeoutException("timed out")
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                result = await trigger_n8n_webhook("sess-degrade", "client-degrade")

        # None returned (graceful) — no exception raised
        assert result is None
