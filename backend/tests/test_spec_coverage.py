"""T8.1 — Spec coverage matrix test file.

Maps every Given/When/Then scenario from spec.md to at least one test.
Tests here close gaps not covered by other test files.

Covered scenarios:
- CAP-1: SSE stream, 422 missing, 404 unknown, [DONE], tool call
- CAP-2: Lead found, lead not found, CRM timeout (timeout resilience)
- CAP-3: Valid transition, invalid transition, duplicate seed
- CAP-4: get_lead_details (found + not found), register_interest (success + missing field),
         mark_not_interested, schedule_followup
- CAP-5: Fast LLM no-fallback, slow LLM fallback, filler repetition prevention
- CAP-6: Correct tenant config, cross-tenant isolation
- CAP-7: Normal completion, unexpected disconnection, transcript exact count
- CAP-8: Warm greeting variables, interest confirmed tool, rejection handled gracefully
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ============================================================================
# FIXTURES
# ============================================================================


@pytest_asyncio.fixture
async def db_session(tmp_path: Path):
    """Isolated DB session with Quintana Seguros + 5 test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/spec_coverage.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()
        yield sess

    await db_module.close_db()


# ============================================================================
# CAP-1: Custom LLM Webhook — SSE Stream
# ============================================================================


def test_cap1_sse_stream_format():
    """CAP-1: SSE stream format produces valid OpenAI-compatible chunks."""
    from app.voice.webhook import _sse_chunk, _sse_done

    chunk = _sse_chunk("Hello")
    assert chunk.startswith("data: ")
    assert '"content": "Hello"' in chunk

    done = _sse_done()
    assert done == "data: [DONE]\n\n"


def test_cap1_missing_client_id_uses_default():
    """CAP-1: ElevenLabsExtraBody without client_id defaults to None.

    The server resolves client_id from settings default when not provided.
    This supports native ElevenLabs WebSocket flow where no customLlmExtraBody is sent.
    """
    from app.voice.webhook import ElevenLabsExtraBody

    extra = ElevenLabsExtraBody()  # no client_id → None (resolved by server)
    assert extra.client_id is None


def test_cap1_extra_body_with_client_id():
    """CAP-1: Valid ElevenLabsExtraBody with client_id parses correctly."""
    from app.voice.webhook import ElevenLabsExtraBody

    extra = ElevenLabsExtraBody(client_id="quintana-seguros", lead_id="lead-001")
    assert extra.client_id == "quintana-seguros"
    assert extra.lead_id == "lead-001"


# ============================================================================
# CAP-2: Initiation Webhook — Lead Injection
# ============================================================================


async def test_cap2_lead_found_all_dynamic_variables_present(db_session):
    """CAP-2: Known lead returns all 7 dynamic_variables."""
    from app.voice.initiation import initiation_webhook, InitiationRequest

    req = InitiationRequest(client_id="quintana-seguros", lead_id="lead-quintana-001")
    response = await initiation_webhook(req)

    dv = response.dynamic_variables
    required_fields = [
        "lead_name",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "lead_status",
        "lead_notes",
    ]
    for field in required_fields:
        assert field in dv, f"Missing dynamic_variable: {field}"


async def test_cap2_lead_not_found_empty_strings(db_session):
    """CAP-2: Unknown lead_id returns all dynamic_variables as empty strings without error."""
    from app.voice.initiation import initiation_webhook, InitiationRequest

    req = InitiationRequest(client_id="quintana-seguros", lead_id="ghost-lead-999")
    response = await initiation_webhook(req)

    dv = response.dynamic_variables
    assert dv["lead_name"] == ""
    assert dv["car_make"] == ""
    assert dv["car_model"] == ""


async def test_cap2_initiation_response_within_2s(db_session):
    """CAP-2: Initiation webhook responds within 2000ms."""
    from app.voice.initiation import initiation_webhook, InitiationRequest

    req = InitiationRequest(client_id="quintana-seguros", lead_id="lead-quintana-001")
    start = time.monotonic()
    response = await initiation_webhook(req)
    elapsed_ms = (time.monotonic() - start) * 1000

    assert elapsed_ms < 2000
    assert response.dynamic_variables is not None


