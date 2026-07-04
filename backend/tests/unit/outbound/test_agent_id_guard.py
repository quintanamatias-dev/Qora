"""RED/GREEN tests for missing elevenlabs_agent_id guard (WU1 Round 4).

Blocker:
  ROUND4-CRITICAL-1: agent.elevenlabs_agent_id is nullable, but there is no guard
    before the pre-dial db.commit(). The two-commit flow commits a dialing CallSession,
    then constructs OutboundCallRequest(agent_id=agent.elevenlabs_agent_id, ...).
    If elevenlabs_agent_id is None, Pydantic raises ValidationError AFTER the dialing
    session is already durably committed — leaving a dangling 'dialing' CallSession in
    the DB with no corresponding provider call.

  Required fix:
    - Guard agent.elevenlabs_agent_id BEFORE db.commit() (before the lock / before
      CallSession creation) — same position as the elevenlabs_phone_number_id guard.
    - Return DialResult(status='failed', failure_code='agent_not_configured', ...).
    - No CallSession must be committed. No provider call must be made.

Spec reference: outbound-call-trigger — "Never raises; always returns DialResult."
Design reference: design.md — Guard checks happen BEFORE db.commit() for pre-dial session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_settings():
    s = MagicMock()
    s.enable_outbound_calls = True
    s.elevenlabs_api_key = SecretStr("test-key")
    return s


def _make_lead():
    lead = MagicMock()
    lead.id = "lead-agent-id-guard-001"
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Agent ID Guard Test Lead"
    return lead


def _make_agent_with_phone_number_id_but_no_agent_id():
    """Agent has elevenlabs_phone_number_id set but elevenlabs_agent_id=None."""
    agent = MagicMock()
    agent.id = "agent-no-el-id"
    agent.elevenlabs_agent_id = None        # ← MISSING — triggers the new blocker
    agent.elevenlabs_phone_number_id = "pn-valid-xyz"  # set — existing guard passes
    agent.name = "Unconfigured Agent"
    return agent


def _make_agent_with_both_ids():
    """Fully configured agent — both IDs set."""
    agent = MagicMock()
    agent.id = "agent-configured"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = "pn-xyz"
    agent.name = "Configured Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "Test Client"
    return client


def _make_mock_db_no_active_sessions():
    """DB mock: no active CallSession, no in_progress ScheduledCall."""
    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def _accepted_result():
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = "el-call-ok"
    r.provider_metadata = {"cost": 0.05}
    r.error_detail = None
    r.error_category = None
    return r


# ---------------------------------------------------------------------------
# ROUND4-CRITICAL-1: Missing elevenlabs_agent_id guard (pre-commit position)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_elevenlabs_agent_id_returns_controlled_failure_no_dangling_session():
    """GIVEN an agent with elevenlabs_agent_id=None (but phone_number_id is set)
    WHEN dial_outbound_call is called
    THEN DialResult(status='failed', failure_code='agent_not_configured') is returned
    AND no db.commit() is called (no dangling dialing CallSession)
    AND no provider API call is made.

    CRITICAL: With the two-commit flow, constructing OutboundCallRequest after the
    pre-dial commit means a dangling 'dialing' session is committed before Pydantic
    raises. The guard must fire BEFORE db.commit() to prevent this.

    Spec: outbound-call-trigger — "Never raises; always returns DialResult."
    """
    from app.outbound.service import dial_outbound_call

    agent = _make_agent_with_phone_number_id_but_no_agent_id()
    mock_db = _make_mock_db_no_active_sessions()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            try:
                result = await dial_outbound_call(
                    db=mock_db,
                    lead=_make_lead(),
                    agent=agent,
                    client=_make_client(),
                    settings=_make_settings(),
                    scheduled_call=None,
                )
            except Exception as exc:
                pytest.fail(
                    f"dial_outbound_call() RAISED {type(exc).__name__} instead of returning "
                    f"DialResult. Contract violated: must NEVER raise. Error: {exc}"
                )

    assert result.status == "failed", (
        f"Missing elevenlabs_agent_id must return status='failed'. Got: {result.status!r}"
    )
    assert result.failure_code == "agent_not_configured", (
        f"failure_code must be 'agent_not_configured'. Got: {result.failure_code!r}"
    )
    assert result.call_session_id is None, (
        "No CallSession must be created when agent_id guard fires. "
        f"Got call_session_id={result.call_session_id!r}. "
        "A committed 'dialing' session with no provider call is a dangling session."
    )
    assert mock_db.commit.call_count == 0, (
        f"db.commit() must NOT be called when agent_id guard fires. "
        f"Got {mock_db.commit.call_count} commit(s). "
        "Guard must fire BEFORE the pre-dial commit to prevent dangling dialing sessions."
    )
    assert mock_api.call_count == 0, (
        f"Provider must NOT be called when agent_id guard fires. "
        f"Got {mock_api.call_count} call(s)."
    )
    error_lower = (result.error or "").lower()
    assert any(
        kw in error_lower
        for kw in ("agent_id", "agent id", "elevenlabs_agent_id", "configured", "missing")
    ), (
        f"Error must mention elevenlabs_agent_id or configuration. Got: {result.error!r}"
    )


@pytest.mark.asyncio
async def test_missing_elevenlabs_agent_id_no_dangling_commit_even_with_valid_phone_number_id():
    """GIVEN an agent where elevenlabs_phone_number_id is set but elevenlabs_agent_id is None
    WHEN dial_outbound_call is called
    THEN the agent_id guard fires BEFORE the existing phone_number_id guard position is bypassed
    AND no CallSession is committed (db.commit not called).

    Triangulation: confirms the guard order is correct — elevenlabs_agent_id must be checked
    before the lock, before db.commit(), in the same pre-lock guard block as phone_number_id.
    """
    from app.outbound.service import dial_outbound_call

    agent = _make_agent_with_phone_number_id_but_no_agent_id()
    mock_db = _make_mock_db_no_active_sessions()

    # Track if add was called (would indicate CallSession construction started)
    add_calls = []
    mock_db.add = MagicMock(side_effect=lambda x: add_calls.append(x))

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=agent,
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "failed"
    assert result.failure_code == "agent_not_configured"
    assert mock_db.commit.call_count == 0, (
        "No commit must happen — guard must fire before the pre-dial commit."
    )
    assert len(add_calls) == 0, (
        "db.add() must not be called — no CallSession must be created before guard fires. "
        f"Got {len(add_calls)} add() call(s)."
    )


@pytest.mark.asyncio
async def test_configured_agent_id_proceeds_normally():
    """GIVEN an agent with BOTH elevenlabs_agent_id AND elevenlabs_phone_number_id set
    WHEN dial_outbound_call is called
    THEN the agent_id guard does NOT fire — call proceeds normally.

    Regression: fixing the new guard must not break calls with fully configured agents.
    """
    from app.outbound.service import dial_outbound_call

    agent = _make_agent_with_both_ids()
    mock_db = _make_mock_db_no_active_sessions()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=_accepted_result(),
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=agent,
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing", (
        f"Configured agent must proceed to dial. Got: {result.status!r}"
    )
    assert result.call_session_id is not None
    assert mock_db.commit.call_count >= 2, (
        "Two-commit flow must still run for configured agents."
    )


@pytest.mark.asyncio
async def test_missing_agent_id_does_not_override_phone_number_id_guard():
    """GIVEN an agent with BOTH elevenlabs_agent_id=None AND elevenlabs_phone_number_id=None
    WHEN dial_outbound_call is called
    THEN the FIRST matching guard fires (whichever is checked first — both are config errors)
    AND failure_code is 'agent_not_configured' (if agent_id checked first) or
        'agent_not_configured' from phone_number_id guard.

    This test accepts either guard firing first — just proves both configs are caught.
    """
    from app.outbound.service import dial_outbound_call

    agent = MagicMock()
    agent.id = "agent-both-missing"
    agent.elevenlabs_agent_id = None
    agent.elevenlabs_phone_number_id = None
    agent.name = "Fully Unconfigured Agent"

    mock_db = _make_mock_db_no_active_sessions()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        result = await dial_outbound_call(
            db=mock_db,
            lead=_make_lead(),
            agent=agent,
            client=_make_client(),
            settings=_make_settings(),
        )

    assert result.status == "failed", (
        f"Both IDs missing must return status='failed'. Got: {result.status!r}"
    )
    assert result.failure_code == "agent_not_configured", (
        f"failure_code must be 'agent_not_configured'. Got: {result.failure_code!r}"
    )
    assert mock_db.commit.call_count == 0, "No commit when agent config guard fires"
    assert mock_api.call_count == 0, "No provider call when agent config guard fires"
