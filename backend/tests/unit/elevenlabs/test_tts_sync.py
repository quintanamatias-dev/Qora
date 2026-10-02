"""Unit tests for ElevenLabs TTS/voice config sync and drift detection.

Spec: production evidence — agent row has tts_speed=1.0, tts_similarity_boost=0.7,
tts_model=eleven_v4_turbo, voice_id=qHkrJuifPpn95wK3rm2A while the ElevenLabs agent
reports speed=1.2, similarity=1.0 — yet Qora marked elevenlabs_sync_status="synced"
because _build_config_payload never sent TTS/voice and PATCH never triggered on
TTS field changes.

Covers:
- _build_config_payload includes conversation_config.tts with the right keys/values
- None TTS fields are omitted from the tts block (NULL-means-skip)
- Patching tts_speed via the agents router triggers a sync
  (_should_trigger_sync with changed_fields={"tts_speed"} -> True)
- sync_agent_config read-back match -> outcome="synced"
- sync_agent_config read-back mismatch (e.g. speed 1.2 vs 1.0) -> outcome="drift"
- sync_agent_config read-back GET failure -> outcome="error"
"""

from __future__ import annotations

import pytest
import respx
import httpx
from pydantic import SecretStr
from unittest.mock import MagicMock


def _make_agent(
    elevenlabs_agent_id: str | None = "el-abc123",
    soft_timeout_seconds: float | None = None,
    soft_timeout_message: str | None = None,
    soft_timeout_use_llm: bool | None = None,
    voicemail_detection_enabled: bool | None = None,
    max_call_duration_seconds: int | None = None,
    voice_id: str | None = "qHkrJuifPpn95wK3rm2A",
    tts_model: str | None = "eleven_v4_turbo",
    tts_speed: float | None = 1.0,
    tts_stability: float | None = 0.4,
    tts_similarity_boost: float | None = 0.7,
):
    """Return a mock agent object mirroring the Agent model TTS/voice fields."""
    agent = MagicMock()
    agent.elevenlabs_agent_id = elevenlabs_agent_id
    agent.soft_timeout_seconds = soft_timeout_seconds
    agent.soft_timeout_message = soft_timeout_message
    agent.soft_timeout_use_llm = soft_timeout_use_llm
    agent.voicemail_detection_enabled = voicemail_detection_enabled
    agent.max_call_duration_seconds = max_call_duration_seconds
    agent.voice_id = voice_id
    agent.tts_model = tts_model
    agent.tts_speed = tts_speed
    agent.tts_stability = tts_stability
    agent.tts_similarity_boost = tts_similarity_boost
    return agent


def _make_settings(api_key: str = "test-xi-api-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key)
    return settings


# ---------------------------------------------------------------------------
# _build_config_payload — tts block
# ---------------------------------------------------------------------------


def test_build_config_payload_includes_tts_block_with_correct_keys_and_values():
    """GIVEN voice_id, tts_model, tts_speed, tts_stability, tts_similarity_boost set
    WHEN _build_config_payload is called
    THEN conversation_config.tts has voice_id, model_id, speed, stability, similarity_boost
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        voice_id="qHkrJuifPpn95wK3rm2A",
        tts_model="eleven_v4_turbo",
        tts_speed=1.2,
        tts_stability=0.5,
        tts_similarity_boost=1.0,
    )
    payload = _build_config_payload(agent)

    tts = payload["conversation_config"]["tts"]
    assert tts == {
        "voice_id": "qHkrJuifPpn95wK3rm2A",
        "model_id": "eleven_v4_turbo",
        "speed": 1.2,
        "stability": 0.5,
        "similarity_boost": 1.0,
    }


def test_build_config_payload_omits_none_tts_fields():
    """GIVEN only voice_id and tts_speed set (others None)
    WHEN _build_config_payload is called
    THEN the tts block contains only the non-None fields
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        voice_id="voice-xyz",
        tts_model=None,
        tts_speed=0.9,
        tts_stability=None,
        tts_similarity_boost=None,
    )
    payload = _build_config_payload(agent)

    tts = payload["conversation_config"]["tts"]
    assert tts == {"voice_id": "voice-xyz", "speed": 0.9}
    assert "model_id" not in tts
    assert "stability" not in tts
    assert "similarity_boost" not in tts


