"""RED tests for WU1 final re-review blockers (round 3).

These tests are written BEFORE the fixes — they define the contracts that
the implementation must satisfy.

Blockers:
  FINAL-CRITICAL-1: Router maps ScheduledCall-overlap DialResult to HTTP 200.
    - dial_outbound_call returns DialResult(status='failed', failure_code='concurrent_scheduled_call')
      when a manual trigger finds an in_progress ScheduledCall.
    - The router currently wraps ALL DialResult outcomes in HTTP 200 — no 409 is returned
      for the ScheduledCall overlap path.
    - Spec: Concurrent call guard is EXTERNALLY VISIBLE. Manual trigger blocked by in_progress
      ScheduledCall MUST return HTTP 409, not HTTP 200.
    - Fix: Add failure_code field to DialResult; router maps 'concurrent_scheduled_call'
      (and 'concurrent_active_session') failure codes to HTTP 409.
    - Tests: endpoint test for ScheduledCall overlap → 409; no provider call.

  FINAL-CRITICAL-2: Pre-dial CallSession is flushed but not durably committed before
    provider API call.
    - Current service: creates CallSession + flush() → calls ElevenLabs → commits after result.
    - Spec/design: "CallSession row with telephony_status='dialing' exists in the database"
      BEFORE the API response arrives. flush() is insufficient — crash between flush and
      commit leaves no durable record.
    - Fix: commit() before provider call, then update in a subsequent commit after result.
    - After commit(), the session object may be expired (SQLAlchemy default behaviour after
      commit). Must call db.refresh(call_session) before accessing attributes.
    - Tests: prove commit occurs before provider dispatch; prove accepted/error paths
      still persist all expected fields; prove refresh is called after pre-dial commit.

  FINAL-SUGGESTION-3: Stale comments mention "raw provider metadata" in service.py.
    - These are documentation-only comments; the actual code already uses allowlisted
      fields via _extract_safe_provider_metadata(). The comments need updating.
    - Fix: Update docstring and inline comments to say "safe/allowlisted metadata".
    - This is a SUGGESTION (no new tests — it's pure comment quality).
"""

from __future__ import annotations

import asyncio
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
    s.outbound_call_cooldown_seconds = 0  # disable cooldown for these tests
    return s


def _make_lead(lead_id: str = "lead-final-001"):
    lead = MagicMock()
    lead.id = lead_id
    lead.phone = "+14155552671"
    lead.client_id = "client-a"
    lead.name = "Final Re-review Lead"
    return lead


def _make_agent(phone_number_id: str = "pn-xyz"):
    agent = MagicMock()
    agent.id = "agent-001"
    agent.elevenlabs_agent_id = "el-agent-abc"
    agent.elevenlabs_phone_number_id = phone_number_id
    agent.name = "Test Agent"
    return agent


def _make_client():
    client = MagicMock()
    client.id = "client-a"
    client.name = "Test Client"
    return client


def _make_in_progress_scheduled_call(call_id: str = "sc-in-progress-final-001"):
    sc = MagicMock()
    sc.id = call_id
    sc.status = "in_progress"
    sc.lead_id = "lead-final-001"
    return sc


def _accepted_result():
    r = MagicMock()
    r.outcome = "accepted"
    r.provider_call_id = "el-call-final-ok"
    r.provider_metadata = {"cost": 0.05, "billed_duration_seconds": 30}
    r.error_detail = None
    r.error_category = None
    return r


def _transient_result(detail: str = "503 Upstream error"):
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "transient"
    return r


def _permanent_result(detail: str = "400 Bad phone number"):
    r = MagicMock()
    r.outcome = "error"
    r.provider_call_id = None
    r.provider_metadata = None
    r.error_detail = detail
    r.error_category = "permanent"
    return r


# ---------------------------------------------------------------------------
# FINAL-CRITICAL-1: DialResult must carry a failure_code
# ---------------------------------------------------------------------------


def test_dial_result_has_failure_code_field():
    """GIVEN DialResult is constructed with a failure_code
    WHEN the field is accessed
    THEN the failure_code is available as an attribute.

    This proves DialResult was extended with a structured failure_code field
    so the router can distinguish concurrent-guard failures from API failures
    without string-matching on the error message.
    """
    from app.outbound.service import DialResult

    result = DialResult(
        status="failed",
        call_session_id=None,
        failure_code="concurrent_scheduled_call",
        error="Lead has an in_progress ScheduledCall.",
    )

    assert result.failure_code == "concurrent_scheduled_call", (
        f"DialResult must carry failure_code='concurrent_scheduled_call'. "
        f"Got: {result.failure_code!r}"
    )


