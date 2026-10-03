"""Phase 1b — Task 1.1: field-policy registry exhaustiveness.

Covers design.md D9 (one policy per field) and config-inheritance spec.md's
"Exactly One Policy Per Field" requirement.
"""

from __future__ import annotations


_LOCKED_STANDARDS_NOT_IN_V1 = {
    "end_call_tool_enabled",
    "analysis_model",
    "memory_window_calls",
    "memory_profile_facts_placement",
    "prompt_assembly_order",
    "load_skill_force_injection",
    "elevenlabs_system_tool_passthrough",
    "technical_retry_max_attempts",
    "max_call_duration_seconds_bounds",
    "post_call_webhook_secret_required",
}


def test_field_policy_registry_is_exhaustive_for_agent_config_v1():
    from app.tenants.agent_config_schema import AgentConfigV1
    from app.tenants.field_policy import FIELD_POLICY

    v1_fields = set(AgentConfigV1.model_fields) - {"schema_version"}
    expected_keys = v1_fields | _LOCKED_STANDARDS_NOT_IN_V1

    assert set(FIELD_POLICY.keys()) == expected_keys


def test_every_field_has_exactly_one_valid_policy_value():
    from app.tenants.field_policy import FIELD_POLICY

    valid_policies = {"locked", "overridable", "client_only", "agent_required"}
    for field, policy in FIELD_POLICY.items():
        assert policy in valid_policies, f"{field} has invalid policy {policy!r}"
