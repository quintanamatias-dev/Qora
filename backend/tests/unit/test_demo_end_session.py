"""Tests for POST /api/v1/demo/sessions/{session_id}/end — reconciliation fallback.

Covers:
  1. Unknown conv_id + matching body.client_id/lead_id → reconciles initiated
     null-conv session and returns 200.
  2. Unknown conv_id + mismatched body.client_id → 403 (cross-tenant guard).
  3. Unknown conv_id + None body.client_id → 403 (None != demo_client_id).
  4. Session found directly (by EL id) and belongs to demo client → 200 normal close.
  5. Session found directly but belongs to a different tenant → 403 scope guard.
  6. Unknown conv_id + matching client_id but no lead_id → 404 (cannot reconcile).

Test layer: Integration (async, in-process SQLite via Alembic, no real network).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEMO_CLIENT_ID = "demo-test-client"
_OTHER_CLIENT_ID = "other-tenant-client"
# Neutral non-secret sentinel for the required API-key setting. The value is
# never validated against a real provider in these tests; it only needs to be
# a present, non-empty string, so it is deliberately not key-shaped.
_TEST_API_KEY = "test-api-key-sentinel"


# ---------------------------------------------------------------------------
# Shared async fixture — isolated DB + FastAPI app
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def demo_app(tmp_path: Path):
    """FastAPI app with demo router wired, isolated DB, and QORA_DEMO_CLIENT_ID set.

    Seeds:
      - demo-test-client with a default agent
      - other-tenant-client with a default agent (for cross-tenant guard tests)
      - one lead per client
    """
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/demo_end_test.db"
    settings = Settings(
        openai_api_key=SecretStr("test-openai-sentinel"),
        elevenlabs_api_key=SecretStr("test-elevenlabs-sentinel"),
        qora_api_key=SecretStr(_TEST_API_KEY),
        database_url=db_url,
        qora_demo_client_id=_DEMO_CLIENT_ID,
        qora_demo_agent_id="el-agent-demo-id",
    )

    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import create_client

        # Demo client (the configured one)
        await create_client(
            sess,
            id=_DEMO_CLIENT_ID,
            name="Demo Client",
            agent_name="DemoAgent",
            voice_id="voice-demo",
        )
        # Other tenant (used for cross-tenant guard tests)
        await create_client(
            sess,
            id=_OTHER_CLIENT_ID,
            name="Other Tenant",
            agent_name="OtherAgent",
            voice_id="voice-other",
        )
        await sess.commit()

    # Import lead model directly for seeding
    async with db_module.async_session_factory() as sess:
        from app.leads.models import Lead

        demo_lead = Lead(
            id="lead-demo-001",
            client_id=_DEMO_CLIENT_ID,
            name="Demo Lead",
            phone="+1234567890",
            status="called",
        )
        other_lead = Lead(
            id="lead-other-001",
            client_id=_OTHER_CLIENT_ID,
            name="Other Lead",
            phone="+0987654321",
            status="called",
        )
        sess.add(demo_lead)
        sess.add(other_lead)
        await sess.commit()

    from fastapi import FastAPI, APIRouter
    from app.demo.router import router as demo_router

    app = FastAPI()
    app.state.settings = settings

    # Patch the module-level calls.service.settings so executor/job checks
    # use the test DB URL, not the default SQLite fallback.
    import app.calls.service as calls_svc

    calls_svc.settings = settings

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(demo_router)
    app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client, db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_initiated_session(db_module, *, client_id: str, lead_id: str) -> str:
    """Insert a CallSession with status=initiated and elevenlabs_conversation_id=NULL.

    Returns the session UUID.
    """
    from app.calls.models import CallSession
    from app.tenants.service import get_default_agent

    session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        agent = await get_default_agent(sess, client_id)
        assert agent is not None, f"No default agent for {client_id!r}"

        cs = CallSession(
            id=session_id,
            client_id=client_id,
            lead_id=lead_id,
            elevenlabs_conversation_id=None,
            status="initiated",
            agent_id=agent.id,
            started_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()

    return session_id


async def _seed_session_with_el_id(db_module, *, client_id: str, lead_id: str, el_conv_id: str) -> str:
    """Insert a CallSession with a known ElevenLabs conversation_id.

    Returns the session UUID.
    """
    from app.calls.models import CallSession
    from app.tenants.service import get_default_agent

    session_id = str(uuid.uuid4())

    async with db_module.async_session_factory() as sess:
        agent = await get_default_agent(sess, client_id)
        assert agent is not None

        cs = CallSession(
            id=session_id,
            client_id=client_id,
            lead_id=lead_id,
            elevenlabs_conversation_id=el_conv_id,
            status="initiated",
            agent_id=agent.id,
            started_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()

    return session_id


# ---------------------------------------------------------------------------
# Test 1: Unknown conv_id + matching client_id/lead_id → reconcile → 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_unknown_conv_id_reconciles_initiated_session(demo_app):
    """Unknown EL conv_id with correct client_id/lead_id reconciles an initiated session.

    GIVEN a CallSession exists with status=initiated, elevenlabs_conversation_id=NULL
      for the demo client and a known lead
    AND the browser sends POST /end with session_id=<unknown_conv_id>,
      body.client_id=<demo_client_id>, body.lead_id=<lead_id>
    THEN the endpoint returns 200
    AND the returned session has status=completed
    AND the session is assigned the unknown conv_id as elevenlabs_conversation_id
    """
    client, db_module = demo_app
    await _seed_initiated_session(db_module, client_id=_DEMO_CLIENT_ID, lead_id="lead-demo-001")

    unknown_conv_id = "conv_unknown_el_id_test_reconcile"

    response = await client.post(
        f"/api/v1/demo/sessions/{unknown_conv_id}/end",
        json={
            "reason": "user_hangup",
            "client_id": _DEMO_CLIENT_ID,
            "lead_id": "lead-demo-001",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert data["closed_reason"] == "user_hangup"

    # Verify the DB session was actually updated
    from app.calls.models import CallSession
    async with db_module.async_session_factory() as sess:
        from sqlalchemy import select
        result = await sess.execute(
            select(CallSession).where(
                CallSession.elevenlabs_conversation_id == unknown_conv_id
            )
        )
        reconciled = result.scalar_one_or_none()

    assert reconciled is not None, "Reconciled session must have the conv_id assigned in DB"
    assert reconciled.status == "completed"
    assert reconciled.client_id == _DEMO_CLIENT_ID
    assert reconciled.ended_at is not None


# ---------------------------------------------------------------------------
# Test 2: Unknown conv_id + mismatched body.client_id → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_unknown_conv_id_wrong_client_id_returns_403(demo_app):
    """Reconciliation with mismatched client_id is rejected with 403.

    GIVEN no session found for the given conv_id
    AND body.client_id does NOT match the configured demo client
    THEN the endpoint returns 403 (cross-tenant guard)
    AND no session is closed
    """
    client, db_module = demo_app

    response = await client.post(
        "/api/v1/demo/sessions/conv_unknown_cross_tenant/end",
        json={
            "reason": "user_hangup",
            "client_id": _OTHER_CLIENT_ID,  # wrong — not the demo client
            "lead_id": "lead-other-001",
        },
    )

    assert response.status_code == 403, response.text
    data = response.json()
    assert data["detail"]["error"] == "demo_scope_violation"


# ---------------------------------------------------------------------------
# Test 3: Unknown conv_id + body.client_id=None → 403
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_unknown_conv_id_null_client_id_returns_403(demo_app):
    """Reconciliation with missing/None client_id is rejected with 403.

    None != demo_client_id, so the cross-tenant guard fires.
    """
    client, _ = demo_app

    response = await client.post(
        "/api/v1/demo/sessions/conv_unknown_no_client/end",
        json={
            "reason": "user_hangup",
            "client_id": None,
            "lead_id": "lead-demo-001",
        },
    )

    assert response.status_code == 403, response.text
    data = response.json()
    assert data["detail"]["error"] == "demo_scope_violation"


# ---------------------------------------------------------------------------
# Test 4: Session found directly (EL id) and is demo client → 200 normal close
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_found_session_demo_client_returns_200(demo_app):
    """Session resolved via ElevenLabs conv_id belonging to demo client → 200.

    This is the happy-path that already worked before the fix — ensure it
    still works after the refactor.
    """
    client, db_module = demo_app

    el_conv_id = "conv_found_direct_demo_client"
    await _seed_session_with_el_id(
        db_module,
        client_id=_DEMO_CLIENT_ID,
        lead_id="lead-demo-001",
        el_conv_id=el_conv_id,
    )

    response = await client.post(
        f"/api/v1/demo/sessions/{el_conv_id}/end",
        json={"reason": "completed"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 5: Session found directly but belongs to other tenant → 403 scope guard
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_found_session_other_tenant_returns_403(demo_app):
    """Session found directly but belonging to another tenant is rejected with 403.

    The scope guard on the direct-found path must still fire even after the
    reconciliation-path changes.
    """
    client, db_module = demo_app

    el_conv_id = "conv_found_direct_other_tenant"
    await _seed_session_with_el_id(
        db_module,
        client_id=_OTHER_CLIENT_ID,
        lead_id="lead-other-001",
        el_conv_id=el_conv_id,
    )

    response = await client.post(
        f"/api/v1/demo/sessions/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )

    assert response.status_code == 403, response.text
    data = response.json()
    assert data["detail"]["error"] == "demo_scope_violation"


# ---------------------------------------------------------------------------
# Test 6: Unknown conv_id + matching client_id but no lead_id → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_unknown_conv_id_no_lead_id_returns_404(demo_app):
    """Reconciliation requires a lead_id hint; without it → 404.

    Without lead_id the reconciliation query cannot find an orphaned session,
    so the endpoint must return 404 rather than a confusing 500.
    """
    client, _ = demo_app

    response = await client.post(
        "/api/v1/demo/sessions/conv_unknown_no_lead/end",
        json={
            "reason": "user_hangup",
            "client_id": _DEMO_CLIENT_ID,
            "lead_id": None,  # missing
        },
    )

    assert response.status_code == 404, response.text
