"""Unit tests for TTS settings — config defaults and HTTP endpoint.

Covers:
- Config defaults: stability=0.4, speed=0.95, similarity_boost=0.75
- GET /api/v1/voice/tts-settings returns correct shape and values from config
- Endpoint is reachable and returns JSON with expected keys
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Config defaults
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
# TTS settings endpoint — shape and values
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

    # Inject known settings into app.state so the endpoint can read them
    mini_app.state.settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        elevenlabs_stability=0.4,
        elevenlabs_speed=0.95,
        elevenlabs_similarity_boost=0.75,
    )

    return mini_app


@pytest.mark.anyio
async def test_tts_settings_endpoint_returns_200(tts_app):
    """GET /api/v1/voice/tts-settings must return HTTP 200."""
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/voice/tts-settings")

    assert resp.status_code == 200


@pytest.mark.anyio
async def test_tts_settings_endpoint_returns_json_with_expected_keys(tts_app):
    """GET /api/v1/voice/tts-settings must return JSON with stability, speed, similarity_boost."""
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/voice/tts-settings")

    data = resp.json()
    assert "stability" in data, f"Missing 'stability' key. Got: {list(data.keys())}"
    assert "speed" in data, f"Missing 'speed' key. Got: {list(data.keys())}"
    assert "similarity_boost" in data, (
        f"Missing 'similarity_boost' key. Got: {list(data.keys())}"
    )


@pytest.mark.anyio
async def test_tts_settings_endpoint_returns_config_values(tts_app):
    """GET /api/v1/voice/tts-settings must return the config default values."""
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/voice/tts-settings")

    data = resp.json()
    assert data["stability"] == 0.4, f"Expected stability=0.4, got {data['stability']}"
    assert data["speed"] == 0.95, f"Expected speed=0.95, got {data['speed']}"
    assert data["similarity_boost"] == 0.75, (
        f"Expected similarity_boost=0.75, got {data['similarity_boost']}"
    )


@pytest.mark.anyio
async def test_tts_settings_endpoint_no_extra_keys(tts_app):
    """TTS settings response must not include voice_id or style overrides.

    Per spec: voice_id stays in EL dashboard; style adds latency and is omitted.
    """
    async with AsyncClient(
        transport=ASGITransport(app=tts_app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/v1/voice/tts-settings")

    data = resp.json()
    assert "voice_id" not in data, (
        "TTS settings must NOT include voice_id — stays in EL dashboard."
    )
    assert "style" not in data, (
        "TTS settings must NOT include style — adds latency, excluded by spec."
    )


# ---------------------------------------------------------------------------
# Demo page static checks — TTS wiring
# ---------------------------------------------------------------------------

_DEMO_PAGE = Path(__file__).parent.parent.parent.parent / "app" / "static" / "index.html"


@pytest.fixture(scope="module")
def demo_html() -> str:
    return _DEMO_PAGE.read_text(encoding="utf-8")


def test_demo_page_does_not_fetch_tts_settings(demo_html: str):
    """The demo page JS must NOT fetch /api/v1/voice/tts-settings.

    ElevenLabs V3 Conversational does not support TTS overrides (speed/stability/
    similarity_boost). The endpoint stays on the backend but the client no longer
    calls it — removed to eliminate 3 pointless reconnection attempts on every start.
    """
    assert "tts-settings" not in demo_html, (
        "Demo page must NOT fetch '/api/v1/voice/tts-settings'. "
        "V3 Conversational rejects TTS overrides with 1008 — the client-side fetch "
        "and retry logic was removed. Backend endpoint stays for future use."
    )


def test_demo_page_sends_conversation_config_override(demo_html: str):
    """The initPayload must include conversation_config_override (empty, for future use)."""
    assert "conversation_config_override" in demo_html, (
        "initPayload must include 'conversation_config_override' (empty object). "
        "Check buildInitPayload() in index.html."
    )


def test_demo_page_does_not_send_tts_overrides(demo_html: str):
    """The demo page must NOT have a live ttsBlock sending TTS override fields.

    V3 Conversational ignores them and previously caused 1008 disconnect loops.
    Speed is now controlled via system-prompt instructions instead.
    """
    assert "ttsBlock" not in demo_html, (
        "Demo page must NOT contain 'ttsBlock'. "
        "V3 Conversational rejects TTS overrides — the ttsBlock was removed entirely."
    )
    assert "rejectedTtsFields" not in demo_html, (
        "Demo page must NOT contain 'rejectedTtsFields'. "
        "The 1008 fallback/retry mechanism was removed as dead code."
    )


def test_demo_page_tts_does_not_override_voice_id(demo_html: str):
    """The demo page must NOT include voice_id — stays configured in EL dashboard."""
    assert "voice_id" not in demo_html, (
        "Demo page must NOT override voice_id. "
        "Per spec: voice_id stays in ElevenLabs agent dashboard configuration."
    )
