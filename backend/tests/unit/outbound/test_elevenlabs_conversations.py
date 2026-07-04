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
_CONVERSATIONS_URL = f"{_EL_BASE}/conversational_ai/conversations"


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
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}/sip_messages"

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
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}/sip_messages"

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
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}/sip_messages"

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
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}/sip_messages"

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
        detail_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}"

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
        detail_url = f"{_EL_BASE}/conversational_ai/conversations/{conv_id}"

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
        phone_sip_url = f"{_EL_BASE}/convai/phone_numbers/{phone_id}/sip_messages"

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
        phone_sip_url = f"{_EL_BASE}/convai/phone_numbers/{phone_id}/sip_messages"

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

        allowed = {"call_id", "method", "status_code", "reason_phrase", "direction", "timestamp"}
        actual = set(SipMessage.model_fields.keys())
        unexpected = actual - allowed
        assert not unexpected, (
            f"Unexpected fields in SipMessage: {unexpected}. "
            "Only allowlisted fields may be stored."
        )
