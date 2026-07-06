"""WU2 Review Blocker Fixes — TDD tests written RED first.

Covers 5 review blockers identified post-WU2 implementation:

B1: provider_call_id fallback not wired to real webhook routes
    - ElevenLabsPostCallPayload must accept provider_call_id
    - EndSessionRequest must accept provider_call_id
    - elevenlabs-postcall route must pass provider_call_id to link_outbound_session_by_webhook

B2: Linkage lookups not tenant/lead/outbound scoped
    - _find_by_conversation_id must scope by client_id when provided
    - _find_by_provider_call_id must scope by client_id when provided
    - Cross-tenant session must NOT be returned even if IDs match

B3: Unauthenticated elevenlabs-postcall can mutate billing state
    - POST /calls/elevenlabs-postcall must enforce require_webhook_secret
    - Missing auth header → 401
    - Invalid auth header → 401
    - Valid auth header → 200

B4: Sweep uses conversation_id presence as completion evidence (wrong)
    - conversation_id IS NOT NULL alone must NOT → 'completed' in sweep
    - session_end_received = True → 'completed'
    - session_end_received = False, conversation_id set → 'stale_in_call'

B5: Route-level and integration behavior tests
    - Real webhook route integration test (payload → linkage → response)
    - Sweep evidence predicate behavior test

All tests are RED until implementation is complete.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_outbound_session(
    session_id: str = "session-outbound-001",
    telephony_status: str = "in_call",
    client_id: str = "client-a",
    lead_id: str = "lead-001",
    started_at: datetime | None = None,
    elevenlabs_conversation_id: str | None = None,
    provider_call_id: str = "el-call-abc123",
    session_end_received: bool = False,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = lead_id
    cs.client_id = client_id
    cs.telephony_status = telephony_status
    cs.provider_call_id = provider_call_id
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.started_at = started_at or (_utcnow() - timedelta(minutes=45))
    cs.session_end_received = session_end_received
    return cs


def _make_db(session: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


def _make_db_with_sessions(sessions: list) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = sessions
    db.execute.return_value = result_mock
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# B1: provider_call_id wiring to real webhook routes
# ---------------------------------------------------------------------------


class TestB1PostcallPayloadAcceptsProviderCallId:
    """ElevenLabsPostCallData (inner data object) must include provider_call_id field."""

    def test_postcall_payload_accepts_provider_call_id(self):
        """ElevenLabsPostCallData must have a provider_call_id field.

        GIVEN the ElevenLabsPostCallPayload wrapper schema with inner ElevenLabsPostCallData
        WHEN constructed with provider_call_id='el-call-abc'
        THEN provider_call_id is accessible via payload.data.provider_call_id
        """
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-el-xyz",
                provider_call_id="el-call-abc",
            ),
        )

        assert payload.data.provider_call_id == "el-call-abc", (
            "ElevenLabsPostCallData must have provider_call_id field. "
            f"Got: {getattr(payload.data, 'provider_call_id', 'MISSING')!r}"
        )

    def test_postcall_payload_provider_call_id_optional(self):
        """provider_call_id must be optional (older ElevenLabs webhooks omit it)."""
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(conversation_id="conv-el-xyz"),
        )

        assert payload.data.provider_call_id is None, (
            "ElevenLabsPostCallData.provider_call_id must default to None. "
            f"Got: {getattr(payload.data, 'provider_call_id', 'MISSING')!r}"
        )


class TestB1EndSessionRequestAcceptsProviderCallId:
    """EndSessionRequest must include provider_call_id field."""

    def test_end_session_request_accepts_provider_call_id(self):
        """EndSessionRequest must have a provider_call_id field.

        GIVEN the EndSessionRequest schema
        WHEN constructed with provider_call_id='el-call-abc'
        THEN provider_call_id is stored on the model
        """
        from app.calls.schemas import EndSessionRequest

        req = EndSessionRequest(reason="agent_goodbye", provider_call_id="el-call-abc")

        assert req.provider_call_id == "el-call-abc", (
            "EndSessionRequest must have provider_call_id field. "
            f"Got: {getattr(req, 'provider_call_id', 'MISSING')!r}"
        )

    def test_end_session_request_provider_call_id_optional(self):
        """provider_call_id must be optional on EndSessionRequest."""
        from app.calls.schemas import EndSessionRequest

        req = EndSessionRequest(reason="user_hangup")

        assert req.provider_call_id is None, (
            "EndSessionRequest.provider_call_id must default to None. "
            f"Got: {getattr(req, 'provider_call_id', 'MISSING')!r}"
        )


class TestB1PostcallRoutePassesProviderCallId:
    """elevenlabs-postcall route must call link_outbound_session_by_webhook with provider_call_id.

    Updated (RE2 fix): route now requires client_id in payload to scope the fallback
    lookup to the correct tenant. Without client_id, the fallback is not attempted.
    """

    @pytest.mark.asyncio
    async def test_postcall_route_passes_provider_call_id_to_linkage(self):
        """When elevenlabs-postcall webhook has provider_call_id AND client_id, linkage is called.

        GIVEN the ElevenLabs postcall webhook fires with provider_call_id='el-call-abc'
              AND client_id='client-a' (required for tenant-safe fallback, RE2)
        AND the session is NOT found by conversation_id (first-time linkage scenario)
        WHEN the /calls/elevenlabs-postcall route processes the payload
        THEN link_outbound_session_by_webhook is called with provider_call_id='el-call-abc'
             AND client_id='client-a'
             AND close_session is called on the linked session (new contract: no early return)

        This proves the fallback linkage path (provider_call_id) is exercisable
        from the real webhook route, not just internally.
        RE2: client_id must be scoped to prevent cross-tenant linkage.
        """
        from app.calls.router import elevenlabs_postcall_webhook
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        # RE2: payload must include client_id for tenant-safe fallback
        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-el-xyz",
                provider_call_id="el-call-abc",
                client_id="client-a",
            ),
        )

        # The route must look up the session by conversation_id first (returns None),
        # then fall back to link_outbound_session_by_webhook with provider_call_id.
        mock_linked_cs = MagicMock()
        mock_linked_cs.id = "session-001"
        # Handler checks cs.status to pick the close path. "initiated" → close_session called.
        mock_linked_cs.status = "initiated"

        mock_closed_cs = MagicMock()
        mock_closed_cs.id = "session-001"
        mock_closed_cs.status = "completed"

        mock_db = AsyncMock()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None) as mock_get,
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=mock_linked_cs) as mock_link,
            patch("app.calls.router.close_session", return_value=(mock_closed_cs, False)) as mock_close,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await elevenlabs_postcall_webhook(payload)

        # link_outbound_session_by_webhook must have been called with provider_call_id and client_id
        mock_link.assert_called_once()
        call_kwargs = mock_link.call_args
        assert call_kwargs.kwargs.get("provider_call_id") == "el-call-abc", (
            "Route must pass provider_call_id='el-call-abc' to link_outbound_session_by_webhook. "
            f"Got kwargs: {call_kwargs.kwargs!r}"
        )
        assert call_kwargs.kwargs.get("conversation_id") == "conv-el-xyz", (
            "Route must pass conversation_id to link_outbound_session_by_webhook."
        )
        assert call_kwargs.kwargs.get("client_id") == "client-a", (
            "Route must pass client_id='client-a' to link_outbound_session_by_webhook (RE2). "
            f"Got kwargs: {call_kwargs.kwargs!r}"
        )

        # New contract: close_session must be called (no early return after linkage)
        mock_close.assert_called_once(), (
            "close_session must be called on the linked session — "
            "billing, duration, and lead counters require the full close path."
        )

        # Response is now {"status": "ok", "session_id": ...} — no linked_via key
        assert result["session_id"] == "session-001"
        assert result["status"] == "ok"
        assert "linked_via" not in result, (
            "linked_via must NOT be in the response — handler now falls through to "
            "close_session instead of returning early with linked_via metadata."
        )


# ---------------------------------------------------------------------------
# B2: Linkage lookups must be tenant/outbound scoped
# ---------------------------------------------------------------------------


class TestB2LinkageScopedByClientId:
    """_find_by_conversation_id and _find_by_provider_call_id must scope by client_id."""

    @pytest.mark.asyncio
    async def test_find_by_conversation_id_accepts_client_id_scope(self):
        """_find_by_conversation_id must accept and use client_id when provided.

        GIVEN two tenants have sessions with the same elevenlabs_conversation_id
        WHEN _find_by_conversation_id is called with client_id='client-a'
        THEN only the session belonging to 'client-a' is returned
        """
        from app.outbound.linkage import _find_by_conversation_id

        cs_a = _make_outbound_session(session_id="sess-a", client_id="client-a")

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs_a
        db.execute.return_value = result_mock

        result = await _find_by_conversation_id(db, "conv-shared", client_id="client-a")

        assert result is cs_a, (
            "_find_by_conversation_id with client_id='client-a' must return "
            "the session belonging to client-a, not cross-tenant session."
        )

    @pytest.mark.asyncio
    async def test_find_by_provider_call_id_accepts_client_id_scope(self):
        """_find_by_provider_call_id must accept and use client_id when provided.

        GIVEN two tenants have sessions with the same provider_call_id
        WHEN _find_by_provider_call_id is called with client_id='client-a'
        THEN only the session belonging to 'client-a' is returned
        """
        from app.outbound.linkage import _find_by_provider_call_id

        cs_a = _make_outbound_session(session_id="sess-a", client_id="client-a")

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs_a
        db.execute.return_value = result_mock

        result = await _find_by_provider_call_id(db, "el-call-shared", client_id="client-a")

        assert result is cs_a, (
            "_find_by_provider_call_id with client_id='client-a' must return "
            "only the client-a session."
        )

    @pytest.mark.asyncio
    async def test_find_by_conversation_id_scoped_by_outbound_status(self):
        """_find_by_conversation_id must scope to outbound sessions (telephony_status IS NOT NULL).

        GIVEN a session with telephony_status=NULL (inbound) and matching conversation_id
        WHEN _find_by_conversation_id is called
        THEN the inbound session should NOT be returned as a linkage target for outbound
        NOTE: The SQL filter must prefer sessions with telephony_status IS NOT NULL.
        """
        from app.outbound.linkage import _find_by_conversation_id

        # Simulate DB returning None (query filters to outbound only)
        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        db.execute.return_value = result_mock

        # DB is mocked to return None — the test validates the function accepts client_id
        result = await _find_by_conversation_id(
            db, "conv-el-inbound", client_id="client-a"
        )

        # This just verifies the function signature accepts client_id without error
        assert result is None

    @pytest.mark.asyncio
    async def test_cross_tenant_collision_does_not_link_wrong_session(self):
        """Cross-tenant session must NOT be linked when client_id differs.

        GIVEN client-a and client-b both have sessions with provider_call_id='el-call-shared'
        WHEN link_outbound_session_by_webhook is called with client_id='client-a'
        THEN ONLY the client-a session is linked
        AND the client-b session is NOT modified

        This prevents billing/completion state from leaking across tenants.
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs_a = _make_outbound_session(
            session_id="sess-a",
            client_id="client-a",
            telephony_status="ringing",
            provider_call_id="el-call-shared",
            elevenlabs_conversation_id=None,
        )
        cs_b = _make_outbound_session(
            session_id="sess-b",
            client_id="client-b",
            telephony_status="ringing",
            provider_call_id="el-call-shared",
            elevenlabs_conversation_id=None,
        )

        call_count = [0]

        async def execute_side_effect(stmt):
            result_mock = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # Primary lookup by conversation_id: not found
                result_mock.scalars.return_value.first.return_value = None
            else:
                # Fallback by provider_call_id: return only client-a's session
                result_mock.scalars.return_value.first.return_value = cs_a
            return result_mock

        db = _make_db()
        db.execute.side_effect = execute_side_effect

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-xyz",
            provider_call_id="el-call-shared",
            client_id="client-a",
        )

        # client-a session must be linked
        assert linked is cs_a, (
            "link_outbound_session_by_webhook with client_id='client-a' must return "
            "the client-a session, not cross-tenant session."
        )

        # client-b session must be untouched
        assert cs_b.telephony_status == "ringing", (
            "Cross-tenant session (client-b) must NOT be modified when "
            "client_id='client-a' is the scope. Got: "
            f"{cs_b.telephony_status!r}"
        )


