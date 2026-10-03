"""Phase 1b — Task 2.1/2.2: resolver + provenance + purity.

Covers design.md D13 and config-inheritance spec.md's "Pure Resolution With
Per-Field Provenance" requirement.
"""

from __future__ import annotations

import ast
import inspect


def test_resolve_locked_field_always_returns_standard():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={"analysis_model": "gpt-4o"},
        agent_overrides={"analysis_model": "gpt-3.5"},
    )

    field = result.fields["analysis_model"]
    assert field.value == AgentConfigStandard.analysis_model
    assert field.provenance == "standard"


def test_resolve_agent_required_field_returns_agent_value():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={},
        agent_overrides={"voice_id": "voice-abc"},
    )

    field = result.fields["voice_id"]
    assert field.value == "voice-abc"
    assert field.provenance == "agent"


def test_resolve_agent_required_field_missing_is_none_and_listed():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={},
        agent_overrides={},
    )

    field = result.fields["voice_id"]
    assert field.value is None
    assert field.provenance == "agent"
    assert "voice_id" in result.missing_required


def test_resolve_client_only_field_prefers_client_over_standard():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={"language": "es"},
        agent_overrides={"language": "en"},
    )

    field = result.fields["language"]
    assert field.value == "es"
    assert field.provenance == "client"


def test_resolve_client_only_field_falls_back_to_standard_when_unset():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={},
        agent_overrides={},
    )

    field = result.fields["language"]
    assert field.value == AgentConfigStandard.language
    assert field.provenance == "standard"


def test_resolve_overridable_field_prefers_agent_then_client_then_standard():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={"tts_speed": 0.8},
        agent_overrides={"tts_speed": 0.9},
    )
    assert result.fields["tts_speed"].value == 0.9
    assert result.fields["tts_speed"].provenance == "agent"

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={"tts_speed": 0.8},
        agent_overrides={},
    )
    assert result.fields["tts_speed"].value == 0.8
    assert result.fields["tts_speed"].provenance == "client"

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={},
        agent_overrides={},
    )
    assert result.fields["tts_speed"].value == AgentConfigStandard.tts_speed
    assert result.fields["tts_speed"].provenance == "standard"


def test_none_override_value_means_not_set_and_inherits():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    result = resolve_effective_config(
        standard=AgentConfigStandard,
        client_overrides={"tts_speed": 0.8},
        agent_overrides={"tts_speed": None},
    )

    field = result.fields["tts_speed"]
    assert field.value == 0.8
    assert field.provenance == "client"


def test_resolver_is_deterministic_across_repeated_calls():
    from app.tenants.config_resolver import resolve_effective_config
    from app.tenants.config_standard import AgentConfigStandard

    standard = AgentConfigStandard
    client_overrides = {"tts_speed": 0.8, "language": "es"}
    agent_overrides = {"voice_id": "voice-abc", "system_prompt": "hi"}

    first = resolve_effective_config(standard, client_overrides, agent_overrides)
    second = resolve_effective_config(standard, client_overrides, agent_overrides)

    assert first == second


def test_resolver_module_has_no_db_or_io_imports():
    import app.tenants.config_resolver as module

    source = inspect.getsource(module)
    tree = ast.parse(source)

    forbidden_substrings = ("sqlalchemy", "httpx", "requests", "aiohttp", "sqlmodel")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            lowered = name.lower()
            assert not any(forbidden in lowered for forbidden in forbidden_substrings), (
                f"forbidden import found in config_resolver.py: {name}"
            )
