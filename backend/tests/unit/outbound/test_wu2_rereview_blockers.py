"""WU2 Re-Review Blocker Fixes — Strict TDD (RED written first).

Covers 4 remaining blockers identified in the second R1/R4 re-review of WU2:

RE1: CRITICAL reliability — /calls/{conversation_id}/end route has provider_call_id
     in EndSessionRequest schema but never actually uses it to link the outbound
     CallSession when conversation_id lookup fails.
     Fix: when close_session() raises ValueError (session not found), attempt
     link_outbound_session_by_webhook() with provider_call_id if provided.

RE2: CRITICAL risk — elevenlabs-postcall route calls link_outbound_session_by_webhook
     WITHOUT client_id, so the tenant guard added in B2 is never exercised.
     Fix: extract client_id from payload (or context) and pass it to linkage.
     When payload has no client_id, do NOT fallback without tenant scope
     (prefer no-match over cross-tenant linkage).

RE3: WARNING auth — route auth dependency is opt-in (QORA_WEBHOOK_AUTH_ENABLED
     defaults False). When ENABLE_OUTBOUND_CALLS=true, real outbound calls will
     flow but webhook endpoints remain unauthenticated unless explicitly configured.
     Fix: add a startup config guard that warns (or fails) when
     ENABLE_OUTBOUND_CALLS=true AND QORA_WEBHOOK_AUTH_ENABLED=false.
     Document in design/tasks/apply-progress.

RE4: WARNING metadata — 'message' field is in _SAFE_PROVIDER_METADATA_FIELDS but
     the provider populates it with human-readable status strings that may contain
     PII (phone numbers, names, caller info injected by SIP providers).
     Fix: remove 'message' from the allowlist; prefer not persisting free-form
     provider messages. Add test proving 'message' is dropped.

All tests written RED first. Implementation turns them GREEN.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_outbound_session(
    session_id: str = "session-outbound-re1",
    telephony_status: str = "in_call",
    client_id: str = "client-re1",
    lead_id: str = "lead-re1",
    elevenlabs_conversation_id: str | None = None,
    provider_call_id: str = "el-call-re1",
    session_end_received: bool = False,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.lead_id = lead_id
    cs.client_id = client_id
    cs.telephony_status = telephony_status
    cs.provider_call_id = provider_call_id
    cs.elevenlabs_conversation_id = elevenlabs_conversation_id
    cs.session_end_received = session_end_received
    cs.status = "completed"
    cs.duration_seconds = 120
    cs.closed_reason = "agent_goodbye"
    return cs


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# RE1: /end route must use provider_call_id for outbound fallback linkage
# ---------------------------------------------------------------------------


class TestRE1EndRouteUsesProviderCallId:
    """POST /calls/{conversation_id}/end must use provider_call_id for outbound linkage.

    The EndSessionRequest schema already has provider_call_id (added in WU2-FIX-B1).
    The route must use it when:
      1. close_session() raises ValueError (conversation_id not found in CallSession)
      2. body.provider_call_id is not None

    In this case, the route must call link_outbound_session_by_webhook() to find
    and link the outbound CallSession via provider_call_id — then return 200.
    """

    @pytest.mark.asyncio
    async def test_end_route_calls_linkage_when_session_not_found_by_conversation_id(self):
        """When /end cannot find session by conversation_id, must try provider_call_id linkage.

        GIVEN no CallSession has elevenlabs_conversation_id == 'conv-unknown'
        AND body.provider_call_id == 'el-call-re1'
        WHEN POST /calls/conv-unknown/end is called
        THEN link_outbound_session_by_webhook is called with provider_call_id='el-call-re1'
        AND close_session is called on the linked session (fully closes it)
        AND the response uses the closed session data (HTTP 200, not 404)

        Updated contract (WU2 reliability fix): the route now calls close_session()
        on the linked session to honor the full /end contract (status, ended_at,
        duration_seconds, etc.). The old behavior of returning the linked-but-not-closed
        state was the defect this fix resolves.
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        linked_cs = _make_outbound_session(
            session_id="session-re1-linked",
            telephony_status="completed",
        )

        # After the route calls close_session on the linked session, it returns
        # the fully closed state.
        closed_cs = _make_outbound_session(
            session_id="session-re1-linked",
            telephony_status="completed",
        )
        closed_cs.status = "completed"
        closed_cs.duration_seconds = 90
        closed_cs.closed_reason = "agent_goodbye"

        body = EndSessionRequest(
            reason="agent_goodbye",
            provider_call_id="el-call-re1",
        )

        mock_db = _make_db()

        # close_session is called twice:
        # 1st call: primary path → raises ValueError (session not found by conversation_id)
        # 2nd call: fallback path on linked.id → returns (closed_cs, False)
        call_count = [0]

        async def close_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("not found")
            return (closed_cs, False)

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=close_session_side_effect),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked_cs) as mock_link,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await end_call_session("conv-unknown", body)

        # Must have called linkage with provider_call_id
        mock_link.assert_called_once()
        call_kwargs = mock_link.call_args
        assert call_kwargs.kwargs.get("provider_call_id") == "el-call-re1", (
            "/end route must call link_outbound_session_by_webhook with provider_call_id. "
            f"Got kwargs: {call_kwargs.kwargs!r}"
        )

        # Response must be 200 with the CLOSED session id and state
        assert response.id == "session-re1-linked", (
            "/end route must return the linked session id. "
            f"Got: {response.id!r}"
        )
        assert response.status == "completed", (
            "/end route must return completed status from close_session. "
            f"Got: {response.status!r}"
        )

    @pytest.mark.asyncio
    async def test_end_route_returns_404_when_no_provider_call_id_and_session_not_found(self):
        """When session not found AND no provider_call_id, still returns 404.

        GIVEN no CallSession has elevenlabs_conversation_id == 'conv-unknown'
        AND body.provider_call_id is None (not provided)
        WHEN POST /calls/conv-unknown/end is called
        THEN 404 is returned (no outbound linkage attempted)
        """
        from fastapi import HTTPException

        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        body = EndSessionRequest(reason="user_hangup")  # no provider_call_id

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=ValueError("not found")),
            patch("app.calls.router.link_outbound_session_by_webhook") as mock_link,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await end_call_session("conv-unknown", body)

        assert exc_info.value.status_code == 404, (
            "/end route without provider_call_id must return 404. "
            f"Got: {exc_info.value.status_code}"
        )
        mock_link.assert_not_called(), (
            "link_outbound_session_by_webhook must NOT be called when provider_call_id is None."
        )

    @pytest.mark.asyncio
    async def test_end_route_returns_404_when_provider_call_id_linkage_fails(self):
        """When provider_call_id fallback also finds nothing, returns 404.

        GIVEN no session found by conversation_id or provider_call_id
        WHEN POST /calls/conv-unknown/end is called with provider_call_id
        THEN 404 is returned
        """
        from fastapi import HTTPException

        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        body = EndSessionRequest(
            reason="user_hangup",
            provider_call_id="el-call-notfound",
        )

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.close_session", side_effect=ValueError("not found")),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=None),
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await end_call_session("conv-unknown", body)

        assert exc_info.value.status_code == 404, (
            "/end route must return 404 when provider_call_id linkage also finds nothing. "
            f"Got: {exc_info.value.status_code}"
        )

    @pytest.mark.asyncio
    async def test_end_route_does_not_call_linkage_when_session_found_normally(self):
        """When session found by conversation_id, no outbound linkage is attempted.

        GIVEN a session IS found by elevenlabs_conversation_id
        WHEN POST /calls/{conversation_id}/end is called
        THEN link_outbound_session_by_webhook is NOT called
        """
        from app.calls.router import end_call_session
        from app.calls.schemas import EndSessionRequest

        found_cs = _make_outbound_session(session_id="sess-found")

        mock_cs = MagicMock()
        mock_cs.id = "sess-found"
        mock_cs.status = "completed"
        mock_cs.duration_seconds = 60
        mock_cs.closed_reason = "user_hangup"

        body = EndSessionRequest(
            reason="user_hangup",
            provider_call_id="el-call-re1",
        )

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=found_cs),
            patch("app.calls.router.close_session", return_value=(mock_cs, False)),
            patch("app.calls.router.link_outbound_session_by_webhook") as mock_link,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await end_call_session("conv-known", body)

        mock_link.assert_not_called(), (
            "link_outbound_session_by_webhook must NOT be called when session is found normally."
        )
        assert response.id == "sess-found"


