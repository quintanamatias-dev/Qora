"""Unit tests for WU5 — Admin API SIP observability fields in GET /calls/{session_id}.

Spec: outbound-call-trigger (delta) — ADDED: GET Call Session — SIP Observability Fields

Tasks:
  5.1 — _session_to_dict() includes all five SIP fields (populated or null)
  5.2 — Admin API response tests for:
          - populated probe evidence
          - null unreconciled fields
  5.3 — Only mocked-provider tests (no live calls)

TDD: Tests written BEFORE the router is extended.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Task 5.1 — _session_to_dict() includes SIP fields
# ---------------------------------------------------------------------------


class TestSessionToDictIncludesSipFields:
    """_session_to_dict must include all five SIP observability fields."""

    def test_session_to_dict_includes_all_five_sip_fields_as_null(self):
        """GIVEN a CallSession with no SIP fields set (null)
        WHEN _session_to_dict is called
        THEN all five SIP fields are present as null (not omitted).

        Spec: Scenario: GET response includes SIP fields as null when not yet reconciled.
        """
        from app.calls.router import _session_to_dict

        cs = MagicMock()
        cs.id = "sess-001"
        cs.client_id = "client-001"
        cs.lead_id = "lead-001"
        cs.status = "failed"
        cs.outcome = None
        cs.closed_reason = None
        cs.started_at = datetime.now(timezone.utc)
        cs.ended_at = None
        cs.duration_seconds = None
        cs.billable_minutes = None
        cs.total_user_turns = 0
        cs.total_agent_turns = 0
        cs.summary = None
        cs.extracted_facts = None
        cs.merged_into_session_id = None
        # SIP fields — all null (not yet reconciled)
        cs.sip_call_id = None
        cs.sip_status_code = None
        cs.sip_reason = None
        cs.reconciled_at = None
        cs.reconciliation_source = None

        result = _session_to_dict(cs)

        # All five fields must be present (not absent — spec requires null not omission)
        assert "sip_call_id" in result, "sip_call_id must be in response"
        assert "sip_status_code" in result, "sip_status_code must be in response"
        assert "sip_reason" in result, "sip_reason must be in response"
        assert "reconciled_at" in result, "reconciled_at must be in response"
        assert "reconciliation_source" in result, "reconciliation_source must be in response"

        # All must be null
        assert result["sip_call_id"] is None
        assert result["sip_status_code"] is None
        assert result["sip_reason"] is None
        assert result["reconciled_at"] is None
        assert result["reconciliation_source"] is None

    def test_session_to_dict_includes_populated_sip_fields(self):
        """GIVEN a CallSession with SIP fields populated by the probe
        WHEN _session_to_dict is called
        THEN all five SIP fields are present with their values.

        Spec: Scenario: GET response includes SIP fields when available.
        """
        from app.calls.router import _session_to_dict

        reconciled_at = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

        cs = MagicMock()
        cs.id = "sess-002"
        cs.client_id = "client-001"
        cs.lead_id = "lead-001"
        cs.status = "ringing"
        cs.outcome = None
        cs.closed_reason = None
        cs.started_at = datetime.now(timezone.utc)
        cs.ended_at = None
        cs.duration_seconds = None
        cs.billable_minutes = None
        cs.total_user_turns = 0
        cs.total_agent_turns = 0
        cs.summary = None
        cs.extracted_facts = None
        cs.merged_into_session_id = None
        # SIP fields — populated by probe
        cs.sip_call_id = "otb_probe_abc123"
        cs.sip_status_code = 200
        cs.sip_reason = "OK"
        cs.reconciled_at = reconciled_at
        cs.reconciliation_source = "probe"

        result = _session_to_dict(cs)

        assert result["sip_call_id"] == "otb_probe_abc123"
        assert result["sip_status_code"] == 200
        assert result["sip_reason"] == "OK"
        assert result["reconciliation_source"] == "probe"
        assert result["reconciled_at"] is not None  # ISO formatted or datetime

    def test_session_to_dict_sip_fields_do_not_break_existing_fields(self):
        """GIVEN a CallSession with SIP fields
        WHEN _session_to_dict is called
        THEN existing fields are still present and unmodified.

        Spec: No existing fields in the GET response are modified or removed.
        """
        from app.calls.router import _session_to_dict

        cs = MagicMock()
        cs.id = "sess-003"
        cs.client_id = "client-003"
        cs.lead_id = "lead-003"
        cs.status = "completed"
        cs.outcome = "interested"
        cs.closed_reason = "session_end"
        cs.started_at = datetime.now(timezone.utc)
        cs.ended_at = datetime.now(timezone.utc)
        cs.duration_seconds = 120.0
        cs.billable_minutes = 2
        cs.total_user_turns = 5
        cs.total_agent_turns = 5
        cs.summary = "Lead was interested"
        cs.extracted_facts = None
        cs.merged_into_session_id = None
        cs.sip_call_id = "otb_abc"
        cs.sip_status_code = 200
        cs.sip_reason = "OK"
        cs.reconciled_at = None
        cs.reconciliation_source = None

        result = _session_to_dict(cs)

        # All existing fields must be present
        assert result["id"] == "sess-003"
        assert result["client_id"] == "client-003"
        assert result["lead_id"] == "lead-003"
        assert result["status"] == "completed"
        assert result["outcome"] == "interested"
        assert result["closed_reason"] == "session_end"
        assert result["duration_seconds"] == 120.0
        assert result["billable_minutes"] == 2
        assert result["total_user_turns"] == 5
        assert result["total_agent_turns"] == 5
        assert result["summary"] == "Lead was interested"


# ---------------------------------------------------------------------------
# Task 5.2 — GET /calls/{session_id} endpoint tests (integration-style)
# ---------------------------------------------------------------------------


def _build_test_app():
    """Build a minimal FastAPI app with the calls router for response tests."""
    from fastapi import FastAPI, APIRouter
    from app.calls.router import router as calls_router

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(calls_router)

    app = FastAPI()
    app.include_router(api_v1)
    return app


class TestGetCallSessionEndpointSipFields:
    """GET /calls/{session_id} returns SIP fields in response."""

    @pytest.mark.asyncio
    async def test_get_session_returns_null_sip_fields_when_unreconciled(self, db_session, db_engine):
        """GIVEN a CallSession in the DB with no SIP evidence
        WHEN GET /calls/{session_id} is called
        THEN the response includes all five SIP fields as null.

        Spec: Scenario: GET response includes SIP fields as null when not yet reconciled.
        """
        import uuid
        from httpx import AsyncClient, ASGITransport
        from app.calls.models import CallSession

        session_id = str(uuid.uuid4())
        cs = CallSession(
            id=session_id,
            client_id="test-client",
            lead_id=None,
            status="failed",
            telephony_status="failed",
            telephony_provider="elevenlabs",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            # SIP fields — all null
        )
        db_session.add(cs)
        await db_session.commit()
        await db_session.refresh(cs)

        app = _build_test_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/calls/{session_id}")

        assert response.status_code == 200
        body = response.json()

        assert "sip_call_id" in body, "sip_call_id must be in GET response"
        assert "sip_status_code" in body
        assert "sip_reason" in body
        assert "reconciled_at" in body
        assert "reconciliation_source" in body

        assert body["sip_call_id"] is None
        assert body["sip_status_code"] is None
        assert body["sip_reason"] is None
        assert body["reconciled_at"] is None
        assert body["reconciliation_source"] is None

    @pytest.mark.asyncio
    async def test_get_session_returns_populated_sip_fields(self, db_session, db_engine):
        """GIVEN a CallSession with probe-populated SIP evidence
        WHEN GET /calls/{session_id} is called
        THEN the response includes all five SIP fields with their values.

        Spec: Scenario: GET response includes SIP fields when available.
        """
        import uuid
        from httpx import AsyncClient, ASGITransport
        from app.calls.models import CallSession

        session_id = str(uuid.uuid4())
        reconciled_at = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)

        cs = CallSession(
            id=session_id,
            client_id="test-client",
            lead_id=None,
            status="ringing",
            telephony_status="ringing",
            telephony_provider="elevenlabs",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            sip_call_id="otb_e2e_test_abc",
            sip_status_code=200,
            sip_reason="OK",
            reconciled_at=reconciled_at,
            reconciliation_source="probe",
        )
        db_session.add(cs)
        await db_session.commit()
        await db_session.refresh(cs)

        app = _build_test_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/calls/{session_id}")

        assert response.status_code == 200
        body = response.json()

        assert body["sip_call_id"] == "otb_e2e_test_abc"
        assert body["sip_status_code"] == 200
        assert body["sip_reason"] == "OK"
        assert body["reconciliation_source"] == "probe"
        assert body["reconciled_at"] is not None
