"""Unit tests for PromptLoader — T1.1, T2.1, and CAP-2 memory wiring.

Covers:
- T1.1: load_prompt, load_knowledge, render, sanitization, fallback
- T2.1: knowledge injection, no-file behavior, truncation
- T14-T21: async render with db param, memory injection, placeholder removal,
           boolean/int stringification (CAP-2)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pydantic import SecretStr


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


@pytest.mark.asyncio
async def test_load_prompt_returns_template_from_file(tmp_path: Path):
    """load_prompt returns the content of clients/{id}/prompt.md."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    prompt_file = client_dir / "prompt.md"
    prompt_file.write_text("Hola {{lead_name}}, soy {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_prompt("my-client")
    assert result == "Hola {{lead_name}}, soy {{agent_name}}."


@pytest.mark.asyncio
async def test_load_prompt_falls_back_when_file_not_found(tmp_path: Path):
    """load_prompt falls back to JAUMPABLO_PROMPT_TEMPLATE when prompt.md missing."""
    from app.prompts.loader import PromptLoader
    from app.prompts.insurance_agent import JAUMPABLO_PROMPT_TEMPLATE

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_prompt("nonexistent-client")
    assert result == JAUMPABLO_PROMPT_TEMPLATE


@pytest.mark.asyncio
async def test_load_prompt_returns_string(tmp_path: Path):
    """load_prompt always returns a string."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_prompt("no-such-client")
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# T1.1 — load_knowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_knowledge_returns_content_when_file_exists(tmp_path: Path):
    """load_knowledge returns content from clients/{id}/knowledge.md."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    knowledge_file = client_dir / "knowledge.md"
    knowledge_file.write_text("# Coberturas\n- RC: básica\n- Todo riesgo")

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_knowledge("my-client")
    assert result is not None
    assert "Coberturas" in result


@pytest.mark.asyncio
async def test_load_knowledge_returns_none_when_file_missing(tmp_path: Path):
    """load_knowledge returns None when knowledge.md does not exist."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_knowledge("no-such-client")
    assert result is None


@pytest.mark.asyncio
async def test_load_knowledge_returns_none_when_client_dir_missing(tmp_path: Path):
    """load_knowledge returns None when client directory itself is missing."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    result = await loader.load_knowledge("ghost-client")
    assert result is None


# ---------------------------------------------------------------------------
# T1.1 — render
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_returns_string(tmp_path: Path):
    """render returns a non-empty string."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    result = await loader.render(client, lead=None)
    assert isinstance(result, str)
    assert len(result) > 100


@pytest.mark.asyncio
async def test_render_no_unfilled_placeholders(tmp_path: Path):
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
    result = await loader.render(client, lead)

    unfilled = re.findall(r"\{\{[^}]+\}\}", result)
    assert unfilled == [], f"Unfilled placeholders remain: {unfilled}"


@pytest.mark.asyncio
async def test_render_injects_lead_name(tmp_path: Path):
    """render substitutes {{lead_name}} with the lead's actual name."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Hola {{lead_name}}!")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    lead = make_lead(name="María López")
    result = await loader.render(client, lead)

    assert "María López" in result


@pytest.mark.asyncio
async def test_render_injects_broker_and_agent_name(tmp_path: Path):
    """render substitutes {{broker_name}} and {{agent_name}}."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("{{agent_name}} de {{broker_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", broker_name="Acme", agent_name="Sofía")
    result = await loader.render(client, lead=None)

    assert "Sofía" in result
    assert "Acme" in result


@pytest.mark.asyncio
async def test_render_uses_fallback_for_unknown_client(tmp_path: Path):
    """render falls back to insurance_agent.py for unknown clients."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="no-such-client")
    lead = make_lead()
    result = await loader.render(client, lead)

    # Should return a valid string using fallback template
    assert isinstance(result, str)
    assert len(result) > 100


# ---------------------------------------------------------------------------
# T1.1 — sanitization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_sanitizes_double_braces_in_lead_name(tmp_path: Path):
    """{{ in lead_name is sanitized to prevent template injection."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Lead: {{lead_name}}. Agent: {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", agent_name="Roberta")
    lead = make_lead(name="}}{{agent_name}}")
    result = await loader.render(client, lead)

    # The literal injection attack should NOT cause agent_name to appear twice
    # The rendered agent should be "Roberta" from client, not injected
    assert "Roberta" in result
    # The injection attempt should not create an unintended substitution
    # i.e., the result should not contain "}}{{agent_name}}" literally rendered as injection
    # The sanitized name should be present as a literal string, not as a substituted var
    assert (
        result.count("Roberta") == 1
    ), "Injection: agent_name should appear exactly once (not injected via lead_name)"


@pytest.mark.asyncio
async def test_render_sanitizes_brace_injection_in_car_make(tmp_path: Path):
    """{{ in car_make field is sanitized before injection."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Auto: {{car_make}}. Agent: {{agent_name}}.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client", agent_name="Roberta")
    lead = make_lead(car_make="{{agent_name}}")
    result = await loader.render(client, lead)

    # agent_name should appear only once (from client), not injected via car_make
    assert result.count("Roberta") == 1


# ---------------------------------------------------------------------------
# T2.1 — Knowledge injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_with_knowledge_includes_section_header(tmp_path: Path):
    """When knowledge.md exists, rendered prompt includes ## INFORMACIÓN DE LA EMPRESA."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text("# Coberturas\n- RC básica\n- Todo riesgo")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = await loader.render(client, lead=None)

    assert "## INFORMACIÓN DE LA EMPRESA" in result


@pytest.mark.asyncio
async def test_render_with_knowledge_includes_content(tmp_path: Path):
    """When knowledge.md exists, its content is appended to the rendered prompt."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    (client_dir / "knowledge.md").write_text("Cobertura especial XYZ disponible.")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = await loader.render(client, lead=None)

    assert "Cobertura especial XYZ disponible." in result


@pytest.mark.asyncio
async def test_render_without_knowledge_excludes_section_header(tmp_path: Path):
    """When knowledge.md does NOT exist, ## INFORMACIÓN DE LA EMPRESA is absent."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Sos {{agent_name}}.")
    # No knowledge.md created

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    result = await loader.render(client, lead=None)

    assert "## INFORMACIÓN DE LA EMPRESA" not in result


@pytest.mark.asyncio
async def test_render_knowledge_truncated_when_exceeds_2000_tokens(tmp_path: Path):
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
    result = await loader.render(client, lead=None)

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


@pytest.mark.asyncio
async def test_render_knowledge_truncation_logs_warning(tmp_path: Path, caplog):
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
        await loader.render(client, lead=None)

    assert any(
        "truncat" in record.message.lower() for record in caplog.records
    ), "Expected a truncation warning log when knowledge exceeds 2000 tokens"


# ---------------------------------------------------------------------------
# T2.1 — Fallback path also works (no prompt.md, no knowledge.md)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_render_no_knowledge_section(tmp_path: Path):
    """Fallback render (no prompt.md, no knowledge.md) has no knowledge section."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="nonexistent")
    result = await loader.render(client, lead=None)

    # Fallback template itself doesn't have this section
    assert "## INFORMACIÓN DE LA EMPRESA" not in result


# ---------------------------------------------------------------------------
# CAP-2 memory wiring tests — DB fixture helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db_loader(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros and one lead for loader tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/loader_memory_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Loader Lead",
            phone="+5411000088",
            lead_id="test-lead-loader-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _create_completed_session_for_loader(
    db_module,
    *,
    lead_id: str,
    summary: str,
    ended_at: datetime | None = None,
) -> str:
    """Helper: create a completed CallSession for loader tests."""
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    session_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="completed",
            ended_at=ended_at or datetime.now(timezone.utc),
            summary=summary,
        )
        sess.add(cs)
        await sess.commit()
    return session_id