# ---------------------------------------------------------------------------
# RE2: postcall route must pass client_id for tenant-safe linkage
# ---------------------------------------------------------------------------


class TestRE2PostcallPassesClientIdToLinkage:
    """POST /calls/elevenlabs-postcall must pass client_id to link_outbound_session_by_webhook.

    The B2 fix scoped linkage by client_id — but the postcall route does NOT pass
    client_id to link_outbound_session_by_webhook(). This means the tenant guard
    is never exercised from the real route (only from unit tests that inject it).

    Fix: extract client_id from the payload (ElevenLabsPostCallPayload) and pass
    it to link_outbound_session_by_webhook(). When payload has no client_id,
    do NOT perform the fallback (prefer safe no-match over cross-tenant linkage).
    """

    def test_postcall_payload_accepts_client_id(self):
        """ElevenLabsPostCallData (inner data) must accept an optional client_id field.

        GIVEN the ElevenLabsPostCallPayload wrapper schema with inner ElevenLabsPostCallData
        WHEN constructed with client_id='client-re2'
        THEN client_id is accessible via payload.data.client_id
        """
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-re2",
                provider_call_id="el-call-re2",
                client_id="client-re2",
            ),
        )

        assert payload.data.client_id == "client-re2", (
            "ElevenLabsPostCallData must have client_id field. "
            f"Got: {getattr(payload.data, 'client_id', 'MISSING')!r}"
        )

    def test_postcall_payload_client_id_optional(self):
        """client_id must be optional on ElevenLabsPostCallData.

        GIVEN the ElevenLabsPostCallPayload wrapper schema
        WHEN constructed WITHOUT client_id in the inner data
        THEN client_id defaults to None
        """
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(conversation_id="conv-re2"),
        )

        assert payload.data.client_id is None, (
            "ElevenLabsPostCallData.client_id must default to None. "
            f"Got: {getattr(payload.data, 'client_id', 'MISSING')!r}"
        )

    @pytest.mark.asyncio
    async def test_postcall_route_passes_client_id_to_linkage_when_present(self):
        """When payload has client_id, route must pass it to link_outbound_session_by_webhook.

        GIVEN the elevenlabs-postcall payload includes client_id='client-re2'
        AND the session is NOT found by conversation_id
        WHEN the route processes the payload
        THEN link_outbound_session_by_webhook is called with client_id='client-re2'
             AND close_session is called on the linked session (new contract: no early return)
        """
        from app.calls.router import elevenlabs_postcall_webhook
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-re2",
                provider_call_id="el-call-re2",
                client_id="client-re2",
            ),
        )

        linked_cs = _make_outbound_session(
            session_id="sess-re2-linked",
            client_id="client-re2",
        )
        # _make_outbound_session sets cs.status = "completed" (line 67).
        # The handler's "completed" branch calls get_transcript — mock it to return [].
        # Also set .client_id explicitly so _schedule_summarize has a real value.
        linked_cs.client_id = "client-re2"

        mock_closed_cs = MagicMock()
        mock_closed_cs.id = "sess-re2-linked"
        mock_closed_cs.status = "completed"

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.link_outbound_session_by_webhook", return_value=linked_cs) as mock_link,
            patch("app.calls.router.get_transcript", return_value=[]) as mock_get_transcript,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            await elevenlabs_postcall_webhook(payload)

        # Primary contract: linkage was called with the correct client_id
        mock_link.assert_called_once()
        call_kwargs = mock_link.call_args
        assert call_kwargs.kwargs.get("client_id") == "client-re2", (
            "elevenlabs-postcall route must pass client_id='client-re2' to "
            "link_outbound_session_by_webhook when payload contains client_id. "
            f"Got kwargs: {call_kwargs.kwargs!r}"
        )

        # The handler must have reached get_transcript (fell through to completed branch)
        mock_get_transcript.assert_called_once(), (
            "get_transcript must be called when linked session is already 'completed' — "
            "handler must fall through instead of returning early."
        )

    @pytest.mark.asyncio
    async def test_postcall_route_does_not_link_without_client_id(self):
        """When payload has no client_id, route must NOT attempt provider_call_id fallback.

        GIVEN the payload has NO client_id
        AND the session is NOT found by conversation_id
        AND the payload has provider_call_id
        WHEN the route processes the payload
        THEN link_outbound_session_by_webhook is NOT called (safe no-match)
        AND 404 is returned (no cross-tenant risk)

        Rationale: performing fallback without client_id scope allows cross-tenant
        session linkage — any tenant's webhook could mark another tenant's outbound
        session as completed. Prefer safe no-match.
        """
        from fastapi import HTTPException

        from app.calls.router import elevenlabs_postcall_webhook
        from app.calls.schemas import ElevenLabsPostCallData, ElevenLabsPostCallPayload

        payload = ElevenLabsPostCallPayload(
            type="post_call_transcription",
            data=ElevenLabsPostCallData(
                conversation_id="conv-no-client",
                provider_call_id="el-call-re2",
                # NO client_id
            ),
        )

        mock_db = _make_db()

        with (
            patch("app.calls.router.get_session_by_elevenlabs_id", return_value=None),
            patch("app.calls.router.link_outbound_session_by_webhook") as mock_link,
            patch("app.calls.router.db_session") as mock_db_ctx,
        ):
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await elevenlabs_postcall_webhook(payload)

        assert exc_info.value.status_code == 404, (
            "postcall route without client_id must NOT attempt provider_call_id linkage "
            "and must return 404. "
            f"Got: {exc_info.value.status_code}"
        )
        mock_link.assert_not_called(), (
            "link_outbound_session_by_webhook must NOT be called without client_id scope."
        )