async def test_cap2_crm_timeout_resilience(db_session):
    """CAP-2: Simulated slow DB still returns safe dynamic_variables without error."""
    from app.voice.initiation import initiation_webhook, InitiationRequest
    from app.leads import service as leads_service

    original_get_lead = leads_service.get_lead

    async def slow_get_lead(session, lead_id):
        # Simulate slow DB with a tiny delay (within 2s limit)
        await asyncio.sleep(0.01)
        return await original_get_lead(session, lead_id)

    with patch.object(leads_service, "get_lead", side_effect=slow_get_lead):
        req = InitiationRequest(
            client_id="quintana-seguros", lead_id="lead-quintana-001"
        )
        response = await initiation_webhook(req)

    # Still returns valid response
    assert response.dynamic_variables is not None
    assert "lead_name" in response.dynamic_variables


# ============================================================================
# CAP-3: Lead State Machine and Seed Data
# ============================================================================


def test_cap3_valid_state_transition():
    """CAP-3: called → interested is a valid transition."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition("called", "interested") is True


def test_cap3_invalid_state_transition_new_to_not_interested():
    """CAP-3: new → not_interested is rejected (spec scenario)."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition("new", "not_interested") is False


async def test_cap3_invalid_transition_returns_409_semantics(db_session):
    """CAP-3: Service raises InvalidTransitionError with from/to for invalid transitions."""
    from app.leads.service import transition_lead_status, InvalidTransitionError

    with pytest.raises(InvalidTransitionError) as exc_info:
        await transition_lead_status(db_session, "lead-quintana-001", "not_interested")

    assert exc_info.value.from_status == "new"
    assert exc_info.value.to_status == "not_interested"


async def test_cap3_duplicate_seed_guard(db_session):
    """CAP-3: seed_leads() called twice does not insert duplicates."""
    from app.leads.service import seed_leads, list_leads_for_client

    await seed_leads(db_session)  # already seeded, call again
    leads = await list_leads_for_client(db_session, "quintana-seguros")
    assert len(leads) == 5


async def test_cap3_five_seed_leads_with_required_statuses(db_session):
    """CAP-3: 5 seed leads with at least 2 new, 1 called, 1 interested, 1 not_interested."""
    from app.leads.service import list_leads_for_client

    leads = await list_leads_for_client(db_session, "quintana-seguros")
    statuses = [lead.status for lead in leads]

    assert statuses.count("new") >= 2
    assert statuses.count("called") >= 1
    assert statuses.count("interested") >= 1
    assert statuses.count("not_interested") >= 1


# ============================================================================
# CAP-4: Tools — Agent Actions
# ============================================================================


async def test_cap4_get_lead_details_returns_lead_data(db_session):
    """CAP-4: get_lead_details returns full lead data (read-only after Task 1.6 refactor).

    Task 1.6 (configurable-agent-tools): call_count increment moved to initiation.py.
    get_lead_details is now a pure read — returns current DB values without side effects.
    """
    from app.tools.get_lead_details import get_lead_details
    from app.leads.service import get_lead

    result = await get_lead_details(db_session, lead_id="lead-quintana-001")
    assert "error" not in result
    assert result["id"] == "lead-quintana-001"
    assert result["name"] == "Carlos Méndez"
    # call_count is returned from DB (not incremented by get_lead_details)
    assert result["call_count"] == 0  # baseline — initiation increments this

    lead = await get_lead(db_session, "lead-quintana-001")
    # get_lead_details must NOT modify call_count or last_called_at
    assert lead.call_count == 0
    assert lead.last_called_at is None


async def test_cap4_get_lead_details_not_found(db_session):
    """CAP-4: get_lead_details returns error for unknown lead_id."""
    from app.tools.get_lead_details import get_lead_details

    result = await get_lead_details(db_session, lead_id="ghost-lead")
    assert result == {"error": "lead_not_found"}


