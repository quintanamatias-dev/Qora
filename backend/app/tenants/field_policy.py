"""QORA field-policy registry (design.md D9).

FIELD_POLICY assigns exactly one policy to every AgentConfigV1 (1a) field
plus every locked Qora standard enumerated in design.md's field-policy
table. The resolver (config_resolver.py) and write-path validation (phase 4)
both treat this registry as exhaustive: a field absent from it is an
unregistered field, not an implicit default.
"""

from __future__ import annotations

from typing import Literal

FieldPolicy = Literal["locked", "overridable", "client_only", "agent_required"]

FIELD_POLICY: dict[str, FieldPolicy] = {
    "system_prompt": "agent_required",
    "goal": "agent_required",
    "voice_id": "agent_required",
    "tts_model": "overridable",
    "tts_speed": "overridable",
    "tts_stability": "overridable",
    "tts_similarity_boost": "overridable",
    "model": "overridable",
    "temperature": "overridable",
    "max_tokens": "overridable",
    "tools_enabled": "overridable",
    "first_message": "overridable",
    "language": "client_only",
    "turn_eagerness": "overridable",
    "soft_timeout_seconds": "overridable",
    "soft_timeout_message": "overridable",
    "soft_timeout_use_llm": "overridable",
    "voicemail_detection_enabled": "overridable",
    "max_call_duration_seconds": "overridable",
    # Locked Qora standards (no AgentConfigV1 counterpart; validated, never overridden)
    "end_call_tool_enabled": "locked",
    "analysis_model": "locked",
    "memory_window_calls": "locked",
    "memory_profile_facts_placement": "locked",
    "prompt_assembly_order": "locked",
    "load_skill_force_injection": "locked",
    "elevenlabs_system_tool_passthrough": "locked",
    "technical_retry_max_attempts": "locked",
    "max_call_duration_seconds_bounds": "locked",
    "post_call_webhook_secret_required": "locked",
}
