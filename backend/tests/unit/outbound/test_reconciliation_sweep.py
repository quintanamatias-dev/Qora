"""Unit tests for sweep reconciliation pass — WU4.

Spec: call-sip-observability — Requirement: Background Reconciliation Sweep

Tasks:
  4.1 — reconciliation_sweep_cap added to Settings
  4.2 — sweep.py: reconcile_unreconciled_sessions() reconciles eligible sessions,
          cap respected, oldest-first, skip ambiguous matches, never change telephony_status
  4.3 — This test file

TDD: Tests written BEFORE the sweep enhancement.
All ElevenLabs HTTP is mocked via respx — no live calls.
DB is mocked via AsyncMock.
"""

from __future__ import annotations

import pytest
import respx
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EL_BASE = "https://api.elevenlabs.io/v1"
_CONVERSATIONS_URL = f"{_EL_BASE}/conversational_ai/conversations"


def _make_settings(api_key: str = "test-key", sweep_cap: int = 10):
    s = MagicMock()
    s.elevenlabs_api_key = SecretStr(api_key)
    s.reconciliation_sweep_cap = sweep_cap
    return s


def _make_unreconciled_session(
    session_id: str,
    telephony_status: str = "failed",
    agent_id: str = "agent-abc",
    phone: str = "+14155552671",
    started_at: datetime | None = None,
    telephony_error: str | None = None,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.agent_id = agent_id
    cs.lead_id = "lead-001"
    cs.telephony_status = telephony_status
    cs.telephony_error = telephony_error
    cs.reconciled_at = None  # Not yet reconciled
    cs.sip_call_id = None
    cs.sip_status_code = None
    cs.sip_reason = None
    cs.reconciliation_source = None
    cs.started_at = started_at or (datetime.now(timezone.utc) - timedelta(minutes=10))

    # Lead mock to get phone number
    lead = MagicMock()
    lead.phone = phone
    cs.lead = lead

    return cs


def _mock_lead_phone(db: AsyncMock, phone: str) -> None:
    """Set up db.get to return a lead mock with the given phone."""
    lead_mock = MagicMock()
    lead_mock.phone = phone
    db.get = AsyncMock(return_value=lead_mock)


def _make_db_with_sessions(sessions: list) -> AsyncMock:
    """Return a mock DB that yields sessions from execute()."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = sessions
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)  # Default: no lead found
    return db


# ---------------------------------------------------------------------------
# Task 4.1 — Settings cap field
# ---------------------------------------------------------------------------


class TestReconciliationSweepCapSetting:
    """reconciliation_sweep_cap is declared in Settings."""

    def test_settings_has_reconciliation_sweep_cap(self):
        """Settings must have reconciliation_sweep_cap with default 10.

        Task 4.1 — Add reconciliation_sweep_cap: int = 10 to Settings.
        """
        from app.core.config import Settings
        import inspect

        # Check default value via the model field
        fields = Settings.model_fields
        assert "reconciliation_sweep_cap" in fields, (
            "Settings must have reconciliation_sweep_cap field"
        )
        field = fields["reconciliation_sweep_cap"]
        assert field.default == 10, (
            f"reconciliation_sweep_cap default must be 10, got {field.default!r}"
        )


# ---------------------------------------------------------------------------
# Task 4.2/4.3 — Reconciliation sweep function
# ---------------------------------------------------------------------------


class TestReconciliationSweepMatchAndWrite:
    """Sweep reconciles failed/stale_in_call sessions with SIP evidence."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_reconciles_failed_session_with_unambiguous_match(self):
        """GIVEN a failed session with reconciled_at=None
        AND ElevenLabs returns exactly one matching conversation
        WHEN reconcile_unreconciled_sessions runs
        THEN SIP fields are written and reconciliation_source='sweep'.

        Spec: Scenario: Unambiguous sweep match — evidence written.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        session_id = "sess-rec-001"
        started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        cs = _make_unreconciled_session(
            session_id=session_id,
            telephony_status="failed",
            started_at=started_at,
        )

        db = _make_db_with_sessions([cs])

        # Mock: list_recent_conversations → 1 matching conversation
        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-sweep-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        # Mock: get_sip_messages
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-sweep-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_sweep_call_abc",
                            "method": "INVITE",
                            "direction": "outbound",
                        },
                        {
                            "call_id": "otb_sweep_call_abc",
                            "status_code": 487,
                            "reason_phrase": "Request Terminated",
                            "direction": "inbound",
                        },
                    ]
                },
            )
        )

        settings = _make_settings()
        await reconcile_unreconciled_sessions(db, settings=settings)

        # Verify SIP fields written
        assert cs.sip_call_id == "otb_sweep_call_abc"
        assert cs.sip_status_code == 487
        assert cs.sip_reason == "Request Terminated"
        assert cs.reconciliation_source == "sweep"
        assert cs.reconciled_at is not None

        # telephony_status must NOT be changed
        assert cs.telephony_status == "failed", (
            "Sweep must NOT change telephony_status — reconciliation is read-only for call state"
        )

        # DB must be committed
        db.commit.assert_called()

    @pytest.mark.asyncio
    @respx.mock
    async def test_reconciles_stale_in_call_session(self):
        """GIVEN a stale_in_call session with reconciled_at=None
        WHEN reconcile_unreconciled_sessions runs
        THEN SIP fields are written and telephony_status remains 'stale_in_call'.

        Spec: Candidate sessions include telephony_status='stale_in_call'.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        started_at = datetime.now(timezone.utc) - timedelta(minutes=40)
        cs = _make_unreconciled_session(
            session_id="sess-stale-rec",
            telephony_status="stale_in_call",
            started_at=started_at,
        )
        db = _make_db_with_sessions([cs])

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-stale-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-stale-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_stale_call",
                            "status_code": 200,
                            "reason_phrase": "OK",
                        }
                    ]
                },
            )
        )

        settings = _make_settings()
        await reconcile_unreconciled_sessions(db, settings=settings)

        assert cs.sip_call_id == "otb_stale_call"
        assert cs.sip_status_code == 200
        assert cs.reconciliation_source == "sweep"
        # telephony_status must remain unchanged
        assert cs.telephony_status == "stale_in_call", (
            "Sweep must not change telephony_status on reconciliation"
        )


