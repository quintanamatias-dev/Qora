"""Unit tests for TTS settings — config defaults and endpoint removal verification.

Covers:
- Config defaults: stability=0.4, speed=0.95, similarity_boost=0.75
- GET /api/v1/voice/tts-settings MUST return 404 (endpoint removed per spec)
- Browser (index.html) no longer depends on /api/v1/voice/tts-settings
- Browser reads TTS from Agent API (currentAgentConfig), not from Settings endpoint
- No hardcoded TTS literals in index.html
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Config defaults — Settings still carry TTS defaults for NULL-fallback
# ---------------------------------------------------------------------------


def test_config_default_stability():
    """elevenlabs_stability must default to 0.4."""
    from app.core.config import Settings

    s = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
    )
    assert s.elevenlabs_stability == 0.4


def test_config_default_speed():
    """elevenlabs_speed must default to 0.95."""
    from app.core.config import Settings

    s = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
    )
    assert s.elevenlabs_speed == 0.95


def test_config_default_similarity_boost():
    """elevenlabs_similarity_boost must default to 0.75."""
    from app.core.config import Settings

    s = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
    )
    assert s.elevenlabs_similarity_boost == 0.75


# ---------------------------------------------------------------------------
# TTS settings endpoint removal — must return 404 after cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tts_app():
    """Minimal FastAPI app with only the voice router mounted."""
    from fastapi import FastAPI
    from pydantic import SecretStr

    from app.core.config import Settings
    from app.voice.webhook import router as voice_router

    mini_app = FastAPI()
    mini_app.include_router(voice_router, prefix="/api/v1")

    mini_app.state.settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        elevenlabs_stability=0.4,
        elevenlabs_speed=0.95,
        elevenlabs_similarity_boost=0.75,
    )

    return mini_app


@pytest.mark.anyio
async def test_tts_settings_endpoint_removed(tts_app):
    """GET /api/v1/voice/tts-settings MUST return 404 — endpoint was removed.

    The endpoint served browser clients with config-driven TTS values.
    After the unify-qora-agent-runtime-config change, the browser reads TTS
    directly from the Agent API (/api/v1/clients/{id}/agents). The settings
    endpoint is dead code and has been removed.
    """
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/voice/tts-settings")

    assert resp.status_code == 404, (
        f"Expected 404 (endpoint removed) but got {resp.status_code}. "
        "GET /api/v1/voice/tts-settings must not exist after cleanup."
    )


@pytest.mark.anyio
async def test_tts_settings_endpoint_not_in_router(tts_app):
    """The voice router must not register any route at /tts-settings.

    Triangulation: verify via OpenAPI schema that the path does not appear
    at all, not just that it returns 404 at runtime.
    """
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        openapi = await client.get("/openapi.json")

    paths = openapi.json().get("paths", {})
    tts_paths = [p for p in paths if "tts-settings" in p]
    assert tts_paths == [], (
        f"Found tts-settings route(s) in OpenAPI schema: {tts_paths}. "
        "The endpoint must be removed entirely from the router."
    )


# ---------------------------------------------------------------------------
# Demo page static checks — browser no longer depends on /tts-settings
# ---------------------------------------------------------------------------

_DEMO_PAGE = Path(__file__).parent.parent.parent.parent / "app" / "static" / "index.html"


@pytest.fixture(scope="module")
def demo_html() -> str:
    return _DEMO_PAGE.read_text(encoding="utf-8")


def test_demo_page_does_not_fetch_tts_settings(demo_html: str):
    """The demo page JS must NOT fetch /api/v1/voice/tts-settings.

    TTS values are now read from the Agent API via loadAgentForClient().
    The old endpoint is removed; the browser must not reference it at all.
    """
    assert "tts-settings" not in demo_html, (
        "Demo page must NOT reference '/api/v1/voice/tts-settings'. "
        "TTS is now sourced from the Agent API (currentAgentConfig)."
    )


def test_demo_page_reads_tts_from_agent_api(demo_html: str):
    """The demo page must read TTS config from the Agent API response.

    currentAgentConfig is populated in loadAgentForClient() from the Agent
    API response fields (tts_speed, tts_stability, tts_similarity_boost).
    This proves the browser is agent-driven, not settings-driven.
    """
    assert "currentAgentConfig" in demo_html, (
        "Demo page must have 'currentAgentConfig' — the state variable "
        "that holds per-agent TTS config fetched from the Agent API."
    )
    assert "tts_speed" in demo_html, (
        "Demo page must reference 'tts_speed' — the Agent API field "
        "loaded into currentAgentConfig by loadAgentForClient()."
    )
    assert "tts_stability" in demo_html, (
        "Demo page must reference 'tts_stability' — the Agent API field "
        "loaded into currentAgentConfig by loadAgentForClient()."
    )
    assert "tts_similarity_boost" in demo_html, (
        "Demo page must reference 'tts_similarity_boost' — the Agent API field "
        "loaded into currentAgentConfig by loadAgentForClient()."
    )


def test_demo_page_no_hardcoded_tts_literals(demo_html: str):
    """The demo page must not contain hardcoded TTS numeric literals.

    Former hardcoded values were speed:1.2, stability:0.40, similarity_boost:1.0.
    These must be gone — replaced by dynamic Agent API values.
    """
    assert "speed: 1.2" not in demo_html, (
        "Demo page must NOT contain hardcoded 'speed: 1.2'. "
        "TTS speed must come from currentAgentConfig.tts_speed."
    )
    assert "stability: 0.40" not in demo_html and "stability: 0.4," not in demo_html, (
        "Demo page must NOT contain hardcoded 'stability: 0.40' or 'stability: 0.4,'. "
        "TTS stability must come from currentAgentConfig.tts_stability."
    )
    assert "similarity_boost: 1.0" not in demo_html, (
        "Demo page must NOT contain hardcoded 'similarity_boost: 1.0'. "
        "TTS similarity_boost must come from currentAgentConfig.tts_similarity_boost."
    )


def test_demo_page_sends_conversation_config_override(demo_html: str):
    """The initPayload must include conversation_config_override (with dynamic TTS)."""
    assert "conversation_config_override" in demo_html, (
        "initPayload must include 'conversation_config_override'. "
        "Check buildInitPayload() in index.html."
    )


def test_demo_page_1008_fallback_skips_tts_override(demo_html: str):
    """The demo page must handle 1008 by retrying WITHOUT the TTS override.

    Per spec: if EL rejects with 1008, retry without conversation_config_override.
    The skipTtsOverride flag must be present in the reconnect logic.
    """
    assert "skipTtsOverride" in demo_html, (
        "Demo page must have 'skipTtsOverride' — the flag used to retry "
        "the EL connection without TTS override after a 1008 rejection."
    )
    assert "1008" in demo_html, (
        "Demo page must handle ElevenLabs 1008 error code in ws.onclose."
    )


def test_demo_page_does_not_send_tts_overrides_to_settings(demo_html: str):
    """No legacy ttsBlock or rejectedTtsFields — dead code must be gone."""
    assert "ttsBlock" not in demo_html, (
        "Demo page must NOT contain 'ttsBlock' — removed as dead code."
    )
    assert "rejectedTtsFields" not in demo_html, (
        "Demo page must NOT contain 'rejectedTtsFields' — removed as dead code."
    )


def test_demo_page_tts_does_not_override_voice_id(demo_html: str):
    """The demo page must NOT include voice_id — stays configured in EL dashboard."""
    assert "voice_id" not in demo_html, (
        "Demo page must NOT override voice_id. "
        "Per spec: voice_id stays in ElevenLabs agent dashboard configuration."
    )
