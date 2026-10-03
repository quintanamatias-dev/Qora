"""Phase 1b — Task 1.2: Qora standard module.

Covers design.md D10/D17 and qora-standards spec.md's "Every locked field has
a non-empty standard value" requirement.
"""

from __future__ import annotations


def test_agent_config_standard_has_value_for_every_locked_field():
    from app.tenants.config_standard import AgentConfigStandard
    from app.tenants.field_policy import FIELD_POLICY

    locked_fields = {
        field for field, policy in FIELD_POLICY.items() if policy == "locked"
    }

    for field in locked_fields:
        value = getattr(AgentConfigStandard, field)
        assert value is not None, f"{field} has no standard value"


def test_standard_version_is_a_non_empty_string():
    from app.tenants.config_standard import STANDARD_VERSION

    assert isinstance(STANDARD_VERSION, str)
    assert STANDARD_VERSION != ""


def test_standard_values_match_d17_production_read():
    from app.tenants.config_standard import AgentConfigStandard

    assert AgentConfigStandard.model == "gpt-4.1-mini"
    assert AgentConfigStandard.tts_model == "eleven_v4_turbo"


def test_agent_config_standard_is_immutable():
    import pytest

    from app.tenants.config_standard import AgentConfigStandard

    with pytest.raises((AttributeError, TypeError)):
        AgentConfigStandard.model = "gpt-4o"