def test_dial_result_failure_code_defaults_to_none():
    """GIVEN DialResult is constructed WITHOUT a failure_code
    WHEN the field is accessed
    THEN failure_code is None (backward-compatible default).

    All existing DialResult constructions must continue to work.
    """
    from app.outbound.service import DialResult

    result = DialResult(status="dialing", call_session_id="sess-123")
    assert result.failure_code is None, (
        f"DialResult.failure_code must default to None. Got: {result.failure_code!r}"
    )


@pytest.mark.asyncio
async def test_scheduled_call_overlap_produces_failure_code_in_dial_result():
    """GIVEN a manual trigger (scheduled_call=None) for a lead that has an in_progress ScheduledCall
    WHEN dial_outbound_call is called
    THEN DialResult.failure_code == 'concurrent_scheduled_call'.

    This structured code enables the router to produce a 409 without string-matching.
    """
    from app.outbound.service import dial_outbound_call

    in_progress_sc = _make_in_progress_scheduled_call()

    mock_db = AsyncMock()
    # SELECT 1: CallSession guard → no active telephony
    no_telephony = MagicMock()
    no_telephony.scalars.return_value.first.return_value = None
    # SELECT 2: ScheduledCall guard → in_progress overlap
    sc_overlap = MagicMock()
    sc_overlap.scalars.return_value.first.return_value = in_progress_sc
    mock_db.execute.side_effect = [no_telephony, sc_overlap]
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
                scheduled_call=None,
            )

    assert result.failure_code == "concurrent_scheduled_call", (
        f"ScheduledCall overlap must set failure_code='concurrent_scheduled_call'. "
        f"Got: {result.failure_code!r}"
    )
    assert result.status == "failed"
    assert mock_api.call_count == 0, "No provider call must be made"


@pytest.mark.asyncio
async def test_active_session_overlap_produces_failure_code_in_dial_result():
    """GIVEN a lead has an active CallSession (telephony_status in dialing/ringing/in_call)
    WHEN dial_outbound_call is called
    THEN DialResult.failure_code == 'concurrent_active_session'.

    Triangulation: both concurrent-guard paths use structured failure codes.
    """
    from app.outbound.service import dial_outbound_call

    active_session = MagicMock()
    active_session.id = "active-sess-final"
    active_session.telephony_status = "in_call"

    mock_db = AsyncMock()
    active_result = MagicMock()
    active_result.scalars.return_value.first.return_value = active_session
    mock_db.execute.return_value = active_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
                scheduled_call=None,
            )

    assert result.failure_code == "concurrent_active_session", (
        f"Active session overlap must set failure_code='concurrent_active_session'. "
        f"Got: {result.failure_code!r}"
    )
    assert result.status == "failed"
    assert mock_api.call_count == 0, "No provider call must be made"


# ---------------------------------------------------------------------------
# FINAL-CRITICAL-1: Router must return 409 for ScheduledCall overlap
# ---------------------------------------------------------------------------


