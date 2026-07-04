"""Tests for safe provider metadata handling (WARNING-5 + RE4).

Review blocker WARNING-5:
  The original implementation persisted `provider_metadata=body` — the raw API response.
  This can contain unexpected PII or sensitive fields (routing numbers, SIP headers,
  internal provider identifiers, etc.) that should not be stored in Qora's DB.

  Fix: only persist an explicit allowlisted subset of provider metadata fields.
  All other fields are discarded at the service boundary.

WU2 re-review RE4:
  'message' was originally allowlisted, but providers may populate it with
  free-form text containing PII (phone numbers, caller names, SIP addresses).
  'message' is now excluded from the allowlist.

Allowlisted fields (safe, non-PII, business-relevant):
  - call_id: provider call identifier (already stored in provider_call_id)
  - status: initial call status from provider
  - duration_seconds: raw call duration
  - billed_duration_seconds: billed duration (cost reporting)
  - cost: call cost in USD (cost reporting)
  NOTE: 'message' is excluded — free-form provider text with PII risk (RE4).

Anything else (SIP URIs, internal trace IDs, routing data, message, etc.) is dropped.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Test: _extract_safe_provider_metadata allowlists only safe fields
# ---------------------------------------------------------------------------


def test_safe_metadata_extracts_only_allowlisted_fields():
    """GIVEN a raw provider response dict with mixed safe and unsafe fields
    WHEN _extract_safe_provider_metadata is called
    THEN only allowlisted fields are returned; unsafe fields are dropped.
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {
        "call_id": "el-call-abc123",
        "status": "initiated",
        "duration_seconds": 0,
        "cost": 0.0,
        "message": "Call accepted",
        # Unsafe / not allowlisted — must be dropped:
        "sip_uri": "sip:+14155552671@telnyx.com",
        "internal_trace_id": "trace-xyzabc",
        "routing_metadata": {"region": "us-east-1", "carrier": "TELNYX"},
        "from_number": "+15555555555",  # potentially PII
        "to_number": "+14155552671",    # PII — lead's phone number
        "agent_phone_number_id": "pn-xyz",  # internal configuration — don't store
        "webhook_url": "https://internal.sip.provider/hooks",
    }

    safe = _extract_safe_provider_metadata(raw)

    # Only allowlisted fields
    assert "call_id" in safe, "call_id must be preserved"
    assert "status" in safe, "status must be preserved"
    assert "duration_seconds" in safe, "duration_seconds must be preserved"
    assert "cost" in safe, "cost must be preserved"

    # 'message' is intentionally excluded (RE4 — free-form text, PII risk)
    assert "message" not in safe, "message must be dropped (PII risk — RE4)"

    # Unsafe fields must be dropped
    assert "sip_uri" not in safe, "sip_uri must be dropped (internal routing)"
    assert "internal_trace_id" not in safe, "internal_trace_id must be dropped"
    assert "routing_metadata" not in safe, "routing_metadata must be dropped"
    assert "from_number" not in safe, "from_number must be dropped (PII)"
    assert "to_number" not in safe, "to_number must be dropped (PII)"
    assert "agent_phone_number_id" not in safe, "agent_phone_number_id must be dropped"
    assert "webhook_url" not in safe, "webhook_url must be dropped"


def test_safe_metadata_handles_none_input():
    """GIVEN provider_metadata is None
    WHEN _extract_safe_provider_metadata is called
    THEN None is returned (no crash).
    """
    from app.outbound.service import _extract_safe_provider_metadata

    result = _extract_safe_provider_metadata(None)
    assert result is None


def test_safe_metadata_handles_empty_dict():
    """GIVEN an empty provider response dict
    WHEN _extract_safe_provider_metadata is called
    THEN an empty dict is returned.
    """
    from app.outbound.service import _extract_safe_provider_metadata

    result = _extract_safe_provider_metadata({})
    assert result == {} or result is None  # either empty dict or None is acceptable


