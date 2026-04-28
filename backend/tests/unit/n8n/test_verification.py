"""Unit tests for dual-write verification logic — Phase 5 (Fix Round 2).

Covers:
- compare_results: agreed=True when all comparison fields match
- compare_results: agreed=False with correct divergent_fields list
- compare_results: agreed=None (pending) when local_facts=None — spec requirement
- _hash_value: same input produces same hash
- _hash_value: different input produces different hash
- VerificationResult structure is consistent with schemas
- log_verification_comparison: emits structlog entry with spec-required fields
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCompareResults:
    """Pure function compare_results() — no DB, no side effects."""

    def test_agreed_when_all_fields_match(self):
        """agreement=True when local and n8n facts are identical on key fields."""
        from app.n8n.verification import compare_results

        local = {
            "interest_level": 80,
            "next_action_suggested": "call_again",
            "current_insurance": "mapfre",
        }
        n8n = {
            "interest_level": 80,
            "next_action_suggested": "call_again",
            "current_insurance": "mapfre",
        }
        result = compare_results("sess-001", local, n8n)

        assert result.agreement is True
        assert "interest_level" in result.matching_fields
        assert "next_action_suggested" in result.matching_fields
        assert result.divergent_fields == []

    def test_disagreed_when_field_differs(self):
        """agreement=False when interest_level diverges."""
        from app.n8n.verification import compare_results

        local = {
            "interest_level": 80,
            "next_action_suggested": "call_again",
            "current_insurance": None,
        }
        n8n = {
            "interest_level": 50,  # Diverges
            "next_action_suggested": "call_again",
            "current_insurance": None,
        }
        result = compare_results("sess-002", local, n8n)

        assert result.agreement is False
        assert "interest_level" in result.divergent_fields
        assert result.details["interest_level"]["local"] == 80
        assert result.details["interest_level"]["n8n"] == 50
        assert result.details["interest_level"]["match"] is False

    def test_partial_match_some_fields_diverge(self):
        """When one field matches and another doesn't, both are tracked correctly."""
        from app.n8n.verification import compare_results

        local = {
            "interest_level": 70,
            "next_action_suggested": "send_quote",
            "current_insurance": None,
        }
        n8n = {
            "interest_level": 70,  # matches
            "next_action_suggested": "call_again",  # diverges
            "current_insurance": None,  # matches
        }
        result = compare_results("sess-003", local, n8n)

        assert result.agreement is False
        assert "interest_level" in result.matching_fields
        assert "current_insurance" in result.matching_fields
        assert "next_action_suggested" in result.divergent_fields

    def test_pending_when_local_facts_is_none(self):
        """When local_facts=None (local pipeline not done), returns agreed=None.

        Spec: 'the system logs agreed=null (pending) and does not raise an error'
        """
        from app.n8n.verification import compare_results

        n8n = {"interest_level": 60}
        result = compare_results("sess-004", None, n8n)

        # Spec: agreed must be None (not False) for pending state
        assert result.agreement is None
        assert "_pending" in result.details
        assert "_all" in result.divergent_fields

    def test_session_id_propagated_to_result(self):
        """Result always includes the session_id for correlation."""
        from app.n8n.verification import compare_results

        result = compare_results("my-session-xyz", {}, {})
        assert result.session_id == "my-session-xyz"


class TestHashValue:
    """_hash_value() pure helper — deterministic, short hex string."""

    def test_same_input_same_hash(self):
        """Same value always produces the same hash."""
        from app.n8n.verification import _hash_value

        h1 = _hash_value("some summary text")
        h2 = _hash_value("some summary text")
        assert h1 == h2
        assert len(h1) == 8  # truncated to 8 chars

    def test_different_input_different_hash(self):
        """Different values produce different hashes."""
        from app.n8n.verification import _hash_value

        h1 = _hash_value("summary A")
        h2 = _hash_value("summary B")
        assert h1 != h2

    def test_none_value_hashable(self):
        """None is handled gracefully — returns a valid 8-char hash."""
        from app.n8n.verification import _hash_value

        h = _hash_value(None)
        assert isinstance(h, str)
        assert len(h) == 8

    def test_dict_value_hashable(self):
        """Dict values are JSON-serialized deterministically."""
        from app.n8n.verification import _hash_value

        h1 = _hash_value({"a": 1, "b": 2})
        h2 = _hash_value({"b": 2, "a": 1})  # Same content, different key order
        assert h1 == h2  # sort_keys=True ensures determinism