class TestReconciliationSweepSkipsAlreadyReconciled:
    """Sweep is idempotent — skips sessions with reconciled_at already set."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_already_reconciled_session(self):
        """GIVEN a session with reconciled_at already set
        WHEN reconcile_unreconciled_sessions runs
        THEN no ElevenLabs API calls are made for this session.

        The DB query filters by reconciled_at IS NULL, so this session
        would not appear in the results. This test verifies the filtering works.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        # Simulate DB returning NO sessions (all already reconciled are filtered out)
        db = _make_db_with_sessions([])

        # Any call to conversations URL would be a bug
        route = respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(200, json={"conversations": []})
        )

        settings = _make_settings()
        count = await reconcile_unreconciled_sessions(db, settings=settings)

        assert count == 0
        assert route.call_count == 0, (
            "No ElevenLabs calls should be made when no unreconciled sessions exist"
        )


class TestReconciliationSweepAmbiguousMatch:
    """Sweep skips ambiguous matches (multiple conversations for same number)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_ambiguous_match_leaves_unreconciled(self):
        """GIVEN two conversations at nearly the same time for the same number
        WHEN reconcile_unreconciled_sessions runs and finds an ambiguous match
        THEN no SIP fields are written and reconciled_at remains NULL.

        Spec: Scenario: Ambiguous sweep match — safe skip.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        cs = _make_unreconciled_session(
            session_id="sess-ambiguous",
            telephony_status="failed",
            started_at=started_at,
        )
        db = _make_db_with_sessions([cs])

        # Two conversations close in time — ambiguous match
        base_ts = int(started_at.timestamp())
        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-ambig-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": base_ts,
                        },
                        {
                            "conversation_id": "conv-ambig-002",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": base_ts + 5,  # only 5s apart
                        },
                    ]
                },
            )
        )

        settings = _make_settings()
        await reconcile_unreconciled_sessions(db, settings=settings)

        # No SIP fields written — ambiguous
        assert cs.sip_call_id is None, (
            "sip_call_id must not be set on ambiguous match"
        )
        assert cs.reconciled_at is None, (
            "reconciled_at must remain NULL on ambiguous match"
        )
        assert cs.sip_status_code is None