def test_safe_metadata_returns_only_present_fields():
    """GIVEN a raw response with only a subset of allowlisted fields
    WHEN _extract_safe_provider_metadata is called
    THEN only the present allowlisted fields are returned (no None padding).
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {"call_id": "el-call-partial", "cost": 0.05}
    safe = _extract_safe_provider_metadata(raw)

    assert safe is not None
    assert safe.get("call_id") == "el-call-partial"
    assert safe.get("cost") == 0.05
    # Fields not in raw must not appear with None values
    assert "sip_uri" not in safe
    assert "from_number" not in safe


def test_safe_metadata_values_preserved():
    """GIVEN allowlisted fields with specific values
    WHEN _extract_safe_provider_metadata is called
    THEN values are preserved exactly (except 'message' which is excluded, RE4).
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {
        "call_id": "abc-123",
        "status": "ringing",
        "duration_seconds": 120,
        "billed_duration_seconds": 2,
        "cost": 0.25,
        "message": "Call connected",  # must be dropped (RE4)
    }
    safe = _extract_safe_provider_metadata(raw)
    assert safe["call_id"] == "abc-123"
    assert safe["status"] == "ringing"
    assert safe["duration_seconds"] == 120
    assert safe["billed_duration_seconds"] == 2
    assert safe["cost"] == 0.25
    # 'message' must NOT be in result (RE4 — free-form text, PII risk)
    assert "message" not in safe, (
        "'message' must be absent from safe provider metadata (RE4). "
        f"Got: {safe.get('message')!r}"
    )


def test_safe_metadata_allowlists_conversation_id_and_sip_call_id():
    """GIVEN the real SIP-trunk outbound response (conversation_id + sip_call_id)
    WHEN _extract_safe_provider_metadata is called
    THEN conversation_id and sip_call_id are preserved (allowlisted).

    The live outbound-call API returns conversation_id (custom-llm session key /
    SIP lookup) and sip_call_id (SIP evidence linkage). Both must survive the
    allowlist so the CallSession can be linked to the conversation and SIP data.
    """
    from app.outbound.service import _extract_safe_provider_metadata

    raw = {
        "success": True,
        "message": "Call initiated",
        "conversation_id": "conv_abc123",
        "sip_call_id": "otb_xyz789",
    }
    safe = _extract_safe_provider_metadata(raw)

    assert safe is not None
    assert safe.get("conversation_id") == "conv_abc123", (
        "conversation_id must be preserved for custom-llm linkage"
    )
    assert safe.get("sip_call_id") == "otb_xyz789", (
        "sip_call_id must be preserved for SIP evidence linkage"
    )
    # free-form / non-allowlisted fields still dropped
    assert "message" not in safe, "message must be dropped (PII risk — RE4)"
    assert "success" not in safe, "non-allowlisted 'success' must be dropped"


# ---------------------------------------------------------------------------
# Test: service stores safe metadata, not raw
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dial_outbound_call_stores_safe_metadata_not_raw():
    """GIVEN ElevenLabs API returns a response with extra unsafe fields
    WHEN dial_outbound_call processes it
    THEN only allowlisted metadata is stored in CallSession.provider_metadata.
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    from pydantic import SecretStr
    from app.outbound.service import dial_outbound_call

    settings = MagicMock()
    settings.enable_outbound_calls = True
    settings.elevenlabs_api_key = SecretStr("test-key")

    lead = MagicMock()
    lead.id = "lead-meta-test"
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Metadata Test Lead"

    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = "pn-xyz"

    client = MagicMock()
    client.id = "client-a"

    session_obj = None

    mock_db = AsyncMock()
    mock_db.add = MagicMock(side_effect=lambda obj: setattr(mock_db, '_session_obj', obj) or None)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    # DB returns no active session
    empty_result = MagicMock()
    empty_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = empty_result

    # Provider result with raw unsafe fields embedded in the API response
    accepted_result = MagicMock()
    accepted_result.outcome = "accepted"
    accepted_result.provider_call_id = "el-call-meta-check"
    accepted_result.provider_metadata = {
        "call_id": "el-call-meta-check",
        "status": "initiated",
        "cost": 0.10,
        "duration_seconds": 0,
        "message": "Call accepted",
        # Unsafe fields that MUST be stripped:
        "sip_uri": "sip:+14155552671@telnyx.com",
        "to_number": "+14155552671",  # PII
        "from_number": "+15555555555",
    }
    accepted_result.error_detail = None
    accepted_result.error_category = None

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=accepted_result,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=lead,
                agent=agent,
                client=client,
                settings=settings,
            )

    assert result.status == "dialing"

    stored_session = getattr(mock_db, '_session_obj', None)
    assert stored_session is not None, "CallSession must be created"

    stored_metadata = stored_session.provider_metadata
    if stored_metadata is not None:
        assert "sip_uri" not in stored_metadata, (
            "sip_uri must NOT be stored (unsafe routing data)"
        )
        assert "to_number" not in stored_metadata, (
            "to_number must NOT be stored (PII — lead's phone number)"
        )
        assert "from_number" not in stored_metadata, (
            "from_number must NOT be stored (PII)"
        )
