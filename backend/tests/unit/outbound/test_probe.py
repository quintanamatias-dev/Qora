"""Unit tests for outbound/probe.py — post-dial SIP evidence probe.

Spec: call-sip-observability — Requirement: Post-Dial Background Probe

Tasks:
  3.1 — probe_call_evidence logic: match found → update, no match → log,
          API error → catch (never propagate), already reconciled → skip
  3.2 — asyncio.create_task fires probe after accepted/failed-unknown
  3.3 — This test file (verify all scenarios)

TDD: Tests written BEFORE probe.py exists.
All ElevenLabs HTTP is mocked via respx — no live calls.
DB is mocked via AsyncMock — no real DB needed for unit tests.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
import respx
import httpx
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EL_BASE = "https://api.elevenlabs.io/v1"
_CONVERSATIONS_URL = f"{_EL_BASE}/conversational_ai/conversations"


def _make_settings(api_key: str = "test-key"):
    s = MagicMock()
    s.elevenlabs_api_key = SecretStr(api_key)
    return s


def _make_call_session(
    session_id: str = "sess-probe-001",
    agent_id: str = "agent-abc",
    to_number: str = "+14155552671",
    reconciled_at: datetime | None = None,
    started_at: datetime | None = None,
) -> MagicMock:
    cs = MagicMock()
    cs.id = session_id
    cs.agent_id = agent_id
    cs.reconciled_at = reconciled_at
    cs.started_at = started_at or datetime.now(timezone.utc)
    cs.sip_call_id = None
    cs.sip_status_code = None
    cs.sip_reason = None
    cs.reconciliation_source = None
    return cs


def _make_db_with_session(cs: MagicMock | None) -> AsyncMock:
    """Return a mock async_session_factory context manager that yields a DB session."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=cs)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = db
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


# ---------------------------------------------------------------------------
# Task 3.1 — Probe logic: successful match
# ---------------------------------------------------------------------------


class TestProbeSuccessfulCapture:
    """Probe finds a matching conversation and writes SIP evidence."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_writes_sip_fields_on_match(self):
        """GIVEN ElevenLabs returns a matching conversation + SIP messages
        WHEN probe_call_evidence runs
        THEN sip_call_id, sip_status_code, sip_reason, reconciled_at, and
             reconciliation_source='probe' are written to CallSession.

        Spec: Scenario: Successful probe capture.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-probe-001"
        agent_id = "agent-abc"
        to_number = "+14155552671"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        cs = _make_call_session(
            session_id=session_id,
            agent_id=agent_id,
            to_number=to_number,
            started_at=started_at,
            reconciled_at=None,  # Not yet reconciled
        )

        factory = _make_db_with_session(cs)

        # Mock: list_recent_conversations → 1 matching conversation
        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-match-001",
                            "agent_id": agent_id,
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        # Mock: get_sip_messages → SIP messages with Call-ID + final response
        sip_url = f"{_EL_BASE}/conversational_ai/conversations/conv-match-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_abc_probe_test",
                            "method": "INVITE",
                            "direction": "outbound",
                            "timestamp": started_at.isoformat(),
                        },
                        {
                            "call_id": "otb_abc_probe_test",
                            "status_code": 200,
                            "reason_phrase": "OK",
                            "direction": "inbound",
                            "timestamp": (started_at + timedelta(seconds=1)).isoformat(),
                        },
                    ]
                },
            )
        )

        settings = _make_settings()

        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id=session_id,
                agent_id=agent_id,
                to_number=to_number,
                settings=settings,
                delay=0,  # No delay in tests
            )

        # Verify SIP fields were written to the CallSession
        assert cs.sip_call_id == "otb_abc_probe_test", (
            f"Expected sip_call_id='otb_abc_probe_test', got {cs.sip_call_id!r}"
        )
        assert cs.sip_status_code == 200, (
            f"Expected sip_status_code=200, got {cs.sip_status_code!r}"
        )
        assert cs.sip_reason == "OK", (
            f"Expected sip_reason='OK', got {cs.sip_reason!r}"
        )
        assert cs.reconciliation_source == "probe", (
            f"Expected reconciliation_source='probe', got {cs.reconciliation_source!r}"
        )
        assert cs.reconciled_at is not None, (
            "reconciled_at must be set after successful probe"
        )

        # Verify DB was committed
        db = factory.return_value
        db.commit.assert_called()


class TestProbeNoMatch:
    """Probe finds no matching conversation — exits without writing anything."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_no_match_does_not_write(self):
        """GIVEN ElevenLabs returns no conversations
        WHEN probe_call_evidence runs
        THEN no SIP fields are written and reconciled_at remains NULL.

        Spec: Scenario: No SIP messages available — no partial write.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-probe-nomatch"
        cs = _make_call_session(session_id=session_id, reconciled_at=None)
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(200, json={"conversations": []})
        )

        settings = _make_settings()
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id=session_id,
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        # No SIP fields must be written
        assert cs.sip_call_id is None
        assert cs.sip_status_code is None
        assert cs.sip_reason is None
        assert cs.reconciled_at is None

        db = factory.return_value
        db.commit.assert_not_called()