def make_lead_with_call_count(
    name: str = "Loader Lead",
    call_count: int = 0,
    extracted_facts: dict | None = None,
    lead_id: str = "test-lead-loader-001",
) -> MagicMock:
    """Create a mock Lead with call_count and extracted_facts."""
    lead = MagicMock()
    lead.id = lead_id
    lead.name = name
    lead.car_make = "Toyota"
    lead.car_model = "Corolla"
    lead.car_year = 2021
    lead.current_insurance = None
    lead.call_count = call_count
    lead.extracted_facts = extracted_facts
    return lead


# ---------------------------------------------------------------------------
# T14 — render accepts optional db parameter (backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_accepts_optional_db_parameter_backward_compat(tmp_path: Path):
    """render() works without db — memory defaults to empty strings."""
    from app.prompts.loader import PromptLoader

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text(
        "History: {{call_history}}\n"
        "Facts: {{confirmed_facts}}\n"
        "Returning: {{is_returning_caller}}\n"
        "CallNum: {{call_number}}"
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")
    lead = make_lead_with_call_count()

    # Call WITHOUT db — should work fine with empty memory defaults
    result = await loader.render(client, lead)

    assert isinstance(result, str)
    assert "History: " in result
    assert "Returning: false" in result
    assert "CallNum: 1" in result


# ---------------------------------------------------------------------------
# T15 — _build_variables is async and returns dict with memory keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_variables_is_async_and_returns_dict(tmp_path: Path):
    """_build_variables is async and returns dict including memory keys."""
    import inspect
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    lead = make_lead_with_call_count()

    # Must be a coroutine function
    assert inspect.iscoroutinefunction(
        loader._build_variables
    ), "_build_variables must be an async function"

    result = await loader._build_variables(client, lead, call_count=1)

    assert isinstance(result, dict)
    assert "call_history" in result
    assert "confirmed_facts" in result
    assert "is_returning_caller" in result
    assert "call_number" in result
    # Also existing keys
    assert "lead_name" in result
    assert "broker_name" in result
    assert "agent_name" in result


# ---------------------------------------------------------------------------
# T16 — _build_variables with db and lead populates real memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_variables_with_db_and_lead_populates_real_memory(
    seeded_db_loader, tmp_path
):
    """With db+lead, _build_variables populates call_history with actual summary."""
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    summary = "Cliente interesado en cobertura total."
    await _create_completed_session_for_loader(
        seeded_db_loader,
        lead_id="test-lead-loader-001",
        summary=summary,
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        lead.call_count = 2

        result = await loader._build_variables(client, lead, call_count=2, db=sess)

    assert (
        summary[:50] in result["call_history"]
    ), f"Expected summary in call_history, got: {result['call_history']!r}"
    assert result["is_returning_caller"] == "true"
    assert result["call_number"] == "3"  # call_count=2 → call_number=3


# ---------------------------------------------------------------------------
# T17 — _build_variables with db=None returns empty memory defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_variables_db_none_returns_empty_defaults(tmp_path: Path):
    """db=None → memory variables resolve to empty defaults."""
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    lead = make_lead_with_call_count(call_count=5)

    result = await loader._build_variables(client, lead, call_count=5, db=None)

    assert result["call_history"] == ""
    assert result["confirmed_facts"] == ""
    assert result["is_returning_caller"] == "false"
    # REQ-2.4: when db=None, call_number MUST be "1" regardless of call_count arg
    assert result["call_number"] == "1"


# ---------------------------------------------------------------------------
# T18 — _build_variables with lead=None returns empty memory defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_variables_lead_none_returns_empty_defaults(tmp_path: Path):
    """lead=None → memory variables resolve to empty defaults even with a db."""
    from app.prompts.loader import PromptLoader
    from unittest.mock import MagicMock as MockDB

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()

    # db can be a mock — should not be called when lead is None
    mock_db = MockDB()

    result = await loader._build_variables(client, None, call_count=1, db=mock_db)

    assert result["call_history"] == ""
    assert result["confirmed_facts"] == ""
    assert result["is_returning_caller"] == "false"
    assert result["call_number"] == "1"


# ---------------------------------------------------------------------------
# T19 — Rendered prompt has no literal memory placeholders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rendered_prompt_has_no_literal_placeholders(seeded_db_loader, tmp_path):
    """After render(), no literal {{call_history}}, etc. remain in the output."""
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    await _create_completed_session_for_loader(
        seeded_db_loader,
        lead_id="test-lead-loader-001",
        summary="Prueba de no dejar placeholders.",
    )

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text(
        "Historial:\n{{call_history}}\n"
        "Hechos:\n{{confirmed_facts}}\n"
        "Vuelve: {{is_returning_caller}}\n"
        "Llamada#: {{call_number}}"
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        result = await loader.render(client, lead, db=sess)

    assert "{{call_history}}" not in result
    assert "{{confirmed_facts}}" not in result
    assert "{{is_returning_caller}}" not in result
    assert "{{call_number}}" not in result


# ---------------------------------------------------------------------------
# T20 — is_returning_caller stringified to "true"/"false"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_returning_caller_stringified_true_false(seeded_db_loader, tmp_path):
    """is_returning_caller → 'true' when lead has history, 'false' when no history."""
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Returning: {{is_returning_caller}}")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")

    # Without history — should be "false"
    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        result_no_history = await loader.render(client, lead, db=sess)

    assert "false" in result_no_history
    assert "True" not in result_no_history  # ensure proper lowercasing

    # Now add a completed session
    await _create_completed_session_for_loader(
        seeded_db_loader,
        lead_id="test-lead-loader-001",
        summary="Sesión de prueba para is_returning_caller.",
    )

    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        result_with_history = await loader.render(client, lead, db=sess)

    assert "true" in result_with_history
    assert "True" not in result_with_history  # ensure proper lowercasing


# ---------------------------------------------------------------------------
# T21 — call_number stringified as digit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_number_stringified_digit(seeded_db_loader, tmp_path):
    """call_number appears as digit string: call_count=2 → '3'."""
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text("Llamada número: {{call_number}}")

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        lead.call_count = 2
        result = await loader.render(client, lead, db=sess)

    assert (
        "Llamada número: 3" in result
    ), f"Expected 'Llamada número: 3', got: {result!r}"


# ---------------------------------------------------------------------------
# T42 unit-level — is_returning_caller stringified in rendered template
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_returning_caller_stringified_true_in_rendered_template(
    seeded_db_loader, tmp_path
):
    """T42: is_returning_caller renders as 'true' in the prompt when lead has a completed session.

    REQ-2.8 / CAP-5: The {{is_returning_caller}} placeholder must be substituted
    with the lowercase string 'true' (not 'True') when the lead has at least one
    completed session.
    """
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    # Seed a completed session WITH a summary
    await _create_completed_session_for_loader(
        seeded_db_loader,
        lead_id="test-lead-loader-001",
        summary="Sesión previa — el lead ya fue contactado.",
    )

    client_dir = tmp_path / "my-client"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text(
        "Lead recurrente: {{is_returning_caller}} (true = ya hablaron antes, false = primer contacto)."
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client")

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        result = await loader.render(client, lead, db=sess)

    assert "recurrente: true" in result, (
        f"Expected 'recurrente: true' in rendered prompt when lead has history. "
        f"Got: {result!r}"
    )
    # Must NOT leave placeholder unsubstituted
    assert "{{is_returning_caller}}" not in result


@pytest.mark.asyncio
async def test_is_returning_caller_stringified_false_in_rendered_template(
    seeded_db_loader, tmp_path
):
    """T42: is_returning_caller renders as 'false' in the prompt for a brand-new lead.

    REQ-2.8 / CAP-5: The {{is_returning_caller}} placeholder must be substituted
    with the lowercase string 'false' (not 'False') when the lead has NO completed sessions.
    """
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    # NO completed sessions seeded — fresh lead

    client_dir = tmp_path / "my-client-2"
    client_dir.mkdir()
    (client_dir / "prompt.md").write_text(
        "Lead recurrente: {{is_returning_caller}} (true = ya hablaron antes, false = primer contacto)."
    )

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client(client_id="my-client-2")

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        result = await loader.render(client, lead, db=sess)

    assert "recurrente: false" in result, (
        f"Expected 'recurrente: false' in rendered prompt when lead has no history. "
        f"Got: {result!r}"
    )
    # Must NOT leave placeholder unsubstituted
    assert "{{is_returning_caller}}" not in result


# ---------------------------------------------------------------------------
# T43 — REQ-2.8: Fallback JAUMPABLO_PROMPT_TEMPLATE branch receives memory kwarg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_jaumpablo_template_receives_memory_kwarg(
    seeded_db_loader, tmp_path
):
    """REQ-2.8 / T43: When the template is JAUMPABLO_PROMPT_TEMPLATE (fallback),
    render() must build memory context and pass the memory kwarg to
    render_system_prompt so that real call data (e.g. call_number) is reflected.

    We verify this by:
    1. Seeding a lead with call_count=1 (1 completed call already)
    2. Calling render() WITHOUT a prompt.md file → uses JAUMPABLO_PROMPT_TEMPLATE fallback
    3. Monkeypatching render_system_prompt to capture the memory kwarg
    4. Asserting the captured memory kwarg is NOT None and has correct call_number
    """
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    # Seed a completed session so memory is real
    await _create_completed_session_for_loader(
        seeded_db_loader,
        lead_id="test-lead-loader-001",
        summary="Llamada previa — cliente interesado.",
    )

    loader = PromptLoader(clients_dir=tmp_path)  # no prompt.md → fallback
    client = make_client(client_id="nonexistent-fallback-client")

    captured_memory: list = []

    import app.prompts.insurance_agent as insurance_module

    # Save the original function before patching
    _original_render_system_prompt = insurance_module.render_system_prompt

    def spy_render_system_prompt(c, lead_arg, call_count, memory=None):
        captured_memory.append(memory)
        # Call the original (saved reference, not the module attribute, to avoid recursion)
        return _original_render_system_prompt(c, lead_arg, call_count, memory=memory)

    # Monkeypatch render_system_prompt in insurance_agent module
    # (loader imports it from there in the render() method)
    insurance_module.render_system_prompt = spy_render_system_prompt

    try:
        assert seeded_db_loader.async_session_factory is not None
        async with seeded_db_loader.async_session_factory() as sess:
            lead = await get_lead(sess, "test-lead-loader-001")
            assert lead is not None
            lead.call_count = 1  # 1 completed call

            await loader.render(client, lead, db=sess)
    finally:
        # Restore the original function
        insurance_module.render_system_prompt = _original_render_system_prompt

    # The memory kwarg MUST have been passed (not None)
    assert len(captured_memory) == 1, (
        f"render_system_prompt was not called, or called more than once. "
        f"captured_memory: {captured_memory}"
    )
    passed_memory = captured_memory[0]
    assert passed_memory is not None, (
        "render_system_prompt must be called with memory kwarg when db+lead are provided. "
        "Got memory=None — the fallback branch is not wiring memory."
    )
    # The memory must reflect real call data
    assert (
        passed_memory["call_number"] == 2
    ), f"Expected call_number=2 (call_count=1 + 1), got {passed_memory['call_number']!r}"
    assert (
        passed_memory["is_returning_caller"] is True
    ), f"Expected is_returning_caller=True, got {passed_memory['is_returning_caller']!r}"


# ---------------------------------------------------------------------------
# T44 — REQ-2.4: call_number MUST be "1" when db=None or lead=None (fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_call_number_is_1_when_db_is_none(tmp_path: Path):
    """REQ-2.4: When db is None, call_number MUST be '1' regardless of call_count arg.

    The call_count kwarg was the legacy path; with memory-aware render,
    call_count should come from build_memory_context (lead.call_count + 1).
    When no memory is built (db=None), fall back to '1'.
    """
    from app.prompts.loader import PromptLoader

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    lead = make_lead_with_call_count(call_count=5)

    # _build_variables with db=None — call_number MUST default to "1" per REQ-2.4
    vars_dict = await loader._build_variables(client, lead, call_count=5, db=None)
    assert vars_dict["call_number"] == "1", (
        f"REQ-2.4 violation: call_number should be '1' when db=None, "
        f"got {vars_dict['call_number']!r}"
    )


@pytest.mark.asyncio
async def test_fallback_call_number_is_1_when_lead_is_none(tmp_path: Path):
    """REQ-2.4: When lead is None, call_number MUST be '1' regardless of call_count arg."""
    from app.prompts.loader import PromptLoader
    from unittest.mock import MagicMock as MockDB

    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()
    mock_db = MockDB()

    # _build_variables with lead=None — call_number MUST default to "1" per REQ-2.4
    vars_dict = await loader._build_variables(client, None, call_count=5, db=mock_db)
    assert vars_dict["call_number"] == "1", (
        f"REQ-2.4 violation: call_number should be '1' when lead=None, "
        f"got {vars_dict['call_number']!r}"
    )


@pytest.mark.asyncio
async def test_call_number_comes_from_memory_when_available(seeded_db_loader, tmp_path):
    """REQ-2.4: When db AND lead are provided, call_number = memory["call_number"]
    which equals lead.call_count + 1. The call_count kwarg is ignored in that case.
    """
    from app.prompts.loader import PromptLoader
    from app.leads.service import get_lead

    # Lead will have call_count=3 → call_number should be 4
    loader = PromptLoader(clients_dir=tmp_path)
    client = make_client()

    assert seeded_db_loader.async_session_factory is not None
    async with seeded_db_loader.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-loader-001")
        assert lead is not None
        lead.call_count = 3  # 3 completed calls → call_number should be 4

        # call_count=99 is passed as legacy kwarg — MUST be ignored when db+lead present
        vars_dict = await loader._build_variables(client, lead, call_count=99, db=sess)

    # call_number MUST come from memory (lead.call_count + 1 = 4), NOT from call_count=99
    assert vars_dict["call_number"] == "4", (
        f"REQ-2.4: call_number should be '4' (lead.call_count=3 + 1), "
        f"got {vars_dict['call_number']!r}. The call_count kwarg must be ignored."
    )