# ---------------------------------------------------------------------------
# RE3: Config guard — ENABLE_OUTBOUND_CALLS=true without webhook auth is risky
# ---------------------------------------------------------------------------


class TestRE3OutboundCallsConfigGuard:
    """When ENABLE_OUTBOUND_CALLS=true, QORA_WEBHOOK_AUTH_ENABLED must be true.

    Upgraded from WARNING-level to FAIL-CLOSED: the Settings model_validator
    validate_outbound_requires_webhook_auth now raises ValueError and aborts
    startup when ENABLE_OUTBOUND_CALLS=true AND QORA_WEBHOOK_AUTH_ENABLED=false.

    The previous advisory warning was insufficient — an unauthenticated actor
    who knows the webhook URL can close outbound sessions, corrupt billing
    counters, and inject transcript turns without placing a real call.
    """

    def test_settings_raises_when_outbound_enabled_without_webhook_auth(self):
        """Settings construction must raise when outbound is enabled without webhook auth.

        GIVEN enable_outbound_calls=True AND qora_webhook_auth_enabled=False
        WHEN Settings() is constructed
        THEN ValueError is raised — startup is aborted (fail-closed).

        This replaces the old advisory WARNING: the system now refuses to start
        rather than logging a warning and continuing in a degraded-security state.
        """
        import pytest
        from pydantic import SecretStr

        from app.core.config import Settings

        with pytest.raises(ValueError, match="ENABLE_OUTBOUND_CALLS=true requires QORA_WEBHOOK_AUTH_ENABLED=true"):
            Settings(
                openai_api_key=SecretStr("test-openai-key-123456"),
                elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
                qora_api_key=SecretStr("test-admin-key"),
                enable_outbound_calls=True,
                qora_webhook_auth_enabled=False,
            )

    def test_settings_no_warning_when_both_outbound_and_auth_enabled(self):
        """No warning when both outbound and webhook auth are enabled.

        GIVEN enable_outbound_calls=True AND qora_webhook_auth_enabled=True
        THEN outbound_without_webhook_auth_warning is False
        """
        from pydantic import SecretStr

        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            enable_outbound_calls=True,
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("safe-webhook-secret-abc"),
        )

        assert settings.outbound_without_webhook_auth_warning is False, (
            "outbound_without_webhook_auth_warning must be False when "
            "both enable_outbound_calls and qora_webhook_auth_enabled are True. "
            f"Got: {settings.outbound_without_webhook_auth_warning!r}"
        )

    def test_settings_no_warning_when_outbound_disabled(self):
        """No warning when outbound calls are disabled (default state).

        GIVEN enable_outbound_calls=False (default)
        THEN outbound_without_webhook_auth_warning is False
        """
        from pydantic import SecretStr

        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("test-openai-key-123456"),
            elevenlabs_api_key=SecretStr("test-elevenlabs-key-123456"),
            qora_api_key=SecretStr("test-admin-key"),
            enable_outbound_calls=False,
            qora_webhook_auth_enabled=False,
        )

        assert settings.outbound_without_webhook_auth_warning is False, (
            "outbound_without_webhook_auth_warning must be False when "
            "enable_outbound_calls=False. "
            f"Got: {settings.outbound_without_webhook_auth_warning!r}"
        )


