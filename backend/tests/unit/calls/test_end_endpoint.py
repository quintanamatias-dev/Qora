"""Unit/integration tests for the POST /{conversation_id}/end endpoint (CAP-2a).

Covers:
- Clean close: session → completed, call_count incremented, ended_at set
- ElevenLabs conversation_id resolution (primary lookup path)
- Idempotency: calling /end twice → 200 both times, call_count incremented only once
- Reconciliation fallback: CAP-4 scenarios (T06-T13)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr
from sqlalchemy import select
from structlog.testing import capture_logs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Initialize isolated SQLite DB with quintana-seguros + one lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/end_test.db",
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
            name="Test Lead",
            phone="+5411000001",
            lead_id="test-lead-end-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


@pytest_asyncio.fixture
async def app_client(seeded_db):
    """Test HTTP client wired to calls router."""
    from fastapi import FastAPI
    from app.calls.router import router as calls_router

    test_app = FastAPI()
    test_app.include_router(calls_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


async def _create_session(seeded_db, *, elevenlabs_conversation_id: str | None = None):
    """Helper: create a CallSession in DB and return it."""
    from app.calls.service import create_session

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id=elevenlabs_conversation_id,
        )
        await sess.commit()
        return cs.id, cs.elevenlabs_conversation_id


# ---------------------------------------------------------------------------
# CAP-2a: Clean close via ElevenLabs conversation ID
# ---------------------------------------------------------------------------


async def test_end_by_elevenlabs_id_sets_completed(seeded_db, app_client):
    """POST /{elevenlabs_conversation_id}/end → session status=completed."""
    el_conv_id = "el-conv-abc123"
    internal_id, _ = await _create_session(
        seeded_db, elevenlabs_conversation_id=el_conv_id
    )

    response = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["closed_reason"] == "user_hangup"
    assert data["id"] == internal_id


async def test_end_by_elevenlabs_id_sets_ended_at(seeded_db, app_client):
    """POST /{elevenlabs_conversation_id}/end → ended_at is set on the session."""
    from app.calls.service import get_session

    el_conv_id = "el-conv-ended-at-test"
    internal_id, _ = await _create_session(
        seeded_db, elevenlabs_conversation_id=el_conv_id
    )

    response = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )
    assert response.status_code == 200

    # Verify in DB
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await get_session(sess, internal_id)
        assert cs is not None
        assert cs.ended_at is not None
        assert cs.status == "completed"


async def test_end_increments_call_count(seeded_db, app_client):
    """POST /{elevenlabs_conversation_id}/end → Lead.call_count incremented once."""
    from sqlalchemy import select
    from app.leads.models import Lead

    el_conv_id = "el-conv-call-count"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    # Verify initial count
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        lead_before = result.scalar_one()
        count_before = lead_before.call_count or 0

    # End the session
    response = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )
    assert response.status_code == 200

    # Verify count incremented by 1
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        lead_after = result.scalar_one()
        assert lead_after.call_count == count_before + 1


# ---------------------------------------------------------------------------
# CAP-2a: Fallback to internal UUID lookup
# ---------------------------------------------------------------------------


async def test_end_by_internal_uuid_fallback(seeded_db, app_client):
    """POST /{internal_uuid}/end → works when no ElevenLabs ID is matched."""
    # Session with no elevenlabs_conversation_id
    internal_id, _ = await _create_session(seeded_db, elevenlabs_conversation_id=None)

    response = await app_client.post(
        f"/api/v1/calls/{internal_id}/end",
        json={"reason": "agent_goodbye"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["id"] == internal_id


# ---------------------------------------------------------------------------
# CAP-2a: Idempotency
# ---------------------------------------------------------------------------


async def test_end_idempotent_twice_returns_200(seeded_db, app_client):
    """POST /{el_id}/end called twice → both return 200."""
    el_conv_id = "el-conv-idempotent"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    r1 = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )
    r2 = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )

    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_end_idempotent_call_count_not_double_incremented(seeded_db, app_client):
    """Calling /end twice → Lead.call_count is only incremented once."""
    from sqlalchemy import select
    from app.leads.models import Lead

    el_conv_id = "el-conv-no-double-count"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    # Initial count
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        count_before = result.scalar_one().call_count or 0

    # Call /end twice
    await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end", json={"reason": "user_hangup"}
    )
    await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end", json={"reason": "user_hangup"}
    )

    # call_count should only be +1 (not +2)
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        lead_after = result.scalar_one()
        assert lead_after.call_count == count_before + 1


# ---------------------------------------------------------------------------
# 404 for completely unknown ID
# ---------------------------------------------------------------------------


async def test_end_unknown_id_returns_404(app_client, seeded_db):
    """POST with unknown ID → 404 with no DB side-effects.

    Rationale: 404 is semantically correct for "resource does not exist".
    The frontend handles 404 benignly on WebSocket close paths — this is
    the expected response when ElevenLabs custom-LLM failed to fire and
    no CallSession was ever created.

    Negative invariants asserted:
    - Response body contains correct detail message
    - No CallSession was created as a side-effect of the 404 path
    - Lead.call_count was NOT incremented
    """
    from app.core import database as db_module
    from app.calls.models import CallSession
    from app.leads.models import Lead
    from sqlalchemy import select

    # Snapshot: capture pre-call lead state + session count
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as s:
        pre_lead = (
            await s.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        ).scalar_one()
        pre_call_count = pre_lead.call_count
        pre_session_count = (await s.execute(select(CallSession))).scalars().all()
        pre_session_count = len(pre_session_count)

    # Act
    response = await app_client.post(
        "/api/v1/calls/completely-unknown-id-xyz/end",
        json={"reason": "user_hangup"},
    )

    # HTTP contract
    assert response.status_code == 404
    assert response.json() == {"detail": "Call session not found"}

    # Negative invariants — no DB side-effects
    async with db_module.async_session_factory() as s:
        post_lead = (
            await s.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        ).scalar_one()
        assert (
            post_lead.call_count == pre_call_count
        ), "Lead.call_count must not change on 404 (no session existed to close)"
        post_session_count = (await s.execute(select(CallSession))).scalars().all()
        assert (
            len(post_session_count) == pre_session_count
        ), "No phantom CallSession should be created on the 404 path"


# ---------------------------------------------------------------------------
# Helpers for reconciliation tests
# ---------------------------------------------------------------------------


async def _create_initiated_session(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str | None = "test-lead-end-001",
    elevenlabs_conversation_id: str | None = None,
    started_at: datetime | None = None,
    status: str = "initiated",
):
    """Helper: create a CallSession with specific started_at and status."""
    from app.calls.models import CallSession
    import uuid

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            elevenlabs_conversation_id=elevenlabs_conversation_id,
            status=status,
            started_at=started_at or datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# T06 — RED: Reconciliation happy path (CAP-4)
# ---------------------------------------------------------------------------


async def test_end_reconciliation_happy_path(seeded_db, app_client):
    """Unknown conversation_id + hints matching initiated session within 120s → reconciled."""
    from app.calls.models import CallSession
    from app.leads.models import Lead

    session_id = await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )

    response = await app_client.post(
        "/api/v1/calls/conv_unknown_reconcile/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.json()}"
    data = response.json()
    assert data["status"] == "completed"
    assert data["closed_reason"] == "user_hangup"
    assert data["id"] == session_id

    # Verify in DB
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.elevenlabs_conversation_id == "conv_unknown_reconcile"
        assert cs.status == "completed"
        assert cs.closed_reason == "user_hangup"
        assert cs.ended_at is not None

    # Verify Lead.call_count was incremented
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        lead = result.scalar_one()
        assert lead.call_count == 1, f"Expected call_count=1, got {lead.call_count}"


# ---------------------------------------------------------------------------
# T07 — RED: call_count incremented exactly once (both paths)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_reconciliation", [False, True])
async def test_end_does_not_double_increment_call_count(
    seeded_db, app_client, use_reconciliation
):
    """Lead.call_count increments 0→1 exactly once, for both direct close and reconciliation."""
    from app.leads.models import Lead

    if use_reconciliation:
        # Orphan session — no elevenlabs_conversation_id → reconciled via hints
        await _create_initiated_session(
            seeded_db,
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id=None,
            started_at=datetime.now(timezone.utc) - timedelta(seconds=15),
        )
        response = await app_client.post(
            "/api/v1/calls/conv_no_double_reconcile/end",
            json={
                "reason": "user_hangup",
                "client_id": "quintana-seguros",
                "lead_id": "test-lead-end-001",
            },
        )
    else:
        # Direct close — session has matching elevenlabs_conversation_id
        await _create_initiated_session(
            seeded_db,
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id="conv_no_double_direct",
        )
        response = await app_client.post(
            "/api/v1/calls/conv_no_double_direct/end",
            json={"reason": "user_hangup"},
        )

    assert response.status_code == 200

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "test-lead-end-001"))
        lead = result.scalar_one()
        assert lead.call_count == 1, (
            f"Expected call_count=1 (not doubled), got {lead.call_count} "
            f"(reconciliation={use_reconciliation})"
        )


# ---------------------------------------------------------------------------
# T08 — RED: Expired window → 404
# ---------------------------------------------------------------------------


async def test_end_reconciliation_expired_window_rejects(seeded_db, app_client):
    """Initiated session older than 120s MUST NOT be reconciled → 404."""
    await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=200),
    )

    response = await app_client.post(
        "/api/v1/calls/conv_expired_window/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 for expired session (200s old, window=120s), got {response.status_code}"


# ---------------------------------------------------------------------------
# T09 — RED: Wrong tenant cannot steal another tenant's session
# ---------------------------------------------------------------------------


async def test_end_reconciliation_does_not_steal_other_tenant_session(
    seeded_db, app_client
):
    """Session belonging to client B cannot be reconciled by client A."""
    from app.calls.models import CallSession
    from app.leads.service import create_lead
    from app.tenants.service import create_client

    # Seed a second client
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        await create_client(
            sess,
            id="other-client",
            name="Other Corp",
            broker_name="OC",
            agent_name="Bot",
            voice_id="pNInz6obpgDQGcFmaJgB",
        )
        await create_lead(
            sess,
            client_id="other-client",
            name="Other Lead",
            phone="+54119999999",
            lead_id="lead-other-001",
        )
        await sess.commit()

    # Session belongs to other-client + lead-other-001
    session_id = await _create_initiated_session(
        seeded_db,
        client_id="other-client",
        lead_id="lead-other-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    # Attempt reconciliation from quintana-seguros (wrong tenant)
    response = await app_client.post(
        "/api/v1/calls/conv_wrong_tenant/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",  # wrong client
            "lead_id": "lead-other-001",
        },
    )

    assert (
        response.status_code == 404
    ), f"Wrong tenant MUST get 404, not {response.status_code}"

    # Verify the other-client session is untouched
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert (
            cs.status == "initiated"
        ), f"Session must remain 'initiated', got {cs.status!r}"
        assert (
            cs.elevenlabs_conversation_id is None
        ), "Session must not have been modified"


# ---------------------------------------------------------------------------
# T10 — RED: Only 'initiated' sessions qualify for reconciliation
# ---------------------------------------------------------------------------


async def test_end_reconciliation_only_matches_initiated_status(seeded_db, app_client):
    """A 'completed' session within 120s MUST NOT be reconciled → 404."""
    await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        status="completed",  # already completed
    )

    response = await app_client.post(
        "/api/v1/calls/conv_completed_status/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )

    assert (
        response.status_code == 404
    ), f"Completed session MUST NOT be reconciled; expected 404, got {response.status_code}"


# ---------------------------------------------------------------------------
# T11 — RED: Most recent session is picked when two match
# ---------------------------------------------------------------------------


async def test_end_reconciliation_picks_most_recent(seeded_db, app_client):
    """Two initiated sessions within 120s → the MORE RECENT one is reconciled."""
    from app.calls.models import CallSession

    now = datetime.now(timezone.utc)
    # Older session (60s ago)
    older_id = await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=now - timedelta(seconds=60),
    )
    # More recent session (30s ago)
    newer_id = await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=now - timedelta(seconds=30),
    )

    response = await app_client.post(
        "/api/v1/calls/conv_pick_most_recent/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.json()}"
    data = response.json()

    # The NEWER session should be reconciled
    assert (
        data["id"] == newer_id
    ), f"Expected newer_id={newer_id!r} to be reconciled, got {data['id']!r}"

    # The OLDER session must remain initiated
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        result = await sess.execute(
            select(CallSession).where(CallSession.id == older_id)
        )
        cs_older = result.scalar_one()
        assert (
            cs_older.status == "initiated"
        ), f"Older session must remain 'initiated', got {cs_older.status!r}"


# ---------------------------------------------------------------------------
# T12 — RED: Reconciliation emits structured log event
# ---------------------------------------------------------------------------


async def test_end_reconciliation_emits_log_event(seeded_db, app_client):
    """Successful reconciliation emits 'end_session_reconciled' log with required fields."""
    session_id = await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=45),
    )

    with capture_logs() as cap:
        response = await app_client.post(
            "/api/v1/calls/conv_log_test/end",
            json={
                "reason": "agent_goodbye",
                "client_id": "quintana-seguros",
                "lead_id": "test-lead-end-001",
            },
        )

    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.json()}"

    # Find reconciliation log
    reconcile_logs = [e for e in cap if e.get("event") == "end_session_reconciled"]
    assert (
        len(reconcile_logs) >= 1
    ), f"Expected 'end_session_reconciled' log, got events: {[e.get('event') for e in cap]}"
    log = reconcile_logs[0]
    assert (
        log.get("reconciled_session_id") == session_id
    ), f"reconciled_session_id wrong: {log}"
    assert log.get("client_id") == "quintana-seguros", f"client_id missing/wrong: {log}"
    assert log.get("lead_id") == "test-lead-end-001", f"lead_id missing/wrong: {log}"
    assert (
        log.get("conversation_id") == "conv_log_test"
    ), f"conversation_id missing/wrong: {log}"
    assert "age_seconds" in log, f"age_seconds missing: {log}"
    assert isinstance(log["age_seconds"], int), f"age_seconds must be int: {log}"


# ---------------------------------------------------------------------------
# T13 — RED: No hints → 404 (backward compat)
# ---------------------------------------------------------------------------


async def test_end_without_hints_still_returns_404(seeded_db, app_client):
    """Unknown conversation_id without client_id/lead_id hints → 404 (no reconciliation)."""
    response = await app_client.post(
        "/api/v1/calls/conv_no_hints_unknown/end",
        json={"reason": "user_hangup"},
        # NO client_id or lead_id in body
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 when no hints provided, got {response.status_code}: {response.json()}"


# ---------------------------------------------------------------------------
# T28 — RED: duration_seconds must be integer, not float (CAP-4)
# ---------------------------------------------------------------------------


async def test_end_duration_seconds_is_integer(seeded_db, app_client):
    """POST /{el_id}/end → response duration_seconds is an integer, not float.

    RED condition: service.py computes duration_seconds via .total_seconds() which returns
    a float. Schema declares float. Spec (CAP-4) requires integer. After the fix:
    - service.py must cast to int: int((ended_at - started_at).total_seconds())
    - schemas.py EndSessionResponse.duration_seconds must be int | None
    """
    el_conv_id = "el-conv-duration-int-test"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    response = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )

    assert response.status_code == 200
    data = response.json()

    duration = data["duration_seconds"]
    assert (
        duration is not None
    ), "duration_seconds should not be None after a valid close"
    assert duration == int(duration), (
        f"duration_seconds must be an integer value, got {duration!r} (type {type(duration).__name__}). "
        f"Fix: use int((ended_at - started_at).total_seconds()) in service.py and "
        f"change EndSessionResponse.duration_seconds to int | None in schemas.py."
    )
    # Verify it's serialized as int (no decimal point) — JSON integers have no .0
    assert isinstance(duration, int), (
        f"JSON-decoded duration_seconds must be Python int, got {type(duration).__name__}: {duration!r}. "
        f"Fix EndSessionResponse schema: duration_seconds: int | None"
    )


# ---------------------------------------------------------------------------
# T30 — GREEN: /end body accepts conversation_id (cosmetic, REQ-2.2)
# ---------------------------------------------------------------------------


async def test_end_body_conversation_id_matching_path_succeeds(seeded_db, app_client):
    """POST /end with conversation_id in body matching path → 200, no warning emitted.

    REQ-2.2: Clients may include conversation_id in body for contract clarity.
    When body value matches path param, request proceeds normally without any warning.
    """
    el_conv_id = "el-conv-t30-match"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    with capture_logs() as cap:
        response = await app_client.post(
            f"/api/v1/calls/{el_conv_id}/end",
            json={
                "reason": "user_hangup",
                "conversation_id": el_conv_id,  # matches path — no mismatch
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"

    # No mismatch warning should be emitted when values match
    mismatch_logs = [e for e in cap if e.get("event") == "conversation_id_mismatch_end"]
    assert len(mismatch_logs) == 0, (
        f"No mismatch warning expected when body conversation_id == path param. "
        f"Got: {mismatch_logs}"
    )


async def test_end_body_conversation_id_mismatch_logs_warning_uses_path(
    seeded_db, app_client
):
    """POST /end with conversation_id in body differing from path → 200, warning logged, path wins.

    Triangulation: test_end_body_conversation_id_matching_path_succeeds covers matching values;
    this covers mismatched values. Path value must win; a warning is logged; session is still closed.
    """
    el_conv_id = "el-conv-t30-mismatch"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    with capture_logs() as cap:
        response = await app_client.post(
            f"/api/v1/calls/{el_conv_id}/end",
            json={
                "reason": "user_hangup",
                "conversation_id": "different-conv-id",  # differs from path
            },
        )

    # Path wins → session is found and closed
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"

    # Warning must be emitted
    mismatch_logs = [e for e in cap if e.get("event") == "conversation_id_mismatch_end"]
    assert len(mismatch_logs) >= 1, (
        f"Expected conversation_id_mismatch_end warning when body differs from path. "
        f"Got events: {[e.get('event') for e in cap]}"
    )
    log = mismatch_logs[0]
    assert (
        log.get("path_conversation_id") == el_conv_id
    ), f"path_conversation_id wrong: {log}"
    assert (
        log.get("body_conversation_id") == "different-conv-id"
    ), f"body_conversation_id wrong: {log}"


# ---------------------------------------------------------------------------
# Issue #22 — Merge siblings in close_session() BEFORE _schedule_summarize()
# ---------------------------------------------------------------------------


async def _create_initiated_session_no_el_id(
    db_module,
    *,
    client_id: str = "quintana-seguros",
    lead_id: str = "test-lead-end-001",
    started_at: datetime | None = None,
):
    """Helper: create an orphan session with no EL ID (sibling candidate)."""
    from app.calls.models import CallSession
    import uuid as _uuid

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(_uuid.uuid4()),
            client_id=client_id,
            lead_id=lead_id,
            elevenlabs_conversation_id=None,
            status="initiated",
            started_at=started_at or datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


async def test_close_session_merges_siblings_before_summarize(seeded_db, app_client):
    """close_session() merges sibling turns into completed session before summarize fires.

    Spec: Requirement: Integration with close_session — "Summarizer receives merged transcript"
    Sibling S has 2 turns; closing primary session C should absorb them.
    """
    from app.calls.service import create_session, add_transcript_turn, get_transcript
    from app.calls.models import CallSession
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None

    # Create primary session (will be closed via /end)
    primary_id = None
    sibling_id = None
    async with seeded_db.async_session_factory() as sess:
        primary = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id="el-conv-merge-test-001",
        )
        primary.started_at = now
        await sess.flush()

        # Sibling: no EL ID, same client/lead, 30s earlier
        sibling = CallSession(
            id=str(__import__("uuid").uuid4()),
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id=None,
            status="initiated",
            started_at=now - timedelta(seconds=30),
        )
        sess.add(sibling)
        await sess.flush()

        # Add 1 turn to primary, 2 to sibling
        await add_transcript_turn(sess, primary.id, "agent", "Primary turn")
        await add_transcript_turn(sess, sibling.id, "user", "Sibling turn 1")
        await add_transcript_turn(sess, sibling.id, "user", "Sibling turn 2")
        await sess.commit()

        primary_id = primary.id
        sibling_id = sibling.id

    # Close via /end
    response = await app_client.post(
        "/api/v1/calls/el-conv-merge-test-001/end",
        json={"reason": "user_hangup"},
    )
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.json()}"

    # Verify: primary session should have 3 turns (absorbed sibling turns)
    async with seeded_db.async_session_factory() as sess:
        turns = await get_transcript(sess, primary_id)
        assert len(turns) == 3, (
            f"Expected 3 turns (1 primary + 2 sibling) after merge, got {len(turns)}. "
            f"Merge must run inside close_session() before summarize fires."
        )

        # Sibling must be marked as merged
        result = await sess.execute(
            select(CallSession).where(CallSession.id == sibling_id)
        )
        sibling_reloaded = result.scalar_one()
        assert sibling_reloaded.merged_into_session_id == primary_id, (
            f"Sibling must have merged_into_session_id={primary_id!r}, "
            f"got {sibling_reloaded.merged_into_session_id!r}"
        )


async def test_close_session_no_siblings_unaffected(seeded_db, app_client):
    """close_session() with no siblings completes normally — no errors, no side effects.

    Spec: Requirement: Integration with close_session — "No siblings found — close_session unaffected"
    """
    el_conv_id = "el-conv-no-siblings-test"
    await _create_session(seeded_db, elevenlabs_conversation_id=el_conv_id)

    response = await app_client.post(
        f"/api/v1/calls/{el_conv_id}/end",
        json={"reason": "user_hangup"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"


async def test_reconcile_session_merges_siblings(seeded_db, app_client):
    """_reconcile_session() also merges sibling turns before scheduling summarize.

    Spec: Design — "_reconcile_session integration: Call _merge_sibling_sessions at end too"
    When a session is reconciled (no EL ID → matched by client/lead), siblings are absorbed.
    """
    from app.calls.models import CallSession
    from app.calls.service import add_transcript_turn, get_transcript
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    assert seeded_db.async_session_factory is not None

    primary_id = None
    sibling_id = None
    async with seeded_db.async_session_factory() as sess:
        # Primary orphan session (no EL ID, will be reconciled)
        primary = CallSession(
            id=str(__import__("uuid").uuid4()),
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id=None,
            status="initiated",
            started_at=now - timedelta(seconds=20),
        )
        # Sibling orphan — also no EL ID, same client/lead/window
        sibling = CallSession(
            id=str(__import__("uuid").uuid4()),
            client_id="quintana-seguros",
            lead_id="test-lead-end-001",
            elevenlabs_conversation_id=None,
            status="abandoned",
            started_at=now - timedelta(seconds=40),
        )
        sess.add_all([primary, sibling])
        await sess.flush()

        await add_transcript_turn(sess, primary.id, "agent", "Primary turn")
        await add_transcript_turn(sess, sibling.id, "user", "Sibling turn")
        await sess.commit()

        primary_id = primary.id
        sibling_id = sibling.id

    # Trigger reconciliation by using unknown conv_id + hints
    response = await app_client.post(
        "/api/v1/calls/conv_reconcile_merge_test/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )
    assert response.status_code == 200

    # The reconciled session must have absorbed sibling turns
    async with seeded_db.async_session_factory() as sess:
        turns = await get_transcript(sess, primary_id)
        assert len(turns) == 2, (
            f"Expected 2 turns after reconciliation+merge, got {len(turns)}. "
            f"_reconcile_session() must call _merge_sibling_sessions()."
        )

        result = await sess.execute(
            select(CallSession).where(CallSession.id == sibling_id)
        )
        sibling_reloaded = result.scalar_one()
        assert sibling_reloaded.merged_into_session_id == primary_id


async def test_end_reconciliation_duration_seconds_is_integer(seeded_db, app_client):
    """Reconciled session close → response duration_seconds is also an integer.

    Triangulation: test_end_duration_seconds_is_integer covers direct close;
    this covers the reconciliation path (_reconcile_session in service.py).
    Both code paths must cast duration to int.
    """
    session_id = await _create_initiated_session(
        seeded_db,
        client_id="quintana-seguros",
        lead_id="test-lead-end-001",
        elevenlabs_conversation_id=None,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )

    response = await app_client.post(
        "/api/v1/calls/conv_reconcile_duration_int/end",
        json={
            "reason": "user_hangup",
            "client_id": "quintana-seguros",
            "lead_id": "test-lead-end-001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id

    duration = data["duration_seconds"]
    assert (
        duration is not None
    ), "duration_seconds should not be None after reconciliation"
    assert isinstance(duration, int), (
        f"Reconciliation path duration_seconds must be Python int, "
        f"got {type(duration).__name__}: {duration!r}. "
        f"Fix: int((now - started).total_seconds()) in _reconcile_session."
    )