def test_build_config_payload_all_tts_fields_none_omits_tts_block():
    """GIVEN all TTS/voice fields None (and no other config fields)
    WHEN _build_config_payload is called
    THEN no tts block is present and the payload is empty
    """
    from app.elevenlabs.service import _build_config_payload

    agent = _make_agent(
        voice_id=None,
        tts_model=None,
        tts_speed=None,
        tts_stability=None,
        tts_similarity_boost=None,
    )
    payload = _build_config_payload(agent)

    assert payload == {}


# ---------------------------------------------------------------------------
# Router — PATCHing tts_speed triggers sync
# ---------------------------------------------------------------------------


def test_should_trigger_sync_on_tts_speed_change():
    """GIVEN an agent bound to ElevenLabs
    WHEN changed_fields={"tts_speed"}
    THEN _should_trigger_sync returns True
    """
    from app.agents.router import _should_trigger_sync

    agent = MagicMock()
    agent.elevenlabs_agent_id = "el-abc123"

    assert _should_trigger_sync(agent, changed_fields={"tts_speed"}) is True


def test_should_trigger_sync_on_voice_id_change():
    """GIVEN an agent bound to ElevenLabs
    WHEN changed_fields={"voice_id"}
    THEN _should_trigger_sync returns True
    """
    from app.agents.router import _should_trigger_sync

    agent = MagicMock()
    agent.elevenlabs_agent_id = "el-abc123"

    assert _should_trigger_sync(agent, changed_fields={"voice_id"}) is True


def test_should_not_trigger_sync_on_unrelated_field_change():
    """GIVEN an agent bound to ElevenLabs
    WHEN changed_fields={"name"} (not a sync field)
    THEN _should_trigger_sync returns False
    """
    from app.agents.router import _should_trigger_sync

    agent = MagicMock()
    agent.elevenlabs_agent_id = "el-abc123"

    assert _should_trigger_sync(agent, changed_fields={"name"}) is False


# ---------------------------------------------------------------------------
# sync_agent_config — read-back drift verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_readback_match_returns_synced():
    """GIVEN the read-back GET reports the same TTS values that were sent
    WHEN sync_agent_config is called
    THEN outcome='synced'
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(tts_speed=1.2, tts_similarity_boost=1.0)
    settings = _make_settings()

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.get("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "conversation_config": {
                    "tts": {
                        "voice_id": agent.voice_id,
                        "model_id": agent.tts_model,
                        "speed": 1.2,
                        "stability": agent.tts_stability,
                        "similarity_boost": 1.0,
                    }
                }
            },
        )
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "synced"


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_readback_mismatch_returns_drift():
    """GIVEN production evidence: agent row has tts_speed=1.0 but the ElevenLabs
    agent reports speed=1.2 after the PATCH
    WHEN sync_agent_config is called
    THEN outcome='drift' and the mismatched field path is reported
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent(tts_speed=1.0, tts_similarity_boost=0.7)
    settings = _make_settings()

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.get("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "conversation_config": {
                    "tts": {
                        "voice_id": agent.voice_id,
                        "model_id": agent.tts_model,
                        "speed": 1.2,
                        "stability": agent.tts_stability,
                        "similarity_boost": 1.0,
                    }
                }
            },
        )
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "drift"
    assert "conversation_config.tts.speed" in result.drift_fields
    assert "conversation_config.tts.similarity_boost" in result.drift_fields


@pytest.mark.asyncio
@respx.mock
async def test_sync_agent_config_readback_get_failure_returns_error():
    """GIVEN the PATCH succeeds but the read-back GET fails (e.g. 500)
    WHEN sync_agent_config is called
    THEN outcome='error', no exception raised
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    agent = _make_agent()
    settings = _make_settings()

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.get("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    service = ElevenLabsService(settings=settings)
    result = await service.sync_agent_config(agent)

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "get_side_effect",
    [
        httpx.Response(200, content=b"<html>not json</html>"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=["non_json_body", "protocol_error"],
)
@respx.mock
async def test_sync_agent_config_unexpected_readback_failure_returns_error(get_side_effect):
    """GIVEN the PATCH succeeds but the read-back fails in a way that is neither
    a timeout nor a network error
    WHEN sync_agent_config is called
    THEN outcome='error' and nothing is raised, so the caller can record it
    """
    from app.elevenlabs.service import ElevenLabsService, SyncResult

    respx.patch("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.get("https://api.elevenlabs.io/v1/convai/agents/el-abc123").mock(
        side_effect=get_side_effect
    )

    service = ElevenLabsService(settings=_make_settings())
    result = await service.sync_agent_config(_make_agent())

    assert isinstance(result, SyncResult)
    assert result.outcome == "error"
