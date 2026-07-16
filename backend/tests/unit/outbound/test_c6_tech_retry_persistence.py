"""Phase C6 — Retry & Recontact Policy: tech-retry ScheduledCall persistence test.

Resilience re-review BLOCKER: dial_outbound_call() calls schedule_tech_retry()
after a recurrent_error, but schedule_tech_retry() only flushes (db.flush inside
create_scheduled_call). If the session is closed without a commit — which is the
case for the manual outbound route — the ScheduledCall is rolled back even though
logs say "tech_retry_scheduled".

Fix: dial_outbound_call() must commit after a successful schedule_tech_retry() call
so the ScheduledCall is durably persisted regardless of whether the caller commits.

Tests (externally-visible contract — highest confidence):
T4. dial_outbound_call() recurrent_error path: a real DB + real schedule_tech_retry()
    + real ScheduledCall persistence. Mocks only the ElevenLabs provider (two
    transient failures). Closes the DB session, opens a fresh one, and asserts:
    - A ScheduledCall row exists with trigger_reason='tech_retry', status='pending'
    - The row references the correct lead_id and client_id
    - source_session_id matches the CallSession created during the dial

Tests (behavior-level helper — secondary proof):
T0. flush-only does NOT survive session close: proves that without a commit,
    a schedule_tech_retry() row is invisible from a fresh DB session.
T1. commit after schedule_tech_retry() makes the ScheduledCall durable: proves
    that after schedule_tech_retry() + db.commit(), a fresh DB session can see
    the ScheduledCall row with trigger_reason='tech_retry'.

Tests (implementation-level — secondary corroboration):
T2. db.commit() is called after schedule_tech_retry() returns non-None ScheduledCall.
T3. No extra commit when schedule_tech_retry returns None (max reached or dedup).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ===========================================================================
# DB fixture — isolated SQLite DB for durability tests
# ===========================================================================


@pytest_asyncio.fixture
async def persistence_db(tmp_path: Path):
    """Isolated DB for tech-retry durability tests (behavior-level proof).

    Mirrors the tech_retry_db fixture in test_c6_backoff_and_tech_retry.py.
    Uses a fresh SQLite DB per test via Alembic migrations.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tech_retry_durability.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db

    await _init_db(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Durability Lead",
            phone="+54119999001",
            lead_id="durability-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ===========================================================================
# T0 (RED — proves the gap): flush-only does NOT survive session close
#
# This test documents the root cause of the original BLOCKER:
# create_scheduled_call() calls db.flush(), not db.commit(). A row that is
# only flushed is visible within the same session but is rolled back when the
# session is closed — it never reaches the DB file.
#
# The test intentionally flushes WITHOUT committing and then verifies the row
# is NOT visible from a fresh session. This is the failure mode we fixed.
# ===========================================================================


async def test_tech_retry_row_lost_without_commit(persistence_db):
    """A flushed-but-not-committed tech_retry row is invisible from a fresh session.

    This is the root-cause demonstration of the original B2 BLOCKER:
    - schedule_tech_retry() calls create_scheduled_call() which only does db.flush().
    - If the caller closes the session without db.commit(), the ScheduledCall row is
      rolled back and disappears — even though logs said 'tech_retry_scheduled'.
    - This test proves the gap so the fix (T1) can prove its remedy.

    RED: this test expects the row to be absent after flush-only + session close.
    """
    from app.scheduler.service import schedule_tech_retry
    from app.scheduler.models import ScheduledCall
    from app.calls.models import CallSession
    from sqlalchemy import select

    # Create a source CallSession so schedule_tech_retry can resolve agent_id
    async with persistence_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="durability-lead-001",
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="recurrent_error",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    # Call schedule_tech_retry and flush — but intentionally do NOT commit
    # (simulating the original broken behaviour before the B2 fix)
    flushed_sc_id: str | None = None
    async with persistence_db.async_session_factory() as sess:
        sc = await schedule_tech_retry(
            sess,
            session_id=session_id,
            lead_id="durability-lead-001",
            client_id="quintana-seguros",
        )
        # DO NOT call sess.commit() — flush only (this is the broken path)
        assert sc is not None, "schedule_tech_retry must return a ScheduledCall here"
        flushed_sc_id = sc.id
        # Session closes here without commit → row is rolled back by SQLite

    # Open a FRESH session and verify the row does NOT exist
    async with persistence_db.async_session_factory() as fresh_sess:
        result = await fresh_sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.id == flushed_sc_id,
            )
        )
        row = result.scalar_one_or_none()

    assert row is None, (
        f"ScheduledCall {flushed_sc_id} should NOT be visible after flush-only "
        f"(no commit). This test proves the original gap: flush-only does not "
        f"survive session close."
    )


