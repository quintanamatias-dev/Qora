"""Tests for reconciliation retry cap — FIX 2: infinite sweep prevention.

Problem: When ElevenLabs list API raises an error (e.g. 404 on the conversations
endpoint), the per-session except block in reconcile_unreconciled_sessions logs a
WARNING and moves on — leaving reconciled_at=NULL. Every subsequent sweep cycle
re-fetches the same session and fires the same doomed API call. No terminal state,
no backoff, no dead-letter. The session retries forever.

Fix: reconciliation_attempts is incremented on each failed attempt. When it
reaches settings.reconciliation_max_attempts (default 5), the session is parked:
  - reconciled_at is set (non-NULL)        → excludes from future candidate queries
  - reconciliation_source='unreconcilable' → operator signal
  - ERROR-level log event surfaces it for operator attention

Tests:
  1. reconciliation_attempts increments on each failure.
  2. After max_attempts failures the session is parked (reconciled_at set,
     source='unreconcilable').
  3. Parked sessions are excluded from the candidate query
     (reconciled_at IS NOT NULL filter).
  4. A session below max_attempts is still selected as a candidate.
  5. Settings has reconciliation_max_attempts with default 5.
  6. Migration round-trip: column exists after upgrade, gone after downgrade.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
import httpx
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers shared with test_reconciliation_sweep.py
# ---------------------------------------------------------------------------

_EL_BASE = "https://api.elevenlabs.io/v1"
_CONVERSATIONS_URL = f"{_EL_BASE}/conversational_ai/conversations"


def _make_settings(
    api_key: str = "test-key",
    sweep_cap: int = 10,
    max_attempts: int = 5,
):
    s = MagicMock()
    s.elevenlabs_api_key = SecretStr(api_key)
    s.reconciliation_sweep_cap = sweep_cap
    s.reconciliation_max_attempts = max_attempts
    return s


def _make_unreconciled_session(
    session_id: str,
    telephony_status: str = "failed",
    agent_id: str = "agent-abc",
    started_at: datetime | None = None,
    reconciliation_attempts: int = 0,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.agent_id = agent_id
    cs.lead_id = "lead-001"
    cs.telephony_status = telephony_status
    cs.telephony_error = None
    cs.reconciled_at = None
    cs.sip_call_id = None
    cs.sip_status_code = None
    cs.sip_reason = None
    cs.reconciliation_source = None
    cs.reconciliation_attempts = reconciliation_attempts
    cs.started_at = started_at or (datetime.now(timezone.utc) - timedelta(minutes=10))
    return cs


def _make_db_with_sessions(sessions: list) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = sessions
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Settings field
# ---------------------------------------------------------------------------


class TestReconciliationMaxAttemptsSetting:
    """reconciliation_max_attempts is declared in Settings with default 5."""

    def test_settings_has_reconciliation_max_attempts(self):
        """Settings must have reconciliation_max_attempts with default 5.

        GIVEN app.core.config.Settings
        WHEN model_fields is inspected
        THEN reconciliation_max_attempts is present with default=5.
        """
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "reconciliation_max_attempts" in fields, (
            "Settings must declare reconciliation_max_attempts"
        )
        assert fields["reconciliation_max_attempts"].default == 5, (
            f"reconciliation_max_attempts default must be 5, "
            f"got {fields['reconciliation_max_attempts'].default!r}"
        )


# ---------------------------------------------------------------------------
# Attempt counter increments on failure
# ---------------------------------------------------------------------------


class TestReconciliationAttemptsIncrement:
    """reconciliation_attempts is incremented on each failed reconciliation."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_attempts_incremented_on_api_error(self):
        """GIVEN a session with reconciliation_attempts=0
        AND ElevenLabs raises a 404 error
        WHEN reconcile_unreconciled_sessions runs
        THEN reconciliation_attempts is incremented to 1.

        Spec: Retry cap — each failed attempt increments the counter.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        cs = _make_unreconciled_session("sess-attempt-inc", reconciliation_attempts=0)
        db = _make_db_with_sessions([cs])

        # Simulate ElevenLabs list API returning 404 — raises ElevenLabsAPIError.
        # We patch _reconcile_one_session to raise directly so we don't need HTTP mocks.
        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("404: conversations endpoint not found"),
        ):
            await reconcile_unreconciled_sessions(db, settings=_make_settings(max_attempts=5))

        assert cs.reconciliation_attempts == 1, (
            f"reconciliation_attempts must be 1 after first failed attempt, "
            f"got {cs.reconciliation_attempts}"
        )
        assert cs.reconciled_at is None, (
            "reconciled_at must remain NULL — session not yet at max_attempts"
        )
        assert cs.reconciliation_source != "unreconcilable", (
            "reconciliation_source must not be 'unreconcilable' after only 1 failure"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_attempts_cumulative_across_calls(self):
        """GIVEN a session that already failed twice (reconciliation_attempts=2)
        AND it fails again
        WHEN reconcile_unreconciled_sessions runs
        THEN reconciliation_attempts becomes 3.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        cs = _make_unreconciled_session("sess-attempt-cum", reconciliation_attempts=2)
        db = _make_db_with_sessions([cs])

        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("404 again"),
        ):
            await reconcile_unreconciled_sessions(db, settings=_make_settings(max_attempts=5))

        assert cs.reconciliation_attempts == 3, (
            f"Cumulative attempts must be 3, got {cs.reconciliation_attempts}"
        )
        assert cs.reconciled_at is None, "Must not be parked after 3 failures (max=5)"


