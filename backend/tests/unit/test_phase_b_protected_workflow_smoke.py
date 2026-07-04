"""Phase B protected workflow smoke tests — Task 3.3 local coverage.

Spec ref: db-migration-tooling/spec.md — Requirement: Core Workflow Smoke Verification.

Six areas must pass on both fresh-DB and stamped-existing-DB paths (spec lines 190-218):

  1. Agent context assembly — agent/client records load; dynamic tools resolve
  2. ElevenLabs webhook path — inbound routing returns 200, CallSession queryable
  3. Post-call analysis — CallAnalysis record is readable/queryable via DB + API
  4. CRM / custom fields — LeadCustomField records are writable and readable
  5. Scheduler / scheduled calls — ScheduledCall records queryable; next-action runs
  6. Lead detail / facts / rollups — lead detail loads; LeadProfileFact & rollup columns present

Coverage note:
  Live ElevenLabs voice traffic (ngrok + cloud call routing) cannot be automated locally.
  These tests use isolated SQLite DBs (created via Alembic upgrade head) and mock only the
  irreducible live-service boundaries (OpenAI SSE, ElevenLabs cloud API).
  All DB schema interactions use the production path (Alembic) to prove migration fidelity.

Stamped-existing path:
  The smoke_stamped_db fixture creates a fresh Alembic-migrated DB, seeds it, then drops the
  alembic_version table to simulate an unstamped-but-compatible legacy DB. It then calls
  scripts/migrate.py (the production pre-start script) which detects the compatible schema and
  stamps it (no DDL). This exercises the spec scenario:
  "All six areas pass on stamped existing DB" (spec Requirement: Core Workflow Smoke Verification).

TDD cycle: RED → GREEN → TRIANGULATE (see evidence at bottom of module).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared fixture — isolated Alembic-migrated DB seeded with quintana data
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def smoke_db(tmp_path: Path):
    """Fresh Alembic-migrated DB seeded with quintana-seguros + test lead.

    Uses the production migration path (Alembic upgrade head) — NOT create_all().
    This is the canonical fresh-DB path from spec scenarios "All six areas pass on fresh DB".
    """
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/smoke_test.db",
    )

    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    yield db_module, settings

    await db_module.close_db()


@pytest_asyncio.fixture
async def smoke_stamped_db(tmp_path: Path):
    """Stamped-existing-DB path: migrated + seeded DB with alembic_version dropped, then re-stamped.

    Simulates the spec scenario "All six areas pass on stamped existing DB":
      1. Fresh Alembic-migrated DB (matches production path)
      2. Seed quintana-seguros + test lead (simulate real populated DB)
      3. Drop alembic_version table (simulate legacy DB without Alembic tracking)
      4. Call scripts/migrate.py (production pre-start script) — detects compatible schema,
         stamps head without DDL (no data loss, no table recreation)
      5. Re-initialize DB engine pointing at the stamped DB

    After this fixture, the DB is in the "stamped-existing" state that the spec requires.
    All six workflow areas must work identically to the fresh-DB path.
    """
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    # Step 1: Create a fresh migrated DB
    db_file = tmp_path / "stamped_smoke.db"
    fresh_url = f"sqlite+aiosqlite:///{db_file}"

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=fresh_url,
    )

    await init_db_with_migrations(db_module, settings)

    # Step 2: Seed data into the fresh DB
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    # Close the engine before we manipulate the file with sqlite3
    await db_module.close_db()

    # Step 3: Drop alembic_version table — simulate an unstamped-but-compatible legacy DB
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("DROP TABLE IF EXISTS alembic_version")
        conn.commit()

    # Verify the table is gone (ensures we're testing the right path)
    with sqlite3.connect(str(db_file)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alembic_version" not in tables, "alembic_version must be absent before stamp test"

    # Step 4: Run the production pre-start migration script — should stamp without DDL
    # Use environment variable to point at the test DB
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file}"
    backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/

    result = subprocess.run(
        [sys.executable, str(backend_dir / "scripts" / "migrate.py")],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"scripts/migrate.py must exit 0 on stamped-compatible DB.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Verify alembic_version was stamped (no DDL — just an INSERT into alembic_version)
    with sqlite3.connect(str(db_file)) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None, "alembic_version must be present after stamp"
    # HEAD revision advances as new migrations are added — accept any known Qora revision.
    # Phase B10 (background_jobs) added 20260624_0002 as the new head.
    # PR3 transcript finalization fields: 20260625_0003
    # C2 outbound telephony: 20260702_0004
    _KNOWN_REVISIONS = {"20241201_0001", "20260624_0002", "20260625_0003", "20260702_0004", "20260703_0005", "20260704_0006"}
    assert row[0] in _KNOWN_REVISIONS, (
        f"Expected a known Qora revision as head, got {row[0]!r}. "
        f"Known revisions: {_KNOWN_REVISIONS}"
    )

    # Step 5: Re-initialize DB engine pointing at the now-stamped DB
    from app.core import database as db_module  # re-bind to pick up fresh state
    db_module.create_engine_and_session(fresh_url)

    import app.tenants.models  # noqa: F401
    import app.leads.models  # noqa: F401
    import app.calls.models  # noqa: F401
    import app.scheduler.models  # noqa: F401

    from sqlalchemy import text
    async with db_module.engine.connect() as raw_conn:  # type: ignore[union-attr]
        await raw_conn.execute(text("PRAGMA journal_mode=WAL"))
        await raw_conn.execute(text("PRAGMA busy_timeout=5000"))
        await raw_conn.commit()

    yield db_module, settings

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Area 1: Agent context assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area1_agent_context_assembly(smoke_db):
    """Smoke: agent and client records load from migrated DB; build_voice_context succeeds.

    GIVEN a fresh Alembic-migrated DB with quintana-seguros seed
    WHEN agent + client records are fetched and build_voice_context is called
    THEN both records are non-None and context has a non-empty system_prompt
    AND the prompt contains agent identity markers (no missing-column OperationalError)
    """
    db_module, settings = smoke_db

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_client, get_default_agent
        from app.leads.service import get_lead
        from app.voice.context import build_voice_context

        client = await get_client(sess, "quintana-seguros")
        agent = await get_default_agent(sess, "quintana-seguros")
        lead = await get_lead(sess, "lead-quintana-001")

        assert client is not None, "Client 'quintana-seguros' must exist in migrated DB"
        assert agent is not None, "Default agent for 'quintana-seguros' must exist"

        # build_voice_context must succeed without OperationalError
        ctx = await build_voice_context(
            agent=agent,
            lead=lead,
            db=sess,
            client=client,
        )

    assert ctx is not None, "build_voice_context must return a VoiceSessionContext"
    assert ctx.system_prompt, "system_prompt must be non-empty — agent context assembly succeeded"
    assert len(ctx.system_prompt) > 20, (
        f"system_prompt too short ({len(ctx.system_prompt)} chars) — context assembly likely failed"
    )


@pytest.mark.asyncio
async def test_smoke_area1_agent_context_has_model_and_tokens(smoke_db):
    """Triangulation: context must carry model and max_tokens (all columns accessible).

    GIVEN a migrated DB with agent record
    WHEN build_voice_context is called
    THEN model and max_tokens are present (proves agent schema columns accessible)
    """
    db_module, settings = smoke_db

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_client, get_default_agent
        from app.voice.context import build_voice_context

        client = await get_client(sess, "quintana-seguros")
        agent = await get_default_agent(sess, "quintana-seguros")

        ctx = await build_voice_context(agent=agent, lead=None, db=sess, client=client)

    assert ctx.model is not None, "model must be set in voice context"
    assert ctx.max_tokens > 0, "max_tokens must be positive integer"


# ---------------------------------------------------------------------------
# Area 2: ElevenLabs webhook path — CallSession queryable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area2_elevenlabs_webhook_path_200(smoke_db, tmp_path):
    """Smoke: voice webhook route returns 200 for a custom-llm request on migrated DB.

    GIVEN a migrated DB with seeded quintana-seguros data
    WHEN POST /api/v1/voice/{client_id}/custom-llm/chat/completions is called
         with a pre-seeded session store entry
    THEN response is 200 (route is reachable, DB schema has no missing columns)

    Note: OpenAI SSE is intercepted via mock to avoid live calls.
    """
    from unittest.mock import patch
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_db

    from app.voice.webhook import router as webhook_router
    from app.voice import session as session_module
    from app.voice.context import VoiceSessionContext

    session_module.session_store._sessions.clear()

    # Pre-seed a session context so the webhook uses the cached fast path
    ctx = VoiceSessionContext(
        system_prompt="Smoke test prompt — area 2.",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
    )
    conversation_id = f"smoke-area2-{uuid.uuid4().hex[:8]}"
    session_module.session_store.create(
        conversation_id=conversation_id,
        client_id="quintana-seguros",
        lead_id="lead-quintana-001",
        session_id="smoke-sess-001",
        context=ctx,
    )

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    captured_messages: list = []

    async def mock_stream(**kwargs):
        captured_messages.append(True)
        yield "data: [DONE]\n\n"

    with patch("app.voice.webhook._stream_llm_response", side_effect=mock_stream):
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
                json={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hola"}],
                    "stream": True,
                    "elevenlabs_extra_body": {
                        "client_id": "quintana-seguros",
                        "conversation_id": conversation_id,
                    },
                },
            )
            _ = response.content

    assert response.status_code == 200, (
        f"ElevenLabs webhook path must return 200. Got {response.status_code}: {response.text!r}"
    )
    assert captured_messages, "_stream_llm_response must have been called (route was reached)"

    session_module.session_store._sessions.clear()


@pytest.mark.asyncio
async def test_smoke_area2_call_session_writable(smoke_db):
    """Triangulation: CallSession record is writable and queryable in migrated DB.

    GIVEN a migrated DB
    WHEN a CallSession is inserted directly via ORM
    THEN it is retrievable — proves call_sessions schema is intact and accessible
    """
    db_module, settings = smoke_db

    session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession
        from sqlalchemy import select

        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            elevenlabs_conversation_id=None,
            status="initiated",
        )
        sess.add(cs)
        await sess.commit()

        result = await sess.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "CallSession must be fetchable after insert (call_sessions schema OK)"
    assert fetched.id == session_id
    assert fetched.status == "initiated"
    assert fetched.client_id == "quintana-seguros"


# ---------------------------------------------------------------------------
# Area 3: Post-call analysis — CallAnalysis readable/queryable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area3_call_analysis_writable_and_readable(smoke_db):
    """Smoke: CallAnalysis record is writable and queryable via migrated DB.

    GIVEN a migrated DB with a CallSession
    WHEN a CallAnalysis is inserted (simulating post-call summarizer output)
    THEN the record is readable with all expected fields non-null
    AND no OperationalError (missing-column) occurs
    """
    db_module, settings = smoke_db

    session_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession, CallAnalysis
        from sqlalchemy import select

        # Write CallSession (prerequisite for FK)
        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            status="completed",
        )
        sess.add(cs)

        # Write CallAnalysis (simulates summarizer writing post-call analysis)
        ca = CallAnalysis(
            id=analysis_id,
            session_id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            analysis_status="success",
            classification="interested",
            summary="Prueba de análisis de llamada.",
            analyzed_at=datetime.now(timezone.utc),
        )
        sess.add(ca)
        await sess.commit()

        # Query back
        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "CallAnalysis must be fetchable after insert (call_analyses schema OK)"
    assert fetched.analysis_status == "success"
    assert fetched.classification == "interested"
    assert fetched.summary == "Prueba de análisis de llamada."
    assert fetched.client_id == "quintana-seguros"


@pytest.mark.asyncio
async def test_smoke_area3_call_analysis_api_route_reachable(smoke_db):
    """Triangulation: GET /api/v1/calls/{session_id}/analysis returns 200 or 404 (not 500).

    GIVEN a migrated DB with a CallSession (no CallAnalysis seeded)
    WHEN GET /{session_id}/analysis is called
    THEN response is 404 (session found, no analysis yet) — proves route is reachable
    AND no OperationalError occurs (call_analyses columns accessible)
    """
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_db
    session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession

        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            status="completed",
        )
        sess.add(cs)
        await sess.commit()

    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(calls_router, prefix="/api/v1/calls")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/calls/{session_id}/analysis")

    # 200 = analysis exists (unlikely without seeding), 404 = no analysis — both are correct
    # 500 = schema problem
    assert response.status_code in (200, 404), (
        f"Expected 200 or 404 for analysis route. Got {response.status_code}: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# Area 4: CRM / custom fields — LeadCustomField writable and readable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area4_crm_custom_fields_writable_and_readable(smoke_db):
    """Smoke: LeadCustomField records are writable and readable in migrated DB.

    GIVEN a migrated DB with quintana-seguros + lead-quintana-001
    WHEN a custom field is upserted for the lead
    THEN the record is fetchable — proves lead_custom_fields schema is intact
    """
    db_module, settings = smoke_db

    async with db_module.async_session_factory() as sess:
        from app.leads.lead_custom_fields_service import upsert, get_all

        # Upsert a custom field (simulates CRM sync writing data)
        await upsert(
            sess,
            lead_id="lead-quintana-001",
            client_id="quintana-seguros",
            field_key="car_model",
            field_value="Toyota Corolla",
            field_type="string",
        )
        await sess.commit()

        # Read back
        fields = await get_all(sess, "lead-quintana-001", "quintana-seguros")

    # get_all returns dict[str, str]: {field_key: field_value}
    assert len(fields) > 0, "LeadCustomField records must be readable after upsert"
    assert "car_model" in fields, f"car_model custom field must be present. Got keys: {list(fields)!r}"
    assert fields["car_model"] == "Toyota Corolla", (
        f"car_model value must be 'Toyota Corolla'. Got {fields['car_model']!r}"
    )


@pytest.mark.asyncio
async def test_smoke_area4_lead_create_with_custom_fields_via_api(smoke_db):
    """Triangulation: POST /api/v1/leads with custom_fields persists to lead_custom_fields table.

    GIVEN a migrated DB
    WHEN a lead is created via POST with custom_fields
    THEN the custom field is stored and visible in GET response
    AND no OperationalError occurs (lead_custom_fields schema OK)
    """
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_db

    from app.leads.router import router as leads_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        # Create lead with custom fields
        create_resp = await client.post(
            "/api/v1/leads?client_id=quintana-seguros",
            json={
                "name": "Smoke Test Lead CRM",
                "phone": "+5411009988",
                "client_id": "quintana-seguros",
                "custom_fields": {"car_year": "2022", "car_brand": "Ford"},
            },
        )
        assert create_resp.status_code in (200, 201), (
            f"Lead creation must succeed. Got {create_resp.status_code}: {create_resp.text!r}"
        )
        lead_id = create_resp.json()["id"]

        # Fetch lead — should include custom_fields
        get_resp = await client.get(f"/api/v1/leads/{lead_id}")

    assert get_resp.status_code == 200, (
        f"Lead GET must return 200. Got {get_resp.status_code}: {get_resp.text!r}"
    )
    data = get_resp.json()
    assert "custom_fields" in data, "GET /leads/{id} response must include custom_fields"
    cf = data["custom_fields"]
    assert "car_year" in cf or "car_brand" in cf, (
        f"At least one custom field must be present. Got custom_fields={cf!r}"
    )


# ---------------------------------------------------------------------------
# Area 5: Scheduler / ScheduledCall — queryable; next-action logic runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area5_scheduled_call_writable_and_queryable(smoke_db):
    """Smoke: ScheduledCall records are writable and queryable in migrated DB.

    GIVEN a migrated DB with lead-quintana-001
    WHEN a ScheduledCall is inserted for a future time
    THEN it is fetchable via ORM — proves scheduled_calls schema is intact
    """
    db_module, settings = smoke_db

    call_id = str(uuid.uuid4())
    future = datetime.now(timezone.utc) + timedelta(hours=2)

    async with db_module.async_session_factory() as sess:
        from app.scheduler.models import ScheduledCall
        from sqlalchemy import select

        sc = ScheduledCall(
            id=call_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            scheduled_at=future,
            trigger_reason="manual",
            status="pending",
        )
        sess.add(sc)
        await sess.commit()

        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == call_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "ScheduledCall must be fetchable (scheduled_calls schema OK)"
    assert fetched.status == "pending"
    assert fetched.client_id == "quintana-seguros"
    assert fetched.lead_id == "lead-quintana-001"


@pytest.mark.asyncio
async def test_smoke_area5_scheduler_service_creates_and_queries(smoke_db):
    """Triangulation: scheduler service can create + query ScheduledCalls end-to-end.

    GIVEN a migrated DB with quintana-seguros and lead-quintana-001
    WHEN create_scheduled_call is used and mark_due_calls_in_progress is run
    THEN the service layer executes without OperationalError
    """
    db_module, settings = smoke_db

    past = datetime.now(timezone.utc) - timedelta(minutes=5)

    async with db_module.async_session_factory() as sess:
        from app.scheduler.service import create_scheduled_call, mark_due_calls_in_progress
        from app.scheduler.models import ScheduledCall
        from sqlalchemy import select

        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            scheduled_at=past,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes="Smoke test call",
        )
        await sess.commit()
        created_id = sc.id

    # Run next-action tick on this DB
    async with db_module.async_session_factory() as sess:
        from app.scheduler.service import mark_due_calls_in_progress

        promoted = await mark_due_calls_in_progress(sess)
        await sess.commit()

    # At least the smoke call should be promoted (it is past-due)
    assert promoted >= 1, (
        f"mark_due_calls_in_progress must promote at least 1 past-due call. Got {promoted}"
    )

    async with db_module.async_session_factory() as sess:
        from app.scheduler.models import ScheduledCall
        from sqlalchemy import select

        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == created_id)
        )
        updated = result.scalar_one_or_none()

    assert updated is not None
    assert updated.status == "in_progress", (
        f"Past-due ScheduledCall must be promoted to in_progress. Got {updated.status!r}"
    )


# ---------------------------------------------------------------------------
# Area 6: Lead detail / facts / rollup columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_area6_lead_profile_facts_writable(smoke_db):
    """Smoke: LeadProfileFact records are writable and queryable in migrated DB.

    GIVEN a migrated DB with lead-quintana-001
    WHEN a LeadProfileFact is inserted (simulating summarizer output)
    THEN the record is fetchable — proves lead_profile_facts schema is intact
    """
    db_module, settings = smoke_db

    fact_id = str(uuid.uuid4())
    source_session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession
        from app.leads.models import LeadProfileFact
        from sqlalchemy import select

        # Need a CallSession for FK (source_call_id)
        cs = CallSession(
            id=source_session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            status="completed",
        )
        sess.add(cs)

        # LeadProfileFact schema: id, lead_id, fact_key, fact_value, source_call_id, recorded_at
        fact = LeadProfileFact(
            id=fact_id,
            lead_id="lead-quintana-001",
            fact_key="car_model",
            fact_value="Toyota Corolla",
            source_call_id=source_session_id,
        )
        sess.add(fact)
        await sess.commit()

        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == fact_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "LeadProfileFact must be fetchable (lead_profile_facts schema OK)"
    assert fetched.fact_key == "car_model"
    assert fetched.fact_value == "Toyota Corolla"
    assert fetched.source_call_id == source_session_id


@pytest.mark.asyncio
async def test_smoke_area6_lead_detail_api_returns_200(smoke_db):
    """Smoke: GET /api/v1/leads/{id} returns 200 for seeded lead in migrated DB.

    GIVEN a migrated DB with lead-quintana-001
    WHEN GET /api/v1/leads/lead-quintana-001 is called
    THEN response is 200 with id and name fields
    AND no OperationalError occurs (all leads columns accessible)
    """
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_db

    from app.leads.router import router as leads_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/leads/lead-quintana-001")

    assert response.status_code == 200, (
        f"Lead detail must return 200. Got {response.status_code}: {response.text!r}"
    )
    data = response.json()
    assert data["id"] == "lead-quintana-001"
    assert "name" in data, "Lead response must include name"
    assert "custom_fields" in data, "Lead response must include custom_fields"


@pytest.mark.asyncio
async def test_smoke_area6_dimension_rollups_returns_200(smoke_db):
    """Triangulation: GET /api/v1/leads/{id}/dimension-rollups returns 200.

    GIVEN a migrated DB with lead-quintana-001 and no call analyses
    WHEN GET dimension-rollups is called with client_id
    THEN response is 200 with empty rollup arrays (not a 500 from missing-column)
    AND call_analyses rollup columns are accessible without OperationalError
    """
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_db

    from app.leads.router import router as leads_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/leads/lead-quintana-001/dimension-rollups",
            params={"client_id": "quintana-seguros"},
        )

    assert response.status_code == 200, (
        f"Dimension rollups must return 200. Got {response.status_code}: {response.text!r}"
    )
    data = response.json()
    # With no call_analyses seeded, all rollups must be empty lists (not errors)
    assert "detected_interests" in data, "Response must include detected_interests"
    assert "objections" in data, "Response must include objections"
    assert isinstance(data["detected_interests"], list), "detected_interests must be a list"
    assert isinstance(data["objections"], list), "objections must be a list"


# ---------------------------------------------------------------------------
# Stamped-existing DB path — six workflow areas
# ---------------------------------------------------------------------------
# Spec: "All six areas pass on stamped existing DB"
# DB path: fresh migrated + seeded → alembic_version dropped → scripts/migrate.py stamps → reopen
# This is the production path for existing deployments upgrading to Alembic management.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stamped_db_area1_agent_context_assembly(smoke_stamped_db):
    """Stamped path: agent and client records load; build_voice_context succeeds.

    GIVEN a stamped-existing DB (unstamped compatible DB stamped by scripts/migrate.py)
    WHEN agent + client records are fetched and build_voice_context is called
    THEN both records are non-None and context has a non-empty system_prompt
    """
    db_module, settings = smoke_stamped_db

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import get_client, get_default_agent
        from app.leads.service import get_lead
        from app.voice.context import build_voice_context

        client = await get_client(sess, "quintana-seguros")
        agent = await get_default_agent(sess, "quintana-seguros")
        lead = await get_lead(sess, "lead-quintana-001")

        assert client is not None, "Client must exist in stamped DB"
        assert agent is not None, "Default agent must exist in stamped DB"

        ctx = await build_voice_context(agent=agent, lead=lead, db=sess, client=client)

    assert ctx is not None
    assert ctx.system_prompt, "system_prompt must be non-empty on stamped-existing path"
    assert len(ctx.system_prompt) > 20


@pytest.mark.asyncio
async def test_stamped_db_area2_call_session_writable(smoke_stamped_db):
    """Stamped path: CallSession record is writable and queryable.

    GIVEN a stamped-existing DB
    WHEN a CallSession is inserted
    THEN it is retrievable — proves call_sessions schema intact on stamped path
    """
    db_module, settings = smoke_stamped_db

    session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession
        from sqlalchemy import select

        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            elevenlabs_conversation_id=None,
            status="initiated",
        )
        sess.add(cs)
        await sess.commit()

        result = await sess.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "CallSession must be fetchable on stamped-existing path"
    assert fetched.status == "initiated"


@pytest.mark.asyncio
async def test_stamped_db_area3_call_analysis_writable(smoke_stamped_db):
    """Stamped path: CallAnalysis record is writable and queryable.

    GIVEN a stamped-existing DB
    WHEN a CallAnalysis is inserted
    THEN it is retrievable — proves call_analyses schema intact on stamped path
    """
    db_module, settings = smoke_stamped_db

    session_id = str(uuid.uuid4())
    analysis_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession, CallAnalysis
        from sqlalchemy import select

        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            status="completed",
        )
        sess.add(cs)

        ca = CallAnalysis(
            id=analysis_id,
            session_id=session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            analysis_status="success",
            classification="interested",
            summary="Stamped path smoke test.",
            analyzed_at=datetime.now(timezone.utc),
        )
        sess.add(ca)
        await sess.commit()

        result = await sess.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "CallAnalysis must be fetchable on stamped-existing path"
    assert fetched.analysis_status == "success"
    assert fetched.classification == "interested"


@pytest.mark.asyncio
async def test_stamped_db_area4_crm_custom_fields(smoke_stamped_db):
    """Stamped path: LeadCustomField records are writable and readable.

    GIVEN a stamped-existing DB with quintana-seguros + lead-quintana-001
    WHEN a custom field is upserted
    THEN the record is fetchable — proves lead_custom_fields schema intact on stamped path
    """
    db_module, settings = smoke_stamped_db

    async with db_module.async_session_factory() as sess:
        from app.leads.lead_custom_fields_service import upsert, get_all

        await upsert(
            sess,
            lead_id="lead-quintana-001",
            client_id="quintana-seguros",
            field_key="stamped_car_model",
            field_value="Honda Civic",
            field_type="string",
        )
        await sess.commit()

        fields = await get_all(sess, "lead-quintana-001", "quintana-seguros")

    assert len(fields) > 0, "LeadCustomField must be readable on stamped-existing path"
    assert "stamped_car_model" in fields
    assert fields["stamped_car_model"] == "Honda Civic"


@pytest.mark.asyncio
async def test_stamped_db_area5_scheduler_writable(smoke_stamped_db):
    """Stamped path: ScheduledCall is writable and next-action logic runs.

    GIVEN a stamped-existing DB
    WHEN a past-due ScheduledCall is created and mark_due_calls_in_progress is run
    THEN the call is promoted to in_progress — proves scheduled_calls schema intact
    """
    db_module, settings = smoke_stamped_db

    past = datetime.now(timezone.utc) - timedelta(minutes=5)

    async with db_module.async_session_factory() as sess:
        from app.scheduler.service import create_scheduled_call

        sc = await create_scheduled_call(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            scheduled_at=past,
            trigger_reason="manual",
            source_session_id=None,
            attempt_number=1,
            max_attempts=3,
            notes="Stamped path smoke",
        )
        await sess.commit()
        created_id = sc.id

    async with db_module.async_session_factory() as sess:
        from app.scheduler.service import mark_due_calls_in_progress

        promoted = await mark_due_calls_in_progress(sess)
        await sess.commit()

    assert promoted >= 1, "mark_due_calls_in_progress must work on stamped-existing path"

    async with db_module.async_session_factory() as sess:
        from app.scheduler.models import ScheduledCall
        from sqlalchemy import select

        result = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.id == created_id)
        )
        updated = result.scalar_one_or_none()

    assert updated is not None
    assert updated.status == "in_progress", (
        f"ScheduledCall must be in_progress on stamped path. Got {updated.status!r}"
    )


@pytest.mark.asyncio
async def test_stamped_db_area6_lead_detail_and_facts(smoke_stamped_db):
    """Stamped path: lead detail and LeadProfileFact are accessible.

    GIVEN a stamped-existing DB with seeded lead-quintana-001
    WHEN GET /api/v1/leads/lead-quintana-001 is called AND a LeadProfileFact is inserted
    THEN lead detail returns 200 and profile fact is queryable
    AND no OperationalError occurs on stamped path (proves full schema intact)
    """
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI

    db_module, settings = smoke_stamped_db

    # Subtest A: lead detail API
    from app.leads.router import router as leads_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(leads_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/leads/lead-quintana-001")

    assert response.status_code == 200, (
        f"Lead detail must return 200 on stamped path. Got {response.status_code}: {response.text!r}"
    )
    data = response.json()
    assert data["id"] == "lead-quintana-001"

    # Subtest B: LeadProfileFact insert + query
    fact_id = str(uuid.uuid4())
    source_session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        from app.calls.models import CallSession
        from app.leads.models import LeadProfileFact
        from sqlalchemy import select

        cs = CallSession(
            id=source_session_id,
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            status="completed",
        )
        sess.add(cs)

        fact = LeadProfileFact(
            id=fact_id,
            lead_id="lead-quintana-001",
            fact_key="stamped_fact_key",
            fact_value="stamped_value",
            source_call_id=source_session_id,
        )
        sess.add(fact)
        await sess.commit()

        result = await sess.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == fact_id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, "LeadProfileFact must be fetchable on stamped-existing path"
    assert fetched.fact_key == "stamped_fact_key"
    assert fetched.fact_value == "stamped_value"


# ---------------------------------------------------------------------------
# TDD Cycle Evidence
# ---------------------------------------------------------------------------
# Task 3.3 — Local protected workflow smoke (fresh path)
#
# | Area | Test(s) | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
# |------|---------|-------|------------|-----|-------|-------------|----------|
# | 1. Agent context | test_smoke_area1_* (×2) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
# | 2. ElevenLabs webhook | test_smoke_area2_* (×2) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
# | 3. Post-call analysis | test_smoke_area3_* (×2) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
# | 4. CRM / custom fields | test_smoke_area4_* (×2) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
# | 5. Scheduler | test_smoke_area5_* (×2) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
# | 6. Lead detail / facts | test_smoke_area6_* (×3) | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 3 cases | ➖ None needed |
#
# Stamped-existing path (verify blocker fix 2026-06-18):
#
# | Area | Test(s) | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
# |------|---------|-------|------------|-----|-------|-------------|----------|
# | 1. Agent context | test_stamped_db_area1_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# | 2. CallSession writable | test_stamped_db_area2_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# | 3. CallAnalysis writable | test_stamped_db_area3_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# | 4. CRM custom fields | test_stamped_db_area4_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# | 5. Scheduler | test_stamped_db_area5_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# | 6. Lead detail / facts | test_stamped_db_area6_* | Integration | ✅ 13/13 | ✅ Written | ✅ Passed | ➖ Covered by fresh path | ➖ None needed |
# ---------------------------------------------------------------------------