class TestProbeIdempotency:
    """Probe exits immediately if reconciled_at is already set — no API calls."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_skips_already_reconciled_session(self):
        """GIVEN CallSession.reconciled_at is not NULL
        WHEN probe_call_evidence runs
        THEN no ElevenLabs API calls are made.

        Spec: Scenario: Probe skipped — already reconciled.
        """
        from app.outbound.probe import probe_call_evidence

        already_reconciled_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        cs = _make_call_session(reconciled_at=already_reconciled_at)
        factory = _make_db_with_session(cs)

        # Track calls to the conversations URL — must be ZERO
        route = respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(200, json={"conversations": []})
        )

        settings = _make_settings()
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id="sess-already-done",
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        # No API call should have been made
        assert route.call_count == 0, (
            f"Probe must not call ElevenLabs when reconciled_at is already set. "
            f"Call count: {route.call_count}"
        )


class TestProbeAPIError:
    """Probe catches exceptions and never propagates them to the caller."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_catches_api_error_does_not_propagate(self):
        """GIVEN the ElevenLabs API returns 500
        WHEN probe_call_evidence runs
        THEN no exception is raised to the caller.

        Spec: Scenario: Probe exception — call trigger unaffected.
        """
        from app.outbound.probe import probe_call_evidence

        cs = _make_call_session(reconciled_at=None)
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(500, json={"error": "internal error"})
        )

        settings = _make_settings()

        # This must NOT raise — probe catches all exceptions
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id="sess-api-error",
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        # reconciled_at must remain NULL (probe failed safely)
        assert cs.reconciled_at is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_catches_network_error_does_not_propagate(self):
        """GIVEN a network error during probe execution
        WHEN probe_call_evidence runs
        THEN no exception is raised.
        """
        from app.outbound.probe import probe_call_evidence

        cs = _make_call_session(reconciled_at=None)
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        settings = _make_settings()
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id="sess-net-error",
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        assert cs.reconciled_at is None

    @pytest.mark.asyncio
    async def test_probe_catches_db_error_does_not_propagate(self):
        """GIVEN a DB error during probe execution
        WHEN probe_call_evidence runs
        THEN no exception is raised (probe is fire-and-forget).
        """
        from app.outbound.probe import probe_call_evidence

        factory = MagicMock()
        error_db = AsyncMock()
        error_db.get = AsyncMock(side_effect=Exception("DB connection failed"))
        error_db.__aenter__ = AsyncMock(return_value=error_db)
        error_db.__aexit__ = AsyncMock(return_value=False)
        factory.return_value = error_db
        factory.return_value.__aenter__ = AsyncMock(return_value=error_db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        settings = _make_settings()
        # Must NOT raise
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id="sess-db-error",
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )


class TestProbeAmbiguousMatch:
    """Probe skips ambiguous matches (multiple conversations within the window).

    Mirrors the sweep's ambiguity handling: if more than one conversation falls
    within the match window, the probe must NOT pick one silently. It logs a
    warning and writes nothing, leaving reconciled_at NULL so the sweep can
    reconcile the session later.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_skips_ambiguous_match_leaves_unreconciled(self):
        """GIVEN two conversations within the match window of started_at
        WHEN probe_call_evidence runs
        THEN no SIP fields are written and reconciled_at remains NULL.

        Spec: Ambiguous match — safe skip; let the sweep reconcile later.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-probe-ambiguous"
        agent_id = "agent-abc"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        cs = _make_call_session(
            session_id=session_id,
            agent_id=agent_id,
            started_at=started_at,
            reconciled_at=None,
        )
        factory = _make_db_with_session(cs)

        # Two conversations only 5s apart — both within _MATCH_WINDOW_SECONDS
        base_ts = int(started_at.timestamp())
        route = respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-ambig-001",
                            "agent_id": agent_id,
                            "status": "done",
                            "start_time_unix_secs": base_ts,
                        },
                        {
                            "conversation_id": "conv-ambig-002",
                            "agent_id": agent_id,
                            "status": "done",
                            "start_time_unix_secs": base_ts + 5,
                        },
                    ]
                },
            )
        )

        settings = _make_settings()
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id=session_id,
                agent_id=agent_id,
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        # Ambiguous → no SIP fields written, session left unreconciled
        assert cs.sip_call_id is None, "sip_call_id must not be set on ambiguous match"
        assert cs.sip_status_code is None
        assert cs.reconciled_at is None, (
            "reconciled_at must remain NULL on ambiguous probe match"
        )

        db = factory.return_value
        db.commit.assert_not_called()

        # Only the conversations list is fetched — no SIP messages call for either candidate
        assert route.call_count == 1


# ---------------------------------------------------------------------------
# Task 3.2 — Service hook: asyncio.create_task fires after dial
# ---------------------------------------------------------------------------


