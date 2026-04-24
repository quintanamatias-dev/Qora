"""Unit tests for Agent-based prompt loading — Phase 7 (Task 4.1 RED).

Covers:
- PromptLoader.render_for_agent() uses agent.system_prompt as DB prompt when set
- PromptLoader.render_for_agent() falls back to filesystem prompt.md when system_prompt is None/empty
- PromptLoader.render_for_agent() uses agent.knowledge_base from DB (not filesystem)
- PromptLoader.render_for_agent() uses agent.name for {{agent_name}} template variable
- PromptLoader.render_for_agent() falls back to JAUMPABLO_PROMPT_TEMPLATE when system_prompt is empty
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
    prompt_file.write_text("Hola, soy {{agent_name}} y te llamo de {{broker_name}}.")

    agent = make_agent(name="Valentina", system_prompt=None)
    lead = make_lead()

    # We need a client object for broker_name
    client = MagicMock()
    client.id = "test-client"
    client.broker_name = "Propiedades del Sur"

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
async def test_render_for_agent_uses_db_knowledge_base(tmp_path: Path):
    """When agent.knowledge_base is set, it is appended to the prompt (not filesystem)."""
    from app.prompts.loader import PromptLoader

    agent = make_agent(
        system_prompt="Sos un agente de seguros.",
        knowledge_base="Coberturas: Auto, Vida, Hogar.",
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "Coberturas: Auto, Vida, Hogar." in result
    assert "INFORMACIÓN DE LA EMPRESA" in result


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
async def test_render_for_agent_db_knowledge_takes_precedence_over_filesystem(
    tmp_path: Path,
):
    """DB knowledge_base takes precedence over filesystem knowledge.md."""
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
        knowledge_base="DB knowledge — should appear.",
    )
    lead = make_lead()

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.render_for_agent(agent, lead)

    assert "DB knowledge — should appear." in result
    assert "Filesystem knowledge — should NOT appear." not in result