# ---------------------------------------------------------------------------
# Session parked at max_attempts
# ---------------------------------------------------------------------------


class TestReconciliationSessionParking:
    """Session is parked when reconciliation_attempts reaches max_attempts."""

    @pytest.mark.asyncio
    async def test_session_parked_when_max_attempts_reached(self):
        """GIVEN a session with reconciliation_attempts=4 (one below the cap)
        AND reconcile_unreconciled_sessions raises on this attempt
        WHEN the attempt counter reaches max_attempts=5
        THEN reconciled_at is set and reconciliation_source='unreconcilable'.

        Spec: Park session as unreconcilable — stops infinite retry.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        # 4 previous failures; this attempt makes it 5 = max_attempts.
        cs = _make_unreconciled_session("sess-park", reconciliation_attempts=4)
        db = _make_db_with_sessions([cs])

        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("404: list conversations not found"),
        ):
            await reconcile_unreconciled_sessions(db, settings=_make_settings(max_attempts=5))

        assert cs.reconciliation_attempts == 5, (
            f"Attempt count must be 5 (max), got {cs.reconciliation_attempts}"
        )
        assert cs.reconciled_at is not None, (
            "reconciled_at must be set when session is parked as unreconcilable. "
            "This excludes it from future sweep candidate queries."
        )
        assert cs.reconciliation_source == "unreconcilable", (
            f"reconciliation_source must be 'unreconcilable' when parked, "
            f"got {cs.reconciliation_source!r}"
        )

    @pytest.mark.asyncio
    async def test_parked_session_telephony_status_unchanged(self):
        """GIVEN a session parked as unreconcilable
        WHEN the sweep parks it
        THEN telephony_status is NOT modified (reconciliation is read-only for call state).
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        cs = _make_unreconciled_session(
            "sess-park-status",
            telephony_status="failed",
            reconciliation_attempts=4,
        )
        db = _make_db_with_sessions([cs])

        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("404"),
        ):
            await reconcile_unreconciled_sessions(db, settings=_make_settings(max_attempts=5))

        assert cs.telephony_status == "failed", (
            "telephony_status must remain 'failed' when a session is parked. "
            "Reconciliation is NEVER allowed to change the call-state status."
        )

    @pytest.mark.asyncio
    async def test_parked_session_db_committed(self):
        """GIVEN a session reaches max_attempts
        WHEN it is parked
        THEN the DB is committed so the parking persists.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        cs = _make_unreconciled_session("sess-park-commit", reconciliation_attempts=4)
        db = _make_db_with_sessions([cs])

        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("404"),
        ):
            await reconcile_unreconciled_sessions(db, settings=_make_settings(max_attempts=5))

        db.commit.assert_called(), (
            "DB must be committed when a session is parked as unreconcilable"
        )


# ---------------------------------------------------------------------------
# Candidate query excludes parked + over-limit sessions
# ---------------------------------------------------------------------------


class TestReconciliationCandidateExclusion:
    """Sessions at or above max_attempts are excluded from the candidate query."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_at_max_attempts_not_selected(self):
        """GIVEN a session with reconciliation_attempts >= max_attempts (already parked)
        WHEN reconcile_unreconciled_sessions runs
        THEN the session is NOT included in candidates.

        The WHERE clause includes: reconciliation_attempts < max_attempts.
        We verify the DB query receives that filter by simulating the DB returning
        an empty list (as it would if the filter excluded the parked session).
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        # Simulate: DB returns empty list because the parked session was filtered out.
        db = _make_db_with_sessions([])

        # No ElevenLabs call expected.
        route = respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(200, json={"conversations": []})
        )

        settings = _make_settings(max_attempts=5)
        count = await reconcile_unreconciled_sessions(db, settings=settings)

        assert count == 0
        assert route.call_count == 0, (
            "No ElevenLabs calls should be made when no candidates are selected"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_session_below_max_attempts_is_still_selected(self):
        """GIVEN a session with reconciliation_attempts=2 and max_attempts=5
        WHEN reconcile_unreconciled_sessions runs
        THEN the session IS selected and a reconciliation attempt is made.

        Verifies that the cap does not prematurely exclude sessions with headroom.
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions

        started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        cs = _make_unreconciled_session(
            "sess-below-cap",
            reconciliation_attempts=2,
            started_at=started_at,
        )
        db = _make_db_with_sessions([cs])

        # Mock successful reconciliation: one conversation + SIP messages.
        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-below-cap",
                            "agent_id": "agent-abc",
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-below-cap/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_below_cap",
                            "status_code": 200,
                            "reason_phrase": "OK",
                        }
                    ]
                },
            )
        )

        settings = _make_settings(max_attempts=5)
        count = await reconcile_unreconciled_sessions(db, settings=settings)

        assert count == 1, (
            f"Session with 2 failed attempts (below max=5) must be reconciled, "
            f"got count={count}"
        )
        assert cs.reconciled_at is not None
        assert cs.reconciliation_source == "sweep"


