"""Verify-fix: no_answer as a distinct telephony_status.

Spec: phase-c2-outbound-call-trigger / Live Status State Machine
  - GIVEN provider reports no answer (ring timeout, voicemail network response)
  - WHEN status is resolved
  - THEN telephony_status is set to 'no_answer'
  - AND no automatic retry is initiated

These tests are written RED before implementation changes to prove the gap
found by sdd-verify, then confirmed GREEN after the fix.

TDD Strict: RED → GREEN cycle.
No live calls — HTTP mocked via respx; service mocked via AsyncMock.
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

_OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call"


def _make_settings(api_key: str = "test-xi-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key)
    return settings


def _make_request():
    from app.elevenlabs.models import OutboundCallRequest

    return OutboundCallRequest(
        agent_id="el-agent-test",
        agent_phone_number_id="pn-test",
        to="+14155552671",
    )


def _make_service_settings(enable_outbound: bool = True):
    s = MagicMock()
    s.enable_outbound_calls = enable_outbound
    s.elevenlabs_api_key = SecretStr("test-xi-key")
    return s


def _make_lead(phone: str = "+14155552671"):
    lead = MagicMock()
    lead.id = "lead-no-answer-001"
    lead.phone = phone
    lead.client_id = "client-a"
    lead.name = "No-Answer Test Lead"
    return lead


def _make_agent():
    agent = MagicMock()
    agent.id = "agent-no-answer-001"
    agent.elevenlabs_agent_id = "el-agent-na"
    agent.elevenlabs_phone_number_id = "pn-na-xyz"
    agent.name = "No-Answer Test Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "No-Answer Test Client"
    return client


def _build_mock_db(active_session=None):
    """Build a mock AsyncSession capturing objects added to it."""
    mock_db = AsyncMock()
    _added: list = []

    def _add(obj):
        _added.append(obj)

    mock_db.add = _add
    mock_db._added = _added

    async def _execute(stmt):
        result = MagicMock()
        result.scalars.return_value.first.return_value = active_session
        return result

    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Layer 1: ElevenLabsService — provider maps no_answer status in response body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_elevenlabs_service_no_answer_status_in_response_returns_no_answer_category():
    """GIVEN ElevenLabs returns 2xx with status='no_answer' in body
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='no_answer', no retry needed.

    Provider-reported no-answer comes via the response body status field.
    This is a distinct, non-retryable outcome — not a system failure.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "call_id": "el-call-na-001",
                "status": "no_answer",
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error", (
        f"no_answer status must be an error outcome, got {result.outcome!r}"
    )
    assert result.error_category == "no_answer", (
        f"error_category must be 'no_answer', got {result.error_category!r}"
    )
    assert result.provider_call_id is None or isinstance(result.provider_call_id, str), (
        "provider_call_id must be None or string for no_answer"
    )


@pytest.mark.asyncio
@respx.mock
async def test_elevenlabs_service_ring_timeout_status_returns_no_answer_category():
    """GIVEN ElevenLabs returns 2xx with status='ring_timeout' in body
    WHEN initiate_outbound_call is called
    THEN outcome='error', error_category='no_answer'.

    ring_timeout is a provider synonym for no_answer.
    """
    from app.elevenlabs.service import ElevenLabsService

    respx.post(_OUTBOUND_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "call_id": "el-call-rt-001",
                "status": "ring_timeout",
            },
        )
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.initiate_outbound_call(_make_request())

    assert result.outcome == "error"
    assert result.error_category == "no_answer", (
        f"ring_timeout must map to error_category='no_answer', got {result.error_category!r}"
    )