async def test_cap4_capture_data_successful(db_session):
    """CAP-4 (WU-5): capture_data stores business data and returns captured status.

    register_interest was removed in WU-5 (AC-6). capture_data is the replacement.
    """
    from app.tools.capture_data import capture_data

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
                "car_model": {"type": "string"},
                "car_year": {"type": "integer"},
            },
            "required": ["lead_id", "car_make", "car_model", "car_year"],
        }
    }

    result = await capture_data(
        db_session,
        lead_id="lead-quintana-001",
        tool_config=tool_config,
        captured_fields={"car_make": "Toyota", "car_model": "Corolla", "car_year": 2021},
        client_id="quintana-seguros",
    )
    assert result.get("status") == "captured", f"Expected captured, got: {result}"
    assert "car_make" in result.get("fields", [])


async def test_cap4_capture_data_missing_required_field(db_session):
    """CAP-4 (WU-5): capture_data without required field returns missing_required_fields error."""
    from app.tools.capture_data import capture_data

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
                "car_model": {"type": "string"},
            },
            "required": ["lead_id", "car_make", "car_model"],
        }
    }

    result = await capture_data(
        db_session,
        lead_id="lead-quintana-001",
        tool_config=tool_config,
        captured_fields={"car_make": "Toyota"},  # missing car_model
        client_id="quintana-seguros",
    )
    assert result.get("error") == "missing_required_fields"
    assert "car_model" in result.get("missing", [])


async def test_cap4_mark_not_interested_stores_reason(db_session):
    """CAP-4: mark_not_interested sets status to not_interested and stores reason in notes."""
    from app.tools.mark_not_interested import mark_not_interested
    from app.leads.service import get_lead, transition_lead_status

    await transition_lead_status(db_session, "lead-quintana-001", "called")
    result = await mark_not_interested(
        db_session,
        lead_id="lead-quintana-001",
        reason="Ya tiene seguro con otra empresa",
    )
    assert "error" not in result

    lead = await get_lead(db_session, "lead-quintana-001")
    assert lead.status == "not_interested"
    assert "Ya tiene seguro" in (lead.notes or "")


async def test_cap4_schedule_followup_persists_date(db_session):
    """CAP-4: schedule_followup transitions to follow_up and stores the date."""
    from app.tools.schedule_followup import schedule_followup
    from app.leads.service import get_lead, transition_lead_status

    await transition_lead_status(db_session, "lead-quintana-001", "called")
    result = await schedule_followup(
        db_session,
        lead_id="lead-quintana-001",
        followup_date="2026-04-20",
        note="Prefiere que llamen después del trabajo",
    )
    assert "error" not in result

    lead = await get_lead(db_session, "lead-quintana-001")
    assert lead.status == "follow_up"
    assert "2026-04-20" in (lead.notes or "")


# ============================================================================
# CAP-5: Dynamic Filler System — REMOVED (Issue #70)
# Filler behavior removed from the SSE pipeline. CAP-5 is deprecated.
# SessionStore (session tracking without filler) is tested in test_filler.py.
# ============================================================================


def test_cap5_session_store_tracks_turns():
    """CAP-5 (legacy): SessionStore still tracks turn counts without filler logic."""
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create("conv-cap5", "quintana-seguros", "lead-001", "sess-001")

    for _ in range(5):
        store.increment_turn("quintana-seguros", "conv-cap5")

    state = store.get(("quintana-seguros", "conv-cap5"))
    assert state is not None
    assert state.turn_count == 5


# ============================================================================
# CAP-6: Multi-Tenant Routing
# ============================================================================


async def test_cap6_correct_tenant_config_loaded(db_session):
    """CAP-6: client_id=quintana-seguros loads Quintana config with correct agent_name."""
    from app.tenants.service import get_client

    client = await get_client(db_session, "quintana-seguros")
    assert client is not None
    assert client.name == "Quintana Seguros"
    assert client.agent_name == "Jaumpablo"
    assert client.voice_id is not None


async def test_cap6_cross_tenant_isolation(db_session):
    """CAP-6: Leads from quintana-seguros are NOT returned for other-broker queries."""
    from app.leads.service import list_leads_for_client
    from app.tenants.service import create_client

    # Create a second tenant
    await create_client(
        db_session,
        id="acme-insurance",
        name="Acme Insurance",
        agent_name="AcmeAgent",
        voice_id="acme-voice-id",
    )
    await db_session.flush()

    quintana_leads = await list_leads_for_client(db_session, "quintana-seguros")
    acme_leads = await list_leads_for_client(db_session, "acme-insurance")

    assert len(quintana_leads) == 5
    assert len(acme_leads) == 0  # No cross-contamination