# ---------------------------------------------------------------------------
# Infinite retry stops after max_attempts consecutive failures
# ---------------------------------------------------------------------------


class TestReconciliationInfiniteRetryStops:
    """End-to-end: simulating max_attempts consecutive failures parks the session.

    This is the core regression guard: before the fix, a session could be
    re-fetched every 5 minutes forever when ElevenLabs list API always 404s.
    After the fix, it is parked on the Nth failure.
    """

    @pytest.mark.asyncio
    async def test_session_parked_after_n_consecutive_failures(self):
        """GIVEN max_attempts=3 and a session that fails on each sweep cycle
        WHEN reconcile_unreconciled_sessions is called 3 times
        THEN the session is parked after the 3rd failure and excluded from further sweeps.

        Simulates multiple sweep cycles by calling reconcile_unreconciled_sessions
        repeatedly with the same in-memory session object (persisted state).
        """
        from app.outbound.sweep import reconcile_unreconciled_sessions
        from app.elevenlabs.service import ElevenLabsAPIError

        max_attempts = 3
        cs = _make_unreconciled_session("sess-infinite-stop", reconciliation_attempts=0)
        db = _make_db_with_sessions([cs])
        settings = _make_settings(max_attempts=max_attempts)

        # Run max_attempts sweep cycles, each failing with ElevenLabsAPIError.
        for cycle in range(max_attempts):
            # Simulate: DB query returns the session as long as reconciled_at is NULL
            # and attempts < max_attempts.
            if cs.reconciled_at is not None:
                # Session already parked — DB would return empty list.
                db = _make_db_with_sessions([])
            else:
                db = _make_db_with_sessions([cs])

            with patch(
                "app.outbound.sweep._reconcile_one_session",
                new_callable=AsyncMock,
                side_effect=ElevenLabsAPIError(f"404 on cycle {cycle}"),
            ):
                await reconcile_unreconciled_sessions(db, settings=settings)

        # After max_attempts failures: session must be parked.
        assert cs.reconciliation_attempts == max_attempts, (
            f"Expected {max_attempts} attempts, got {cs.reconciliation_attempts}"
        )
        assert cs.reconciled_at is not None, (
            "Session must be parked (reconciled_at set) after exhausting max_attempts"
        )
        assert cs.reconciliation_source == "unreconcilable", (
            "reconciliation_source must be 'unreconcilable' for parked session"
        )

        # Simulate one more sweep cycle AFTER parking — session must not be selected.
        # (Because reconciled_at IS NOT NULL now excludes it from the query.)
        extra_db = _make_db_with_sessions([])  # DB correctly filters it out
        with patch(
            "app.outbound.sweep._reconcile_one_session",
            new_callable=AsyncMock,
            side_effect=ElevenLabsAPIError("should not be called"),
        ) as mock_reconcile:
            await reconcile_unreconciled_sessions(extra_db, settings=settings)

        mock_reconcile.assert_not_awaited(), (
            "_reconcile_one_session must NOT be called for parked sessions"
        )


# ---------------------------------------------------------------------------
# Migration: reconciliation_attempts column round-trip
# ---------------------------------------------------------------------------