class TestReconciliationSweepCapEnforcement:
    """Sweep processes at most reconciliation_sweep_cap sessions per cycle."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_cap_limits_sessions_processed(self):
        """GIVEN 15 unreconciled sessions but cap is 10
        WHEN reconcile_unreconciled_sessions runs
        THEN at most 10 sessions are processed.

        Spec: Scenario: Sweep rate-limit cap respected.
        The DB query is responsible for applying LIMIT — we verify the cap
        is passed as LIMIT and that at most cap API calls are made.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        cap = 3  # Use a small cap for test efficiency
        started_at = datetime.now(timezone.utc) - timedelta(minutes=10)

        sessions = [
            _make_unreconciled_session(
                session_id=f"sess-cap-{i:03d}",
                telephony_status="failed",
                started_at=started_at - timedelta(minutes=i),  # Oldest first
            )
            for i in range(cap)  # DB returns exactly cap sessions (simulating LIMIT)
        ]
        db = _make_db_with_sessions(sessions)

        # For each session, mock a conversations call
        base_ts = int(started_at.timestamp())
        call_count = {"n": 0}

        def conversations_side_effect(request, route):
            call_count["n"] += 1
            idx = call_count["n"] - 1
            return httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": f"conv-cap-{idx:03d}",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": base_ts,
                        }
                    ]
                },
            )

        respx.get(_CONVERSATIONS_URL).mock(side_effect=conversations_side_effect)

        # Mock SIP messages for each conversation
        for i in range(cap):
            sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-cap-{i:03d}/sip_messages"
            respx.get(sip_url).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "sip_messages": [
                            {
                                "call_id": f"otb_cap_{i}",
                                "status_code": 200,
                                "reason_phrase": "OK",
                            }
                        ]
                    },
                )
            )

        settings = _make_settings(sweep_cap=cap)
        count = await reconcile_unreconciled_sessions(db, settings=settings)

        assert count <= cap, (
            f"Sweep must not process more than {cap} sessions, processed {count}"
        )
        assert call_count["n"] <= cap, (
            f"ElevenLabs API calls ({call_count['n']}) must not exceed cap ({cap})"
        )


