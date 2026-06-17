"""Phase A: Tests for enriched lead detail response and context-preview endpoint.

Tests cover:
- _lead_to_dict includes email, external_crm_id, external_lead_id, quote_fields
- _compute_quote_fields produces correct fill status from CRM config
- GET /api/v1/leads/{lead_id}/context-preview returns correct structure
- Context preview returns error gracefully when no agent exists
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead(**kwargs: Any):
    """Construct a minimal Lead ORM object for testing _lead_to_dict."""
    from app.leads.models import Lead

    defaults = {
        "id": str(uuid.uuid4()),
        "client_id": "test-client",
        "name": "Test Lead",
        "phone": "+5491100000001",
        "status": "new",
        "call_count": 0,
        "do_not_call": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    lead = Lead(**defaults)
    return lead


def _make_crm_config(custom_fields_list: list[dict], quote_ready_fields: list[str] | None = None):
    """Construct a mock CRMConfig for _compute_quote_fields."""
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    fields = [CustomFieldDef(**f) for f in custom_fields_list]
    cfg = CRMConfig.model_construct(
        provider="airtable",
        base_id="appXXX",
        table_id="tblXXX",
        api_key="KEY",
        match_field="lead_id",
        field_mappings=[],
        custom_fields=fields,
        quote_ready_fields=quote_ready_fields or [],
    )
    return cfg


# ---------------------------------------------------------------------------
# _compute_quote_fields
# ---------------------------------------------------------------------------


def test_compute_quote_fields_empty_without_crm_config():
    """No CRM config → empty list."""
    from app.leads.router import _compute_quote_fields

    result = _compute_quote_fields({}, None)
    assert result == []


def test_compute_quote_fields_filled_required():
    """Quote-ready field with value is filled=True, in_quote_ready_fields=True."""
    from app.leads.router import _compute_quote_fields

    crm_config = _make_crm_config(
        [
            {"field_key": "car_make", "label": "Car Make", "field_type": "string", "required": True},
            {"field_key": "car_model", "label": "Car Model", "field_type": "string", "required": True},
        ],
        quote_ready_fields=["car_make", "car_model"],
    )
    custom_fields = {"car_make": "Toyota", "car_model": ""}
    result = _compute_quote_fields(custom_fields, crm_config)

    assert len(result) == 2
    by_key = {f["field_key"]: f for f in result}

    assert by_key["car_make"]["filled"] is True
    assert by_key["car_make"]["required"] is True
    assert by_key["car_make"]["in_quote_ready_fields"] is True
    assert by_key["car_make"]["source"] == "quote_ready"
    assert by_key["car_make"]["current_value"] == "Toyota"

    assert by_key["car_model"]["filled"] is False
    assert by_key["car_model"]["in_quote_ready_fields"] is True
    assert by_key["car_model"]["current_value"] == ""


def test_compute_quote_fields_missing_quote_ready_sorted_first():
    """Missing quote-ready fields appear before filled ones in sorted output."""
    from app.leads.router import _compute_quote_fields

    crm_config = _make_crm_config(
        [
            {"field_key": "car_make", "label": "Car Make", "field_type": "string", "required": True},
            {"field_key": "age", "label": "Age", "field_type": "integer", "required": True},
            {"field_key": "current_insurance", "label": "Current Insurance", "field_type": "string", "required": False},
        ],
        quote_ready_fields=["car_make", "age"],
    )
    custom_fields = {"car_make": "VW", "current_insurance": "La Caja"}
    # age is missing (quote-ready)

    result = _compute_quote_fields(custom_fields, crm_config)
    assert len(result) == 3

    # First item must be the missing quote-ready field
    assert result[0]["field_key"] == "age"
    assert result[0]["filled"] is False
    assert result[0]["in_quote_ready_fields"] is True


def test_compute_quote_fields_optional_fields_included():
    """Non-quote-ready CRM fields appear with in_quote_ready_fields=False."""
    from app.leads.router import _compute_quote_fields

    crm_config = _make_crm_config(
        [
            {"field_key": "current_insurance", "label": "Current Insurance", "field_type": "string", "required": False},
        ],
        quote_ready_fields=[],
    )
    result = _compute_quote_fields({"current_insurance": "Meridian"}, crm_config)

    assert len(result) == 1
    assert result[0]["required"] is False
    assert result[0]["in_quote_ready_fields"] is False
    assert result[0]["source"] == "crm_provided"
    assert result[0]["filled"] is True


def test_compute_quote_fields_readiness_diverges_from_required():
    """Quote readiness uses quote_ready_fields, NOT the per-field required flag.

    A field marked required=True but absent from quote_ready_fields must NOT be
    treated as a quoting field; a field marked required=False but present in
    quote_ready_fields MUST be treated as a quoting field.
    """
    from app.leads.router import _compute_quote_fields

    crm_config = _make_crm_config(
        [
            # required=True but NOT in quote_ready_fields → crm_provided
            {"field_key": "internal_flag", "label": "Internal Flag", "field_type": "string", "required": True},
            # required=False but IN quote_ready_fields → quote_ready
            {"field_key": "zona", "label": "Zone", "field_type": "string", "required": False},
        ],
        quote_ready_fields=["zona"],
    )
    result = _compute_quote_fields({}, crm_config)
    by_key = {f["field_key"]: f for f in result}

    assert by_key["internal_flag"]["required"] is True
    assert by_key["internal_flag"]["in_quote_ready_fields"] is False
    assert by_key["internal_flag"]["source"] == "crm_provided"

    assert by_key["zona"]["required"] is False
    assert by_key["zona"]["in_quote_ready_fields"] is True
    assert by_key["zona"]["source"] == "quote_ready"


# ---------------------------------------------------------------------------
# _lead_to_dict — Phase A fields
# ---------------------------------------------------------------------------


def test_lead_to_dict_includes_email():
    """_lead_to_dict must include email field (null when not set)."""
    from app.leads.router import _lead_to_dict

    lead = _make_lead(email=None)
    result = _lead_to_dict(lead)
    assert "email" in result
    assert result["email"] is None


def test_lead_to_dict_email_value():
    """_lead_to_dict includes non-null email."""
    from app.leads.router import _lead_to_dict

    lead = _make_lead(email="test@example.com")
    result = _lead_to_dict(lead)
    assert result["email"] == "test@example.com"


def test_lead_to_dict_includes_external_ids():
    """_lead_to_dict includes external_crm_id and external_lead_id."""
    from app.leads.router import _lead_to_dict

    lead = _make_lead(external_crm_id="recABC123", external_lead_id=999)
    result = _lead_to_dict(lead)
    assert result["external_crm_id"] == "recABC123"
    assert result["external_lead_id"] == 999


def test_lead_to_dict_external_ids_null_by_default():
    """_lead_to_dict returns null external IDs when not set."""
    from app.leads.router import _lead_to_dict

    lead = _make_lead()
    result = _lead_to_dict(lead)
    assert result["external_crm_id"] is None
    assert result["external_lead_id"] is None


def test_lead_to_dict_quote_fields_empty_without_crm_config():
    """_lead_to_dict returns empty quote_fields when no CRM config."""
    from app.leads.router import _lead_to_dict

    lead = _make_lead()
    result = _lead_to_dict(lead, crm_config=None)
    assert result["quote_fields"] == []


def test_lead_to_dict_quote_fields_with_crm_config():
    """_lead_to_dict includes annotated quote_fields when CRM config provided."""
    from app.leads.router import _lead_to_dict

    crm_config = _make_crm_config(
        [
            {"field_key": "car_make", "label": "Car Make", "field_type": "string", "required": True},
        ],
        quote_ready_fields=["car_make"],
    )
    lead = _make_lead()
    result = _lead_to_dict(lead, custom_fields={"car_make": "Ford"}, crm_config=crm_config)
    assert len(result["quote_fields"]) == 1
    assert result["quote_fields"][0]["field_key"] == "car_make"
    assert result["quote_fields"][0]["in_quote_ready_fields"] is True
    assert result["quote_fields"][0]["filled"] is True
    assert result["quote_fields"][0]["current_value"] == "Ford"


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{lead_id}/context-preview — integration test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app_client(test_settings, db_engine):
    """HTTPX async client with isolated test DB + FastAPI app."""
    from app.main import app, lifespan

    # Patch DB so the app uses the test DB
    import app.core.database as db_module
    original_factory = db_module.async_session_factory

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    # Restore
    db_module.async_session_factory = original_factory


@pytest_asyncio.fixture
async def seeded_lead(db_session):
    """Create a minimal lead in the test DB and return its ID."""
    from app.leads.models import Lead

    lead_id = str(uuid.uuid4())
    lead = Lead(
        id=lead_id,
        client_id="quintana-seguros",
        name="Test Fernández",
        phone="+5491199999",
        status="new",
        call_count=0,
        do_not_call=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    await db_session.commit()
    return lead_id


@pytest.mark.asyncio
async def test_context_preview_lead_not_found(db_session):
    """GET context-preview returns 404 for unknown lead ID via router function."""
    from app.leads.router import get_lead_context_preview, get_db_session
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        await get_lead_context_preview(
            lead_id="nonexistent-lead-id",
            session=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_context_preview_structure(db_session):
    """Context-preview endpoint returns all required keys."""
    from app.leads.models import Lead
    from app.leads.router import get_lead_context_preview

    lead_id = str(uuid.uuid4())
    lead = Lead(
        id=lead_id,
        client_id="quintana-seguros",
        name="Preview Lead",
        phone="+5491199998",
        status="new",
        call_count=0,
        do_not_call=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    await db_session.commit()

    result = await get_lead_context_preview(lead_id=lead_id, session=db_session)

    # Must have all required keys
    assert "lead_id" in result
    assert "system_prompt_present" in result
    assert "lead_profile" in result
    assert "call_history" in result
    assert "misc_notes" in result
    assert "skills_index" in result
    assert "tools" in result
    assert "model" in result
    assert "temperature" in result
    assert "max_tokens" in result
    assert "is_returning_caller" in result
    assert "call_number" in result
    assert "error" in result

    assert result["lead_id"] == lead_id
    assert isinstance(result["system_prompt_present"], bool)
    assert isinstance(result["call_history"], str)
    assert isinstance(result["is_returning_caller"], bool)
    # call_number = call_count + 1 = 0 + 1 = 1
    assert result["call_number"] == 1


@pytest.mark.asyncio
async def test_context_preview_no_agent_returns_error(db_session):
    """Context-preview gracefully returns error message when no agent exists."""
    from app.leads.models import Lead
    from app.leads.router import get_lead_context_preview

    # Use a client_id with no agent in the test DB
    lead_id = str(uuid.uuid4())
    lead = Lead(
        id=lead_id,
        client_id="no-agents-client",
        name="Orphan Lead",
        phone="+5491100000099",
        status="new",
        call_count=0,
        do_not_call=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    await db_session.commit()

    result = await get_lead_context_preview(lead_id=lead_id, session=db_session)

    # Should not raise — should return graceful error
    assert result["error"] is not None
    assert "agent" in result["error"].lower() or "no active agent" in result["error"].lower()
    # Other fields still present
    assert "call_number" in result
    assert result["call_number"] == 1
    # Model config absent when assembly could not run
    assert result["model"] is None
    assert result["temperature"] is None
    assert result["max_tokens"] is None


# ---------------------------------------------------------------------------
# Runtime-parity tests — preview must match build_voice_context() output
#
# These tests prove the preview is derived from the SAME runtime assembly path
# the agent uses (get_default_agent + build_voice_context). The literal,
# non-system-prompt context fields are compared field-by-field against a direct
# build_voice_context() call, so the preview cannot silently diverge.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_quintana_lead(db_session):
    """Seed quintana-seguros (client + default agent) and a lead with custom fields.

    Returns the lead_id. quintana's default agent has a real system_prompt, so the
    preview exercises the full build_voice_context() path with a present prompt.
    """
    from app.tenants.service import seed_quintana
    from app.leads.models import Lead
    from app.leads import lead_custom_fields_service as cf_service

    await seed_quintana(db_session)

    lead_id = str(uuid.uuid4())
    lead = Lead(
        id=lead_id,
        client_id="quintana-seguros",
        name="Parity Tester",
        phone="+5491100000111",
        status="new",
        call_count=2,
        do_not_call=False,
        extracted_facts={"misc_notes": "Prefiere ser contactado por la tarde."},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    await db_session.flush()

    # Seed custom fields so the lead_profile block is non-trivial
    await cf_service.upsert(
        db_session, lead_id=lead_id, client_id="quintana-seguros",
        field_key="car_make", field_value="Toyota",
    )
    await cf_service.upsert(
        db_session, lead_id=lead_id, client_id="quintana-seguros",
        field_key="car_model", field_value="Corolla",
    )
    await db_session.commit()
    return lead_id


@pytest.mark.asyncio
async def test_context_preview_matches_runtime_assembly(db_session, seeded_quintana_lead):
    """Preview literal fields equal build_voice_context() output for the same lead."""
    from app.leads.router import get_lead_context_preview
    from app.leads.service import get_lead
    from app.tenants.service import get_client, get_default_agent
    from app.voice.context import build_voice_context

    lead_id = seeded_quintana_lead

    # Runtime path — exactly what the agent receives.
    lead = await get_lead(db_session, lead_id)
    agent = await get_default_agent(db_session, "quintana-seguros")
    client = await get_client(db_session, "quintana-seguros")
    assert agent is not None
    assert client is not None

    ctx = await build_voice_context(agent=agent, lead=lead, db=db_session, client=client)

    result = await get_lead_context_preview(lead_id=lead_id, session=db_session)

    assert result["error"] is None

    # system prompt: presence reflects runtime, content never exposed.
    assert result["system_prompt_present"] == bool(ctx.system_prompt and ctx.system_prompt.strip())
    assert "system_prompt" not in result  # content must NOT leak

    # Literal non-system-prompt context — must match runtime context exactly.
    expected_profile = "" if ctx.skip_lead_profile_in_assembly else (ctx.lead_profile or "")
    assert result["lead_profile"] == expected_profile
    assert result["misc_notes"] == (ctx.misc_notes or "")
    assert result["skills_index"] == ctx.skills_index

    # Tool names are derived from the same built tool definitions the agent gets.
    expected_tool_names = None
    if ctx.tools:
        expected_tool_names = [t["function"]["name"] for t in ctx.tools if t.get("function")]
        expected_tool_names = expected_tool_names or None
    assert result["tools"] == expected_tool_names

    # Model config mirrors runtime config — no invented values.
    assert result["model"] == ctx.model
    assert result["temperature"] == ctx.temperature
    assert result["max_tokens"] == ctx.max_tokens


@pytest.mark.asyncio
async def test_context_preview_redacts_system_prompt_content(db_session, seeded_quintana_lead):
    """Preview indicates system prompt presence but never returns its content."""
    from app.leads.router import get_lead_context_preview
    from app.tenants.service import get_default_agent

    lead_id = seeded_quintana_lead

    agent = await get_default_agent(db_session, "quintana-seguros")
    assert agent is not None
    system_prompt = agent.system_prompt
    assert system_prompt  # quintana agent has a real prompt

    result = await get_lead_context_preview(lead_id=lead_id, session=db_session)

    # Presence is signalled but the prompt text appears nowhere in the response.
    assert result["system_prompt_present"] is True
    serialized = str(result)
    # A distinctive chunk of the system prompt must not appear in any field.
    distinctive = system_prompt.strip().splitlines()[0][:30]
    assert distinctive not in serialized


@pytest.mark.asyncio
async def test_context_preview_misc_notes_match_runtime(db_session, seeded_quintana_lead):
    """misc_notes block is the literal runtime value (faithful, not reformatted)."""
    from app.leads.router import get_lead_context_preview
    from app.leads.service import get_lead
    from app.tenants.service import get_client, get_default_agent
    from app.voice.context import build_voice_context

    lead_id = seeded_quintana_lead
    lead = await get_lead(db_session, lead_id)
    agent = await get_default_agent(db_session, "quintana-seguros")
    client = await get_client(db_session, "quintana-seguros")

    ctx = await build_voice_context(agent=agent, lead=lead, db=db_session, client=client)
    result = await get_lead_context_preview(lead_id=lead_id, session=db_session)

    # The seeded misc_note must round-trip identically through both paths.
    assert "Prefiere ser contactado por la tarde." in result["misc_notes"]
    assert result["misc_notes"] == (ctx.misc_notes or "")