class TestLogVerificationComparisonPayload:
    """log_verification_comparison must emit a structlog entry with spec-required fields.

    Spec: 'Each log entry MUST include session_id, agreed (bool), n8n_summary_hash,
    local_summary_hash, and timestamp.'
    """

    @pytest.mark.asyncio
    async def test_log_emits_session_id_and_agreed_fields(self):
        """Log entry must include session_id and agreed fields.

        Behavioral: intercept the structlog call and assert the exact fields emitted.
        """
        from app.n8n.verification import log_verification_comparison

        captured_log = {}

        def fake_info(event, **kwargs):
            if event == "n8n_verification_comparison":
                captured_log.update(kwargs)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No local analysis yet
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.n8n.verification.logger") as mock_logger:
            mock_logger.info.side_effect = fake_info

            await log_verification_comparison(
                session_id="sess-log-test",
                n8n_summary="GPT summary text",
                n8n_facts={"interest_level": 70},
                db=mock_db,
            )

        assert mock_logger.info.called, "Expected logger.info to be called"
        call_args = mock_logger.info.call_args

        # Verify event name
        assert call_args[0][0] == "n8n_verification_comparison"

        # Verify spec-required fields are present
        kwargs = call_args[1]
        assert "session_id" in kwargs, f"Missing session_id in log. Got: {kwargs}"
        assert "agreed" in kwargs, f"Missing agreed in log. Got: {kwargs}"
        assert (
            "n8n_summary_hash" in kwargs
        ), f"Missing n8n_summary_hash in log. Got: {kwargs}"
        assert (
            "local_summary_hash" in kwargs
        ), f"Missing local_summary_hash in log. Got: {kwargs}"
        assert "timestamp" in kwargs, f"Missing timestamp in log. Got: {kwargs}"

        # Verify correctness of values
        assert kwargs["session_id"] == "sess-log-test"
        assert kwargs["agreed"] is None  # No local analysis → pending
        assert isinstance(kwargs["n8n_summary_hash"], str)
        assert len(kwargs["n8n_summary_hash"]) == 8  # hash is 8-char hex

    @pytest.mark.asyncio
    async def test_log_agreed_true_when_results_match(self):
        """Log entry has agreed=True when local and n8n results match.

        Verifies the agreed field reflects the actual comparison outcome.
        """
        from app.n8n.verification import log_verification_comparison
        from app.calls.models import CallAnalysis

        # Build a mock CallAnalysis with matching values
        mock_ca = MagicMock(spec=CallAnalysis)
        mock_ca.analysis_status = "ok"
        mock_ca.summary = "Matching summary"
        mock_ca.interest_level = 80
        mock_ca.next_action_suggested = "send_quote"
        mock_ca.current_insurance = "mapfre"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_ca
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.n8n.verification.logger") as mock_logger:
            await log_verification_comparison(
                session_id="sess-match-test",
                n8n_summary="Matching summary",
                n8n_facts={
                    "interest_level": 80,
                    "next_action_suggested": "send_quote",
                    "current_insurance": "mapfre",
                },
                db=mock_db,
            )

        assert mock_logger.info.called
        kwargs = mock_logger.info.call_args[1]
        assert kwargs["session_id"] == "sess-match-test"
        assert kwargs["agreed"] is True

    @pytest.mark.asyncio
    async def test_log_includes_matching_and_divergent_fields(self):
        """Log entry includes matching_fields and divergent_fields lists.

        Verifies comparison detail is captured in the log, not just the boolean.
        """
        from app.n8n.verification import log_verification_comparison
        from app.calls.models import CallAnalysis

        mock_ca = MagicMock(spec=CallAnalysis)
        mock_ca.analysis_status = "ok"
        mock_ca.summary = "Local summary"
        mock_ca.interest_level = 80
        mock_ca.next_action_suggested = "send_quote"
        mock_ca.current_insurance = "mapfre"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_ca
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.n8n.verification.logger") as mock_logger:
            await log_verification_comparison(
                session_id="sess-fields-test",
                n8n_summary="N8N summary",
                n8n_facts={
                    "interest_level": 50,  # diverges from local 80
                    "next_action_suggested": "send_quote",  # matches
                    "current_insurance": "mapfre",  # matches
                },
                db=mock_db,
            )

        assert mock_logger.info.called
        kwargs = mock_logger.info.call_args[1]
        assert kwargs["agreed"] is False
        assert "matching_fields" in kwargs
        assert "divergent_fields" in kwargs
        assert "interest_level" in kwargs["divergent_fields"]
        assert "next_action_suggested" in kwargs["matching_fields"]