class TestRouterScheduledCallOverlap409:
    """Router must produce HTTP 409 for ScheduledCall-blocked concurrent call.

    Spec: outbound-call-trigger — Requirement: Concurrent Call Guard
      "The system MUST reject a trigger attempt if the lead already has an active
       CallSession or an in_progress ScheduledCall."
    The 409 is the EXTERNALLY VISIBLE response — it must be 409, not 200.
    """

    def test_scheduled_call_overlap_returns_409(self):
        """GIVEN flag on, valid lead, no active CallSession, but in_progress ScheduledCall
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 409 is returned (not 200).

        The ScheduledCall guard is in dial_outbound_call() and returns
        DialResult(failure_code='concurrent_scheduled_call'). The router must
        map this to HTTP 409.
        """
        from app.outbound.router import router as outbound_router, get_db_session, get_settings
        from app.core.auth import require_api_key
        from app.outbound.service import DialResult
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(outbound_router)

        mock_settings = MagicMock()
        mock_settings.enable_outbound_calls = True
        mock_settings.outbound_call_cooldown_seconds = 0

        async def _fake_settings():
            return mock_settings

        mock_db = AsyncMock()
        # No active CallSession in router-level guard
        no_active = MagicMock()
        no_active.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = no_active

        async def _fake_db():
            yield mock_db

        app.dependency_overrides[get_settings] = _fake_settings
        app.dependency_overrides[get_db_session] = _fake_db
        app.dependency_overrides[require_api_key] = lambda: None

        test_client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            mock_client.return_value = MagicMock(id="client-a")
            lead = MagicMock()
            lead.id = "lead-final-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            mock_lead.return_value = lead
            mock_agent.return_value = _make_agent()

            # dial_outbound_call returns ScheduledCall-overlap failure code
            mock_dial.return_value = DialResult(
                status="failed",
                call_session_id=None,
                failure_code="concurrent_scheduled_call",
                error="Lead has an in_progress ScheduledCall.",
            )

            response = test_client.post("/clients/client-a/leads/lead-final-001/call")

        assert response.status_code == 409, (
            f"ScheduledCall overlap must return HTTP 409. Got HTTP {response.status_code}. "
            "Current implementation returns HTTP 200 for all DialResult outcomes, "
            "even concurrent guard failures."
        )
        # No provider call must have been made
        mock_dial.assert_called_once()

    def test_scheduled_call_overlap_409_body_mentions_conflict(self):
        """GIVEN a ScheduledCall overlap failure
        WHEN HTTP 409 is returned
        THEN the response body mentions the conflict reason (scheduled call or concurrent).
        """
        from app.outbound.router import router as outbound_router, get_db_session, get_settings
        from app.core.auth import require_api_key
        from app.outbound.service import DialResult
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(outbound_router)

        mock_settings = MagicMock()
        mock_settings.enable_outbound_calls = True
        mock_settings.outbound_call_cooldown_seconds = 0

        async def _fake_settings():
            return mock_settings

        mock_db = AsyncMock()
        no_active = MagicMock()
        no_active.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = no_active

        async def _fake_db():
            yield mock_db

        app.dependency_overrides[get_settings] = _fake_settings
        app.dependency_overrides[get_db_session] = _fake_db
        app.dependency_overrides[require_api_key] = lambda: None

        test_client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            mock_client.return_value = MagicMock(id="client-a")
            lead = MagicMock()
            lead.id = "lead-final-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            mock_lead.return_value = lead
            mock_agent.return_value = _make_agent()

            mock_dial.return_value = DialResult(
                status="failed",
                call_session_id=None,
                failure_code="concurrent_scheduled_call",
                error="Lead has an in_progress ScheduledCall (id=sc-123). Reject duplicate call.",
            )

            response = test_client.post("/clients/client-a/leads/lead-final-001/call")

        assert response.status_code == 409
        body = response.json()
        detail = (body.get("detail") or "").lower()
        assert any(kw in detail for kw in ("scheduled", "concurrent", "conflict", "active")), (
            f"409 response body must mention the reason. Got: {body.get('detail')!r}"
        )

    def test_active_session_overlap_still_returns_409(self):
        """GIVEN an active CallSession overlap (concurrent_active_session failure_code)
        WHEN the router receives the DialResult
        THEN HTTP 409 is returned.

        Triangulation: both failure codes produce 409.
        """
        from app.outbound.router import router as outbound_router, get_db_session, get_settings
        from app.core.auth import require_api_key
        from app.outbound.service import DialResult
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(outbound_router)

        mock_settings = MagicMock()
        mock_settings.enable_outbound_calls = True
        mock_settings.outbound_call_cooldown_seconds = 0

        async def _fake_settings():
            return mock_settings

        mock_db = AsyncMock()
        # No active session at ROUTER guard level (guard runs again in dial_outbound_call)
        no_active = MagicMock()
        no_active.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = no_active

        async def _fake_db():
            yield mock_db

        app.dependency_overrides[get_settings] = _fake_settings
        app.dependency_overrides[get_db_session] = _fake_db
        app.dependency_overrides[require_api_key] = lambda: None

        test_client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            mock_client.return_value = MagicMock(id="client-a")
            lead = MagicMock()
            lead.id = "lead-final-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            mock_lead.return_value = lead
            mock_agent.return_value = _make_agent()

            mock_dial.return_value = DialResult(
                status="failed",
                call_session_id=None,
                failure_code="concurrent_active_session",
                error="Lead already has an active call session (id=sess-x, status=in_call).",
            )

            response = test_client.post("/clients/client-a/leads/lead-final-001/call")

        assert response.status_code == 409, (
            f"concurrent_active_session failure_code must also return HTTP 409. "
            f"Got HTTP {response.status_code}."
        )

    def test_successful_dial_still_returns_200(self):
        """GIVEN a successful DialResult (no failure_code)
        WHEN the router receives it
        THEN HTTP 200 is returned.

        Regression: fixing 409 must not break the happy path.
        """
        from app.outbound.router import router as outbound_router, get_db_session, get_settings
        from app.core.auth import require_api_key
        from app.outbound.service import DialResult
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(outbound_router)

        mock_settings = MagicMock()
        mock_settings.enable_outbound_calls = True
        mock_settings.outbound_call_cooldown_seconds = 0

        async def _fake_settings():
            return mock_settings

        mock_db = AsyncMock()
        no_active = MagicMock()
        no_active.scalars.return_value.first.return_value = None
        mock_db.execute.return_value = no_active

        async def _fake_db():
            yield mock_db

        app.dependency_overrides[get_settings] = _fake_settings
        app.dependency_overrides[get_db_session] = _fake_db
        app.dependency_overrides[require_api_key] = lambda: None

        test_client = TestClient(app, raise_server_exceptions=False)

        with patch("app.outbound.router.get_client", new_callable=AsyncMock) as mock_client, \
             patch("app.outbound.router.get_lead", new_callable=AsyncMock) as mock_lead, \
             patch("app.outbound.router.get_default_agent", new_callable=AsyncMock) as mock_agent, \
             patch("app.outbound.router.dial_outbound_call", new_callable=AsyncMock) as mock_dial:

            mock_client.return_value = MagicMock(id="client-a")
            lead = MagicMock()
            lead.id = "lead-final-001"
            lead.client_id = "client-a"
            lead.phone = "+14155552671"
            mock_lead.return_value = lead
            mock_agent.return_value = _make_agent()

            mock_dial.return_value = DialResult(
                status="dialing",
                call_session_id="sess-final-ok",
            )

            response = test_client.post("/clients/client-a/leads/lead-final-001/call")

        assert response.status_code == 200, (
            f"Successful dial must still return HTTP 200. Got HTTP {response.status_code}."
        )
        body = response.json()
        assert body["status"] == "dialing"
        assert body["call_session_id"] == "sess-final-ok"


