"""Approval tests for build_dynamic_variables() extraction.

Spec: outbound-call-trigger — Requirement: Scheduler Reuse Contract
  "Shared build_dynamic_variables() helper extracted from initiation.py"

Approval test approach (refactoring task):
  1. Document current behavior of dynamic variable construction in initiation.py
  2. Write tests that capture that behavior as the "approved output"
  3. After extraction to outbound.dynamic_vars, the same tests must pass against the
     extracted function — proving the refactoring preserved behavior.

These tests are RED because build_dynamic_variables() doesn't exist yet as a
standalone importable helper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_lead(
    name: str = "Ana López",
    phone: str = "+5491123456789",
    status: str = "new",
    notes: str = "Test notes",
    client_id: str = "client-a",
    lead_id: str = "lead-001",
):
    lead = MagicMock()
    lead.id = lead_id
    lead.client_id = client_id
    lead.name = name
    lead.phone = phone
    lead.status = status
    lead.notes = notes
    lead.do_not_call = False
    return lead


def _make_agent(
    name: str = "Jaumpablo",
    client_id: str = "client-a",
):
    agent = MagicMock()
    agent.id = "agent-001"
    agent.name = name
    agent.client_id = client_id
    return agent


def _make_client(
    client_id: str = "client-a",
    name: str = "Quintana Seguros",
):
    client = MagicMock()
    client.id = client_id
    client.name = name
    return client


# ---------------------------------------------------------------------------
# RED — build_dynamic_variables does not exist yet in outbound module
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_dynamic_variables_returns_lead_name():
    """GIVEN a lead, agent, and client
    WHEN build_dynamic_variables is called
    THEN the result includes 'lead_name' matching the lead's name.
    """
    from app.outbound.dynamic_vars import build_dynamic_variables

    db = AsyncMock()
    lead = _make_lead(name="Ana López")
    agent = _make_agent()
    client = _make_client()

    # Mock the custom fields service to return empty (no car/insurance data)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.leads.lead_custom_fields_service.get_all",
            AsyncMock(return_value={}),
        )
        vars_ = await build_dynamic_variables(db=db, lead=lead, agent=agent, client=client)

    assert vars_["lead_name"] == "Ana López"
    assert vars_["_lead_name_"] == "Ana López"


@pytest.mark.asyncio
async def test_build_dynamic_variables_includes_company_name():
    """GIVEN a client with name 'Quintana Seguros'
    WHEN build_dynamic_variables is called
    THEN company_name and _company_name_ match the client name.
    """
    from app.outbound.dynamic_vars import build_dynamic_variables

    db = AsyncMock()
    lead = _make_lead()
    agent = _make_agent()
    client = _make_client(name="Quintana Seguros")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.leads.lead_custom_fields_service.get_all",
            AsyncMock(return_value={}),
        )
        vars_ = await build_dynamic_variables(db=db, lead=lead, agent=agent, client=client)

    assert vars_["company_name"] == "Quintana Seguros"
    assert vars_["_company_name_"] == "Quintana Seguros"


@pytest.mark.asyncio
async def test_build_dynamic_variables_includes_agent_name():
    """GIVEN an agent with name 'Jaumpablo'
    WHEN build_dynamic_variables is called
    THEN agent_name and _agent_name_ match the agent name.
    """
    from app.outbound.dynamic_vars import build_dynamic_variables

    db = AsyncMock()
    lead = _make_lead()
    agent = _make_agent(name="Jaumpablo")
    client = _make_client()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.leads.lead_custom_fields_service.get_all",
            AsyncMock(return_value={}),
        )
        vars_ = await build_dynamic_variables(db=db, lead=lead, agent=agent, client=client)

    assert vars_["agent_name"] == "Jaumpablo"
    assert vars_["_agent_name_"] == "Jaumpablo"


@pytest.mark.asyncio
async def test_build_dynamic_variables_returns_dict_with_required_keys():
    """GIVEN valid lead/agent/client
    WHEN build_dynamic_variables is called
    THEN result contains the complete set of expected keys.
    """
    from app.outbound.dynamic_vars import build_dynamic_variables

    db = AsyncMock()
    lead = _make_lead()
    agent = _make_agent()
    client = _make_client()

    EXPECTED_KEYS = {
        "lead_name", "_lead_name_",
        "company_name", "_company_name_",
        "agent_name", "_agent_name_",
        "car_make", "_car_make_",
        "car_model", "_car_model_",
        "car_year", "_car_year_",
        "current_insurance", "_current_insurance_",
        "lead_status", "lead_notes",
        "broker_name", "_broker_name_",
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.leads.lead_custom_fields_service.get_all",
            AsyncMock(return_value={}),
        )
        vars_ = await build_dynamic_variables(db=db, lead=lead, agent=agent, client=client)

    for key in EXPECTED_KEYS:
        assert key in vars_, f"Expected key '{key}' missing from dynamic variables"