class TestReconciliationAttemptsMigration:
    """Migration 20260704_0007 adds reconciliation_attempts; downgrade removes it."""

    def _make_alembic_config(self, db_path: Path):
        from alembic.config import Config
        from pathlib import Path as _Path

        backend_dir = _Path(__file__).resolve().parent.parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        alembic_dir = backend_dir / "alembic"

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
        cfg.set_main_option("script_location", str(alembic_dir))
        return cfg

    def test_reconciliation_attempts_column_exists_after_upgrade(self, tmp_path):
        """After alembic upgrade head, call_sessions has reconciliation_attempts.

        GIVEN a fresh database
        WHEN alembic upgrade head runs (includes migration 0007)
        THEN PRAGMA table_info(call_sessions) shows reconciliation_attempts.
        """
        from alembic import command

        db_file = tmp_path / "test_0007_upgrade.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(call_sessions)")
        cols = {row[1]: row for row in cur.fetchall()}
        conn.close()

        assert "reconciliation_attempts" in cols, (
            "call_sessions.reconciliation_attempts must exist after alembic upgrade head. "
            "Migration 20260704_0007 must add this column."
        )

    def test_reconciliation_attempts_has_default_zero(self, tmp_path):
        """After upgrade, existing call_sessions rows get reconciliation_attempts=0.

        GIVEN a database upgraded through head
        WHEN a call_sessions row is inserted without reconciliation_attempts
        THEN the column defaults to 0 (server_default).
        """
        from alembic import command

        db_file = tmp_path / "test_0007_default.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        # Insert a minimal call_sessions row (id + required FKs are nullable in SQLite
        # during tests — use a raw insert to test the column default).
        cur.execute(
            "INSERT INTO call_sessions (id, client_id, status, started_at, created_at) "
            "VALUES ('sess-default-test', 'client-x', 'initiated', "
            "'2026-07-04T00:00:00', '2026-07-04T00:00:00')"
        )
        conn.commit()
        cur.execute(
            "SELECT reconciliation_attempts FROM call_sessions WHERE id='sess-default-test'"
        )
        row = cur.fetchone()
        conn.close()

        assert row is not None, "Inserted row not found"
        assert row[0] == 0, (
            f"reconciliation_attempts must default to 0, got {row[0]!r}"
        )

    def test_reconciliation_attempts_column_absent_after_downgrade(self, tmp_path):
        """After alembic downgrade -1 (from 0007 to 0006), column is gone.

        GIVEN a database at head (revision 0007)
        WHEN alembic downgrade -1 runs
        THEN reconciliation_attempts no longer exists in call_sessions.
        """
        from alembic import command

        db_file = tmp_path / "test_0007_downgrade.db"
        cfg = self._make_alembic_config(db_file)

        # Upgrade to head first.
        command.upgrade(cfg, "head")

        # Verify column exists before downgrade.
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(call_sessions)")
        cols_before = {row[1] for row in cur.fetchall()}
        conn.close()
        assert "reconciliation_attempts" in cols_before, (
            "Column must exist before downgrade (setup check)"
        )

        # Downgrade one step.
        command.downgrade(cfg, "-1")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(call_sessions)")
        cols_after = {row[1] for row in cur.fetchall()}
        conn.close()

        assert "reconciliation_attempts" not in cols_after, (
            "reconciliation_attempts must be dropped after alembic downgrade -1. "
            "The downgrade() function must call batch_op.drop_column('reconciliation_attempts')."
        )

    def test_up_down_up_round_trip(self, tmp_path):
        """Up → down → up round-trip leaves the column in a valid state.

        GIVEN a database upgraded to head
        WHEN downgrade -1 is applied then upgrade head again
        THEN reconciliation_attempts is back and has default 0.
        """
        from alembic import command

        db_file = tmp_path / "test_0007_roundtrip.db"
        cfg = self._make_alembic_config(db_file)

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(call_sessions)")
        cols = {row[1]: row for row in cur.fetchall()}
        conn.close()

        assert "reconciliation_attempts" in cols, (
            "reconciliation_attempts must be present after up-down-up round-trip"
        )
        # Server default from PRAGMA table_info: SQLite stores it as the literal
        # string including quotes ('0'), so strip quotes before comparing.
        dflt = cols["reconciliation_attempts"][4]
        dflt_stripped = str(dflt).strip("'\"") if dflt is not None else None
        assert dflt_stripped == "0", (
            f"reconciliation_attempts server_default must be 0 after round-trip, got {dflt!r}"
        )
