"""Unit tests for n8n Pydantic schemas — Phase 2.1 RED.

Covers:
- N8nTriggerPayload: valid shape, required fields
- N8nCallbackPayload: success/failed status variants, optional fields
- VerificationResult: agreed/disagreed/pending states
- Schema validation failure raises on missing required fields
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestN8nTriggerPayload:
    """Trigger payload sent from backend to n8n webhook."""

    def test_trigger_payload_valid(self):
        """Valid trigger payload has session_id, client_id, and timestamp."""
        from app.n8n.schemas import N8nTriggerPayload

        p = N8nTriggerPayload(
            session_id="sess-123",
            client_id="client-abc",
            timestamp="2026-04-28T10:00:00Z",
        )
        assert p.session_id == "sess-123"
        assert p.client_id == "client-abc"
        assert p.timestamp == "2026-04-28T10:00:00Z"

    def test_trigger_payload_missing_session_id_raises(self):
        """session_id is required — missing raises ValidationError."""
        from app.n8n.schemas import N8nTriggerPayload

        with pytest.raises(ValidationError):
            N8nTriggerPayload(
                client_id="client-abc",
                timestamp="2026-04-28T10:00:00Z",
            )

    def test_trigger_payload_missing_client_id_raises(self):
        """client_id is required — missing raises ValidationError."""
        from app.n8n.schemas import N8nTriggerPayload

        with pytest.raises(ValidationError):
            N8nTriggerPayload(
                session_id="sess-123",
                timestamp="2026-04-28T10:00:00Z",
            )

    def test_trigger_payload_serializes_to_dict(self):
        """model_dump() returns dict with all three keys."""
        from app.n8n.schemas import N8nTriggerPayload

        p = N8nTriggerPayload(
            session_id="s1",
            client_id="c1",
            timestamp="2026-01-01T00:00:00Z",
        )
        d = p.model_dump()
        assert d["session_id"] == "s1"
        assert d["client_id"] == "c1"
        assert "timestamp" in d


class TestN8nCallbackPayload:
    """Callback payload sent from n8n back to internal API.

    Spec contract: {session_id, summary, facts} — no 'status' field.
    Only session_id is required.
    """

    def test_callback_spec_contract_payload(self):
        """Spec callback has session_id, summary, and facts — no 'status' required."""
        from app.n8n.schemas import N8nCallbackPayload

        cb = N8nCallbackPayload(
            session_id="sess-456",
            summary="The lead was interested.",
            facts={"interest_level": 80},
        )
        assert cb.session_id == "sess-456"
        assert cb.summary == "The lead was interested."
        assert cb.facts == {"interest_level": 80}
        assert cb.n8n_execution_id is None

    def test_callback_with_only_session_id(self):
        """session_id is the only required field — all others are optional."""
        from app.n8n.schemas import N8nCallbackPayload

        cb = N8nCallbackPayload(session_id="sess-789")
        assert cb.session_id == "sess-789"
        assert cb.summary is None
        assert cb.facts is None

    def test_callback_missing_session_id_raises(self):
        """session_id is required in callback payload — missing raises ValidationError."""
        from app.n8n.schemas import N8nCallbackPayload

        with pytest.raises(ValidationError):
            N8nCallbackPayload(summary="no session", facts={})

    def test_callback_optional_n8n_execution_id(self):
        """n8n_execution_id is optional and can be a string."""
        from app.n8n.schemas import N8nCallbackPayload

        cb = N8nCallbackPayload(
            session_id="s1",
            n8n_execution_id="exec-001",
        )
        assert cb.n8n_execution_id == "exec-001"

    def test_callback_facts_can_be_any_dict(self):
        """facts is an open dict[str, Any] — accepts any JSON-serializable values."""
        from app.n8n.schemas import N8nCallbackPayload

        cb = N8nCallbackPayload(
            session_id="sess-999",
            summary="Summary text",
            facts={"interest_level": 9, "nested": {"a": 1}},
        )
        assert cb.facts["interest_level"] == 9
        assert cb.facts["nested"] == {"a": 1}


class TestVerificationResult:
    """Agreement result produced by the comparison logic."""

    def test_verification_agreed(self):
        """agreed=True when results match."""
        from app.n8n.schemas import VerificationResult

        r = VerificationResult(
            session_id="sess-001",
            agreement=True,
            matching_fields=["interest_level", "classification"],
            divergent_fields=[],
            details={},
        )
        assert r.agreement is True
        assert "interest_level" in r.matching_fields
        assert r.divergent_fields == []

    def test_verification_disagreed(self):
        """agreed=False when results diverge."""
        from app.n8n.schemas import VerificationResult

        r = VerificationResult(
            session_id="sess-002",
            agreement=False,
            matching_fields=["classification"],
            divergent_fields=["interest_level"],
            details={"interest_level": {"local": 80, "n8n": 50, "match": False}},
        )
        assert r.agreement is False
        assert "interest_level" in r.divergent_fields
        assert r.details["interest_level"]["local"] == 80

    def test_verification_session_id_required(self):
        """session_id is required in VerificationResult."""
        from app.n8n.schemas import VerificationResult

        with pytest.raises(ValidationError):
            VerificationResult(
                agreement=True,
                matching_fields=[],
                divergent_fields=[],
                details={},
            )
