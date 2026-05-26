"""Unit tests for Jaumpablo system prompt template rendering.

Tests verify:
- render_system_prompt(client, lead) returns string with all variables filled
- name injected correctly
- agent_name injected correctly
- lead name and car data injected
- call_count > 1 triggers returning caller context
- No unfilled {{ variables }} remain in output
- filler_instructions present in prompt

Covers: T6.1 (prompt rendering tests) + CAP-8 scenarios.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_client(
    name: str = "Quintana Seguros",
    agent_name: str = "Jaumpablo",
) -> MagicMock:
    """Create a mock Client object."""
    client = MagicMock()
    client.name = name
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
# T6.1: render_system_prompt — variable injection
# ---------------------------------------------------------------------------


def test_render_returns_string():
    """render_system_prompt() returns a non-empty string."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead)
    assert isinstance(result, str)
    assert len(result) > 100


def test_name_injected():
    """name is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client(name="Acme Seguros")
    lead = make_lead()
    result = render_system_prompt(client, lead)
    assert "Acme Seguros" in result


def test_agent_name_injected():
    """agent_name is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client(agent_name="Roberta")
    lead = make_lead()
    result = render_system_prompt(client, lead)
    assert "Roberta" in result


def test_lead_name_injected():
    """lead name is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(name="María López")
    result = render_system_prompt(client, lead)
    assert "María López" in result


def test_car_make_injected():
    """Car make is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(car_make="Honda")
    result = render_system_prompt(client, lead)
    assert "Honda" in result


def test_car_model_injected():
    """Car model is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(car_model="Civic")
    result = render_system_prompt(client, lead)
    assert "Civic" in result


def test_car_year_injected():
    """Car year is correctly substituted in the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(car_year=2022)
    result = render_system_prompt(client, lead)
    assert "2022" in result


def test_no_unfilled_template_variables():
    """No {{ variable }} placeholders remain in rendered output."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead)
    # Check for any remaining {{ ... }} patterns
    unfilled = re.findall(r"\{\{[^}]+\}\}", result)
    assert unfilled == [], f"Unfilled variables found: {unfilled}"


def test_filler_instructions_present():
    """Prompt includes explicit instructions for contextual fillers."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead)
    # Must contain filler-related instructions
    lower = result.lower()
    assert any(
        keyword in lower
        for keyword in [
            "filler",
            "dale",
            "a ver",
            "mmm",
            "primer token",
            "primeras palabras",
        ]
    ), "Prompt must contain filler instructions"


def test_voseo_present_in_prompt():
    """Prompt specifies Rioplatense voseo language."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead)
    lower = result.lower()
    assert any(
        keyword in lower for keyword in ["voseo", "rioplatense", "vos", "hablás"]
    ), "Prompt must include voseo/Rioplatense specification"


def test_call_count_1_is_first_caller():
    """call_count=1 renders without 'returning caller' context."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead, call_count=1)
    # Should be a valid prompt
    assert isinstance(result, str)
    assert len(result) > 100


def test_call_count_greater_than_1_triggers_returning_context():
    """call_count > 1 adds returning caller context to the prompt."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result_first = render_system_prompt(client, lead, call_count=1)
    result_returning = render_system_prompt(client, lead, call_count=3)

    # Returning call prompt should differ from first call
    assert (
        result_first != result_returning
    ), "Prompt should differ for returning callers"


def test_render_without_lead_uses_defaults():
    """render_system_prompt(client, lead=None) renders safely without lead data."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    result = render_system_prompt(client, lead=None)
    assert isinstance(result, str)
    # No unfilled templates
    unfilled = re.findall(r"\{\{[^}]+\}\}", result)
    assert unfilled == [], f"Unfilled variables found: {unfilled}"


def test_current_insurance_injected_when_present():
    """current_insurance value is included in prompt when lead has one."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(current_insurance="Mapfre")
    result = render_system_prompt(client, lead)
    assert "Mapfre" in result


def test_current_insurance_fallback_when_none():
    """Prompt handles None current_insurance gracefully."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead(current_insurance=None)
    result = render_system_prompt(client, lead)
    # Should not crash and no unfilled templates
    assert isinstance(result, str)
    unfilled = re.findall(r"\{\{[^}]+\}\}", result)
    assert unfilled == []


def test_tool_invocation_rules_present():
    """Prompt includes instructions about tool usage rules."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client()
    lead = make_lead()
    result = render_system_prompt(client, lead)
    lower = result.lower()
    # Must reference tool usage instructions
    assert any(
        keyword in lower
        for keyword in [
            "register_interest",
            "get_lead_details",
            "mark_not_interested",
            "schedule_followup",
        ]
    ), "Prompt must include tool invocation rules"


def test_quintana_specific_prompt_content():
    """Quintana Seguros prompt references insurance context."""
    from app.prompts.insurance_agent import render_system_prompt

    client = make_client(name="Quintana Seguros")
    lead = make_lead()
    result = render_system_prompt(client, lead)
    lower = result.lower()
    assert any(
        keyword in lower for keyword in ["seguro", "cotización", "cobertura", "póliza"]
    ), "Prompt should reference insurance context"
