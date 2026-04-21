"""Integration E2E tests for the full session continuity memory cycle (CAP-5).

T21 — RED: Full memory cycle test.

Covers CAP-5 scenarios:
- First call creates a CallSession with lead_id persisted (via custom-LLM path route)
- /end closes the session as 'completed'
- Summarizer data is injected directly into DB (simulating summarizer ran)
- Second call initiation returns is_returning_caller=True with non-empty call_history

T33 — RED: Second call custom-LLM prompt contains prior summary content.
T34 — RED: call_number renders as 2 in prompt on second call.
T35 — RED: is_returning_caller renders as 'true' in prompt when prior session exists.

Uses in-memory SQLite, mocks OpenAI (via respx), and bypasses the actual summarizer
by directly updating the DB (the summarizer's output is the unit under test here, not
the summarizer itself).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response
from pydantic import SecretStr
from sqlalchemy import select


# ---------------------------------------------------------------------------
# SSE helpers (mirroring other test files for consistency)
# ---------------------------------------------------------------------------


def _make_sse_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
) -> bytes:
    """Build a fake OpenAI SSE data line."""
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if content is not None:
        choice["delta"]["content"] = content
    payload = {
        "id": "chatcmpl-e2e-test",
        "object": "chat.completion.chunk",
        "choices": [choice],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _build_simple_stream(*tokens: str) -> bytes:
    chunks = b""
    for token in tokens:
        chunks += _make_sse_chunk(content=token)
    chunks += _make_sse_chunk(finish_reason="stop")
    chunks += b"data: [DONE]\n\n"
    return chunks


# ---------------------------------------------------------------------------
# App fixture — wires webhook + calls + initiation routers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def e2e_app_client(tmp_path: Path):
    """Create a test app with all three routers for the full E2E cycle.

    Includes:
    - webhook router (for custom-LLM call initiation)
    - calls router (for /end endpoint)
    - initiation router (for /initiation second call)
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e_continuity_test.db",
    )

    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        # Create a specific lead for our E2E test (not using seed_leads to avoid conflicts)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Roberto Perez",
            phone="+5411155500",
            car_make="Toyota",
            car_model="Corolla",
            car_year=2020,
            current_insurance="La Caja",
            lead_id="lead-quintana-001",
        )
        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from app.calls.router import router as calls_router
    from app.voice.initiation import router as initiation_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")
    test_app.include_router(calls_router, prefix="/api/v1")
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T21 — RED: Full memory cycle — first call then second call has history
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_full_memory_cycle_first_call_then_second_call_has_history(
    e2e_app_client,
    monkeypatch,
):
    """CAP-5: Full end-to-end memory cycle.

    Flow:
    1. First call: POST to custom-LLM path route with lead_id → CallSession created
    2. POST /end for first call → session completed
    3. Simulate summarizer ran (directly update DB — avoids real OpenAI call)
    4. Second call: POST /initiation → response must include memory from first call

    This test is RED until:
    - CAP-3 is active (lead_id persisted on session creation) — Done in Batch 1
    - CAP-4 is active (/end closes session correctly) — Done in Batch 1
    - CAP-5 initiation loads completed sessions for the lead — Already in initiation.py

    After Batch 1 fixes, this test should pass (T22 glue = none needed).
    """
    client, db_module = e2e_app_client

    # Prevent _schedule_summarize from creating background asyncio tasks
    # that may leak between tests. We'll inject summary data manually.
    import app.calls.service as calls_service_mod

    monkeypatch.setattr(
        calls_service_mod, "_schedule_summarize", lambda session_id: None
    )

    LEAD_ID = "lead-quintana-001"
    CONV_ID = "conv_first_call_abc"

    # ------------------------------------------------------------------
    # Step 1: First call simulation — POST to custom-LLM path route
    # ------------------------------------------------------------------
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola Roberto, ¿cómo estás?"),
            headers={"content-type": "text/event-stream"},
        )
    )

    first_call_body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": CONV_ID,
        },
    }

    resp = await client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=first_call_body,
    )
    assert (
        resp.status_code == 200
    ), f"First call failed: {resp.status_code} — {resp.text}"

    # Verify CallSession created with lead_id and conversation_id
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.elevenlabs_conversation_id == CONV_ID)
        )
        cs_first = result.scalar_one_or_none()

    assert cs_first is not None, (
        f"CallSession with elevenlabs_conversation_id='{CONV_ID}' not found. "
        "Batch 1 fix (T05) must persist conversation_id on session creation."
    )
    assert cs_first.lead_id == LEAD_ID, (
        f"CallSession.lead_id should be '{LEAD_ID}', got {cs_first.lead_id!r}. "
        "Batch 1 fix (T05) must persist lead_id on session creation."
    )
    assert (
        cs_first.status == "initiated"
    ), f"Expected status='initiated', got {cs_first.status!r}"

    first_session_id = cs_first.id

    # ------------------------------------------------------------------
    # Step 2: POST /end for first call
    # ------------------------------------------------------------------
    end_resp = await client.post(
        f"/api/v1/calls/{CONV_ID}/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": LEAD_ID,
        },
    )
    assert (
        end_resp.status_code == 200
    ), f"/end failed: {end_resp.status_code} — {end_resp.text}"

    # Verify session is now completed
    async with db_module.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.id == first_session_id)
        )
        cs_after_end = result.scalar_one_or_none()

    assert cs_after_end is not None
    assert (
        cs_after_end.status == "completed"
    ), f"Expected status='completed' after /end, got {cs_after_end.status!r}"
    assert (
        cs_after_end.closed_reason == "user_hangup"
    ), f"Expected closed_reason='user_hangup', got {cs_after_end.closed_reason!r}"

    # ------------------------------------------------------------------
    # Step 3: Simulate summarizer ran — directly update DB
    # ------------------------------------------------------------------
    # Inject summary and facts into the CallSession and Lead to mimic what
    # generate_summary_and_facts() would produce after a real GPT call.
    from app.leads.models import Lead
    from app.calls.models import CallSession as CS

    SUMMARY_TEXT = "Cliente preguntó por seguro del Toyota Corolla 2020. Tiene La Caja actualmente."
    EXTRACTED_FACTS = {"current_insurance": "La Caja", "interest_level": 70}

    async with db_module.async_session_factory() as sess:
        # Update CallSession
        result = await sess.execute(select(CS).where(CS.id == first_session_id))
        cs = result.scalar_one_or_none()
        assert cs is not None
        cs.summary = SUMMARY_TEXT
        cs.extracted_facts = EXTRACTED_FACTS

        # Update Lead (mimic _merge_facts_into_lead)
        lead_result = await sess.execute(select(Lead).where(Lead.id == LEAD_ID))
        lead = lead_result.scalar_one_or_none()
        assert lead is not None
        lead.summary_last_call = SUMMARY_TEXT
        lead.extracted_facts = EXTRACTED_FACTS
        lead.call_count = lead.call_count or 0  # already incremented by /end

        await sess.commit()

    # ------------------------------------------------------------------
    # Step 4: Second call initiation
    # ------------------------------------------------------------------
    init_resp = await client.post(
        "/api/v1/voice/initiation",
        params={"client_id": "quintana-seguros", "lead_id": LEAD_ID},
        json={},
    )
    assert (
        init_resp.status_code == 200
    ), f"Second call initiation failed: {init_resp.status_code} — {init_resp.text}"

    dv = init_resp.json().get("dynamic_variables", {})

    # ------------------------------------------------------------------
    # CAP-5 assertions
    # ------------------------------------------------------------------

    # is_returning_caller MUST be True (completed session exists)
    is_returning = dv.get("is_returning_caller")
    assert is_returning is True or str(is_returning).lower() == "true", (
        f"Expected is_returning_caller=True for second call, got {is_returning!r}. "
        "initiation.py must load completed sessions for the lead."
    )

    # call_history MUST be non-empty and contain the summary snippet
    call_history = dv.get("call_history", "")
    assert call_history, (
        f"Expected non-empty call_history for second call, got {call_history!r}. "
        "initiation.py must format completed sessions into call_history."
    )
    assert (
        "Toyota" in call_history
        or "La Caja" in call_history
        or "preguntó" in call_history
    ), f"call_history should contain summary content from first call, got: {call_history!r}"

    # confirmed_facts MUST be non-empty (extracted_facts were set)
    confirmed_facts = dv.get("confirmed_facts", "")
    assert confirmed_facts, (
        f"Expected non-empty confirmed_facts for second call, got {confirmed_facts!r}. "
        "initiation.py must format Lead.extracted_facts into confirmed_facts."
    )
    assert (
        "La Caja" in confirmed_facts
    ), f"confirmed_facts should mention current_insurance='La Caja', got: {confirmed_facts!r}"

    # call_number MUST be >= 2
    call_number = dv.get("call_number", 0)
    assert call_number >= 2, (
        f"Expected call_number >= 2 for returning caller, got {call_number!r}. "
        "call_number is (lead.call_count + 1) at initiation time."
    )