# ---------------------------------------------------------------------------
# RE4: 'message' must be removed from provider_metadata allowlist
# ---------------------------------------------------------------------------


class TestRE4MessageRemovedFromAllowlist:
    """'message' must NOT be in the safe provider metadata allowlist.

    The 'message' field is a free-form human-readable string that providers
    may populate with call status, error descriptions, or routing info that
    could contain PII (phone numbers, caller names, SIP addresses, etc.).

    Safe fields: call_id, status, duration_seconds, billed_duration_seconds, cost.
    NOT safe: message (free-form text from provider — PII risk).

    Spec (outbound-call-trigger — Scenario: Successful API response persisted):
      "CallSession.provider_metadata stores only safe/allowlisted provider fields
       (permitted: call_id, status, duration_seconds, billed_duration_seconds, cost;
        all other fields including PII and routing data are dropped)"
    NOTE: 'message' was in the spec allowlist but should be removed.
    """

    def test_message_field_is_dropped_from_provider_metadata(self):
        """'message' field must be stripped by _extract_safe_provider_metadata.

        GIVEN a raw provider API response with 'message' field
        WHEN _extract_safe_provider_metadata() is called
        THEN the 'message' field is NOT in the result
        """
        from app.outbound.service import _extract_safe_provider_metadata

        raw = {
            "call_id": "el-call-abc",
            "status": "initiated",
            "duration_seconds": 120,
            "billed_duration_seconds": 2,
            "cost": 0.007,
            "message": "Call to +15551234567 completed. Agent: Sofia. Session xyz123.",  # PII risk
        }

        result = _extract_safe_provider_metadata(raw)

        assert "message" not in result, (
            "'message' must be dropped from provider_metadata to prevent PII persistence. "
            f"Got result keys: {list(result.keys())!r}"
        )

    def test_safe_fields_still_persisted_without_message(self):
        """Safe fields (call_id, status, cost, etc.) must still be persisted.

        GIVEN a raw provider API response with both safe and unsafe fields
        WHEN _extract_safe_provider_metadata() is called
        THEN safe fields (call_id, status, duration_seconds, billed_duration_seconds, cost) are present
        AND 'message' is absent
        """
        from app.outbound.service import _extract_safe_provider_metadata

        raw = {
            "call_id": "el-call-safe-test",
            "status": "initiated",
            "duration_seconds": 90,
            "billed_duration_seconds": 2,
            "cost": 0.007,
            "message": "Call completed to +15551234567",  # must be dropped
            "sip_uri": "sip:+15551234567@carrier.com",   # must also be dropped (not in allowlist)
        }

        result = _extract_safe_provider_metadata(raw)

        assert result["call_id"] == "el-call-safe-test"
        assert result["status"] == "initiated"
        assert result["duration_seconds"] == 90
        assert result["billed_duration_seconds"] == 2
        assert result["cost"] == 0.007
        assert "message" not in result, (
            "'message' must be absent from safe provider metadata."
        )
        assert "sip_uri" not in result, (
            "'sip_uri' must be absent (not in allowlist)."
        )

    def test_allowlist_does_not_contain_message(self):
        """_SAFE_PROVIDER_METADATA_FIELDS must not contain 'message'.

        Direct inspection of the allowlist constant.
        """
        from app.outbound.service import _SAFE_PROVIDER_METADATA_FIELDS

        assert "message" not in _SAFE_PROVIDER_METADATA_FIELDS, (
            "'message' must be removed from _SAFE_PROVIDER_METADATA_FIELDS. "
            f"Current allowlist: {sorted(_SAFE_PROVIDER_METADATA_FIELDS)!r}"
        )

    def test_payload_with_only_message_returns_empty_dict(self):
        """If the only field is 'message', result must be empty dict (not None).

        GIVEN raw = {'message': 'some provider text'}
        WHEN _extract_safe_provider_metadata() is called
        THEN result is {} (empty — no safe fields present, but raw was non-empty)
        """
        from app.outbound.service import _extract_safe_provider_metadata

        raw = {"message": "Call completed normally"}

        result = _extract_safe_provider_metadata(raw)

        assert result == {}, (
            "If only 'message' is present, result must be empty dict. "
            f"Got: {result!r}"
        )
        assert result is not None, (
            "Result must be {} (not None) when raw dict was non-empty (even if all fields stripped)."
        )
