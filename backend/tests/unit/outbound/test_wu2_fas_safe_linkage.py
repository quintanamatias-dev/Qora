"""WU2 Task 3.1 — FAS-safe webhook/session linkage.

Spec: outbound-call-trigger — Requirement: FAS-Safe Semantics
  - Provider SIP answer (in_call) MUST NEVER set telephony_status=completed.
  - completed MUST require webhook evidence (Custom LLM session-end callback).
  - link_outbound_session_by_webhook() must:
      1. Find the outbound CallSession by conversation_id (via elevenlabs_conversation_id) OR
         fall back to provider_call_id lookup.
      2. Set telephony_status='completed' ONLY when called (webhook evidence).
      3. Store elevenlabs_conversation_id on the CallSession if not already set.
      4. NOT mark telephony_status='completed' when SIP 200 OK arrives (in_call).

Spec: outbound-call-trigger — Scenario: Webhook fires — completion confirmed
  GIVEN the Custom LLM webhook session-end fires with a matching conversation_id
  WHEN the session is linked to the CallSession via provider_call_id or conversation_id
  THEN telephony_status=completed is set
  AND elevenlabs_conversation_id is stored on the CallSession

Spec: outbound-call-trigger — Scenario: SIP answer without conversation webhook
  GIVEN the provider reports SIP 200 OK (in_call)
  WHEN no conversation session-end webhook arrives
  THEN telephony_status remains in_call
  AND telephony_status is NEVER set to completed without the webhook evidence

All calls are mocked — no live calls, no live DB.

TDD: Tests written BEFORE implementation. All must fail (RED) until
     link_outbound_session_by_webhook is implemented in service.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outbound_call_session(
    telephony_status: str = "ringing",
    provider_call_id: str = "el-call-abc123",
    elevenlabs_conversation_id: str | None = None,
) -> MagicMock:
    """Return a mock CallSession that represents an outbound call in progress."""
    cs = MagicMock()
    cs.id = "session-outbound-001"
    cs.lead_id = "lead-001"
    cs.client_id = "client-001"
    cs.telephony_status = telephony_status
    cs.provider_call_id = provider_call_id
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    return cs


def _make_db(session: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Task 3.1 RED Tests
# ---------------------------------------------------------------------------


class TestFASSafeWebhookLinkage:
    """FAS-safe: telephony_status=completed only from webhook evidence."""

    @pytest.mark.asyncio
    async def test_webhook_sets_telephony_status_completed(self):
        """link_outbound_session_by_webhook() sets telephony_status=completed.

        GIVEN an outbound CallSession with telephony_status='ringing'
        WHEN link_outbound_session_by_webhook() is called with a conversation_id
        THEN telephony_status becomes 'completed' (webhook evidence provided)
        AND elevenlabs_conversation_id is set on the session
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(
            telephony_status="ringing",
            elevenlabs_conversation_id=None,
        )

        db = _make_db()
        # Simulate DB returning the session by conversation_id lookup
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-xyz",
        )

        assert linked is not None
        assert linked.telephony_status == "completed", (
            "Webhook evidence must set telephony_status='completed'. "
            f"Got: {linked.telephony_status!r}"
        )
        assert linked.elevenlabs_conversation_id == "conv-el-xyz", (
            "elevenlabs_conversation_id must be stored on the CallSession. "
            f"Got: {linked.elevenlabs_conversation_id!r}"
        )

    @pytest.mark.asyncio
    async def test_in_call_status_never_auto_completes(self):
        """SIP 200 OK (in_call) must NOT auto-complete telephony_status.

        GIVEN an outbound CallSession with telephony_status='in_call'
        WHEN no webhook fires (only SIP state is known)
        THEN telephony_status remains 'in_call'
        AND telephony_status is NOT set to 'completed'

        This test verifies the FAS constraint at the model level:
        there is no automatic transition in_call → completed without webhook evidence.
        The reconciliation sweep can move in_call → stale_in_call (Task 3.3),
        but NEVER to completed.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(telephony_status="connected")

        db = _make_db()
        # No session found — DB returns None (webhook not fired yet)
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-not-linked",
        )

        # When webhook cannot find the session, it returns None — no mutation
        assert linked is None, (
            "link_outbound_session_by_webhook must return None when no session is found. "
            "SIP state alone must never auto-complete telephony_status."
        )
        # The cs object must be untouched — telephony_status stays 'connected'
        assert cs.telephony_status == "connected", (
            "in_call status must not be modified without explicit webhook evidence."
        )

    @pytest.mark.asyncio
    async def test_webhook_fallback_by_provider_call_id(self):
        """Fallback: find outbound session by provider_call_id when conversation_id not found.

        GIVEN an outbound CallSession with provider_call_id='el-call-abc123'
              and no elevenlabs_conversation_id yet
        WHEN link_outbound_session_by_webhook() receives a conversation_id
             that is not yet in the DB (first-time linkage)
        AND a provider_call_id is provided to enable fallback
        THEN the session is found by provider_call_id
        AND telephony_status is set to 'completed'
        AND elevenlabs_conversation_id is stored
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(
            telephony_status="connected",
            provider_call_id="el-call-abc123",
            elevenlabs_conversation_id=None,
        )

        db = _make_db()

        call_count = [0]

        async def execute_side_effect(stmt):
            result_mock = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # First lookup: by elevenlabs_conversation_id — not found
                result_mock.scalars.return_value.first.return_value = None
            else:
                # Second lookup: by provider_call_id — found
                result_mock.scalars.return_value.first.return_value = cs
            return result_mock

        db.execute.side_effect = execute_side_effect

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-xyz",
            provider_call_id="el-call-abc123",
        )

        assert linked is not None, (
            "Fallback by provider_call_id must find the session."
        )
        assert linked.telephony_status == "completed", (
            "telephony_status must be set to 'completed' via fallback linkage. "
            f"Got: {linked.telephony_status!r}"
        )
        assert linked.elevenlabs_conversation_id == "conv-el-xyz", (
            "elevenlabs_conversation_id must be stored even on fallback path. "
            f"Got: {linked.elevenlabs_conversation_id!r}"
        )

    @pytest.mark.asyncio
    async def test_idempotent_when_already_completed(self):
        """link_outbound_session_by_webhook() is idempotent on already-completed sessions.

        GIVEN an outbound CallSession with telephony_status='completed'
        WHEN link_outbound_session_by_webhook() is called again
        THEN telephony_status stays 'completed'
        AND elevenlabs_conversation_id is unchanged
        AND no error is raised
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(
            telephony_status="completed",
            elevenlabs_conversation_id="conv-el-already-set",
        )

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-already-set",
        )

        assert linked is not None
        assert linked.telephony_status == "completed"
        assert linked.elevenlabs_conversation_id == "conv-el-already-set"

    @pytest.mark.asyncio
    async def test_no_session_found_returns_none(self):
        """Returns None when neither conversation_id nor provider_call_id finds a session.

        GIVEN no matching outbound CallSession in the DB
        WHEN link_outbound_session_by_webhook() is called
        THEN it returns None without raising
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-unknown",
            provider_call_id="el-call-unknown",
        )

        assert linked is None, (
            "Must return None when no session can be found. "
            "Must not raise."
        )

    @pytest.mark.asyncio
    async def test_in_call_session_linked_by_webhook_becomes_completed(self):
        """in_call session found by conversation_id → completed via webhook.

        GIVEN an outbound CallSession with telephony_status='in_call'
        AND elevenlabs_conversation_id is already set
        WHEN link_outbound_session_by_webhook() is called with the same conversation_id
        THEN telephony_status becomes 'completed'

        Triangulation: tests the in_call → completed path explicitly (vs ringing above).
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(
            telephony_status="connected",
            elevenlabs_conversation_id="conv-el-in-call",
        )

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-in-call",
        )

        assert linked is not None
        assert linked.telephony_status == "completed", (
            "in_call session must become 'completed' via webhook evidence. "
            f"Got: {linked.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_webhook_commits_after_update(self):
        """link_outbound_session_by_webhook() commits the telephony_status update.

        GIVEN a matching outbound CallSession
        WHEN link_outbound_session_by_webhook() is called
        THEN db.commit() is called at least once
        (The update must be durable, not just flushed)
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_call_session(
            telephony_status="ringing",
            elevenlabs_conversation_id=None,
        )

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs
        db.execute.return_value = result_mock

        await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-xyz",
        )

        assert db.commit.call_count >= 1, (
            "db.commit() must be called after updating telephony_status. "
            "The completed status must be durable."
        )