# ---------------------------------------------------------------------------
# Triangulation: First call — no history (CAP-5 Scenario: First call — no history)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_initiation_has_no_history(e2e_app_client):
    """CAP-5: First call for a brand-new lead → call_history='', is_returning_caller=False.

    Triangulation test: confirms the absence of history for a fresh lead.
    This exercises the opposite code path from the memory cycle test.
    """
    client, db_module = e2e_app_client

    init_resp = await client.post(
        "/api/v1/voice/initiation",
        params={"client_id": "quintana-seguros", "lead_id": "lead-quintana-001"},
        json={},
    )
    assert (
        init_resp.status_code == 200
    ), f"Initiation failed: {init_resp.status_code} — {init_resp.text}"

    dv = init_resp.json().get("dynamic_variables", {})

    # No completed sessions → call_history must be empty string
    call_history = dv.get("call_history", "UNSET")
    assert (
        call_history == ""
    ), f"Expected call_history='' for first call (no history), got {call_history!r}"

    # is_returning_caller must be False
    is_returning = dv.get("is_returning_caller")
    assert (
        is_returning is False
    ), f"Expected is_returning_caller=False for first call, got {is_returning!r}"

    # call_number must be 1 (no prior calls)
    call_number = dv.get("call_number", 0)
    assert (
        call_number == 1
    ), f"Expected call_number=1 for first call, got {call_number!r}"