# ---------------------------------------------------------------------------
# FINAL-CRITICAL-2: Pre-dial commit before provider API call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_dial_commit_before_provider_dispatch():
    """GIVEN a valid outbound trigger
    WHEN dial_outbound_call runs
    THEN db.commit() must be called BEFORE ElevenLabs initiate_outbound_call() is called.

    Spec: outbound-call-trigger — Requirement: Call Attempt Persistence
      "GIVEN a trigger request passes all guards
       WHEN the ElevenLabs API call is about to be dispatched
       THEN a CallSession row with telephony_status='dialing' exists in the database
       AND the row is visible before the API response arrives."

    'Visible in the database' means durably committed, not just flushed.
    A flush within the same session is not durable across crashes or independent
    DB connections — the pre-dial record must be committed.
    """
    from app.outbound.service import dial_outbound_call

    commit_count_before_api = []

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    commit_tracker = [0]

    async def _tracked_commit():
        commit_tracker[0] += 1

    mock_db.commit = _tracked_commit
    mock_db.refresh = AsyncMock()  # needed after pre-dial commit

    async def _check_commit_before_api(request):
        # When the API is called, the commit count must already be >= 1
        commit_count_before_api.append(commit_tracker[0])
        return _accepted_result()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        side_effect=_check_commit_before_api,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing"
    assert len(commit_count_before_api) == 1, "API must be called exactly once"
    assert commit_count_before_api[0] >= 1, (
        f"db.commit() must be called BEFORE the ElevenLabs API is dispatched. "
        f"Commit count when API was called: {commit_count_before_api[0]}. "
        "Current code only flushes before provider call — crashes between flush and "
        "the post-result commit leave no durable pre-dial record."
    )


