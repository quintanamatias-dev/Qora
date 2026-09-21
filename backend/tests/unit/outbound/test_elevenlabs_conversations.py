"""Unit tests for ElevenLabs conversation list and SIP message API methods.

Spec: call-sip-observability — Requirement: ElevenLabs API Client Methods

These tests MUST fail (RED) until the implementation is added to ElevenLabsService
and the Pydantic models are added to elevenlabs/models.py.

All HTTP is mocked via respx — no live ElevenLabs calls in this suite.

TDD cycle: RED → GREEN → REFACTOR
"""

from __future__ import annotations

import pytest
import respx
import httpx
from pydantic import SecretStr
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EL_BASE = "https://api.elevenlabs.io/v1"
_CONVERSATIONS_URL = f"{_EL_BASE}/convai/conversations"


def _make_settings(api_key: str = "test-xi-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key)
    return settings


# ---------------------------------------------------------------------------
# Task 1.1 — Pydantic model tests (structural, no HTTP needed)
# ---------------------------------------------------------------------------


class TestConversationModels:
    """ConversationSummary and SipMessage model tests — allowlist enforcement."""

    def test_conversation_summary_parses_known_fields(self):
        """ConversationSummary accepts conversation_id, agent_id, status.

        GIVEN a dict with known fields
        WHEN ConversationSummary is constructed
        THEN the fields are parsed and accessible.
        """
        from app.elevenlabs.models import ConversationSummary

        cs = ConversationSummary(
            conversation_id="conv-abc123",
            agent_id="agent-xyz",
            status="done",
            call_successful="true",
            start_time_unix_secs=1720000000,
        )
        assert cs.conversation_id == "conv-abc123"
        assert cs.agent_id == "agent-xyz"
        assert cs.status == "done"
        assert cs.start_time_unix_secs == 1720000000

    def test_conversation_summary_all_optional_except_id(self):
        """ConversationSummary requires only conversation_id.

        GIVEN only conversation_id
        WHEN ConversationSummary is constructed
        THEN all optional fields default to None.
        """
        from app.elevenlabs.models import ConversationSummary

        cs = ConversationSummary(conversation_id="conv-min")
        assert cs.conversation_id == "conv-min"
        assert cs.agent_id is None
        assert cs.status is None

    def test_conversation_list_response_defaults_to_empty(self):
        """ConversationListResponse defaults to empty list.

        GIVEN no conversations
        WHEN ConversationListResponse is constructed with no args
        THEN conversations is an empty list.
        """
        from app.elevenlabs.models import ConversationListResponse

        clr = ConversationListResponse()
        assert clr.conversations == []

    def test_sip_message_extracts_safe_fields_only(self):
        """SipMessage stores only allowlisted fields — no raw body.

        GIVEN a dict with call_id, status_code, reason_phrase, method
        WHEN SipMessage is constructed
        THEN only the declared fields are accessible (no raw_body).
        """
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(
            call_id="otb_call_abc123",
            method="INVITE",
            status_code=200,
            reason_phrase="OK",
            direction="outbound",
            timestamp="2026-07-04T12:00:00Z",
        )
        assert sm.call_id == "otb_call_abc123"
        assert sm.status_code == 200
        assert sm.reason_phrase == "OK"
        assert not hasattr(sm, "raw_body"), "SipMessage must not expose raw_body"

    def test_sip_message_normalizes_upstream_raw_message_without_retaining_it(self):
        """Provider raw SIP is reduced to safe structured fields before storage."""
        from app.elevenlabs.models import SipMessage

        sensitive_address = "sip:+14155550100@203.0.113.10"
        sensitive_header = "Authorization: Digest username=secret"
        sm = SipMessage(
            call_id="otb_call_abc",
            raw_message=(
                "SIP/2.0 487 Request Terminated\r\n"
                "CSeq: 42 INVITE\r\n"
                f"To: <{sensitive_address}>\r\n"
                f"{sensitive_header}\r\n"
            ),
            error_message="provider diagnostic with sensitive address",
            direction="outbound",
            created_at_unix_micro=1720000000123456,
        )

        assert sm.status_code == 487
        assert sm.reason_phrase == "Request Terminated"
        assert sm.method == "INVITE"
        assert sm.cseq == 42
        assert sm.timestamp == "2024-07-03T09:46:40.123456+00:00"
        serialized = repr(sm.model_dump()) + repr(sm)
        assert sensitive_address not in serialized
        assert sensitive_header not in serialized
        assert not hasattr(sm, "raw_message")
        assert not hasattr(sm, "error_message")

    def test_sip_message_treats_malformed_raw_message_as_unknown(self):
        """Malformed raw provider text exposes no derived SIP fields."""
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(raw_message="not a SIP start line\nCSeq: invalid")

        assert sm.status_code is None
        assert sm.reason_phrase is None
        assert sm.method is None
        assert sm.cseq is None

    @pytest.mark.parametrize(
        ("provider_direction", "expected_direction"),
        [
            ("in", "inbound"),
            ("out", "outbound"),
            ("inbound", "inbound"),
            ("outbound", "outbound"),
        ],
    )
    def test_sip_message_normalizes_provider_direction_aliases(
        self, provider_direction, expected_direction
    ):
        """Provider in/out aliases use the same stored vocabulary as full directions."""
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(direction=provider_direction)

        assert sm.direction == expected_direction

    def test_sip_message_uses_cseq_from_headers_not_body(self):
        """A body line resembling CSeq cannot fabricate request evidence."""
        from app.elevenlabs.models import SipMessage

        sensitive_body = "CSeq: 73 INVITE\r\nAuthorization: Digest username=secret"
        sm = SipMessage(
            raw_message=(
                "SIP/2.0 200 OK\r\n"
                "Via: SIP/2.0/TCP example.invalid\r\n"
                f"\r\n{sensitive_body}"
            ),
            created_at_unix_micro=1720000000123456,
        )

        assert sm.status_code is None
        assert sm.reason_phrase is None
        assert sm.method is None
        assert sm.cseq is None
        assert sm.timestamp is None
        assert sensitive_body not in repr(sm.model_dump()) + repr(sm)

    @pytest.mark.parametrize(
        "raw_message",
        [
            "INVITE sip:callee@example.invalid SIP/2.0\r\nCSeq: 42 ACK\r\n\r\n",
            "INVITE sip:callee@example.invalid SIP/2.0\r\nCSeq: malformed\r\n\r\n",
        ],
    )
    def test_sip_message_rejects_conflicting_or_malformed_request_cseq(
        self, raw_message
    ):
        """A request line and CSeq must agree before SIP evidence is retained."""
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(
            raw_message=raw_message, created_at_unix_micro=1720000000123456
        )

        assert sm.status_code is None
        assert sm.reason_phrase is None
        assert sm.method is None
        assert sm.cseq is None
        assert sm.timestamp is None

    @pytest.mark.parametrize("malformed_direction", [{"value": "out"}, ["out"]])
    def test_sip_message_drops_unhashable_direction_without_leaking_raw_input(
        self, malformed_direction
    ):
        """Malformed provider direction is unknown rather than a validation failure."""
        from app.elevenlabs.models import SipMessage

        sensitive_raw = "SIP/2.0 200 OK\r\nCSeq: 1 INVITE\r\n\r\nsecret-body"
        sm = SipMessage(direction=malformed_direction, raw_message=sensitive_raw)

        assert sm.direction is None
        assert sensitive_raw not in repr(sm.model_dump()) + repr(sm)

    def test_sip_message_rejects_oversized_raw_message_without_partial_evidence(self):
        """Oversized provider bytes are unknown, never truncated into valid evidence."""
        from app.elevenlabs.models import SipMessage

        sensitive_tail = "Authorization: Digest username=secret"
        sm = SipMessage(
            raw_message=(
                "SIP/2.0 200 OK\r\nCSeq: 1 INVITE\r\n\r\n"
                + "x" * 4096
                + sensitive_tail
            ),
            created_at_unix_micro=1720000000123456,
        )

        assert sm.status_code is None
        assert sm.reason_phrase is None
        assert sm.method is None
        assert sm.cseq is None
        assert sm.timestamp is None
        assert sensitive_tail not in repr(sm.model_dump()) + repr(sm)

    @pytest.mark.parametrize("status_code", [99, 700])
    def test_sip_message_drops_out_of_range_response_codes(self, status_code):
        """Only SIP response codes in the protocol range are retained."""
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(status_code=status_code)

        assert sm.status_code is None

    @pytest.mark.parametrize("status_code", [100, 699])
    def test_sip_message_keeps_boundary_response_codes(self, status_code):
        """The inclusive SIP response-code boundaries remain valid."""
        from app.elevenlabs.models import SipMessage

        sm = SipMessage(status_code=status_code)

        assert sm.status_code == status_code

    def test_sip_messages_response_preserves_cursor_completeness_fields(self):
        """Cursor metadata remains available so callers can reject partial results."""
        from app.elevenlabs.models import SipMessagesResponse

        response = SipMessagesResponse(
            sip_messages=[], has_more=True, next_cursor="cursor-next-page"
        )

        assert response.has_more is True
        assert response.next_cursor == "cursor-next-page"

    def test_sip_messages_response_defaults_to_empty(self):
        """SipMessagesResponse defaults to empty list.

        GIVEN no sip_messages key
        WHEN SipMessagesResponse is constructed
        THEN sip_messages is an empty list.
        """
        from app.elevenlabs.models import SipMessagesResponse

        sr = SipMessagesResponse()
        assert sr.sip_messages == []

    def test_proxy_authorization_never_in_sip_message(self):
        """SipMessage model has no field for Proxy-Authorization or raw headers.

        Spec: Structured-Field-Only SIP Extraction — secrets excluded.
        GIVEN we attempt to store a Proxy-Authorization value via SipMessage
        WHEN SipMessage is constructed with extra fields
        THEN extra fields are ignored (no proxy_authorization attribute stored).
        """
        from app.elevenlabs.models import SipMessage

        # Pydantic v2 by default ignores extra fields
        sm = SipMessage(call_id="x", status_code=200)
        assert not hasattr(sm, "proxy_authorization"), (
            "SipMessage must not store proxy_authorization"
        )
        assert not hasattr(sm, "raw_body"), (
            "SipMessage must not store raw SIP body"
        )


# ---------------------------------------------------------------------------
# Task 1.2 — ElevenLabsService method tests
# ---------------------------------------------------------------------------


class TestListRecentConversations:
    """list_recent_conversations method — spec: ElevenLabs API Client Methods."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_conversations_on_200(self):
        """GIVEN ElevenLabs returns 200 with a conversations list
        WHEN list_recent_conversations is called
        THEN a ConversationListResponse is returned with the conversations.
        """
        from app.elevenlabs.service import ElevenLabsService
        from app.elevenlabs.models import ConversationListResponse

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": 1720000000,
                        }
                    ]
                },
            )
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.list_recent_conversations(agent_id="agent-abc")

        assert isinstance(result, ConversationListResponse)
        assert len(result.conversations) == 1
        assert result.conversations[0].conversation_id == "conv-001"
        assert result.conversations[0].agent_id == "agent-abc"

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_list_on_empty_response(self):
        """GIVEN ElevenLabs returns 200 with empty conversations array
        WHEN list_recent_conversations is called
        THEN an empty ConversationListResponse is returned.
        """
        from app.elevenlabs.service import ElevenLabsService
        from app.elevenlabs.models import ConversationListResponse

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(200, json={"conversations": []})
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.list_recent_conversations(agent_id="agent-abc")

        assert isinstance(result, ConversationListResponse)
        assert result.conversations == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_non_429_error(self):
        """GIVEN ElevenLabs returns HTTP 404
        WHEN list_recent_conversations is called
        THEN a typed exception is raised (not None returned silently).

        Spec: Non-429 error — typed exception raised.
        """
        from app.elevenlabs.service import ElevenLabsService

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception) as exc_info:
            await service.list_recent_conversations(agent_id="agent-abc")

        assert exc_info.value is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429_and_succeeds(self):
        """GIVEN ElevenLabs returns 429 then 200
        WHEN list_recent_conversations is called
        THEN it retries and returns the successful response.

        Spec: Rate-limit — exponential backoff applied (at least one retry).
        """
        from app.elevenlabs.service import ElevenLabsService
        from app.elevenlabs.models import ConversationListResponse

        call_count = {"n": 0}

        def side_effect(request, route):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"conversations": []})

        respx.get(_CONVERSATIONS_URL).mock(side_effect=side_effect)

        service = ElevenLabsService(settings=_make_settings())
        result = await service.list_recent_conversations(agent_id="agent-abc")

        assert isinstance(result, ConversationListResponse)
        assert call_count["n"] >= 2, "Must retry at least once on 429"

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_after_exhausting_429_retries(self):
        """GIVEN ElevenLabs keeps returning 429
        WHEN list_recent_conversations is called
        THEN it raises after exhausting retries.

        Spec: Rate-limit — exponential backoff applied.
        """
        from app.elevenlabs.service import ElevenLabsService

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception):
            await service.list_recent_conversations(agent_id="agent-abc")

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout_raises_exception(self):
        """GIVEN the ElevenLabs API times out
        WHEN list_recent_conversations is called
        THEN a timeout exception propagates (caller handles it).
        """
        from app.elevenlabs.service import ElevenLabsService

        respx.get(_CONVERSATIONS_URL).mock(
            side_effect=httpx.ReadTimeout("timed out")
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception):
            await service.list_recent_conversations(agent_id="agent-abc")


class TestGetSipMessages:
    """get_sip_messages method — spec: ElevenLabs API Client Methods."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_sip_messages_on_200(self):
        """GIVEN ElevenLabs returns 200 with SIP messages
        WHEN get_sip_messages is called
        THEN a SipMessagesResponse is returned with parsed SipMessage objects.

        Spec: Scenario: Mocked ElevenLabs probe test.
        """
        from app.elevenlabs.service import ElevenLabsService
        from app.elevenlabs.models import SipMessagesResponse

        conv_id = "conv-sip-001"
        sip_url = f"{_EL_BASE}/convai/conversations/{conv_id}/sip-messages"

        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_call_abc",
                            "method": "INVITE",
                            "direction": "outbound",
                            "timestamp": "2026-07-04T12:00:00Z",
                        },
                        {
                            "call_id": "otb_call_abc",
                            "status_code": 200,
                            "reason_phrase": "OK",
                            "direction": "inbound",
                            "timestamp": "2026-07-04T12:00:01Z",
                        },
                    ]
                },
            )
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.get_sip_messages(conversation_id=conv_id)

        assert isinstance(result, SipMessagesResponse)
        assert len(result.sip_messages) == 2
        assert result.sip_messages[0].call_id == "otb_call_abc"
        assert result.sip_messages[1].status_code == 200
        assert result.sip_messages[1].reason_phrase == "OK"

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_empty_on_no_sip_messages(self):
        """GIVEN ElevenLabs returns 200 with empty sip_messages array
        WHEN get_sip_messages is called
        THEN an empty SipMessagesResponse is returned.
        """
        from app.elevenlabs.service import ElevenLabsService

        conv_id = "conv-empty"
        sip_url = f"{_EL_BASE}/convai/conversations/{conv_id}/sip-messages"

        respx.get(sip_url).mock(
            return_value=httpx.Response(200, json={"sip_messages": []})
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.get_sip_messages(conversation_id=conv_id)

        assert result.sip_messages == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_404(self):
        """GIVEN ElevenLabs returns 404 for the conversation
        WHEN get_sip_messages is called
        THEN a typed exception is raised.

        Spec: Non-429 error — typed exception raised.
        """
        from app.elevenlabs.service import ElevenLabsService

        conv_id = "conv-not-found"
        sip_url = f"{_EL_BASE}/convai/conversations/{conv_id}/sip-messages"

        respx.get(sip_url).mock(
            return_value=httpx.Response(404, json={"detail": "not found"})
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception):
            await service.get_sip_messages(conversation_id=conv_id)

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429(self):
        """GIVEN ElevenLabs returns 429 then 200 for SIP messages
        WHEN get_sip_messages is called
        THEN it retries and returns the successful response.
        """
        from app.elevenlabs.service import ElevenLabsService

        conv_id = "conv-rate-limited"
        sip_url = f"{_EL_BASE}/convai/conversations/{conv_id}/sip-messages"

        call_count = {"n": 0}

        def side_effect(request, route):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"sip_messages": []})

        respx.get(sip_url).mock(side_effect=side_effect)

        service = ElevenLabsService(settings=_make_settings())
        result = await service.get_sip_messages(conversation_id=conv_id)

        assert call_count["n"] >= 2, "Must retry at least once on 429"
        assert result.sip_messages == []


