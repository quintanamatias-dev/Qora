"""Phase 2 (agent-config-revisions-routing) — Task 2.1: AgentConfigV1 schema.

Covers design.md D5 (field scope) and spec.md's "AgentConfigV1 Schema
Validation" requirement.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


_FULL_PAYLOAD = {
    "schema_version": "v1",
    "system_prompt": "You are a helpful assistant.",
    "voice_id": "voice-abc123",
    "tts_model": "eleven_v4_turbo",
    "tts_speed": 0.95,
    "tts_stability": 0.4,
    "tts_similarity_boost": 0.75,
    "model": "gpt-4.1-mini",
    "temperature": 0.7,
    "max_tokens": 300,
    "tools_enabled": ["get_lead_details"],
}


def test_agent_config_v1_requires_system_prompt_and_voice_id():
    from app.tenants.agent_config_schema import AgentConfigV1

    payload = dict(_FULL_PAYLOAD)
    del payload["system_prompt"]
    with pytest.raises(ValidationError):
        AgentConfigV1(**payload)

    payload = dict(_FULL_PAYLOAD)
    del payload["voice_id"]
    with pytest.raises(ValidationError):
        AgentConfigV1(**payload)


def test_agent_config_v1_accepts_full_payload_without_goal():
    from app.tenants.agent_config_schema import AgentConfigV1

    config = AgentConfigV1(**_FULL_PAYLOAD)
    assert config.schema_version == "v1"
    assert config.goal is None


def test_agent_config_v1_accepts_optional_goal():
    from app.tenants.agent_config_schema import AgentConfigV1

    config = AgentConfigV1(**_FULL_PAYLOAD, goal="Book a demo call.")
    assert config.goal == "Book a demo call."


def test_agent_config_v1_pins_schema_version():
    from app.tenants.agent_config_schema import AgentConfigV1

    with pytest.raises(ValidationError):
        AgentConfigV1(**{**_FULL_PAYLOAD, "schema_version": "v2"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_call_duration_seconds", 10),
        ("max_call_duration_seconds", 10000),
        ("tts_speed", 0.1),
        ("tts_speed", 5.0),
        ("tts_stability", -0.1),
        ("tts_stability", 1.5),
        ("tts_similarity_boost", -0.1),
        ("tts_similarity_boost", 1.5),
        ("soft_timeout_seconds", 0.1),
        ("soft_timeout_seconds", 20.0),
    ],
)
def test_agent_config_v1_rejects_out_of_range_values(field, value):
    from app.tenants.agent_config_schema import AgentConfigV1

    with pytest.raises(ValidationError):
        AgentConfigV1(**{**_FULL_PAYLOAD, field: value})


def test_agent_config_v1_accepts_boundary_values():
    from app.tenants.agent_config_schema import AgentConfigV1

    config = AgentConfigV1(
        **{
            **_FULL_PAYLOAD,
            "max_call_duration_seconds": 30,
            "soft_timeout_seconds": 0.5,
        }
    )
    assert config.max_call_duration_seconds == 30
    assert config.soft_timeout_seconds == 0.5

    config = AgentConfigV1(
        **{
            **_FULL_PAYLOAD,
            "max_call_duration_seconds": 7200,
            "soft_timeout_seconds": 8.0,
        }
    )
    assert config.max_call_duration_seconds == 7200
    assert config.soft_timeout_seconds == 8.0
