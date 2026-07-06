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
_CONVERSATIONS_URL = f"{_EL_BASE}/convai/conversations"


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
        sip_url = f"{_EL_BASE}/convai/conversations/conv-match-001/sip_messages"
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


# ---------------------------------------------------------------------------
# SIP routing failure detection — production fix (Telnyx 404 UNALLOCATED_NUMBER)
# ---------------------------------------------------------------------------


class TestProbeDetectsSipRoutingFailure:
    """Probe detects quick SIP failure (4xx/5xx) and transitions session to no_answer."""

    def _make_ringing_session(self, session_id: str = "sess-sip-fail") -> MagicMock:
        cs = _make_call_session(session_id=session_id, reconciled_at=None)
        cs.telephony_status = "ringing"
        return cs

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_transitions_to_no_answer_on_sip_404(self):
        """GIVEN ElevenLabs accepted the call AND SIP final response is 404
        AND conversation status is 'done' with no successful interaction
        WHEN probe_call_evidence runs
        THEN telephony_status → 'no_answer', SIP fields written, reconciled_at set,
             and probe_detected_sip_routing_failure is logged.

        Production incident: Telnyx returns 404 UNALLOCATED_NUMBER on Argentina
        mobile numbers. Session was stuck in 'ringing' for 30 minutes.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-sip-404"
        agent_id = "agent-abc"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        cs = self._make_ringing_session(session_id=session_id)
        cs.started_at = started_at
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-sip-fail-001",
                            "agent_id": agent_id,
                            "status": "done",
                            "call_successful": "false",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        sip_url = f"{_EL_BASE}/convai/conversations/conv-sip-fail-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_6001kwq98hjae6mv22tyyw13m2p1",
                            "method": "INVITE",
                            "direction": "outbound",
                            "timestamp": started_at.isoformat(),
                        },
                        {
                            "call_id": "otb_6001kwq98hjae6mv22tyyw13m2p1",
                            "status_code": 404,
                            "reason_phrase": "Not Found",
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
                to_number="+5491140485464",
                settings=settings,
                delay=0,
            )

        # Spec: call-state-machine MODIFIED — SIP routing failures now set
        # telephony_status='failed' + outcome_reason='sip_routing_error'
        # (previously 'no_answer') for distinguishability.
        assert cs.telephony_status == "failed", (
            f"SIP 404 routing failure must transition telephony_status to 'failed', "
            f"got {cs.telephony_status!r}"
        )
        assert cs.outcome_reason == "sip_routing_error"
        assert cs.sip_status_code == 404
        assert cs.sip_reason == "Not Found"
        assert cs.sip_call_id == "otb_6001kwq98hjae6mv22tyyw13m2p1"
        assert cs.reconciled_at is not None
        assert cs.reconciliation_source == "probe"

        db = factory.return_value
        db.commit.assert_called()

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_transitions_to_no_answer_on_sip_486_busy(self):
        """GIVEN SIP final response is 486 Busy Here
        WHEN probe_call_evidence runs
        THEN telephony_status → 'no_answer'.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-sip-486"
        agent_id = "agent-abc"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=8)

        cs = self._make_ringing_session(session_id=session_id)
        cs.started_at = started_at
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-busy-001",
                            "agent_id": agent_id,
                            "status": "failed",
                            "call_successful": None,
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )
        sip_url = f"{_EL_BASE}/convai/conversations/conv-busy-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_busy_test",
                            "status_code": 486,
                            "reason_phrase": "Busy Here",
                            "direction": "inbound",
                            "timestamp": started_at.isoformat(),
                        }
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

        # Spec: call-state-machine MODIFIED — SIP routing failures now set failed+sip_routing_error
        assert cs.telephony_status == "failed"
        assert cs.outcome_reason == "sip_routing_error"
        assert cs.sip_status_code == 486

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_does_not_flag_sip_200_as_failure(self):
        """GIVEN SIP final response is 200 OK
        WHEN probe_call_evidence runs
        THEN telephony_status is NOT changed to 'no_answer'.

        A successful SIP response must never be classified as a routing failure.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-sip-200"
        agent_id = "agent-abc"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=30)

        cs = self._make_ringing_session(session_id=session_id)
        cs.started_at = started_at
        # Simulate session already in_call (answered)
        cs.telephony_status = "in_call"
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-answered-001",
                            "agent_id": agent_id,
                            "status": "done",
                            "call_successful": "success",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )
        sip_url = f"{_EL_BASE}/convai/conversations/conv-answered-001/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sip_messages": [
                        {
                            "call_id": "otb_answered_test",
                            "status_code": 200,
                            "reason_phrase": "OK",
                            "direction": "inbound",
                            "timestamp": started_at.isoformat(),
                        }
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

        # SIP 200 + call_successful='success' must NOT change telephony_status
        assert cs.telephony_status == "in_call", (
            f"SIP 200 OK must not flip telephony_status to 'no_answer', "
            f"got {cs.telephony_status!r}"
        )
        # But SIP fields ARE written
        assert cs.sip_status_code == 200
        assert cs.reconciled_at is not None


class TestProbeEvidenceUnavailable:
    """Probe handles the case where ElevenLabs conversations API returns 404.

    The probe must not crash. Session is left for the stale sweep (safety net).
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_handles_conversations_api_404_gracefully(self):
        """GIVEN ElevenLabs conversations API returns 404
        WHEN probe_call_evidence runs
        THEN no exception is raised, reconciled_at remains NULL (sweep picks it up).

        The probe must fail safely and let the sweep handle it later.
        """
        from app.outbound.probe import probe_call_evidence

        cs = _make_call_session(reconciled_at=None)
        cs.telephony_status = "ringing"
        factory = _make_db_with_session(cs)

        # ElevenLabs conversations API returns 404 (known intermittent issue)
        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
        )

        settings = _make_settings()

        # Must NOT raise — probe is fire-and-forget
        with patch("app.outbound.probe.async_session_factory", factory):
            await probe_call_evidence(
                session_id="sess-conv-404",
                agent_id="agent-abc",
                to_number="+14155552671",
                settings=settings,
                delay=0,
            )

        # Session is unchanged — sweep will handle it via STALE_RINGING_THRESHOLD
        assert cs.reconciled_at is None, (
            "reconciled_at must remain NULL when probe cannot fetch evidence — "
            "stale sweep is the safety net"
        )
        assert cs.telephony_status == "ringing", (
            "telephony_status must not be changed when probe has no evidence"
        )
        # DB must NOT be committed on failure
        db = factory.return_value
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_handles_sip_messages_api_404_gracefully(self):
        """GIVEN conversation list returns a match but SIP messages API returns 404
        WHEN probe_call_evidence runs
        THEN no exception is raised, reconciled_at remains NULL.
        """
        from app.outbound.probe import probe_call_evidence

        session_id = "sess-sip-msg-404"
        agent_id = "agent-abc"
        started_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        cs = _make_call_session(
            session_id=session_id,
            agent_id=agent_id,
            started_at=started_at,
            reconciled_at=None,
        )
        cs.telephony_status = "ringing"
        factory = _make_db_with_session(cs)

        respx.get(_CONVERSATIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-sip-404",
                            "agent_id": agent_id,
                            "status": "done",
                            "start_time_unix_secs": int(started_at.timestamp()),
                        }
                    ]
                },
            )
        )

        sip_url = f"{_EL_BASE}/convai/conversations/conv-sip-404/sip_messages"
        respx.get(sip_url).mock(
            return_value=httpx.Response(404, json={"detail": "Not found"})
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

        assert cs.reconciled_at is None
        db = factory.return_value
        db.commit.assert_not_called()


class TestIsSipRoutingFailureUnit:
    """Unit tests for the _is_sip_routing_failure helper directly."""

    def _make_conv(
        self,
        status: str | None = "done",
        call_successful: str | None = None,
    ) -> MagicMock:
        conv = MagicMock()
        conv.status = status
        conv.call_successful = call_successful
        return conv

    def test_sip_404_done_no_success_is_failure(self):
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("done", None), 404) is True

    def test_sip_404_failed_status_is_failure(self):
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("failed", None), 404) is True

    def test_sip_486_failed_is_failure(self):
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("failed", None), 486) is True

    def test_sip_503_done_is_failure(self):
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("done", "false"), 503) is True

    def test_sip_200_success_is_not_failure(self):
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("done", "success"), 200) is False

    def test_sip_200_no_call_successful_is_not_failure(self):
        """SIP 200 is never a routing failure regardless of call_successful."""
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("done", None), 200) is False

    def test_none_sip_status_code_is_not_failure(self):
        """Without an explicit SIP error code we cannot confirm failure."""
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("failed", None), None) is False

    def test_sip_404_success_call_is_not_failure(self):
        """If call_successful='success', do not override even with 4xx SIP code."""
        from app.outbound.probe import _is_sip_routing_failure

        # Unusual combination but must not classify as failure to avoid false positives
        assert _is_sip_routing_failure(self._make_conv("done", "success"), 404) is False

    def test_sip_404_processing_conv_status_is_not_failure(self):
        """Conversation status 'processing' is not a terminal failure state."""
        from app.outbound.probe import _is_sip_routing_failure

        assert _is_sip_routing_failure(self._make_conv("processing", None), 404) is False
