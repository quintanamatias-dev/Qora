"""agent-config-inheritance Phase 4 — Task 4.1: AgentConfigV2 sparse overrides.

Covers design.md D12/D18 and spec.md's "AgentConfigV2 Sparse Overrides, V1
Frozen" requirement: every field optional, no inherited defaults baked in,
locked/client_only fields rejected as unregistered.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_agent_config_v2_accepts_sparse_payload():
    from app.tenants.agent_config_schema import AgentConfigV2

    config = AgentConfigV2(system_prompt="You are helpful.", voice_id="voice-abc123")
    assert config.schema_version == "v2"
    assert config.system_prompt == "You are helpful."
    assert config.voice_id == "voice-abc123"
    assert config.model is None
    assert config.goal is None


def test_agent_config_v2_accepts_empty_payload():
    from app.tenants.agent_config_schema import AgentConfigV2

    config = AgentConfigV2()
    assert config.schema_version == "v2"
    assert config.model_dump(exclude_none=True) == {"schema_version": "v2"}


def test_agent_config_v2_rejects_locked_field():
    from app.tenants.agent_config_schema import AgentConfigV2

    with pytest.raises(ValidationError):
        AgentConfigV2(end_call_tool_enabled=True)


def test_agent_config_v2_rejects_client_only_field():
    from app.tenants.agent_config_schema import AgentConfigV2

    with pytest.raises(ValidationError):
        AgentConfigV2(language="es")


def test_agent_config_v2_enforces_overridable_field_bounds():
    from app.tenants.agent_config_schema import AgentConfigV2

    with pytest.raises(ValidationError):
        AgentConfigV2(tts_speed=99.0)


def test_agent_config_v2_patch_accepts_note():
    from app.tenants.agent_config_schema import AgentConfigV2Patch

    patch = AgentConfigV2Patch(temperature=0.5, note="tuning")
    assert patch.temperature == 0.5
    assert patch.note == "tuning"