# ===========================================================================
# T1 (GREEN — behavior-level primary proof): commit makes the row durable
#
# Proves the fix: after schedule_tech_retry() + db.commit(), a fresh DB session
# can see the ScheduledCall row with trigger_reason='tech_retry'.
# This is the behavioral contract that dial_outbound_call() must uphold.
# ===========================================================================


async def test_tech_retry_row_survives_session_close_after_commit(persistence_db):
    """A committed tech_retry row is visible from a fresh DB session after close.

    Behavior-level primary proof of the B2 fix:
    - schedule_tech_retry() creates a ScheduledCall via db.flush() only.
    - dial_outbound_call() now calls db.commit() after schedule_tech_retry()
      returns non-None (the B2 fix).
    - This test simulates that commit and verifies the row persists across a
      session boundary — proving durability independent of whether the caller
      (the manual outbound route) closes the session afterward.

    GREEN: the ScheduledCall row is visible from a fresh session after commit.
    """
    from app.scheduler.service import schedule_tech_retry
    from app.scheduler.models import ScheduledCall
    from app.calls.models import CallSession
    from sqlalchemy import select

    # Create a source CallSession
    async with persistence_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="durability-lead-001",
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="recurrent_error",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        sess.add(cs)
        await sess.commit()
        session_id = cs.id

    # Call schedule_tech_retry AND commit — simulating what dial_outbound_call() does
    committed_sc_id: str | None = None
    async with persistence_db.async_session_factory() as sess:
        sc = await schedule_tech_retry(
            sess,
            session_id=session_id,
            lead_id="durability-lead-001",
            client_id="quintana-seguros",
        )
        assert sc is not None, "schedule_tech_retry must return a ScheduledCall"
        # Simulate the B2 fix: dial_outbound_call() commits after successful tech retry
        await sess.commit()
        committed_sc_id = sc.id
        # Session closes here — the committed row must survive

    # Open a FRESH session and verify the row IS visible
    async with persistence_db.async_session_factory() as fresh_sess:
        result = await fresh_sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.id == committed_sc_id,
            )
        )
        row = result.scalar_one_or_none()

    assert row is not None, (
        f"ScheduledCall {committed_sc_id} must be visible from a fresh DB session "
        f"after session close. The B2 fix (db.commit() in dial_outbound_call) must "
        f"have persisted the row durably."
    )
    assert row.trigger_reason == "tech_retry", (
        f"Expected trigger_reason='tech_retry', got {row.trigger_reason!r}"
    )
    assert row.status == "pending", (
        f"New tech retry must have status='pending', got {row.status!r}"
    )


# ---------------------------------------------------------------------------
# Helper — build an OutboundCallResult for a transient error
# ---------------------------------------------------------------------------


def _transient_result(detail: str = "503 Service Unavailable"):
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "transient"
    return r


def _make_settings():
    s = MagicMock()
    s.enable_outbound_calls = True
    return s


