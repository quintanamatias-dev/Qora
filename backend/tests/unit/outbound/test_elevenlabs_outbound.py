"""Unit tests for ElevenLabsService.initiate_outbound_call().

Spec: outbound-call-trigger — Requirement: Call Attempt Persistence
  "ElevenLabsService.initiate_outbound_call() — POST to SIP trunk outbound-call API"

Design:
  POST https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call
  body: { agent_id, agent_phone_number_id, to, conversation_initiation_client_data }
  On 2xx with valid JSON + call_id/conversation_id/sip_call_id → outcome='accepted',
    provider_call_id (first non-empty in that priority order) + provider_metadata stored
  On 2xx with malformed JSON → outcome='error', error_category='permanent' (defensive)
  On 2xx with none of call_id/conversation_id/sip_call_id → outcome='error',
    error_category='permanent' (defensive — no linkage identifier)
  On transient error (5xx/timeout/429) → error_category='transient'
  On permanent error (4xx non-429) → error_category='permanent'
  No live calls in automated tests — HTTP mocked via respx.
"""

from __future__ import annotations

import pytest
import respx
import httpx
from pydantic import SecretStr
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_settings(api_key: str = "test-xi-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key)
    return settings


def _make_request(
    agent_id: str = "el-agent-abc",
    agent_phone_number_id: str = "pn-xyz",
    to: str = "+14155552671",
    client_data: dict | None = None,
):
    from app.elevenlabs.models import OutboundCallRequest

    return OutboundCallRequest(
        agent_id=agent_id,
        agent_phone_number_id=agent_phone_number_id,
        to=to,
        conversation_initiation_client_data=client_data,
    )


_OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call"


# ---------------------------------------------------------------------------
# RED — initiate_outbound_call does not exist yet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_accepted_200():
    """GIVEN ElevenLabs returns 200 with provider_call_id
    WHEN initiate_outbound_call is called
    THEN outcome='accepted', provider_call_id is set from response, no exception raised.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "call_id": "el-call-9999",
                "status": "initiated",
                "cost": 0.0,
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_call_id == "el-call-9999"
    assert result.error_detail is None
    assert result.error_category is None


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_sends_correct_payload():
    """GIVEN an OutboundCallRequest
    WHEN initiate_outbound_call is called
    THEN the POST body contains agent_id, agent_phone_number_id, and to_number.

    Regression: the ElevenLabs SIP trunk outbound-call API requires the field
    "to_number" (NOT "to"). Sending "to" caused an HTTP 422 permanent error and
    no call was placed. The wire payload must use "to_number" and must NOT
    include the legacy "to" key.
    """
    from app.elevenlabs.service import ElevenLabsService

    captured: dict = {}

    def capture(request, route):
        import json
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"call_id": "x"})

    respx.post(_OUTBOUND_URL).mock(side_effect=capture)

    service = ElevenLabsService(settings=_make_settings(api_key="my-key"))
    req = _make_request(
        agent_id="el-agent-abc",
        agent_phone_number_id="pn-xyz",
        to="+5491123456789",
        client_data={"lead_name": "Juan"},
    )
    await service.initiate_outbound_call(req)

    body = captured["body"]
    assert body["agent_id"] == "el-agent-abc"
    assert body["agent_phone_number_id"] == "pn-xyz"
    # API-required field name: to_number (regression guard against reintroducing "to")
    assert body["to_number"] == "+5491123456789"
    assert "to" not in body
    assert body.get("conversation_initiation_client_data") == {"lead_name": "Juan"}
    assert captured["headers"].get("xi-api-key") == "my-key"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_5xx_returns_transient_error():
    """GIVEN ElevenLabs returns 503 (transient)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='transient', no exception raised.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(503, json={"error": "Service unavailable"})
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "transient"
    assert result.error_detail is not None
    assert "503" in result.error_detail


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_4xx_returns_permanent_error():
    """GIVEN ElevenLabs returns 400 (permanent, not retryable)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='permanent'.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(400, json={"error": "Invalid agent_id"})
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "permanent"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_429_returns_transient_error():
    """GIVEN ElevenLabs returns 429 (rate limit — transient, not permanent)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='transient'.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "transient"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_network_error_returns_transient():
    """GIVEN a network error (DNS/connection refused)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='transient', no exception raised.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "transient"
    assert result.error_detail is not None


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_read_timeout_returns_unknown():
    """GIVEN a read timeout AFTER the request was sent
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='unknown' (ambiguous side effect).

    Regression (duplicate-call bug): the provider can accept the request and start
    ringing a real SIP call while the HTTP response is still pending. A read
    timeout here does NOT mean the call was not placed. It must be classified as
    'unknown' (not 'transient') so the caller does NOT retry and dial a second
    billed call.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        side_effect=httpx.ReadTimeout("timed out waiting for response")
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "unknown", (
        f"ReadTimeout after send must be 'unknown' (do not retry), "
        f"got {result.error_category!r}"
    )
    assert result.provider_call_id is None
    assert result.error_detail is not None


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_connect_timeout_returns_transient():
    """GIVEN a connect timeout (connection never established)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='transient' (safe to retry).

    A connect timeout means the request never reached ElevenLabs, so no SIP call
    could have been placed — unlike a read timeout, retrying is safe.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        side_effect=httpx.ConnectTimeout("could not connect")
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "transient", (
        f"ConnectTimeout must be 'transient' (retry eligible), "
        f"got {result.error_category!r}"
    )


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_stores_provider_metadata():
    """GIVEN ElevenLabs response includes cost and billed_duration_seconds
    WHEN initiate_outbound_call is called
    THEN provider_metadata is the raw response dict with those fields preserved.
    """
    from app.elevenlabs.service import ElevenLabsService

    response_body = {
        "call_id": "el-call-meta-test",
        "status": "initiated",
        "cost": 0.42,
        "billed_duration_seconds": 120,
    }
    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(200, json=response_body)
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_metadata is not None
    assert result.provider_metadata.get("cost") == 0.42
    assert result.provider_metadata.get("billed_duration_seconds") == 120


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_malformed_json_returns_error():
    """GIVEN ElevenLabs returns 200 with non-JSON body (e.g. plain text or HTML)
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='permanent' — malformed JSON is not a ringing state.

    Defensive: response.json() can raise JSONDecodeError on some 2xx bodies
    (proxy errors, maintenance pages, etc.). This must NOT let a session transition
    to 'ringing' without a valid provider_call_id.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"<html>Service Unavailable</html>",
            headers={"content-type": "text/html"},
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "permanent"
    assert result.provider_call_id is None
    assert result.error_detail is not None
    assert "json" in result.error_detail.lower() or "parse" in result.error_detail.lower()


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_missing_call_id_returns_error():
    """GIVEN ElevenLabs returns 200 with valid JSON but no call_id field
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='permanent' — no call_id means no linkage.

    Without provider_call_id, Qora cannot track or reconcile the call.
    Treating this as success and transitioning to 'ringing' would create an
    untrackable billed call — so it must be classified as a provider failure.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={"status": "initiated"},  # missing call_id
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "permanent"
    assert result.provider_call_id is None
    assert result.error_detail is not None
    assert "call_id" in result.error_detail


# ---------------------------------------------------------------------------
# provider_call_id resolution — real ElevenLabs SIP trunk response shape
#
# The live API does NOT return "call_id". On success it returns:
#   {"success": true, "conversation_id": "...", "sip_call_id": "otb_..."}
# provider_call_id must be resolved from call_id / conversation_id / sip_call_id
# in that priority order (first non-empty wins).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_accepts_conversation_id_when_call_id_absent():
    """GIVEN the real SIP-trunk response with conversation_id + sip_call_id (no call_id)
    WHEN initiate_outbound_call is called
    THEN outcome='accepted' and provider_call_id is the conversation_id.

    Regression: the live outbound-call API returns conversation_id/sip_call_id,
    never call_id. Requiring call_id marked successful SIP calls as permanent
    errors and lost all linkage to the CallSession.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "Call initiated",
                "conversation_id": "conv_abc123",
                "sip_call_id": "otb_xyz789",
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_call_id == "conv_abc123"
    assert result.error_detail is None
    assert result.error_category is None


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_accepts_sip_call_id_when_others_absent():
    """GIVEN a 2xx response with only sip_call_id (no call_id, no conversation_id)
    WHEN initiate_outbound_call is called
    THEN outcome='accepted' and provider_call_id is the sip_call_id.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "sip_call_id": "otb_only_sip"},
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_call_id == "otb_only_sip"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_provider_call_id_priority_order():
    """GIVEN a 2xx response containing call_id, conversation_id AND sip_call_id
    WHEN initiate_outbound_call is called
    THEN provider_call_id is the call_id (highest priority).

    Priority order: call_id > conversation_id > sip_call_id.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "call_id": "call_wins",
                "conversation_id": "conv_second",
                "sip_call_id": "otb_third",
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_call_id == "call_wins"


@pytest.mark.asyncio
@respx.mock
async def test_initiate_outbound_call_conversation_id_wins_over_sip_call_id():
    """GIVEN a 2xx response with conversation_id AND sip_call_id (no call_id)
    WHEN initiate_outbound_call is called
    THEN provider_call_id is the conversation_id (second priority beats third).
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "conversation_id": "conv_second",
                "sip_call_id": "otb_third",
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "accepted"
    assert result.provider_call_id == "conv_second"
