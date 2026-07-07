"""Unit tests for ElevenLabsService — sync_soft_timeout and sync_agent_config.

Spec: sdd/elevenlabs-provisioning/spec — Requirement: ElevenLabsService PATCH
Spec: sdd/elevenlabs-config/spec — Requirement: Unified Config Sync

Covers (sync_soft_timeout):
- Happy path: 200 response → SyncResult(outcome="synced")
- PATCH body shape: only soft_timeout_config, correct field names (timeout_seconds, use_llm_generated_message)
- Authentication: xi-api-key header with the configured API key
- 5xx retry: first 503 then 200 → synced (1 retry on 5xx)
- Both attempts fail (503, 503) → SyncResult(outcome="error"), no exception raised
- Skip when elevenlabs_agent_id is None → SyncResult(outcome="skipped"), no HTTP call
- Skip when all soft_timeout fields are None → SyncResult(outcome="skipped"), no HTTP call
- Timeout handling: ReadTimeout → SyncResult(outcome="error"), no exception raised

Covers (sync_agent_config — sdd/elevenlabs-config):
- All three config blocks present → single PATCH, outcome="synced"
- Partial: only soft_timeout set → PATCH with only soft_timeout_config block
- All fields NULL → no HTTP call, outcome="skipped"
- No EL binding → no HTTP call, outcome="skipped"
- 4xx error → outcome="error", no exception
- 5xx retry exhausted → outcome="error", no exception

Covers (_build_config_payload — sdd/elevenlabs-config):
- All three blocks set → merged dict with all three blocks
- Partial NULL combos → only non-NULL blocks present
- All NULL → returns {}
"""

from __future__ import annotations

import pytest
import respx
import httpx
from pydantic import SecretStr
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers: fake agent and settings
# ---------------------------------------------------------------------------


def _make_agent(
    elevenlabs_agent_id: str | None = "el-abc123",
    soft_timeout_seconds: float | None = 3.0,
    soft_timeout_message: str | None = "Mmm...",
    soft_timeout_use_llm: bool | None = False,
    voicemail_detection_enabled: bool | None = None,
    max_call_duration_seconds: int | None = None,
):
    """Return a mock agent object mirroring the Agent model fields we need."""
    agent = MagicMock()
    agent.elevenlabs_agent_id = elevenlabs_agent_id
    agent.soft_timeout_seconds = soft_timeout_seconds
    agent.soft_timeout_message = soft_timeout_message
    agent.soft_timeout_use_llm = soft_timeout_use_llm
    agent.voicemail_detection_enabled = voicemail_detection_enabled
    agent.max_call_duration_seconds = max_call_duration_seconds
    return agent