class TestGetConversationDetail:
    """get_conversation_detail method — returns raw safe fields dict."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_dict_on_200(self):
        """GIVEN ElevenLabs returns 200 with conversation detail
        WHEN get_conversation_detail is called
        THEN a dict is returned with conversation fields.
        """
        from app.elevenlabs.service import ElevenLabsService

        conv_id = "conv-detail-001"
        detail_url = f"{_EL_BASE}/convai/conversations/{conv_id}"

        respx.get(detail_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversation_id": conv_id,
                    "agent_id": "agent-abc",
                    "status": "done",
                    "metadata": {"call_duration_secs": 42},
                },
            )
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.get_conversation_detail(conversation_id=conv_id)

        assert isinstance(result, dict)
        assert result["conversation_id"] == conv_id

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_non_2xx(self):
        """GIVEN ElevenLabs returns 500
        WHEN get_conversation_detail is called
        THEN a typed exception is raised.
        """
        from app.elevenlabs.service import ElevenLabsService

        conv_id = "conv-error"
        detail_url = f"{_EL_BASE}/convai/conversations/{conv_id}"

        respx.get(detail_url).mock(
            return_value=httpx.Response(500, json={"error": "internal error"})
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception):
            await service.get_conversation_detail(conversation_id=conv_id)


class TestGetSipMessagesByPhone:
    """get_sip_messages_by_phone method — fallback SIP lookup by phone ID."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_sip_messages_on_200(self):
        """GIVEN ElevenLabs returns 200 with SIP messages by phone ID
        WHEN get_sip_messages_by_phone is called
        THEN a SipMessagesResponse is returned.
        """
        from app.elevenlabs.service import ElevenLabsService
        from app.elevenlabs.models import SipMessagesResponse

        phone_id = "pn-xyz-001"
        phone_sip_url = f"{_EL_BASE}/convai/phone-numbers/{phone_id}/sip-messages"

        respx.get(phone_sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_phone_call_abc",
                            "status_code": 487,
                            "reason_phrase": "Request Terminated",
                            "direction": "outbound",
                        }
                    ]
                },
            )
        )

        service = ElevenLabsService(settings=_make_settings())
        result = await service.get_sip_messages_by_phone(phone_number_id=phone_id)

        assert isinstance(result, SipMessagesResponse)
        assert len(result.sip_messages) == 1
        assert result.sip_messages[0].call_id == "otb_phone_call_abc"
        assert result.sip_messages[0].status_code == 487

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_non_2xx(self):
        """GIVEN ElevenLabs returns 403
        WHEN get_sip_messages_by_phone is called
        THEN a typed exception is raised.
        """
        from app.elevenlabs.service import ElevenLabsService

        phone_id = "pn-forbidden"
        phone_sip_url = f"{_EL_BASE}/convai/phone-numbers/{phone_id}/sip-messages"

        respx.get(phone_sip_url).mock(
            return_value=httpx.Response(403, json={"error": "forbidden"})
        )

        service = ElevenLabsService(settings=_make_settings())
        with pytest.raises(Exception):
            await service.get_sip_messages_by_phone(phone_number_id=phone_id)


class TestSipFieldExtractionSafety:
    """Verify no raw bodies or secret fields leak through the Pydantic models."""

    def test_sip_message_no_raw_body_field(self):
        """SipMessage must not have a raw_body attribute at class level."""
        from app.elevenlabs.models import SipMessage
        import inspect

        fields = set(SipMessage.model_fields.keys())
        assert "raw_body" not in fields, "raw_body must not be a SipMessage field"
        assert "proxy_authorization" not in fields
        assert "authorization" not in fields

    def test_sip_message_field_allowlist(self):
        """SipMessage fields are exactly the allowed set — no extras."""
        from app.elevenlabs.models import SipMessage

        allowed = {"call_id", "method", "status_code", "reason_phrase", "direction", "timestamp", "cseq"}
        actual = set(SipMessage.model_fields.keys())
        unexpected = actual - allowed
        assert not unexpected, (
            f"Unexpected fields in SipMessage: {unexpected}. "
            "Only allowlisted fields may be stored."
        )