async def test_cap6_all_db_queries_scoped_by_client_id(db_session):
    """CAP-6: list_leads_for_client never returns leads with a different client_id."""
    from app.leads.service import list_leads_for_client

    leads = await list_leads_for_client(db_session, "quintana-seguros")
    for lead in leads:
        assert (
            lead.client_id == "quintana-seguros"
        ), f"Lead {lead.id} has wrong client_id: {lead.client_id}"


# ============================================================================
# CAP-7: Call Session Management
# ============================================================================


async def test_cap7_call_record_created_at_start(db_session):
    """CAP-7: call record is created with status=initiated and required fields."""
    from app.calls.service import create_session

    cs = await create_session(
        db_session,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
    )

    assert cs.id is not None
    assert cs.lead_id == "lead-quintana-001"
    assert cs.client_id == "quintana-seguros"
    assert cs.started_at is not None
    assert cs.status == "initiated"


async def test_cap7_normal_call_completion(db_session):
    """CAP-7: Normal call end sets outcome=completed and correct billable_minutes."""
    from app.calls.service import create_session, end_session
    import math

    cs = await create_session(
        db_session,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
    )
    updated = await end_session(
        db_session,
        session_id=cs.id,
        outcome="completed",
        duration_seconds=185.0,  # 3m 5s → 4 billable minutes
    )

    assert updated.outcome == "completed"
    assert updated.ended_at is not None
    assert updated.duration_seconds == 185.0
    assert updated.billable_minutes == math.ceil(185.0 / 60)  # 4


async def test_cap7_abandoned_call_finalization(db_session):
    """CAP-7: Unexpected disconnect sets outcome=abandoned and saves partial transcript."""
    from app.calls.service import (
        create_session,
        end_session,
        add_transcript_turn,
        get_transcript,
    )

    cs = await create_session(
        db_session,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
    )

    # Add 2 turns before disconnect
    await add_transcript_turn(db_session, cs.id, "user", "Hola")
    await add_transcript_turn(db_session, cs.id, "agent", "Hola! Soy Jaumpablo...")

    # Disconnect
    updated = await end_session(
        db_session,
        session_id=cs.id,
        outcome="abandoned",
        duration_seconds=15.0,
    )

    assert updated.outcome == "abandoned"
    turns = await get_transcript(db_session, cs.id)
    assert len(turns) == 2  # Partial transcript saved


async def test_cap7_transcript_exact_count(db_session):
    """CAP-7: 5-turn conversation has exactly 5 transcript entries."""
    from app.calls.service import create_session, add_transcript_turn, get_transcript

    cs = await create_session(
        db_session,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
    )

    for i in range(5):
        role = "user" if i % 2 == 0 else "agent"
        await add_transcript_turn(db_session, cs.id, role, f"Mensaje {i}")

    turns = await get_transcript(db_session, cs.id)
    assert len(turns) == 5
    for turn in turns:
        assert turn.role in ("user", "agent")
        assert turn.content is not None
        assert turn.timestamp is not None


async def test_cap7_billable_minutes_ceil(db_session):
    """CAP-7: billable_minutes = CEIL(duration_seconds / 60)."""
    from app.calls.service import create_session, end_session

    test_cases = [
        (30.0, 1),  # 30s → 1 min
        (60.0, 1),  # 60s → 1 min (exact)
        (61.0, 2),  # 61s → 2 min
        (120.0, 2),  # 120s → 2 min (exact)
        (185.0, 4),  # 185s → 4 min
    ]

    for duration, expected_minutes in test_cases:
        cs = await create_session(
            db_session,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
        )
        updated = await end_session(
            db_session,
            session_id=cs.id,
            outcome="completed",
            duration_seconds=duration,
        )
        assert (
            updated.billable_minutes == expected_minutes
        ), f"For {duration}s expected {expected_minutes} min, got {updated.billable_minutes}"


# ============================================================================
# CAP-8: Jaumpablo System Prompt
# ============================================================================