class TestServiceHookFiresProbe:
    """dial_outbound_call fires probe via create_task after accepted/failed-unknown."""

    @pytest.mark.asyncio
    async def test_probe_task_fired_on_accepted_result(self):
        """GIVEN dial_outbound_call returns accepted
        WHEN the call succeeds
        THEN asyncio.create_task is called with probe_call_evidence.

        Spec: Post-Dial Background Probe — fires after accepted or unknown result.
        The trigger response latency must NOT be affected by the probe.
        """
        from app.outbound.service import dial_outbound_call
        from app.elevenlabs.models import OutboundCallResult

        lead = MagicMock()
        lead.id = "lead-001"
        lead.phone = "+14155552671"

        agent = MagicMock()
        agent.id = "agent-001"
        agent.elevenlabs_agent_id = "el-agent-abc"
        agent.elevenlabs_phone_number_id = "pn-xyz"

        client = MagicMock()
        client.id = "client-001"

        settings = MagicMock()
        settings.enable_outbound_calls = True
        settings.elevenlabs_api_key = SecretStr("test-key")

        db = AsyncMock()

        # Mock: no active sessions
        active_check = MagicMock()
        active_check.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=active_check)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        fake_session = MagicMock()
        fake_session.id = "sess-001"
        db.add = MagicMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        accepted_result = OutboundCallResult(
            outcome="accepted",
            provider_call_id="el-call-9999",
            provider_metadata={"call_id": "el-call-9999", "status": "initiated"},
        )

        tasks_created: list = []

        def fake_create_task(coro, *args, **kwargs):
            tasks_created.append(coro)
            # Cancel the coroutine to avoid ResourceWarning
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with (
            patch("app.outbound.service.ElevenLabsService") as MockService,
            patch("app.outbound.service.asyncio.create_task", side_effect=fake_create_task),
            patch("app.outbound.service._find_active_call_session", new_callable=AsyncMock, return_value=None),
            patch("app.outbound.service._find_in_progress_scheduled_call", new_callable=AsyncMock, return_value=None),
            patch("app.outbound.service.CallSession") as MockCallSession,
            patch("app.outbound.dynamic_vars.build_dynamic_variables", new_callable=AsyncMock, return_value={}),
        ):
            mock_instance = MockService.return_value
            mock_instance.initiate_outbound_call = AsyncMock(return_value=accepted_result)

            mock_cs = MagicMock()
            mock_cs.id = "sess-001"
            MockCallSession.return_value = mock_cs

            result = await dial_outbound_call(
                db,
                lead=lead,
                agent=agent,
                client=client,
                settings=settings,
            )

        assert result.status == "dialing", f"Expected 'dialing', got {result.status!r}"
        assert len(tasks_created) >= 1, (
            "dial_outbound_call must fire asyncio.create_task for the probe "
            "after a successful dial result"
        )

    @pytest.mark.asyncio
    async def test_probe_task_fired_on_ambiguous_timeout(self):
        """GIVEN dial_outbound_call encounters an ambiguous timeout (unknown category)
        WHEN the call result is 'unknown'
        THEN asyncio.create_task is called with probe_call_evidence.

        Spec: Post-Dial Background Probe — fires after accepted or ambiguous timeout.
        The safety fix (no retry on unknown) must remain intact.
        """
        from app.outbound.service import dial_outbound_call
        from app.elevenlabs.models import OutboundCallResult

        lead = MagicMock()
        lead.id = "lead-002"
        lead.phone = "+14155552671"

        agent = MagicMock()
        agent.id = "agent-001"
        agent.elevenlabs_agent_id = "el-agent-abc"
        agent.elevenlabs_phone_number_id = "pn-xyz"

        client = MagicMock()
        client.id = "client-001"

        settings = MagicMock()
        settings.enable_outbound_calls = True
        settings.elevenlabs_api_key = SecretStr("test-key")

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        unknown_result = OutboundCallResult(
            outcome="error",
            error_detail="read_timeout=ReadTimeout: timed out",
            error_category="unknown",
        )

        tasks_created: list = []

        def fake_create_task(coro, *args, **kwargs):
            tasks_created.append(coro)
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with (
            patch("app.outbound.service.ElevenLabsService") as MockService,
            patch("app.outbound.service.asyncio.create_task", side_effect=fake_create_task),
            patch("app.outbound.service._find_active_call_session", new_callable=AsyncMock, return_value=None),
            patch("app.outbound.service._find_in_progress_scheduled_call", new_callable=AsyncMock, return_value=None),
            patch("app.outbound.service.CallSession") as MockCallSession,
            patch("app.outbound.dynamic_vars.build_dynamic_variables", new_callable=AsyncMock, return_value={}),
        ):
            mock_instance = MockService.return_value
            mock_instance.initiate_outbound_call = AsyncMock(return_value=unknown_result)

            mock_cs = MagicMock()
            mock_cs.id = "sess-002"
            MockCallSession.return_value = mock_cs

            result = await dial_outbound_call(
                db,
                lead=lead,
                agent=agent,
                client=client,
                settings=settings,
            )

        # The session must be failed (unknown error — no retry)
        # Probe must still fire — it's the mechanism that resolves ambiguous timeouts
        assert result.status == "failed", (
            f"Ambiguous timeout must result in 'failed' status, got {result.status!r}"
        )
        assert len(tasks_created) >= 1, (
            "dial_outbound_call must fire probe via create_task even on ambiguous timeout — "
            "the probe is the reconciliation mechanism for unknown states"
        )