def _make_lead(lead_id: str = "lead-persist-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = "+5491100000099"
    return lead


def _make_agent():
    agent = MagicMock()
    agent.id = "agent-persist-001"
    agent.elevenlabs_agent_id = "el-agent-persist"
    agent.elevenlabs_phone_number_id = "pnum-persist"
    return agent


def _make_client(client_id: str = "client-persist"):
    client = MagicMock()
    client.id = client_id
    return client


# ---------------------------------------------------------------------------
# T2: db.commit() must be called after successful schedule_tech_retry()
#
# Strategy: mock schedule_tech_retry to return a non-None ScheduledCall
# (simulating success), then verify that db.commit() is called after it.
# Secondary corroboration: confirms the code path that calls commit() exists.
# The primary durability proof is in T0/T1 above (real DB, real session close).
# ---------------------------------------------------------------------------


async def test_dial_recurrent_error_commits_after_tech_retry():
    """dial_outbound_call() must commit the DB after schedule_tech_retry succeeds.

    Secondary corroboration (implementation-level): mocks schedule_tech_retry
    and asserts db.commit() call count. For the behavior-level primary proof,
    see test_tech_retry_row_survives_session_close_after_commit (T1 above).

    Spec (C6 resilience): When recurrent_error path calls schedule_tech_retry()
    and it returns a non-None ScheduledCall, dial_outbound_call() MUST call
    db.commit() to durably persist the scheduled row. Without this commit, the
    ScheduledCall is lost if the session is closed by the caller (e.g. the
    manual outbound route) without an explicit commit.
    """
    from app.outbound.service import dial_outbound_call

    # Track every commit call
    commit_calls: list[str] = []

    class FakeCallSession:
        id = "cs-persist-001"
        telephony_status = "dialing"
        telephony_error = None
        outcome_reason = None
        elevenlabs_conversation_id = None
        provider_call_id = None
        provider_metadata = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

    fake_cs = FakeCallSession()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    commit_seq: list[str] = []

    async def _tracked_commit():
        commit_seq.append("commit")

    mock_db.commit.side_effect = _tracked_commit
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    # A fake ScheduledCall returned by schedule_tech_retry (simulating success)
    fake_scheduled_call = MagicMock()
    fake_scheduled_call.id = "sc-tech-001"
    fake_scheduled_call.trigger_reason = "tech_retry"

    with (
        patch("app.outbound.service.validate_e164"),
        patch("app.outbound.service._find_active_call_session", return_value=None),
        patch("app.outbound.service._find_in_progress_scheduled_call", return_value=None),
        patch("app.outbound.service.CallSession", return_value=fake_cs),
        patch("app.outbound.service.ElevenLabsService") as MockEL,
        patch("app.outbound.dynamic_vars.build_dynamic_variables", return_value={}),
        # Patch schedule_tech_retry to return a ScheduledCall (success scenario)
        patch(
            "app.scheduler.service.schedule_tech_retry",
            new_callable=AsyncMock,
            return_value=fake_scheduled_call,
        ),
    ):
        MockEL.return_value.initiate_outbound_call = AsyncMock(
            return_value=_transient_result()
        )

        result = await dial_outbound_call(
            mock_db,
            lead=_make_lead(),
            agent=_make_agent(),
            client=_make_client(),
            settings=_make_settings(),
        )

    assert result.status == "recurrent_error", (
        f"Expected recurrent_error, got {result.status!r}"
    )

    # KEY ASSERTION: db.commit() must be called at least twice.
    # - First commit: pre-dial CallSession (dialing → durable before provider call).
    # - Second commit: recurrent_error outcome (telephony_status='recurrent_error').
    # - Third commit (NEW): after schedule_tech_retry() succeeds (durable ScheduledCall).
    # With the pre-fix code, only 2 commits happen — the ScheduledCall is NOT committed.
    assert len(commit_seq) >= 3, (
        f"Expected at least 3 db.commit() calls after recurrent_error + successful "
        f"schedule_tech_retry(), got {len(commit_seq)}. "
        f"The ScheduledCall created by schedule_tech_retry() is NOT durably persisted "
        f"without a commit in dial_outbound_call() — it will be rolled back when the "
        f"DB session is closed by the caller (manual outbound route)."
    )


# ---------------------------------------------------------------------------
# T3 TRIANGULATE: when schedule_tech_retry returns None (max reached), no extra commit
# ---------------------------------------------------------------------------


async def test_dial_recurrent_error_no_extra_commit_when_tech_retry_skipped():
    """When schedule_tech_retry returns None (max retries reached), no extra commit.

    Triangulation (implementation-level): proves the commit is conditional on
    schedule_tech_retry returning a non-None value. When it returns None (max
    exhausted or dedup), the commit count stays at 2 (pre-dial + recurrent_error).
    """
    from app.outbound.service import dial_outbound_call

    class FakeCallSession:
        id = "cs-persist-002"
        telephony_status = "dialing"
        telephony_error = None
        outcome_reason = None
        elevenlabs_conversation_id = None
        provider_call_id = None
        provider_metadata = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

    fake_cs = FakeCallSession()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    commit_seq: list[str] = []

    async def _tracked_commit():
        commit_seq.append("commit")

    mock_db.commit.side_effect = _tracked_commit
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    with (
        patch("app.outbound.service.validate_e164"),
        patch("app.outbound.service._find_active_call_session", return_value=None),
        patch("app.outbound.service._find_in_progress_scheduled_call", return_value=None),
        patch("app.outbound.service.CallSession", return_value=fake_cs),
        patch("app.outbound.service.ElevenLabsService") as MockEL,
        patch("app.outbound.dynamic_vars.build_dynamic_variables", return_value={}),
        # schedule_tech_retry returns None → max retries exhausted or dedup
        patch(
            "app.scheduler.service.schedule_tech_retry",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        MockEL.return_value.initiate_outbound_call = AsyncMock(
            return_value=_transient_result()
        )

        result = await dial_outbound_call(
            mock_db,
            lead=_make_lead(),
            agent=_make_agent(),
            client=_make_client(),
            settings=_make_settings(),
        )

    assert result.status == "recurrent_error"
    # When schedule_tech_retry returns None, exactly 2 commits:
    # 1. pre-dial CallSession, 2. recurrent_error outcome.
    # No third commit needed — nothing new was persisted.
    assert len(commit_seq) == 2, (
        f"Expected exactly 2 commits when schedule_tech_retry returns None, "
        f"got {len(commit_seq)}"
    )


# ===========================================================================
# T4 (externally-visible contract — highest-confidence proof):
# dial_outbound_call() recurrent_error path → ScheduledCall durable in fresh session
#
# This is the primary externally-visible contract test for the B2 fix.
# Unlike T2/T3 (mock-based commit-count checks) and T0/T1 (schedule_tech_retry
# called directly), this test exercises the FULL dial_outbound_call() code path:
#
#   1. Uses a real DB (isolated SQLite via Alembic migrations)
#   2. Seeds quintana-seguros client + agent + lead
#   3. Mocks ONLY the ElevenLabs provider to return two transient failures
#      (simulating the recurrent_error path)
#   4. Calls dial_outbound_call() with a real AsyncSession — real schedule_tech_retry()
#      is invoked inside dial_outbound_call() (NOT mocked here)
#   5. Closes the DB session (mimicking what the manual outbound route does)
#   6. Opens a FRESH DB session and asserts:
#      - A ScheduledCall row with trigger_reason='tech_retry', status='pending'
#      - The row references the correct lead_id, client_id, source_session_id
#
# This test proves that the B2 fix (db.commit() in dial_outbound_call after
# schedule_tech_retry succeeds) makes the ScheduledCall durable even when the
# caller (the manual outbound route) does not commit after dial_outbound_call().
# ===========================================================================


async def test_dial_outbound_call_recurrent_error_schedules_durable_tech_retry(
    persistence_db,
):
    """dial_outbound_call() recurrent_error path creates a durable ScheduledCall.

    Externally-visible contract (T4 — highest confidence):
    - Mocks ONLY the ElevenLabs provider (two transient failures).
    - Does NOT mock schedule_tech_retry() — uses the real implementation.
    - Closes the DB session after dial_outbound_call() returns.
    - Opens a FRESH DB session and asserts the ScheduledCall row exists.

    Fields verified from the fresh session:
    - trigger_reason == 'tech_retry'
    - status == 'pending'
    - lead_id == the dialed lead's ID
    - client_id == 'quintana-seguros'
    - source_session_id == the CallSession created during the dial

    Spec (C6 resilience): A ScheduledCall created by dial_outbound_call() on the
    recurrent_error path MUST survive session close without a caller commit.
    """
    from app.outbound.service import dial_outbound_call
    from app.scheduler.models import ScheduledCall
    from app.tenants.models import Agent
    from sqlalchemy import select
    from pydantic import SecretStr
    from unittest.mock import AsyncMock, MagicMock, patch

    # --- Build a transient-error result to simulate the provider failing twice ---
    def _transient(detail: str):
        r = MagicMock()
        r.outcome = "error"
        r.provider_call_id = None
        r.provider_metadata = None
        r.error_detail = detail
        r.error_category = "transient"
        return r

    # --- Resolve the quintana agent from the DB ---
    async with persistence_db.async_session_factory() as sess:
        agent_result = await sess.execute(
            select(Agent).where(Agent.client_id == "quintana-seguros")
        )
        real_agent = agent_result.scalars().first()
        assert real_agent is not None, (
            "quintana-seguros agent must exist after seed_quintana()"
        )
        agent_id = real_agent.id
        # ElevenLabs fields may be None on seed data — set them for the test
        real_agent.elevenlabs_agent_id = real_agent.elevenlabs_agent_id or "el-test-agent"
        real_agent.elevenlabs_phone_number_id = (
            real_agent.elevenlabs_phone_number_id or "pnum-test-001"
        )
        await sess.commit()

    # --- Build a mock lead (real lead row exists in DB; agent_id used for resolution) ---
    mock_lead = MagicMock()
    mock_lead.id = "durability-lead-001"
    mock_lead.phone = "+54119999001"

    # --- Build a mock agent (id matches real DB row so schedule_tech_retry can find it) ---
    mock_agent = MagicMock()
    mock_agent.id = agent_id
    mock_agent.elevenlabs_agent_id = "el-test-agent"
    mock_agent.elevenlabs_phone_number_id = "pnum-test-001"

    # --- Build a mock client ---
    mock_client = MagicMock()
    mock_client.id = "quintana-seguros"

    # --- Build a mock settings ---
    mock_settings = MagicMock()
    mock_settings.enable_outbound_calls = True
    mock_settings.elevenlabs_api_key = SecretStr("sk-test")

    # --- Call dial_outbound_call() with a real DB session ---
    call_session_id: str | None = None

    async with persistence_db.async_session_factory() as db:
        with (
            patch(
                "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
                new_callable=AsyncMock,
                side_effect=[
                    _transient("503 attempt 1"),
                    _transient("503 attempt 2"),
                ],
            ),
            patch(
                "app.outbound.dynamic_vars.build_dynamic_variables",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await dial_outbound_call(
                db,
                lead=mock_lead,
                agent=mock_agent,
                client=mock_client,
                settings=mock_settings,
            )

        # Capture the call_session_id BEFORE the session closes
        call_session_id = result.call_session_id
    # <-- DB session closed here (no caller commit after dial_outbound_call).
    #     dial_outbound_call() must have committed internally for the
    #     ScheduledCall to survive.

    # Assert dial resulted in recurrent_error
    assert result.status == "recurrent_error", (
        f"Expected status='recurrent_error' on two consecutive transient failures, "
        f"got {result.status!r}"
    )
    assert call_session_id is not None, "A CallSession must have been created"

    # --- Open a FRESH DB session and verify the ScheduledCall row is durable ---
    async with persistence_db.async_session_factory() as fresh_sess:
        sc_result = await fresh_sess.execute(
            select(ScheduledCall).where(
                ScheduledCall.lead_id == "durability-lead-001",
                ScheduledCall.client_id == "quintana-seguros",
                ScheduledCall.trigger_reason == "tech_retry",
            )
        )
        sc_row = sc_result.scalar_one_or_none()

    assert sc_row is not None, (
        "A ScheduledCall with trigger_reason='tech_retry' must be visible from a "
        "fresh DB session after dial_outbound_call() returns recurrent_error. "
        "The B2 fix (db.commit() in dial_outbound_call) must persist the row "
        "durably regardless of whether the caller commits afterward."
    )
    assert sc_row.status == "pending", (
        f"New tech_retry ScheduledCall must have status='pending', got {sc_row.status!r}"
    )
    assert sc_row.lead_id == "durability-lead-001", (
        f"ScheduledCall.lead_id must match the dialed lead, got {sc_row.lead_id!r}"
    )
    assert sc_row.client_id == "quintana-seguros", (
        f"ScheduledCall.client_id must be 'quintana-seguros', got {sc_row.client_id!r}"
    )
    assert sc_row.source_session_id == call_session_id, (
        f"ScheduledCall.source_session_id must reference the CallSession created "
        f"during the dial (expected {call_session_id!r}), got {sc_row.source_session_id!r}"
    )
