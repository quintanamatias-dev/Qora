"""Unit tests for PromptLoader — T1.1 and T2.1.

Covers:
- T1.1: load_prompt, load_knowledge, render, sanitization, fallback
- T2.1: knowledge injection, no-file behavior, truncation
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_client(
    broker_name: str = "Quintana Seguros",
    agent_name: str = "Jaumpablo",
    client_id: str = "quintana-seguros",
) -> MagicMock:
    """Create a mock Client object."""
    client = MagicMock()
    client.id = client_id
    client.broker_name = broker_name
    client.agent_name = agent_name
    return client


def make_lead(
    name: str = "Carlos Méndez",
    car_make: str = "Toyota",
    car_model: str = "Corolla",
    car_year: int = 2021,
    current_insurance: str | None = None,
) -> MagicMock:
    """Create a mock Lead object."""
    lead = MagicMock()
    lead.name = name
    lead.car_make = car_make
    lead.car_model = car_model
    lead.car_year = car_year
    lead.current_insurance = current_insurance
    return lead


# ---------------------------------------------------------------------------
# T1.1 — load_prompt
# ---------------------------------------------------------------------------


def test_load_prompt_returns_template_from_file(tmp_path: Path):
    """load_prompt returns the content of clients/{id}/prompt.md."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    prompt_file = client_dir / "prompt.md"
    prompt_file.write_text("Hola {{lead_name}}, soy {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_prompt("my-client")
    assert result == "Hola {{lead_name}}, soy {{agent_name}}."


def test_load_prompt_falls_back_when_file_not_found(tmp_path: Path):
    """load_prompt falls back to JAUMPABLO_PROMPT_TEMPLATE when prompt.md missing."""
    from app.prompts.loader import PromptLoader
    from app.prompts.insurance_agent import JAUMPABLO_PROMPT_TEMPLATE

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_prompt("nonexistent-client")
    assert result == JAUMPABLO_PROMPT_TEMPLATE


def test_load_prompt_returns_string(tmp_path: Path):
    """load_prompt always returns a string."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_prompt("no-such-client")
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# T1.1 — load_knowledge
# ---------------------------------------------------------------------------


def test_load_knowledge_returns_content_when_file_exists(tmp_path: Path):
    """load_knowledge returns content from clients/{id}/knowledge.md."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    knowledge_file = client_dir / "knowledge.md"
    knowledge_file.write_text("# Coberturas\n- RC: básica\n- Todo riesgo")

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_knowledge("my-client")
    assert result is not None
    assert "Coberturas" in result


def test_load_knowledge_returns_none_when_file_missing(tmp_path: Path):
    """load_knowledge returns None when knowledge.md does not exist."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_knowledge("no-such-client")
    assert result is None


def test_load_knowledge_returns_none_when_client_dir_missing(tmp_path: Path):
    """load_knowledge returns None when client directory itself is missing."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = loader.load_knowledge("ghost-client")
    assert result is None


# ---------------------------------------------------------------------------
# T1.1 — render
# ---------------------------------------------------------------------------


def test_render_returns_string(tmp_path: Path):
    """render returns a non-empty string."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    result = loader.render(client, lead=None)
    assert isinstance(result, str)
    assert len(result) > 100


def test_render_no_unfilled_placeholders(tmp_path: Path):
    """render returns string with NO {{}} placeholders remaining."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    prompt_file = client_dir / "prompt.md"
    prompt_file.write_text(
        "Hola {{lead_name}}, soy {{agent_name}} de {{broker_name}}.\n"
        "Auto: {{car_make}} {{car_model}} {{car_year}}.\n"
        "Seguro: {{current_insurance}}."
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    lead = make_lead()
    result = loader.render(client, lead)

    unfilled = re.findall(r"\{\{[^}]+\}\}", result)
    assert unfilled == [], f"Unfilled placeholders remain: {unfilled}"


def test_render_injects_lead_name(tmp_path: Path):
    """render substitutes {{lead_name}} with the lead's actual name."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Hola {{lead_name}}!")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    lead = make_lead(name="María López")
    result = loader.render(client, lead)

    assert "María López" in result


def test_render_injects_broker_and_agent_name(tmp_path: Path):
    """render substitutes {{broker_name}} and {{agent_name}}."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("{{agent_name}} de {{broker_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", broker_name="Acme", agent_name="Sofía")
    result = loader.render(client, lead=None)

    assert "Sofía" in result
    assert "Acme" in result


def test_render_uses_fallback_for_unknown_client(tmp_path: Path):
    """render falls back to insurance_agent.py for unknown clients."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="no-such-client")
    lead = make_lead()
    result = loader.render(client, lead)

    # Should return a valid string using fallback template
    assert isinstance(result, str)
    assert len(result) > 100


# ---------------------------------------------------------------------------
# T1.1 — sanitization
# ---------------------------------------------------------------------------


def test_render_sanitizes_double_braces_in_lead_name(tmp_path: Path):
    """{{ in lead_name is sanitized to prevent template injection."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Lead: {{lead_name}}. Agent: {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", agent_name="Roberta")
    lead = make_lead(name="}}{{agent_name}}")
    result = loader.render(client, lead)

    # The literal injection attack should NOT cause agent_name to appear twice
    # The rendered agent should be "Roberta" from client, not injected
    assert "Roberta" in result
    # The injection attempt should not create an unintended substitution
    # i.e., the result should not contain "}}{{agent_name}}" literally rendered as injection
    # The sanitized name should be present as a literal string, not as a substituted var
    assert result.count("Roberta") == 1, (
        "Injection: agent_name should appear exactly once (not injected via lead_name)"
    )


def test_render_sanitizes_brace_injection_in_car_make(tmp_path: Path):
    """{{ in car_make field is sanitized before injection."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Auto: {{car_make}}. Agent: {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", agent_name="Roberta")
    lead = make_lead(car_make="{{agent_name}}")
    result = loader.render(client, lead)

    # agent_name should appear only once (from client), not injected via car_make
    assert result.count("Roberta") == 1


# ---------------------------------------------------------------------------
# T2.1 — Knowledge injection
# ---------------------------------------------------------------------------


def test_render_with_knowledge_includes_section_header(tmp_path: Path):
    """When knowledge.md exists, rendered prompt includes ## INFORMACIÓN DE LA EMPRESA."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text("# Coberturas\n- RC básica\n- Todo riesgo")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = loader.render(client, lead=None)

    assert "## INFORMACIÓN DE LA EMPRESA" in result


def test_render_with_knowledge_includes_content(tmp_path: Path):
    """When knowledge.md exists, its content is appended to the rendered prompt."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text("Cobertura especial XYZ disponible.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = loader.render(client, lead=None)

    assert "Cobertura especial XYZ disponible." in result


def test_render_without_knowledge_excludes_section_header(tmp_path: Path):
    """When knowledge.md does NOT exist, ## INFORMACIÓN DE LA EMPRESA is absent."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    # No knowledge.md created

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = loader.render(client, lead=None)

    assert "## INFORMACIÓN DE LA EMPRESA" not in result


def test_render_knowledge_truncated_when_exceeds_2000_tokens(tmp_path: Path):
    """Knowledge is truncated to ≤ 2000 tokens when content is too large."""
    from app.prompts.loader import PromptLoader

    # Create content significantly over 2000 tokens
    # Using word × 1.3 estimation, we need > 2000/1.3 ≈ 1539 words
    large_content = " ".join(["palabra"] * 2000)  # ~2000 words → ~2600 tokens estimated

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text(large_content)

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = loader.render(client, lead=None)

    # Extract the knowledge section and estimate its tokens
    assert "## INFORMACIÓN DE LA EMPRESA" in result
    section_start = result.index("## INFORMACIÓN DE LA EMPRESA")
    injected_section = result[section_start:]
    # Strip the header
    knowledge_injected = injected_section.replace("## INFORMACIÓN DE LA EMPRESA\n", "")
    estimated_tokens = len(knowledge_injected.split()) * 1.3
    assert estimated_tokens <= 2000 * 1.1, (  # 10% tolerance for truncation boundary
        f"Injected knowledge tokens ({estimated_tokens:.0f}) exceed 2000 token limit"
    )


def test_render_knowledge_truncation_logs_warning(tmp_path: Path, caplog):
    """A warning is logged when knowledge is truncated due to token limit."""
    import logging
    from app.prompts.loader import PromptLoader

    large_content = " ".join(["palabra"] * 2000)

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text(large_content)

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")

    with caplog.at_level(logging.WARNING):
        loader.render(client, lead=None)

    assert any("truncat" in record.message.lower() for record in caplog.records), (
        "Expected a truncation warning log when knowledge exceeds 2000 tokens"
    )


# ---------------------------------------------------------------------------
# T2.1 — Fallback path also works (no prompt.md, no knowledge.md)
# ---------------------------------------------------------------------------


def test_fallback_render_no_knowledge_section(tmp_path: Path):
    """Fallback render (no prompt.md, no knowledge.md) has no knowledge section."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="nonexistent")
    result = loader.render(client, lead=None)

    # Fallback template itself doesn't have this section
    assert "## INFORMACIÓN DE LA EMPRESA" not in result
