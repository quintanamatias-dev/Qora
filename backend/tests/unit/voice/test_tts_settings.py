"""Unit tests for TTS settings — config defaults and endpoint removal verification.

Covers:
- Config defaults: stability=0.4, speed=0.95, similarity_boost=0.75
- GET /api/v1/voice/tts-settings MUST return 404 (endpoint removed per spec)
"""

from __future__ import annotations

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


@pytest.fixture()
def tts_app():
    """Minimal FastAPI app with only the voice router mounted.

    Function-scoped so the conftest autouse monkeypatch
    (ENABLE_OUTBOUND_CALLS=false) is active before module imports.
    """
    from fastapi import FastAPI
    from pydantic import SecretStr

    from app.core.config import Settings
    from app.voice.webhook import router as voice_router

    mini_app = FastAPI()
    mini_app.include_router(voice_router, prefix="/api/v1")

    mini_app.state.settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),  # B8: now required
        enable_outbound_calls=False,  # Explicit — .env may have true
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

