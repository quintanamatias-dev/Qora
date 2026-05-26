"""Unit tests for Agent-based prompt loading — Phase 7 (Task 4.1 RED).

Covers:
- PromptLoader.render_for_agent() uses agent.system_prompt as DB prompt when set
- PromptLoader.render_for_agent() falls back to filesystem prompt.md when system_prompt is None/empty
- PromptLoader.render_for_agent() does not append legacy agent.knowledge_base
- PromptLoader.render_for_agent() uses agent.name for {{agent_name}} template variable
- PromptLoader.render_for_agent() falls back to JAUMPABLO_PROMPT_TEMPLATE when system_prompt is empty
- PromptLoader.render_for_agent() uses filesystem system-prompt.md as source of truth, overriding DB
- PromptLoader.load_agent_system_prompt() returns None when file is absent
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent(
    name: str = "Valentina",
    voice_id: str = "v-test",
    system_prompt: str | None = None,
    knowledge_base: str | None = None,
    client_id: str = "test-client",
) -> MagicMock:
    """Create a mock Agent object."""
    agent = MagicMock()
    agent.name = name
    agent.voice_id = voice_id
    agent.system_prompt = system_prompt
    agent.knowledge_base = knowledge_base
    agent.client_id = client_id
    agent.model = "gpt-4o"
    agent.temperature = 0.7
    agent.max_tokens = 300
    return agent


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
# Tests: render_for_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_for_agent_uses_db_system_prompt(tmp_path: Path):
    """When agent.system_prompt is set, render_for_agent uses it as the prompt body."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(
        name="Valentina",
        system_prompt="Sos Valentina, agente de Propiedades del Sur.",
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "Valentina" in result
    assert "Propiedades del Sur" in result


@pytest.mark.asyncio
async def test_render_for_agent_uses_agent_name_in_template_variable(tmp_path: Path):
    """render_for_agent replaces {{agent_name}} with agent.name in a file-based template."""
    from app.prompts.loader import PromptLoader

    # Create a template file that uses {{agent_name}}
    client_dir = tmp_path / "test-client"
    client_dir.mkdir()
    prompt_file = client_dir / "prompt.md"
    prompt_file.write_text("Hola, soy {{agent_name}} y te llamo de {{company_name}}.")

    agent = make_agent(name="Valentina", system_prompt=None)
    lead = make_lead()

    # We need a client object for name
    client = MagicMock()
    client.id = "test-client"
    client.name = "Propiedades del Sur"

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead, client=client)

    assert "Valentina" in result
    assert "{{agent_name}}" not in result


@pytest.mark.asyncio
async def test_render_for_agent_falls_back_to_filesystem_when_no_system_prompt(
    tmp_path: Path,
):
    """When agent.system_prompt is None, render_for_agent falls back to filesystem or JAUMPABLO template."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(system_prompt=None, client_id="fallback-client")
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    # Should return a non-empty string (either file or JAUMPABLO fallback)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_render_for_agent_empty_system_prompt_falls_back(tmp_path: Path):
    """When agent.system_prompt is empty string, render_for_agent falls back to template."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(system_prompt="", client_id="empty-prompt-client")
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    # Falls back to JAUMPABLO template (rendered), which should be non-empty
    assert len(result) > 10


@pytest.mark.asyncio
async def test_render_for_agent_does_not_append_legacy_db_knowledge_base(tmp_path: Path):
    """Agent.knowledge_base is legacy and is not appended automatically."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(
        system_prompt="Sos un agente de seguros.",
        knowledge_base="Coberturas: Auto, Vida, Hogar.",
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "Coberturas: Auto, Vida, Hogar." not in result
    assert "INFORMACIÓN DE LA EMPRESA" not in result


@pytest.mark.asyncio
async def test_render_for_agent_no_knowledge_base_no_section(tmp_path: Path):
    """When agent.knowledge_base is None, the knowledge section is not appended."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(
        system_prompt="Sos un agente de seguros.",
        knowledge_base=None,
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    # No knowledge section
    assert "INFORMACIÓN DE LA EMPRESA" not in result


