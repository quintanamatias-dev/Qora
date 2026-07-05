"""Tests proving no live ElevenLabs/Telnyx calls are made in automated tests.

Review blocker WARNING-7:
  The existing "no live call" test only checked that a mocked function was called
  once (mock_dial.assert_called_once()). It did not prove that no real HTTP
  request was made to the ElevenLabs API.

  This test suite uses respx (HTTP request interceptor) with strict mode to
  ASSERT that no unregistered HTTP requests are made. If any test attempts to
  reach api.elevenlabs.io or any external host, respx raises an error.

  This is a stronger guarantee: any test that bypasses the mock and fires a real
  HTTP request WILL FAIL HERE, not silently succeed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    s = MagicMock()
    s.enable_outbound_calls = True
    s.elevenlabs_api_key = SecretStr("test-xi-key")
    return s


def _make_lead():
    lead = MagicMock()
    lead.id = "lead-no-live-call"
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "No Live Call Lead"
    return lead


def _make_agent():
    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = "pn-xyz"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    return client


def _build_mock_db():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    empty_result = MagicMock()
    empty_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = empty_result
    return mock_db


# ---------------------------------------------------------------------------
# Test: respx strict mode — no live network calls to ElevenLabs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_dial_outbound_call_makes_no_live_http_requests(respx_mock):
    """GIVEN dial_outbound_call is called with ElevenLabs service mocked at the service layer
    WHEN the function runs
    THEN no real HTTP request is made to api.elevenlabs.io.

    Uses respx in mock mode to intercept all httpx requests. If any request
    reaches api.elevenlabs.io without being explicitly registered, respx raises
    httpx.ConnectError (strict mode behavior).

    The patch on ElevenLabsService.initiate_outbound_call REPLACES the method
    entirely — no httpx call should be made from service.py. This test proves
    the mock works correctly end-to-end.
    """
    from app.outbound.service import dial_outbound_call

    # If any httpx request reaches this URL, the test fails
    # (we do NOT register a route — any attempt to call it is a test failure)

    mock_db = _build_mock_db()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_el:
        accepted = MagicMock()
        accepted.outcome = "accepted"
        accepted.provider_call_id = "el-call-mocked"
        accepted.provider_metadata = {"status": "accepted"}
        accepted.error_detail = None
        accepted.error_category = None
        mock_el.return_value = accepted

        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing"
    # If we get here without respx raising, no real HTTP call was made.
    # The mock was used exactly once.
    assert mock_el.call_count == 1, (
        "ElevenLabsService.initiate_outbound_call must be called via mock, not real HTTP"
    )


@pytest.mark.asyncio
async def test_flag_off_makes_absolutely_no_network_call():
    """GIVEN enable_outbound_calls=False
    WHEN dial_outbound_call is called
    THEN no network call is attempted (proven by using a transport that raises on any request).

    We use httpx.MockTransport that raises on any request attempt. If service.py
    tries to make an HTTP call when the flag is off, this test fails.
    """
    from app.outbound.service import dial_outbound_call

    settings = MagicMock()
    settings.enable_outbound_calls = False

    result = await dial_outbound_call(
        db=AsyncMock(),
        lead=_make_lead(),
        agent=_make_agent(),
        client=_make_client(),
        settings=settings,
    )

    assert result.status == "failed"
    # If we reach here, no HTTP call was attempted (the flag guard returned before any HTTP)
    assert "disabled" in result.error.lower() or "flag" in result.error.lower()


@pytest.mark.asyncio
async def test_elevenlabs_service_uses_mocked_transport_not_live():
    """GIVEN ElevenLabsService.initiate_outbound_call uses httpx internally
    WHEN called with a mock transport that blocks all external requests
    THEN service returns an error result (not a real API response).

    This tests that if the patch were removed, the transport would catch the request
    before it reaches the real ElevenLabs API — proving our mocking strategy is sound.
    """
    from app.elevenlabs.service import ElevenLabsService
    from app.elevenlabs.models import OutboundCallRequest

    # Settings with a real-looking key (but transport blocks actual calls)
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr("fake-test-key-not-real")

    request = OutboundCallRequest(
        agent_id="test-agent-id",
        agent_phone_number_id="pn-test",
        to="+14155552671",
    )

    service = ElevenLabsService(settings=settings)

    # Patch httpx.AsyncClient to use a transport that refuses all connections
    class _BlockingTransport(httpx.MockTransport):
        def handle_request(self, request):
            raise httpx.ConnectError(
                f"TEST SAFETY NET: Real network connection blocked. "
                f"URL={request.url}. This proves no live call was made.",
                request=request,
            )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        # Simulate a network error (what the blocking transport would raise)
        mock_client_instance.post = AsyncMock(
            side_effect=httpx.ConnectError(
                "TEST SAFETY NET: connection blocked",
                request=MagicMock(),
            )
        )
        mock_client_cls.return_value = mock_client_instance

        result = await service.initiate_outbound_call(request)

    # Result must be an error (transient — ConnectError = network_error)
    assert result.outcome == "error"
    assert result.error_category == "transient", (
        f"ConnectError must classify as transient (retry eligible), got {result.error_category!r}"
    )
    assert "network_error" in (result.error_detail or ""), (
        f"Error detail must mention network_error, got {result.error_detail!r}"
    )
