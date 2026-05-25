"""Unit tests for ElevenLabsService.sync_soft_timeout — RED phase.

Spec: sdd/elevenlabs-provisioning/spec — Requirement: ElevenLabsService PATCH

Covers:
- Happy path: 200 response → SyncResult(outcome="synced")
- PATCH body shape: only soft_timeout_config, correct field names (timeout_seconds, use_llm_generated_message)
- Authentication: xi-api-key header with the configured API key
- 5xx retry: first 503 then 200 → synced (1 retry on 5xx)
- Both attempts fail (503, 503) → SyncResult(outcome="error"), no exception raised
- Skip when elevenlabs_agent_id is None → SyncResult(outcome="skipped"), no HTTP call
- Skip when all soft_timeout fields are None → SyncResult(outcome="skipped"), no HTTP call
- Timeout handling: ReadTimeout → SyncResult(outcome="error"), no exception raised
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
):
    """Return a mock agent object mirroring the Agent model fields we need."""
    agent = MagicMock()
    agent.elevenlabs_agent_id = elevenlabs_agent_id
    agent.soft_timeout_seconds = soft_timeout_seconds
    agent.soft_timeout_message = soft_timeout_message
    agent.soft_timeout_use_llm = soft_timeout_use_llm
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