# ---------------------------------------------------------------------------
# Fixture: E2E app client with a lead seeded with one completed session
# (for T33-T35 custom-LLM prompt content tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def e2e_memory_prompt_client(tmp_path: Path):
    """E2E app for testing custom-LLM prompt memory injection.

    Seeds a lead with one completed CallSession + summary + extracted_facts so
    the second call renders with real memory content.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e_memory_prompt_test.db",
    )

    await db_module.init_db(settings)

    LEAD_ID = "lead-e2e-prompt-001"

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.calls.models import CallSession
        from app.leads.models import Lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Ana Torres",
            phone="+5411155503",
            car_make="Ford",
            car_model="Focus",
            car_year=2018,
            current_insurance="Zurich",
            lead_id=LEAD_ID,
        )
        await sess.flush()

        # One completed session — simulating a prior call was summarized
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=LEAD_ID,
            status="completed",
            summary="El cliente preguntó por cobertura de granizo para el Ford Focus",
            started_at=datetime(2026, 4, 10, 14, 0, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 4, 10, 14, 20, 0, tzinfo=timezone.utc),
        )
        sess.add(cs)
        await sess.flush()

        # Simulate summarizer result: update lead
        lead_result = await sess.execute(select(Lead).where(Lead.id == LEAD_ID))
        lead_obj = lead_result.scalar_one_or_none()
        if lead_obj is not None:
            lead_obj.call_count = 1  # 1 completed call
            lead_obj.extracted_facts = {
                "current_insurance": "Zurich",
                "interest_level": 65,
            }

        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as http_client:
        yield http_client, db_module, LEAD_ID

    await db_module.close_db()


# ---------------------------------------------------------------------------
# T33 — RED: Second call custom-LLM prompt contains prior summary
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_second_call_prompt_contains_prior_summary(
    e2e_memory_prompt_client,
    monkeypatch,
):
    """CAP-5: custom-LLM system prompt for second call includes prior session summary.

    Flow:
    1. POST to custom-LLM webhook for a lead that already has a completed session
    2. Capture the system message sent to OpenAI
    3. Assert: system prompt contains 'Llamada del' (from call_history) AND
       contains substring from the prior summary ('granizo' or 'Ford Focus')

    RED until webhook.py passes db=db to render() (T28 fix).
    """
    import app.calls.service as calls_service_mod

    monkeypatch.setattr(
        calls_service_mod, "_schedule_summarize", lambda session_id: None
    )

    http_client, db_module, LEAD_ID = e2e_memory_prompt_client

    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola Ana"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": "conv-e2e-second-call-001",
        },
        "client_id": "quintana-seguros",
    }

    resp = await http_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert len(captured_messages) > 0, "OpenAI was never called"

    system_content = captured_messages[0][0]["content"]

    # The system prompt MUST contain 'Llamada del' from call_history
    assert "Llamada del" in system_content, (
        f"System prompt must contain 'Llamada del' from call_history for second call. "
        f"Got: {system_content[:300]!r}"
    )

    # The summary content must appear (at least a meaningful substring)
    assert "granizo" in system_content or "Ford Focus" in system_content, (
        f"System prompt should contain summary content from prior call. "
        f"Got: {system_content[:300]!r}"
    )


# ---------------------------------------------------------------------------
# T34 — RED: call_number renders as 2 for lead with 1 completed session
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_call_number_renders_as_2_when_lead_has_one_completed(
    e2e_memory_prompt_client,
    monkeypatch,
):
    """CAP-5: call_number in system prompt reflects call_count+1.

    Lead has call_count=1 (one completed session) → call_number should render
    as 2 in the system prompt. The quintana-seguros prompt template uses
    {{call_number}} which is substituted as "2".

    RED until webhook.py passes db=db to render() (T28 fix).
    """
    import app.calls.service as calls_service_mod

    monkeypatch.setattr(
        calls_service_mod, "_schedule_summarize", lambda session_id: None
    )

    http_client, db_module, LEAD_ID = e2e_memory_prompt_client

    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": "conv-e2e-call-number-001",
        },
        "client_id": "quintana-seguros",
    }

    resp = await http_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert len(captured_messages) > 0, "OpenAI was never called"

    system_content = captured_messages[0][0]["content"]

    # The prompt template uses "{{call_number}}" → substituted with "2"
    # The quintana prompt says e.g. "Este es el llamado número {{call_number}}"
    # We assert the digit "2" appears somewhere in the prompt from call_number substitution
    assert "2" in system_content, (
        f"System prompt must contain '2' (call_number=2 for lead with call_count=1). "
        f"Got: {system_content[:300]!r}"
    )


# ---------------------------------------------------------------------------
# T35 — RED: is_returning_caller=True produces call_history in prompt
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_is_returning_caller_renders_true_when_lead_has_history(
    e2e_memory_prompt_client,
    monkeypatch,
):
    """CAP-5: Returning caller (is_returning_caller=True) produces non-empty call_history
    in the rendered system prompt.

    The quintana-seguros template renders {{call_history}} which will contain
    'Llamada del' when is_returning_caller=True (at least one completed session).
    A first-call (no completed sessions) would produce empty call_history.

    Verifies:
    - 'Llamada del' in system prompt (only present when is_returning_caller=True)
    - Prompt does NOT have literal '{{is_returning_caller}}' placeholder (substituted)

    RED until webhook.py passes db=db to render() (T28 fix).
    """
    import app.calls.service as calls_service_mod

    monkeypatch.setattr(
        calls_service_mod, "_schedule_summarize", lambda session_id: None
    )

    http_client, db_module, LEAD_ID = e2e_memory_prompt_client

    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": "conv-e2e-returning-001",
        },
        "client_id": "quintana-seguros",
    }

    resp = await http_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert len(captured_messages) > 0, "OpenAI was never called"

    system_content = captured_messages[0][0]["content"]

    # When is_returning_caller=True, the rendered prompt must contain literal "true"
    # from the {{is_returning_caller}} substitution in the prompt template.
    # The quintana-seguros prompt now includes:
    # "Lead recurrente: {{is_returning_caller}} (true = ya hablaron antes, ...)"
    # → substituted as "Lead recurrente: true (true = ya hablaron antes, ...)"
    assert "true" in system_content.lower(), (
        f"System prompt must contain 'true' (from is_returning_caller substitution) "
        f"for a returning caller. "
        f"Got: {system_content[:300]!r}"
    )

    # Also verify 'Llamada del' is in the prompt (call_history is non-empty)
    assert "Llamada del" in system_content, (
        f"System prompt must contain 'Llamada del' (from call_history) for returning caller. "
        f"Got: {system_content[:300]!r}"
    )

    # The '{{is_returning_caller}}' placeholder must not remain unsubstituted
    assert (
        "{{is_returning_caller}}" not in system_content
    ), "{{is_returning_caller}} placeholder must be substituted in rendered prompt"

    # The '{{call_history}}' placeholder must not remain unsubstituted
    assert (
        "{{call_history}}" not in system_content
    ), "{{call_history}} placeholder must be substituted in rendered prompt"


# ---------------------------------------------------------------------------
# T42c — is_returning_caller renders 'false' for first call (no prior sessions)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def e2e_first_call_client(tmp_path: Path):
    """E2E app for a brand-new lead with no prior sessions (first call).

    The quintana-seguros prompt template must render is_returning_caller='false'.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e2e_first_call_test.db",
    )

    await db_module.init_db(settings)

    LEAD_ID = "lead-e2e-first-001"

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Carlos Nuevo",
            phone="+5411155504",
            car_make="Honda",
            car_model="Civic",
            car_year=2022,
            lead_id=LEAD_ID,
        )
        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as http_client:
        yield http_client, db_module, LEAD_ID

    await db_module.close_db()