def _make_settings(api_key: str = "test-xi-api-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key)
    return settings


# ---------------------------------------------------------------------------
# Task 1.1 RED — Happy path: 200 → synced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_happy_path():
    """GIVEN agent with soft_timeout_seconds=3.0 and elevenlabs_agent_id='el-abc123'
    WHEN sync_soft_timeout is called
    THEN PATCH sent to correct URL, response 200, outcome='synced'
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent()
    settings = _make_settings()

    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "synced"
    assert result.error_detail is None
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_patch_body_shape():
    """PATCH body contains only soft_timeout_config with correct field names.

    Verified against real ElevenLabs API (2026-05-24):
    body = {"conversation_config": {"turn": {"soft_timeout_config": {
        "timeout_seconds": 3.0, "message": "Mmm...", "use_llm_generated_message": false
    }}}}
    """
    from app.elevenlabs.service import ElevenLabsService

    agent = _make_agent(
        soft_timeout_seconds=3.0,
        soft_timeout_message="Mmm...",
        soft_timeout_use_llm=False,
    )
    settings = _make_settings()

    captured_request = {}

    def capture(request, route):
        import json
        captured_request["body"] = json.loads(request.content)
        captured_request["headers"] = dict(request.headers)
        return httpx.Response(200, json={})

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=capture
    )

    service = ElevenLabsService(settings=settings)
    await service.sync_soft_timeout(agent)

    body = captured_request["body"]
    assert "conversation_config" in body
    turn = body["conversation_config"]["turn"]
    stc = turn["soft_timeout_config"]
    assert "enabled" not in stc  # ElevenLabs doesn't use 'enabled' field
    assert stc["timeout_seconds"] == 3.0
    assert stc["message"] == "Mmm..."
    assert stc["use_llm_generated_message"] is False


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_xi_api_key_header():
    """PATCH request includes xi-api-key header with the configured API key."""
    from app.elevenlabs.service import ElevenLabsService

    agent = _make_agent()
    settings = _make_settings(api_key="my-secret-key")

    captured_headers = {}

    def capture(request, route):
        captured_headers.update(dict(request.headers))
        return httpx.Response(200, json={})

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=capture
    )

    service = ElevenLabsService(settings=settings)
    await service.sync_soft_timeout(agent)

    assert captured_headers.get("xi-api-key") == "my-secret-key"


# ---------------------------------------------------------------------------
# Task 1.1 RED — 5xx retry: first 503 then 200 → synced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_retry_succeeds_on_second_attempt():
    """GIVEN first call returns 503, second call returns 200
    WHEN sync_soft_timeout is called
    THEN service retries once and outcome='synced'
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent()
    settings = _make_settings()

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=[
            httpx.Response(503, json={"error": "service unavailable"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "synced"


# ---------------------------------------------------------------------------
# Task 1.1 RED — Both attempts fail (503, 503) → error, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_both_attempts_fail_returns_error():
    """GIVEN both attempts return 503
    WHEN sync_soft_timeout is called
    THEN outcome='error', error_detail is set, no exception raised to caller
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent()
    settings = _make_settings()

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=[
            httpx.Response(503, json={"error": "unavailable"}),
            httpx.Response(503, json={"error": "unavailable"}),
        ]
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"
    assert result.error_detail is not None
    assert "503" in result.error_detail


# ---------------------------------------------------------------------------
# Task 1.1 RED — Skip when elevenlabs_agent_id is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_skips_when_no_agent_id():
    """GIVEN elevenlabs_agent_id is None
    WHEN sync_soft_timeout is called
    THEN no HTTP call is made and outcome='skipped'
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(elevenlabs_agent_id=None, soft_timeout_seconds=3.0)
    settings = _make_settings()

    # Register route — it must NOT be called
    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/"
    ).mock(return_value=httpx.Response(200, json={}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "skipped"
    assert not route.called


# ---------------------------------------------------------------------------
# Task 1.1 RED — Skip when all soft timeout fields are None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_skips_when_all_fields_none():
    """GIVEN soft_timeout_seconds, soft_timeout_message, soft_timeout_use_llm all None
    WHEN sync_soft_timeout is called
    THEN no HTTP call is made and outcome='skipped'
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(
        elevenlabs_agent_id="el-abc123",
        soft_timeout_seconds=None,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
    )
    settings = _make_settings()

    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(return_value=httpx.Response(200, json={}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "skipped"
    assert not route.called


# ---------------------------------------------------------------------------
# Task 1.1 RED — Timeout handling → error, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_soft_timeout_handles_read_timeout():
    """GIVEN ElevenLabs API does not respond within timeout
    WHEN sync_soft_timeout is called
    THEN outcome='error', error_detail is set, no exception raised
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent()
    settings = _make_settings()

    # Simulate timeout on both attempts
    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=httpx.ReadTimeout("timed out", request=None)
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_soft_timeout(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"
    assert result.error_detail is not None


# ===========================================================================
# sdd/elevenlabs-config — Phase 1 (Task 1.1 RED): Agent model column tests
# ===========================================================================


def test_agent_model_has_voicemail_detection_enabled_column():
    """Agent model MUST have voicemail_detection_enabled as nullable bool column.

    Spec: sdd/elevenlabs-config — Requirement: Agent Model Fields
    """
    from app.tenants.models import Agent

    mapper = Agent.__mapper__
    assert "voicemail_detection_enabled" in mapper.columns, (
        "Agent model is missing voicemail_detection_enabled column"
    )
    col = mapper.columns["voicemail_detection_enabled"]
    assert col.nullable is True, "voicemail_detection_enabled must be nullable"


def test_agent_model_has_max_call_duration_seconds_column():
    """Agent model MUST have max_call_duration_seconds as nullable int column.

    Spec: sdd/elevenlabs-config — Requirement: Agent Model Fields
    """
    from app.tenants.models import Agent

    mapper = Agent.__mapper__
    assert "max_call_duration_seconds" in mapper.columns, (
        "Agent model is missing max_call_duration_seconds column"
    )
    col = mapper.columns["max_call_duration_seconds"]
    assert col.nullable is True, "max_call_duration_seconds must be nullable"


def test_agent_model_new_columns_default_null():
    """New Agent columns must default to NULL.

    Spec: sdd/elevenlabs-config — Scenario: New agent created without these fields
    """
    from app.tenants.models import Agent

    agent = Agent(
        id="test-id",
        client_id="test-client",
        slug="test-slug",
        name="Test",
        voice_id="voice-abc",
    )
    assert agent.voicemail_detection_enabled is None
    assert agent.max_call_duration_seconds is None


# ===========================================================================
# sdd/elevenlabs-config — Phase 2 (Task 2.2 RED): _build_config_payload tests
# ===========================================================================


def test_build_config_payload_all_three_set():
    """_build_config_payload returns merged dict with all three blocks when all fields set.

    Spec: sdd/elevenlabs-config — Scenario: All three config blocks present
    Correct paths verified from live ElevenLabs API GET response (2026-07-07):
    - voicemail: conversation_config.agent.prompt.built_in_tools.voicemail_detection
    - max_duration: conversation_config.conversation.max_duration_seconds
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        soft_timeout_seconds=3.0,
        soft_timeout_message="Still there?",
        soft_timeout_use_llm=False,
        voicemail_detection_enabled=True,
        max_call_duration_seconds=120,
    )
    payload = _build_config_payload(agent)

    assert "conversation_config" in payload
    assert "turn" in payload["conversation_config"]
    assert "soft_timeout_config" in payload["conversation_config"]["turn"]
    # Voicemail goes under conversation_config.agent.prompt.built_in_tools (NOT platform_settings)
    assert "platform_settings" not in payload
    built_in_tools = payload["conversation_config"]["agent"]["prompt"]["built_in_tools"]
    assert "voicemail_detection" in built_in_tools
    assert built_in_tools["voicemail_detection"] == {"system_tool_type": "voicemail_detection"}
    # max_duration goes under conversation_config.conversation.max_duration_seconds
    assert payload["conversation_config"]["conversation"]["max_duration_seconds"] == 120


def test_build_config_payload_only_soft_timeout():
    """_build_config_payload with only soft_timeout set returns only soft_timeout_config block."""
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        soft_timeout_seconds=2.5,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=None,
        max_call_duration_seconds=None,
    )
    payload = _build_config_payload(agent)

    assert "conversation_config" in payload
    assert "turn" in payload["conversation_config"]
    assert "soft_timeout_config" in payload["conversation_config"]["turn"]
    assert "platform_settings" not in payload
    assert "max_duration_seconds" not in payload.get("conversation_config", {})


def test_build_config_payload_only_voicemail():
    """_build_config_payload with only voicemail set returns only voicemail block.

    When voicemail_detection_enabled is False, voicemail_detection is set to None
    to explicitly disable. When True, system_tool_type is set.
    Correct path: conversation_config.agent.prompt.built_in_tools.voicemail_detection
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        soft_timeout_seconds=None,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=False,
        max_call_duration_seconds=None,
    )
    payload = _build_config_payload(agent)

    assert "platform_settings" not in payload
    built_in_tools = payload["conversation_config"]["agent"]["prompt"]["built_in_tools"]
    assert "voicemail_detection" in built_in_tools
    assert built_in_tools["voicemail_detection"] is None  # False → explicit disable via null
    assert "turn" not in payload.get("conversation_config", {})
    assert "conversation" not in payload.get("conversation_config", {})


def test_build_config_payload_only_max_duration():
    """_build_config_payload with only max_call_duration_seconds set returns only max_duration block.

    Correct path: conversation_config.conversation.max_duration_seconds
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        soft_timeout_seconds=None,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=None,
        max_call_duration_seconds=300,
    )
    payload = _build_config_payload(agent)

    assert "conversation_config" in payload
    assert payload["conversation_config"]["conversation"]["max_duration_seconds"] == 300
    assert "turn" not in payload.get("conversation_config", {})
    assert "agent" not in payload.get("conversation_config", {})
    assert "platform_settings" not in payload


def test_build_config_payload_all_null_returns_empty():
    """_build_config_payload returns {} when all agent config fields are NULL."""
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        soft_timeout_seconds=None,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=None,
        max_call_duration_seconds=None,
    )
    payload = _build_config_payload(agent)
    assert payload == {}


# ===========================================================================
# sdd/elevenlabs-config — Phase 2 (Task 2.1 RED): sync_agent_config tests
# ===========================================================================


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_all_three_blocks_sends_single_patch():
    """GIVEN agent with all three config blocks set → single PATCH, outcome='synced'."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(
        soft_timeout_seconds=3.0,
        soft_timeout_message="Still there?",
        soft_timeout_use_llm=False,
        voicemail_detection_enabled=True,
        max_call_duration_seconds=120,
    )
    settings = _make_settings()

    captured: dict = {}

    def capture(request, route):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(side_effect=capture)

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "synced"
    assert route.call_count == 1
    body = captured["body"]
    assert "turn" in body.get("conversation_config", {})
    assert "max_duration_seconds" in body.get("conversation_config", {}).get("conversation", {})
    built_in_tools = body.get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("built_in_tools", {})
    assert "voicemail_detection" in built_in_tools
    assert built_in_tools["voicemail_detection"] == {"system_tool_type": "voicemail_detection"}
    assert "platform_settings" not in body


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_partial_only_soft_timeout():
    """GIVEN only soft_timeout set → PATCH with only soft_timeout_config block."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(
        soft_timeout_seconds=2.0,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=None,
        max_call_duration_seconds=None,
    )
    settings = _make_settings()
    captured: dict = {}

    def capture(request, route):
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={})

    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(side_effect=capture)

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert result.outcome == "synced"
    body = captured["body"]
    assert "turn" in body.get("conversation_config", {})
    assert "platform_settings" not in body
    assert "agent" not in body.get("conversation_config", {})
    assert "conversation" not in body.get("conversation_config", {})


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_all_null_skips_no_http_call():
    """GIVEN all config fields NULL → no HTTP call, outcome='skipped'."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(
        soft_timeout_seconds=None,
        soft_timeout_message=None,
        soft_timeout_use_llm=None,
        voicemail_detection_enabled=None,
        max_call_duration_seconds=None,
    )
    settings = _make_settings()
    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(return_value=httpx.Response(200, json={}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert result.outcome == "skipped"
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_no_binding_skips():
    """GIVEN no elevenlabs_agent_id → no HTTP call, outcome='skipped'."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(
        elevenlabs_agent_id=None,
        soft_timeout_seconds=3.0,
        voicemail_detection_enabled=True,
        max_call_duration_seconds=120,
    )
    settings = _make_settings()
    route = respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/"
    ).mock(return_value=httpx.Response(200, json={}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert result.outcome == "skipped"
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_4xx_returns_error_no_exception():
    """GIVEN EL API returns 422 → outcome='error', no exception."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(voicemail_detection_enabled=True)
    settings = _make_settings()
    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(return_value=httpx.Response(422, json={"detail": "bad request"}))

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"
    assert result.error_detail is not None
    assert "422" in result.error_detail


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_5xx_retry_exhausted_returns_error():
    """GIVEN EL API returns 503 on both attempts → outcome='error', no exception."""
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(voicemail_detection_enabled=True)
    settings = _make_settings()
    respx.patch(
        "https://api.elevenlabs.io/v1/convai/agents/el-abc123"
    ).mock(side_effect=[
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(503, json={"error": "unavailable"}),
    ])

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"
    assert result.error_detail is not None