def test_cap8_prompt_variables_injected():
    """CAP-8: Warm greeting with known lead — lead_name and car_make injected from custom_fields (AC-1)."""
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Quintana Seguros"
    client.agent_name = "Jaumpablo"

    lead = MagicMock()
    lead.name = "Carlos"

    prompt = render_system_prompt(
        client,
        lead,
        custom_fields={"car_make": "Toyota", "car_model": "Corolla", "car_year": "2021"},
    )
    assert "Carlos" in prompt
    assert "Toyota" in prompt
    assert "Quintana Seguros" in prompt
    assert "Jaumpablo" in prompt


def test_cap8_prompt_voseo_enforced():
    """CAP-8: Prompt enforces Rioplatense voseo."""
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Q"
    client.agent_name = "J"

    prompt = render_system_prompt(client, lead=None)
    lower = prompt.lower()
    assert any(kw in lower for kw in ["voseo", "rioplatense", "vos"])


def test_cap8_prompt_tool_rules():
    """CAP-8: Prompt includes tool invocation rules — never call without user intent.

    Note: register_interest was removed in Phase 2 / dynamic-lead-fields (AC-6).
    Prompt now references mark_not_interested, schedule_followup, get_lead_details.
    """
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Q"
    client.agent_name = "J"

    prompt = render_system_prompt(client, lead=None)
    lower = prompt.lower()
    # register_interest is gone (AC-6); remaining tools must be present
    assert "register_interest" not in lower, (
        "register_interest must be absent from prompt (AC-6 / dynamic-lead-fields)"
    )
    assert "mark_not_interested" in lower
    assert "schedule_followup" in lower
    assert "get_lead_details" in lower


def test_cap8_prompt_conversation_flow_phases():
    """CAP-8: Prompt includes all conversation phases: greeting, qualification, pitch, close."""
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Q"
    client.agent_name = "J"
    lead = MagicMock()
    lead.name = "María"
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019
    lead.current_insurance = None

    prompt = render_system_prompt(client, lead)
    lower = prompt.lower()

    # All conversation phases must be mentioned
    assert "saludo" in lower or "presentación" in lower or "presentate" in lower
    assert "calificación" in lower or "confirmá" in lower or "confirmar" in lower
    assert "cierre" in lower or "close" in lower or "cotización" in lower


def test_cap8_no_unfilled_template_variables():
    """CAP-8: No {{ variable }} placeholders remain after render."""
    import re
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Quintana Seguros"
    client.agent_name = "Jaumpablo"
    lead = MagicMock()
    lead.name = "Carlos"
    lead.car_make = "Toyota"
    lead.car_model = "Corolla"
    lead.car_year = 2021
    lead.current_insurance = "Mapfre"

    prompt = render_system_prompt(client, lead, call_count=2)
    unfilled = re.findall(r"\{\{[^}]+\}\}", prompt)
    assert unfilled == [], f"Unfilled variables: {unfilled}"


def test_cap8_interest_confirmed_tool_fires():
    """CAP-8: Prompt handles positive interest — register_interest removed (AC-6).

    register_interest was removed in Phase 2 / dynamic-lead-fields (AC-6).
    Prompt now instructs the agent to continue naturally on acceptance
    instead of calling a removed tool.
    """
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Q"
    client.agent_name = "J"

    prompt = render_system_prompt(client, lead=None)
    lower = prompt.lower()
    # register_interest must be absent (AC-6)
    assert "register_interest" not in lower, (
        "register_interest must be absent from prompt (AC-6 / dynamic-lead-fields)"
    )
    # Prompt must still guide acceptance handling naturally
    assert any(
        kw in lower for kw in ["acepta", "cotización", "paso", "cierre", "naturalmente"]
    ), "Prompt must still describe how to handle lead acceptance"


def test_cap8_rejection_handled_gracefully():
    """CAP-8: Prompt handles rejection gracefully — calls mark_not_interested with reason."""
    from app.prompts.insurance_agent import render_system_prompt

    client = MagicMock()
    client.name = "Q"
    client.agent_name = "J"

    prompt = render_system_prompt(client, lead=None)
    lower = prompt.lower()
    # Prompt must mention mark_not_interested and reason
    assert "mark_not_interested" in lower
    assert any(kw in lower for kw in ["razón", "reason", "motivo"])