# ---------------------------------------------------------------------------
# Layer 2: dial_outbound_call() — no_answer sets telephony_status='no_answer', no retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_outbound_no_answer_sets_telephony_status_no_answer():
    """GIVEN ElevenLabs returns no_answer (via error_category='no_answer')
    WHEN dial_outbound_call handles it
    THEN call_session.telephony_status == 'no_answer'
    AND exactly 1 API call made (no retry)
    AND result.status == 'failed' (DialResult uses 'failed' for non-dialing outcomes)

    Spec: telephony_status='no_answer' (distinct from 'failed')
    AND no automatic retry is initiated.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    # Provider returns no_answer
    no_answer_result = MagicMock()
    no_answer_result.outcome = "error"
    no_answer_result.provider_call_id = None
    no_answer_result.provider_metadata = None
    no_answer_result.error_detail = "no_answer: lead did not pick up within ring timeout"
    no_answer_result.error_category = "no_answer"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=no_answer_result,
    ) as mock_api:
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
                settings=_make_service_settings(),
            )

    # Must NOT retry — no_answer is not a transient system error
    assert mock_api.call_count == 1, (
        f"no_answer must NOT be retried. API called {mock_api.call_count} time(s)."
    )

    # telephony_status must be 'no_answer' — distinct from 'failed'
    added_sessions = [obj for obj in mock_db._added]
    assert len(added_sessions) >= 1, "CallSession must have been created"
    call_session = added_sessions[0]
    assert call_session.telephony_status == "no_answer", (
        f"telephony_status must be 'no_answer', got {call_session.telephony_status!r}"
    )

    # DialResult.status is 'failed' (external result enum) — no_answer is a non-dialing outcome
    # The key check is telephony_status on the persisted session, not DialResult.status
    assert result.status in ("failed",), (
        f"DialResult.status must be 'failed' for no_answer, got {result.status!r}"
    )


@pytest.mark.asyncio
async def test_dial_outbound_no_answer_does_not_retry():
    """GIVEN dial_outbound_call receives no_answer from the provider
    WHEN the result is processed
    THEN exactly 1 provider API call is made (no automatic retry).

    Retrying a no-answer is wasteful and semantically wrong (the called
    party chose not to answer or the ring timed out).
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    no_answer_result = MagicMock()
    no_answer_result.outcome = "error"
    no_answer_result.provider_call_id = None
    no_answer_result.provider_metadata = None
    no_answer_result.error_detail = "no_answer: ring timeout"
    no_answer_result.error_category = "no_answer"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=no_answer_result,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_service_settings(),
            )

    assert mock_api.call_count == 1, (
        f"no_answer must fire exactly 1 API call (no retry). "
        f"Got {mock_api.call_count} calls."
    )


@pytest.mark.asyncio
async def test_dial_outbound_no_answer_telephony_error_populated():
    """GIVEN ElevenLabs returns no_answer
    WHEN telephony_status is set to 'no_answer'
    THEN telephony_error is populated with the provider detail for operator visibility.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    no_answer_result = MagicMock()
    no_answer_result.outcome = "error"
    no_answer_result.provider_call_id = None
    no_answer_result.provider_metadata = None
    no_answer_result.error_detail = "no_answer: lead did not pick up"
    no_answer_result.error_category = "no_answer"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=no_answer_result,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_service_settings(),
            )

    added_sessions = [obj for obj in mock_db._added]
    assert len(added_sessions) >= 1
    call_session = added_sessions[0]

    assert call_session.telephony_status == "no_answer", (
        f"telephony_status must be 'no_answer', got {call_session.telephony_status!r}"
    )
    assert call_session.telephony_error is not None, (
        "telephony_error must be populated for operator visibility"
    )


# ---------------------------------------------------------------------------
# Regression: existing permanent errors still map to 'failed' (not 'no_answer')
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_outbound_permanent_error_still_maps_to_failed():
    """GIVEN ElevenLabs returns a permanent error (e.g. 400 Bad Request)
    WHEN dial_outbound_call handles it
    THEN telephony_status is 'failed', NOT 'no_answer'.

    This regression test ensures no_answer handling is narrowly scoped.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = _build_mock_db(active_session=None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    permanent_result = MagicMock()
    permanent_result.outcome = "error"
    permanent_result.provider_call_id = None
    permanent_result.provider_metadata = None
    permanent_result.error_detail = "http_status=400"
    permanent_result.error_category = "permanent"

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=permanent_result,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_service_settings(),
            )

    added_sessions = [obj for obj in mock_db._added]
    assert len(added_sessions) >= 1
    call_session = added_sessions[0]

    assert call_session.telephony_status == "failed", (
        f"permanent error must map to 'failed', got {call_session.telephony_status!r}"
    )
    assert call_session.telephony_status != "no_answer", (
        "permanent error must NOT map to 'no_answer'"
    )
