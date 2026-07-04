"""Unit tests for OutboundCallRequest and OutboundCallResult Pydantic models.

Spec: outbound-call-trigger — Requirement: Call Attempt Persistence
Design: backend/app/elevenlabs/models.py additions — OutboundCallRequest, OutboundCallResult
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# RED — OutboundCallRequest / OutboundCallResult do not exist yet
# ---------------------------------------------------------------------------


class TestOutboundCallRequest:
    """Pydantic model validation for outbound call initiation request."""

    def test_valid_minimal_request(self):
        """GIVEN required fields agent_id, agent_phone_number_id, and to
        WHEN OutboundCallRequest is constructed
        THEN it succeeds and fields are accessible.
        """
        from app.elevenlabs.models import OutboundCallRequest

        req = OutboundCallRequest(
            agent_id="el-agent-123",
            agent_phone_number_id="pn-abc",
            to="+14155552671",
        )
        assert req.agent_id == "el-agent-123"
        assert req.agent_phone_number_id == "pn-abc"
        assert req.to == "+14155552671"
        assert req.conversation_initiation_client_data is None

    def test_valid_request_with_client_data(self):
        """GIVEN all fields including optional conversation_initiation_client_data
        WHEN OutboundCallRequest is constructed
        THEN the optional field is set.
        """
        from app.elevenlabs.models import OutboundCallRequest

        req = OutboundCallRequest(
            agent_id="el-agent-123",
            agent_phone_number_id="pn-abc",
            to="+5491123456789",
            conversation_initiation_client_data={"lead_name": "Maria"},
        )
        assert req.conversation_initiation_client_data == {"lead_name": "Maria"}

    def test_missing_required_fields_raises(self):
        """GIVEN a request with missing required fields
        WHEN OutboundCallRequest is constructed
        THEN ValidationError is raised.
        """
        from app.elevenlabs.models import OutboundCallRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OutboundCallRequest(agent_id="x")  # missing agent_phone_number_id and to


class TestOutboundCallResult:
    """Pydantic model validation for outbound call API result."""

    def test_accepted_outcome(self):
        """GIVEN outcome='accepted' with a provider_call_id
        WHEN OutboundCallResult is constructed
        THEN fields are accessible and error fields are None.
        """
        from app.elevenlabs.models import OutboundCallResult

        result = OutboundCallResult(
            outcome="accepted",
            provider_call_id="call-xyz-123",
            provider_metadata={"cost": 0.21},
        )
        assert result.outcome == "accepted"
        assert result.provider_call_id == "call-xyz-123"
        assert result.provider_metadata == {"cost": 0.21}
        assert result.error_detail is None
        assert result.error_category is None

    def test_transient_error_outcome(self):
        """GIVEN outcome='error' with a transient error category
        WHEN OutboundCallResult is constructed
        THEN error fields are populated and provider fields are None.
        """
        from app.elevenlabs.models import OutboundCallResult

        result = OutboundCallResult(
            outcome="error",
            error_detail="HTTP 503: Service Unavailable",
            error_category="transient",
        )
        assert result.outcome == "error"
        assert result.error_category == "transient"
        assert result.error_detail == "HTTP 503: Service Unavailable"
        assert result.provider_call_id is None

    def test_permanent_error_outcome(self):
        """GIVEN outcome='error' with a permanent error category
        WHEN OutboundCallResult is constructed
        THEN error_category='permanent'.
        """
        from app.elevenlabs.models import OutboundCallResult

        result = OutboundCallResult(
            outcome="error",
            error_detail="HTTP 400: Bad agent ID",
            error_category="permanent",
        )
        assert result.error_category == "permanent"

    def test_invalid_outcome_raises(self):
        """GIVEN an invalid outcome literal
        WHEN OutboundCallResult is constructed
        THEN ValidationError is raised.
        """
        from app.elevenlabs.models import OutboundCallResult
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OutboundCallResult(outcome="unknown_status")