@pytest.mark.asyncio
async def test_pre_dial_commit_then_refresh_before_provider():
    """GIVEN the pre-dial CallSession is committed before provider dispatch
    WHEN dial_outbound_call completes the pre-dial commit
    THEN db.refresh(call_session) is called after commit and before provider dispatch.

    SQLAlchemy expires session attributes after commit() by default. Without a refresh,
    accessing call_session.id or other attributes after the pre-dial commit raises
    or returns stale/empty values. The fix must call db.refresh(call_session) to
    reload the object from the DB.
    """
    from app.outbound.service import dial_outbound_call

    refresh_calls = []
    pre_api_refresh_count = [0]

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    commit_count = [0]

    async def _tracked_commit():
        commit_count[0] += 1

    mock_db.commit = _tracked_commit

    async def _tracked_refresh(obj):
        refresh_calls.append(obj)

    mock_db.refresh = _tracked_refresh

    async def _check_refresh_before_api(request):
        # When API is called, refresh must have been called after the pre-dial commit
        pre_api_refresh_count[0] = len(refresh_calls)
        return _accepted_result()

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        side_effect=_check_refresh_before_api,
    ):
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing"
    assert pre_api_refresh_count[0] >= 1, (
        f"db.refresh(call_session) must be called BEFORE the provider API dispatch, "
        f"to reload session attributes expired by the pre-dial commit. "
        f"Got {pre_api_refresh_count[0]} refresh(es) before API call."
    )


@pytest.mark.asyncio
async def test_accepted_path_still_persists_all_fields_after_two_commit_flow():
    """GIVEN the pre-dial commit → provider call → post-result commit flow
    WHEN ElevenLabs returns accepted
    THEN CallSession has telephony_status='ringing', provider_call_id, provider_metadata,
         and final state is durably committed.

    Regression: the two-commit flow must not break accepted path field persistence.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result

    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    accepted = _accepted_result()
    accepted.provider_call_id = "el-call-2commit-ok"
    accepted.provider_metadata = {"cost": 0.15, "billed_duration_seconds": 45}

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=accepted,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "dialing"
    assert result.call_session_id is not None

    # Provider called exactly once
    assert mock_api.call_count == 1

    # Session fields updated on the object
    assert session_obj is not None
    assert session_obj.telephony_status == "ringing", (
        f"After accepted, telephony_status must be 'ringing', got {session_obj.telephony_status!r}"
    )
    assert session_obj.provider_call_id == "el-call-2commit-ok"

    # At least 2 commits: pre-dial + post-result
    assert mock_db.commit.call_count >= 2, (
        f"Two-commit flow requires at least 2 db.commit() calls "
        f"(pre-dial + post-result). Got {mock_db.commit.call_count}."
    )


@pytest.mark.asyncio
async def test_error_path_still_persists_fields_after_two_commit_flow():
    """GIVEN the pre-dial commit → provider call → post-result commit flow
    WHEN ElevenLabs returns a permanent error
    THEN telephony_status='failed', telephony_error set, committed after error.

    Regression: the two-commit flow must not break the error path either.
    """
    from app.outbound.service import dial_outbound_call

    mock_db = AsyncMock()
    no_result = MagicMock()
    no_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = no_result

    session_obj = None

    def _capture_add(obj):
        nonlocal session_obj
        session_obj = obj

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    perm = _permanent_result("400 Invalid agent ID")

    with patch(
        "app.elevenlabs.service.ElevenLabsService.initiate_outbound_call",
        new_callable=AsyncMock,
        return_value=perm,
    ) as mock_api:
        with patch(
            "app.outbound.dynamic_vars.build_dynamic_variables",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await dial_outbound_call(
                db=mock_db,
                lead=_make_lead(),
                agent=_make_agent(),
                client=_make_client(),
                settings=_make_settings(),
            )

    assert result.status == "failed"
    assert result.call_session_id is not None

    assert mock_api.call_count == 1, "Permanent error must not retry"

    assert session_obj is not None
    assert session_obj.telephony_status == "failed", (
        f"Permanent error must set telephony_status='failed', got {session_obj.telephony_status!r}"
    )
    assert session_obj.telephony_error is not None, "telephony_error must be set"
    assert mock_db.commit.call_count >= 2, (
        f"Two-commit flow: at least 2 commits expected (pre-dial + post-error). "
        f"Got {mock_db.commit.call_count}."
    )