@pytest.mark.asyncio
async def test_render_for_agent_ignores_db_and_filesystem_knowledge(
    tmp_path: Path,
):
    """Agent path does not append legacy DB or filesystem knowledge."""
    from app.prompts.loader import PromptLoader

    # Create a filesystem knowledge.md that should NOT be used
    client_dir = tmp_path / "test-client"
    client_dir.mkdir()
    (client_dir / "knowledge.md").write_text(
        "Filesystem knowledge — should NOT appear."
    )

    agent = make_agent(
        client_id="test-client",
        system_prompt="Sos agente.",
        knowledge_base="DB knowledge — should NOT appear.",
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "DB knowledge — should NOT appear." not in result
    assert "Filesystem knowledge — should NOT appear." not in result
    assert "INFORMACIÓN DE LA EMPRESA" not in result


# ---------------------------------------------------------------------------
# Filesystem system-prompt.md is source of truth (overrides DB prompt)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_for_agent_filesystem_overrides_db_system_prompt(
    tmp_path: Path,
):
    """Filesystem system-prompt.md overrides agent.system_prompt (DB).

    Priority: filesystem > DB > legacy client fallback.
    When clients/{client_id}/agents/{agent_slug}/system-prompt.md exists,
    it MUST be used even when agent.system_prompt is set in the DB.
    """
    from app.prompts.loader import PromptLoader

    # Set up filesystem structure: clients/my-client/agents/valentina/system-prompt.md
    agent_dir = tmp_path / "my-client" / "agents" / "valentina"
    agent_dir.mkdir(parents=True)
    (agent_dir / "system-prompt.md").write_text(
        "FILESYSTEM PROMPT: Soy Valentina desde el filesystem."
    )

    # Agent with a DB system_prompt that should be overridden
    agent = make_agent(
        name="Valentina",
        system_prompt="DB PROMPT: This should NOT appear — filesystem wins.",
        client_id="my-client",
    )
    # Ensure slug is set so the loader finds the correct directory
    agent.slug = "valentina"
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "FILESYSTEM PROMPT" in result, (
        "Filesystem system-prompt.md must override DB agent.system_prompt. "
        f"Got: {result[:300]!r}"
    )
    assert "DB PROMPT" not in result, (
        "DB agent.system_prompt must NOT appear when filesystem system-prompt.md exists."
    )


@pytest.mark.asyncio
async def test_render_for_agent_falls_back_to_db_when_no_filesystem_prompt(
    tmp_path: Path,
):
    """When filesystem system-prompt.md is absent, DB agent.system_prompt is used.

    This is the legacy fallback: agents not yet migrated to the filesystem layout
    continue to work via their DB-stored system_prompt.
    """
    from app.prompts.loader import PromptLoader

    # No filesystem prompt — agents/valentina/ directory does not exist

    agent = make_agent(
        name="Valentina",
        system_prompt="DB PROMPT: Soy Valentina desde la base de datos.",
        client_id="my-client",
    )
    agent.slug = "valentina"
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "DB PROMPT" in result, (
        "When no filesystem system-prompt.md exists, DB agent.system_prompt must be used. "
        f"Got: {result[:300]!r}"
    )


@pytest.mark.asyncio
async def test_load_agent_system_prompt_returns_content_when_file_exists(
    tmp_path: Path,
):
    """load_agent_system_prompt() returns file content when system-prompt.md is present."""
    from app.prompts.loader import PromptLoader

    agent_dir = tmp_path / "acme-client" / "agents" / "sofia"
    agent_dir.mkdir(parents=True)
    (agent_dir / "system-prompt.md").write_text(
        "Sos Sofia, asistente virtual de Acme."
    )

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_system_prompt("acme-client", "sofia")

    assert result is not None
    assert "Sofia" in result
    assert "Acme" in result


@pytest.mark.asyncio
async def test_load_agent_system_prompt_returns_none_when_file_absent(
    tmp_path: Path,
):
    """load_agent_system_prompt() returns None when system-prompt.md does not exist."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_agent_system_prompt("nonexistent-client", "nonexistent-agent")

    assert result is None


@pytest.mark.asyncio
async def test_render_for_agent_filesystem_prompt_is_rendered_as_template(
    tmp_path: Path,
):
    """Filesystem system-prompt.md supports {{variable}} template substitution.

    Variables like {{agent_name}}, {{lead_name}}, {{company_name}} are substituted
    just like any other template when the filesystem prompt is used.
    """
    from app.prompts.loader import PromptLoader

    agent_dir = tmp_path / "my-client" / "agents" / "sofia"
    agent_dir.mkdir(parents=True)
    (agent_dir / "system-prompt.md").write_text(
        "Hola {{lead_name}}, soy {{agent_name}} de Qora."
    )

    agent = make_agent(
        name="Sofia",
        system_prompt="DB PROMPT: should not appear",
        client_id="my-client",
    )
    agent.slug = "sofia"
    lead = make_lead(name="Juan Pérez")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "Juan Pérez" in result, "{{lead_name}} must be substituted from filesystem prompt"
    assert "Sofia" in result, "{{agent_name}} must be substituted from filesystem prompt"
    assert "{{lead_name}}" not in result, "No unresolved placeholders should remain"
    assert "DB PROMPT" not in result, "DB prompt must be overridden by filesystem"