@respx.mock
@pytest.mark.asyncio
async def test_is_returning_caller_renders_false_when_lead_is_first_call(
    e2e_first_call_client,
    monkeypatch,
):
    """CAP-5 / T42c: First call for a brand-new lead renders is_returning_caller='false'
    in the system prompt via the {{is_returning_caller}} placeholder.

    The quintana-seguros prompt template contains:
    'Lead recurrente: {{is_returning_caller}} (true = ya hablaron antes, false = primer contacto).'
    → For a first call this renders as:
    'Lead recurrente: false (true = ya hablaron antes, false = primer contacto).'
    """
    import app.calls.service as calls_service_mod

    monkeypatch.setattr(
        calls_service_mod, "_schedule_summarize", lambda session_id: None
    )

    http_client, db_module, LEAD_ID = e2e_first_call_client

    captured_messages: list[list[dict]] = []

    import httpx

    def intercept_openai(request: httpx.Request):
        body = json.loads(request.content)
        captured_messages.append(body.get("messages", []))
        return Response(
            200,
            content=_build_simple_stream("Hola Carlos"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=intercept_openai
    )

    body = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": LEAD_ID,
            "conversation_id": "conv-e2e-first-call-is-returning-001",
        },
        "client_id": "quintana-seguros",
    }

    resp = await http_client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=body,
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert len(captured_messages) > 0, "OpenAI was never called"

    system_content = captured_messages[0][0]["content"]

    # The rendered prompt must contain "Lead recurrente: false"
    # (from {{is_returning_caller}} → "false" for no prior completed sessions)
    assert "recurrente: false" in system_content, (
        f"System prompt must contain 'recurrente: false' for a first call. "
        f"The {{{{is_returning_caller}}}} placeholder must be substituted with 'false'. "
        f"Got: {system_content[:400]!r}"
    )

    # '{{is_returning_caller}}' must not remain unsubstituted
    assert (
        "{{is_returning_caller}}" not in system_content
    ), "{{is_returning_caller}} placeholder must be substituted in rendered prompt"