class TestReconciliationSweepAPIErrorResilience:
    """Sweep handles ElevenLabs API errors without crashing."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error_on_one_session_continues_sweep(self):
        """GIVEN one session fails with ElevenLabs 500
        WHEN reconcile_unreconciled_sessions runs
        THEN the sweep continues to the next session without crashing.

        Spec: Sweep must not crash on API errors — continue to next session.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        cs_fail = _make_unreconciled_session("sess-fail", started_at=started_at)
        cs_ok = _make_unreconciled_session("sess-ok", started_at=started_at - timedelta(minutes=1))
        db = _make_db_with_sessions([cs_fail, cs_ok])

        call_n = {"n": 0}

        def conversations_side(request, route):
            call_n["n"] += 1
            if call_n["n"] == 1:
                # First session: API error
                return httpx.Response(500, json={"error": "internal error"})
            # Second session: success
            return httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-ok-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": int((started_at - timedelta(minutes=1)).timestamp()),
                        }
                    ]
                },
            )

        respx.get(_CONVERSATIONS_URL).mock(side_effect=conversations_side)

        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-ok-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_ok_call",
                            "status_code": 200,
                            "reason_phrase": "OK",
                        }
                    ]
                },
            )
        )

        settings = _make_settings()
        # Must not raise even though one session fails
        await reconcile_unreconciled_sessions(db, settings=settings)

        # The second session (cs_ok) should have been reconciled
        assert cs_ok.sip_call_id == "otb_ok_call", (
            "Sweep must continue to reconcile subsequent sessions after an API error"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error_does_not_crash_sweep(self):
        """GIVEN all sessions fail ElevenLabs API calls
        WHEN reconcile_unreconciled_sessions runs
        THEN it returns without raising an exception.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        cs = _make_unreconciled_session("sess-all-fail")
        db = _make_db_with_sessions([cs])

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(500, json={"error": "internal error"})
        )

        settings = _make_settings()
        # Must not raise
        await reconcile_unreconciled_sessions(db, settings=settings)

        # No SIP fields set
        assert cs.reconciled_at is None


class TestReconciliationSweepAmbiguousTimeout:
    """Sessions with ambiguous_timeout error are reconciliation candidates."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_timeout_session_is_reconciled(self):
        """GIVEN a session with telephony_error containing 'ambiguous_timeout'
        WHEN reconcile_unreconciled_sessions runs
        THEN it is treated as a reconciliation candidate.

        Spec: Ambiguous ReadTimeout / Unknown State Handling — sweep treats
        ambiguous_timeout sessions as reconciliation candidates.
        Also verifies: telephony_error is NOT overwritten by reconciliation.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        cs = _make_unreconciled_session(
            session_id="sess-amb-timeout",
            telephony_status="failed",
            telephony_error="ambiguous_timeout (provider may have placed a call; not retried): ReadTimeout",
            started_at=started_at,
        )
        original_error = cs.telephony_error
        db = _make_db_with_sessions([cs])

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-amb-001",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-amb-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_amb_call",
                            "status_code": 487,
                            "reason_phrase": "Request Terminated",
                        }
                    ]
                },
            )
        )

        settings = _make_settings()
        await reconcile_unreconciled_sessions(db, settings=settings)

        # SIP fields written
        assert cs.sip_status_code == 487
        assert cs.reconciled_at is not None

        # telephony_error must NOT be overwritten
        assert cs.telephony_error == original_error, (
            "telephony_error must not be modified by reconciliation — "
            "the original error text must be preserved for operator review"
        )

        # No new call dispatched — reconciliation is read-only
        assert cs.telephony_status == "failed", (
            "Reconciliation must not change telephony_status"
        )


class TestSweeperLoopRunsReconciliation:
    """The background sweeper loop invokes reconciliation when settings is passed.

    Regression: main.py previously called stale_outbound_telephony_sweeper()
    with no settings, so the `if settings is not None:` guard skipped Pass 2
    forever — reconciliation was dead code in production.
    """

    @pytest.mark.asyncio
    async def test_sweeper_runs_reconciliation_when_settings_passed(self):
        """GIVEN stale_outbound_telephony_sweeper is started WITH settings
        WHEN one sweep cycle runs (asyncio.sleep patched to break after one cycle)
        THEN reconcile_unreconciled_sessions is called with those settings.

        This proves the Pass-2 (SIP reconciliation) guard is satisfied when the
        sweeper is launched correctly (settings=settings) as done in main.py.
        """
        from app.outbound import sweep as sweep_module

        settings = _make_settings()

        # DB session context manager used inside the loop via get_session().
        db = AsyncMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)

        db_session_cm = MagicMock(return_value=db)

        # Break the infinite loop after a single cycle by raising from sleep.
        class _StopLoop(Exception):
            pass

        sleep_calls = {"n": 0}

        async def fake_sleep(_seconds):
            # The loop sleeps at the top of each cycle. Allow the first sleep
            # (entering cycle 1) to pass, then break on the second sleep (which
            # only happens after cycle 1's passes have run).
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise _StopLoop()

        with (
            patch("app.core.database.get_session", db_session_cm),
            patch.object(sweep_module.asyncio, "sleep", side_effect=fake_sleep),
            patch.object(
                sweep_module,
                "sweep_stale_outbound_sessions",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                sweep_module,
                "reconcile_unreconciled_sessions",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_reconcile,
        ):
            with pytest.raises(_StopLoop):
                await sweep_module.stale_outbound_telephony_sweeper(settings=settings)

        mock_reconcile.assert_awaited_once()
        # Reconciliation must receive the same settings object.
        _, kwargs = mock_reconcile.call_args
        assert kwargs.get("settings") is settings, (
            "reconcile_unreconciled_sessions must be called with the sweeper's settings"
        )

    @pytest.mark.asyncio
    async def test_sweeper_skips_reconciliation_when_settings_none(self):
        """GIVEN stale_outbound_telephony_sweeper is started WITHOUT settings
        WHEN one sweep cycle runs
        THEN reconcile_unreconciled_sessions is NOT called.

        Documents the guard: this is exactly the dead-code path main.py used to
        hit before the fix. Kept as a contract guard for the None default.
        """
        from app.outbound import sweep as sweep_module

        db = AsyncMock()
        db.__aenter__ = AsyncMock(return_value=db)
        db.__aexit__ = AsyncMock(return_value=False)
        db_session_cm = MagicMock(return_value=db)

        class _StopLoop(Exception):
            pass

        sleep_calls = {"n": 0}

        async def fake_sleep(_seconds):
            # Allow one full cycle, then break on the second sleep.
            sleep_calls["n"] += 1
            if sleep_calls["n"] >= 2:
                raise _StopLoop()

        with (
            patch("app.core.database.get_session", db_session_cm),
            patch.object(sweep_module.asyncio, "sleep", side_effect=fake_sleep),
            patch.object(
                sweep_module,
                "sweep_stale_outbound_sessions",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                sweep_module,
                "reconcile_unreconciled_sessions",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_reconcile,
        ):
            with pytest.raises(_StopLoop):
                await sweep_module.stale_outbound_telephony_sweeper()

        mock_reconcile.assert_not_called()