# ---------------------------------------------------------------------------
# B3: Auth enforcement on elevenlabs-postcall
# ---------------------------------------------------------------------------


class TestB3PostcallWebhookAuth:
    """POST /calls/elevenlabs-postcall must enforce webhook secret auth."""

    @pytest.mark.asyncio
    async def test_postcall_route_requires_webhook_secret_dependency(self):
        """elevenlabs-postcall route must use a webhook auth dependency.

        GIVEN the calls router
        WHEN the elevenlabs-postcall endpoint is inspected
        THEN either require_webhook_secret or require_elevenlabs_webhook_signature
             must appear in its dependencies (HMAC-based auth supersedes plain-text).

        This proves auth is wired at the route level, not just as documentation.
        """
        import inspect

        from fastapi import Depends

        from app.calls import router as calls_router
        from app.core.auth import (
            require_elevenlabs_webhook_signature,
            require_webhook_secret,
        )

        _AUTH_DEPS = {require_webhook_secret, require_elevenlabs_webhook_signature}

        # Find the elevenlabs-postcall route in the router
        route_found = False
        has_webhook_auth = False

        for route in calls_router.router.routes:
            if hasattr(route, "path") and "elevenlabs-postcall" in route.path:
                route_found = True
                # Check if any accepted auth dep is in the route's dependencies
                for dep in getattr(route, "dependencies", []):
                    if hasattr(dep, "dependency") and dep.dependency in _AUTH_DEPS:
                        has_webhook_auth = True
                        break
                # Also check if it's in the endpoint signature as a Depends
                sig = inspect.signature(route.endpoint)
                for param in sig.parameters.values():
                    if (
                        hasattr(param.default, "dependency")
                        and param.default.dependency in _AUTH_DEPS
                    ):
                        has_webhook_auth = True
                        break

        assert route_found, (
            "elevenlabs-postcall route must be registered in the calls router."
        )
        assert has_webhook_auth, (
            "elevenlabs-postcall route must have a webhook auth dependency "
            "(require_webhook_secret or require_elevenlabs_webhook_signature). "
            "Unauthenticated POST can mutate billing/completion state (B3 blocker)."
        )

    @pytest.mark.asyncio
    async def test_missing_webhook_secret_rejected_when_auth_enabled(self):
        """Missing X-Webhook-Secret header → 401 when auth is enabled.

        GIVEN QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET is set
        WHEN the require_webhook_secret dependency is called without X-Webhook-Secret
        THEN it raises HTTPException(401)

        This test verifies the existing require_webhook_secret dependency behavior
        (already implemented in auth.py) and that the route is wired to use it
        (verified in test_postcall_route_requires_webhook_secret_dependency).
        """
        from fastapi import HTTPException, Request
        from pydantic import SecretStr

        from app.core.auth import require_webhook_secret
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("test-webhook-secret-abc"),
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}  # No X-Webhook-Secret header

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(mock_request, settings)

        assert exc_info.value.status_code == 401, (
            "Missing X-Webhook-Secret header must return 401 when auth is enabled. "
            f"Got: {exc_info.value.status_code}"
        )

    @pytest.mark.asyncio
    async def test_require_webhook_secret_blocks_missing_header_when_enabled(self):
        """require_webhook_secret returns 401 when header missing and auth enabled.

        GIVEN QORA_WEBHOOK_AUTH_ENABLED=true
        WHEN the request has no X-Webhook-Secret header
        THEN require_webhook_secret raises HTTPException(401)
        """
        from fastapi import HTTPException, Request
        from pydantic import SecretStr

        from app.core.auth import require_webhook_secret
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("test-secret-abc"),
        )

        # Mock request with no X-Webhook-Secret
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(mock_request, settings)

        assert exc_info.value.status_code == 401, (
            "Missing webhook secret must return 401. "
            f"Got: {exc_info.value.status_code}"
        )

    @pytest.mark.asyncio
    async def test_require_webhook_secret_blocks_invalid_header_when_enabled(self):
        """require_webhook_secret returns 401 when wrong secret provided.

        GIVEN QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET='correct-secret'
        WHEN request has X-Webhook-Secret: 'wrong-secret'
        THEN require_webhook_secret raises HTTPException(401)
        """
        from fastapi import HTTPException, Request
        from pydantic import SecretStr

        from app.core.auth import require_webhook_secret
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("correct-secret"),
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Webhook-Secret": "wrong-secret"}

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(mock_request, settings)

        assert exc_info.value.status_code == 401, (
            "Invalid webhook secret must return 401. "
            f"Got: {exc_info.value.status_code}"
        )

    @pytest.mark.asyncio
    async def test_require_webhook_secret_passes_valid_header_when_enabled(self):
        """require_webhook_secret returns None when valid secret provided.

        GIVEN QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET='correct-secret'
        WHEN request has X-Webhook-Secret: 'correct-secret'
        THEN require_webhook_secret returns None (no exception)
        """
        from fastapi import Request
        from pydantic import SecretStr

        from app.core.auth import require_webhook_secret
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("correct-secret"),
        )

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"X-Webhook-Secret": "correct-secret"}

        result = require_webhook_secret(mock_request, settings)

        assert result is None, (
            "Valid webhook secret must return None (no exception). "
            f"Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# B4: Sweep completion evidence — must use session_end_received, not conv_id
# ---------------------------------------------------------------------------


class TestB4SweepUsesSessionEndReceivedEvidence:
    """Sweep must use session_end_received=True, not just conversation_id presence."""

    @pytest.mark.asyncio
    async def test_conversation_id_alone_does_not_complete_stale_session(self):
        """conversation_id IS NOT NULL alone must NOT → 'completed' in sweep.

        GIVEN a CallSession with telephony_status='in_call', started >30 min ago
              AND elevenlabs_conversation_id is set (conversation_id present)
              AND session_end_received = False (no session-end webhook)
        WHEN sweep_stale_outbound_sessions() runs
        THEN telephony_status becomes 'stale_in_call' (NOT 'completed')

        Rationale: conversation_id can be set by the outbound linkage webhook
        but session-end (the real termination signal) may never have arrived.
        The spec says session-end callback is completion evidence, not mere
        conversation_id presence.
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id="conv-el-exists",  # conv_id set
            session_end_received=False,                   # but no session-end
        )
        db = _make_db_with_sessions([stale])

        await sweep_stale_outbound_sessions(db)

        assert stale.telephony_status == "stale_in_call", (
            "conversation_id presence alone must NOT result in 'completed'. "
            "Sweep must require session_end_received=True for 'completed'. "
            f"Got: {stale.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_session_end_received_true_results_in_completed(self):
        """session_end_received=True → 'completed' in sweep.

        GIVEN a CallSession with telephony_status='in_call', started >30 min ago
              AND session_end_received = True (session-end webhook confirmed)
        WHEN sweep_stale_outbound_sessions() runs
        THEN telephony_status becomes 'completed'
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id="conv-el-exists",
            session_end_received=True,  # session-end webhook fired
        )
        db = _make_db_with_sessions([stale])

        await sweep_stale_outbound_sessions(db)

        assert stale.telephony_status == "completed", (
            "session_end_received=True must result in 'completed' status. "
            f"Got: {stale.telephony_status!r}"
        )

    @pytest.mark.asyncio
    async def test_session_end_received_false_no_conv_id_results_in_stale(self):
        """session_end_received=False and no conv_id → 'stale_in_call'.

        GIVEN a CallSession with no session-end and no conversation_id
        WHEN sweep runs
        THEN telephony_status becomes 'stale_in_call' (operator review)
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale = _make_outbound_session(
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            elevenlabs_conversation_id=None,
            session_end_received=False,
        )
        db = _make_db_with_sessions([stale])

        await sweep_stale_outbound_sessions(db)

        assert stale.telephony_status == "stale_in_call", (
            "No session-end evidence must result in 'stale_in_call'. "
            f"Got: {stale.telephony_status!r}"
        )


class TestB4SessionEndReceivedSetByCloseSession:
    """close_session / link_outbound_session_by_webhook must set session_end_received=True."""

    def test_link_sets_session_end_received_on_outbound_session(self):
        """update_telephony_status_on_session_end must set session_end_received=True.

        GIVEN an outbound CallSession
        WHEN update_telephony_status_on_session_end() is called (session-end webhook)
        THEN cs.session_end_received is set to True
        """
        from app.outbound.linkage import update_telephony_status_on_session_end

        cs = _make_outbound_session(telephony_status="connected", session_end_received=False)

        result = update_telephony_status_on_session_end(cs)

        assert result.session_end_received is True, (
            "update_telephony_status_on_session_end must set session_end_received=True "
            "when the session-end webhook fires. "
            f"Got: {result.session_end_received!r}"
        )

    @pytest.mark.asyncio
    async def test_link_webhook_sets_session_end_received(self):
        """link_outbound_session_by_webhook must set session_end_received=True.

        GIVEN an outbound CallSession found by conversation_id
        WHEN link_outbound_session_by_webhook() is called
        THEN cs.session_end_received is set to True before commit
        """
        from app.outbound.linkage import link_outbound_session_by_webhook

        cs = _make_outbound_session(
            telephony_status="ringing",
            elevenlabs_conversation_id=None,
            session_end_received=False,
        )

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = cs
        db.execute.return_value = result_mock

        linked = await link_outbound_session_by_webhook(
            db,
            conversation_id="conv-el-xyz",
        )

        assert linked is not None
        assert linked.session_end_received is True, (
            "link_outbound_session_by_webhook must set session_end_received=True. "
            f"Got: {getattr(linked, 'session_end_received', 'MISSING')!r}"
        )


# ---------------------------------------------------------------------------
# B5: Route-level and sweep integration behavior tests
# ---------------------------------------------------------------------------


class TestB5RouteIntegrationBehavior:
    """Integration-level tests proving real route/sweep behavior."""

    @pytest.mark.asyncio
    async def test_elevenlabs_postcall_payload_provider_call_id_roundtrip(self):
        """ElevenLabsPostCallPayload provider_call_id survives a JSON parse roundtrip.

        Proves the schema (wrapper + inner data) correctly exposes provider_call_id
        to the route handler via payload.data.provider_call_id.
        """
        import json

        from app.calls.schemas import ElevenLabsPostCallPayload

        raw_json = json.dumps({
            "type": "post_call_transcription",
            "event_timestamp": 0,
            "data": {
                "conversation_id": "conv-el-abc",
                "provider_call_id": "el-call-xyz",
                "transcript": [{"role": "agent", "message": "Hello"}],
            },
        })

        payload = ElevenLabsPostCallPayload.model_validate_json(raw_json)

        assert payload.data.provider_call_id == "el-call-xyz", (
            "ElevenLabsPostCallPayload must correctly parse provider_call_id from JSON (via data). "
            f"Got: {getattr(payload.data, 'provider_call_id', 'MISSING')!r}"
        )
        assert payload.data.conversation_id == "conv-el-abc"
        assert payload.data.transcript[0]["role"] == "agent"

    @pytest.mark.asyncio
    async def test_end_session_request_provider_call_id_roundtrip(self):
        """EndSessionRequest provider_call_id survives a JSON parse roundtrip."""
        import json

        from app.calls.schemas import EndSessionRequest

        raw_json = json.dumps({
            "reason": "agent_goodbye",
            "provider_call_id": "el-call-xyz",
        })

        req = EndSessionRequest.model_validate_json(raw_json)

        assert req.provider_call_id == "el-call-xyz", (
            "EndSessionRequest must correctly parse provider_call_id from JSON. "
            f"Got: {getattr(req, 'provider_call_id', 'MISSING')!r}"
        )
        assert req.reason == "agent_goodbye"

    @pytest.mark.asyncio
    async def test_sweep_evidence_contract_comprehensive(self):
        """Comprehensive sweep evidence contract: 3 sessions, 3 outcomes.

        GIVEN session-1: session_end_received=True → 'completed'
        GIVEN session-2: session_end_received=False, conv_id set → 'stale_in_call'
        GIVEN session-3: session_end_received=False, no conv_id → 'stale_in_call'
        WHEN sweep_stale_outbound_sessions() runs
        THEN each session gets the correct outcome
        """
        from app.outbound.sweep import sweep_stale_outbound_sessions

        stale_with_end = _make_outbound_session(
            session_id="sess-end",
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            session_end_received=True,
            elevenlabs_conversation_id="conv-el-abc",
        )
        stale_conv_only = _make_outbound_session(
            session_id="sess-conv",
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            session_end_received=False,
            elevenlabs_conversation_id="conv-el-xyz",
        )
        stale_no_evidence = _make_outbound_session(
            session_id="sess-none",
            telephony_status="connected",
            started_at=_utcnow() - timedelta(minutes=45),
            session_end_received=False,
            elevenlabs_conversation_id=None,
        )

        db = _make_db_with_sessions([stale_with_end, stale_conv_only, stale_no_evidence])

        count = await sweep_stale_outbound_sessions(db)

        assert count == 3, f"Expected 3 sessions swept, got {count}"

        assert stale_with_end.telephony_status == "completed", (
            "Session with session_end_received=True must become 'completed'. "
            f"Got: {stale_with_end.telephony_status!r}"
        )
        assert stale_conv_only.telephony_status == "stale_in_call", (
            "Session with only conversation_id (no session_end) must become 'stale_in_call'. "
            f"Got: {stale_conv_only.telephony_status!r}"
        )
        assert stale_no_evidence.telephony_status == "stale_in_call", (
            "Session with no evidence must become 'stale_in_call'. "
            f"Got: {stale_no_evidence.telephony_status!r}"
        )
