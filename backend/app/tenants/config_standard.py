"""QORA standard configuration (design.md D10, D17).

AgentConfigStandard is the code-defined floor of every locked field's value
plus the Qora default for every overridable/client_only field. It lives in
code, not the database (D10): no API or panel can write to it, and changing
a value requires a reviewed PR that bumps STANDARD_VERSION.

Values are drawn from design.md's field-policy table; model/tts_model are
confirmed from the production agent the user deliberately tuned (D17).
"""

from __future__ import annotations

from dataclasses import dataclass, field


STANDARD_VERSION = "2026-10-02.1"


@dataclass(frozen=True)
class _AgentConfigStandard:
    # Overridable fields — Qora default, client/agent may override
    tts_model: str = "eleven_v4_turbo"
    tts_speed: float = 0.95
    tts_stability: float = 0.4
    tts_similarity_boost: float = 0.75
    model: str = "gpt-4.1-mini"
    temperature: float = 0.7
    max_tokens: int = 300
    tools_enabled: list[str] = field(default_factory=lambda: ["get_lead_details"])
    first_message: str | None = None
    turn_eagerness: str | None = "normal"
    soft_timeout_seconds: float | None = None
    soft_timeout_message: str | None = None
    soft_timeout_use_llm: bool | None = None
    voicemail_detection_enabled: bool | None = True
    max_call_duration_seconds: int | None = 120

    # client_only field — no platform default, set once per client (D16)
    language: str | None = None

    # Locked Qora standards — never overridden at any level
    end_call_tool_enabled: bool = True
    analysis_model: str = "gpt-4o-mini"
    memory_window_calls: int = 3
    memory_profile_facts_placement: str = (
        "end of prompt, after memory, lead-evidenced facts only"
    )
    prompt_assembly_order: str = (
        "fixed content first, variable content (lead data, memory, time) last"
    )
    load_skill_force_injection: str = (
        "load_skill tool always present when the agent has a skills registry.yaml"
    )
    elevenlabs_system_tool_passthrough: str = (
        "forward every EL system tool not already claimed by a Qora tool name"
    )
    technical_retry_max_attempts: int = 2
    max_call_duration_seconds_bounds: tuple[int, int] = (30, 7200)
    post_call_webhook_secret_required: str = (
        "enforced when QORA_WEBHOOK_AUTH_ENABLED=true"
    )


AgentConfigStandard = _AgentConfigStandard()
