"""QORA Outbound — Central dialing service.

The sole entry point for all outbound calls. Both the manual trigger endpoint
and the future scheduler tick call this function — no duplication.

Design (design.md):
  dial_outbound_call() lives in its own module to avoid circular imports with
  calls/service.py. It is the only place that calls ElevenLabsService.initiate_outbound_call().

Spec: outbound-call-trigger
  - Feature Flag Guard: flag off → no call, no CallSession, no charge
  - E.164 Validation: invalid phone → fail before any charge
  - Concurrent Call Guard: active session → fail, no new session
  - Call Attempt Persistence: CallSession created BEFORE ElevenLabs API call
  - Failure Classification: transient → retry once; permanent → no retry
  - Recurrent Error: second consecutive transient failure → recurrent_error
  - Scheduler Reuse: accepts scheduled_call=None for manual trigger
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession
from app.core.logging import get_logger
from app.elevenlabs.models import OutboundCallRequest, OutboundCallResult
from app.elevenlabs.service import ElevenLabsService
from app.outbound.phone import validate_e164

logger = get_logger(__name__)

# Active telephony statuses — a session in any of these blocks a new dial attempt.
_ACTIVE_TELEPHONY_STATUSES = {"dialing", "ringing", "in_call"}

# ---------------------------------------------------------------------------
# Background task strong-reference registry (FIX: GC safety for fire-and-forget)
#
# CPython only keeps a weak reference to bare asyncio tasks. A task created with
# asyncio.create_task() that is not retained by the caller can be garbage-collected
# and silently cancelled before it completes — a critical risk for the post-dial
# probe, which is the PRIMARY reconciliation path for ambiguous-ReadTimeout incidents.
#
# Pattern: a module-level set holds a strong reference for each in-flight task.
# The done-callback removes the task after completion/cancellation, so the set
# does not grow unboundedly.
# ---------------------------------------------------------------------------
_background_tasks: set[asyncio.Task] = set()

# ---------------------------------------------------------------------------
# Per-lead asyncio locks — prevent two concurrent dials for the same lead_id.
#
# Problem: Without a lock, two coroutines can both pass the DB SELECT (seeing
# no active session), then both create CallSessions and fire provider calls —
# a classic TOCTOU race in a single asyncio process.
#
# Solution: An asyncio.Lock per lead_id acquired BEFORE the DB check.
# The guard check and CallSession creation happen inside the lock, so the
# second coroutine will block until the first has flushed its row and released.
# The second waiter then re-runs the SELECT inside the lock and finds the
# 'dialing' session — so it returns "failed" (concurrent guard).
#
# Memory: Regular dict, one asyncio.Lock per unique lead_id seen in-process.
# For MVP (single-process), this is safe. Future: move to Redis distributed lock
# for multi-process deployments. The Lock objects are lightweight (~50 bytes each).
# ---------------------------------------------------------------------------
_LEAD_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lead_lock(lead_id: str) -> asyncio.Lock:
    """Return (or create) the per-lead asyncio.Lock for lead_id.

    Thread-safe in asyncio context — dict.get/setdefault is atomic in CPython.
    """
    lock = _LEAD_LOCKS.get(lead_id)
    if lock is None:
        lock = asyncio.Lock()
        _LEAD_LOCKS.setdefault(lead_id, lock)
        lock = _LEAD_LOCKS[lead_id]  # re-fetch in case of race (setdefault wins)
    return lock


@dataclass
class DialResult:
    """Result of a dial_outbound_call() attempt.

    status: "dialing"         — API accepted; call is in progress
            "failed"          — Failed before or after API call (permanent, no_answer, or pre-check)
            "recurrent_error" — Second consecutive transient failure
    call_session_id: UUID of the created CallSession, or None if never created.
    error: Human-readable description of failure, or None on success.
    failure_code: Structured failure category for callers that need to distinguish
        guard failures without string-matching on the error message.
        "concurrent_active_session"  — Lead already has an active CallSession
        "concurrent_scheduled_call"  — Lead already has an in_progress ScheduledCall
        "flag_off"                   — ENABLE_OUTBOUND_CALLS is False
        "invalid_phone"              — Phone number is not valid E.164
        "agent_not_configured"       — Agent is missing elevenlabs_phone_number_id
        None                         — Success or provider-API-level failure
    """

    status: Literal["dialing", "failed", "recurrent_error"]
    call_session_id: str | None
    error: str | None = None
    failure_code: str | None = None


async def dial_outbound_call(
    db: AsyncSession,
    *,
    lead,
    agent,
    client,
    settings,
    scheduled_call=None,  # None for manual trigger; future scheduler passes a ScheduledCall
) -> DialResult:
    """Sole entry point for outbound dialing.

    Guards (checked in order, short-circuit on failure):
      1. Feature flag: enable_outbound_calls must be True
      2. E.164 phone validation
      2b-i. Agent elevenlabs_agent_id must be set (pre-commit guard — no dangling session)
      2b-ii. Agent elevenlabs_phone_number_id must be set (pre-commit guard — no dangling session)
      3. Concurrent call guard: no active CallSession for this lead

    Execution:
      4. Create CallSession (telephony_status='dialing') BEFORE API call
      5. Build dynamic variables
      6. Call ElevenLabsService.initiate_outbound_call()
      7. On accepted: update status to 'ringing', store provider_call_id + metadata
      8. On transient error: update status to 'failed', retry once
         - On retry accepted: status → 'ringing'
         - On retry transient: status → 'recurrent_error'
      9. On no_answer (ring timeout): status → 'no_answer' on session, no retry
     10. On permanent error: status → 'failed', no retry

    Always returns DialResult — never raises.

    Args:
        db: Async DB session.
        lead: Lead ORM instance.
        agent: Agent ORM instance.
        client: Client ORM instance.
        settings: Settings instance (checked for enable_outbound_calls).
        scheduled_call: Optional ScheduledCall ORM instance (None for manual trigger).

    Returns:
        DialResult with status, call_session_id, and optional error.
    """
    # ------------------------------------------------------------------
    # Guard 1: Feature flag
    # ------------------------------------------------------------------
    if not settings.enable_outbound_calls:
        logger.info(
            "outbound_dial_blocked_flag_off",
            lead_id=lead.id,
            flag="ENABLE_OUTBOUND_CALLS",
        )
        return DialResult(
            status="failed",
            call_session_id=None,
            failure_code="flag_off",
            error="Outbound calls are disabled. Set ENABLE_OUTBOUND_CALLS=true to enable.",
        )

    # ------------------------------------------------------------------
    # Guard 2: E.164 phone validation
    # ------------------------------------------------------------------
    try:
        validate_e164(lead.phone)
    except ValueError as exc:
        logger.warning(
            "outbound_dial_invalid_phone",
            lead_id=lead.id,
            error=str(exc),
        )
        return DialResult(
            status="failed",
            call_session_id=None,
            failure_code="invalid_phone",
            error=f"Invalid phone number: {exc}",
        )

    # ------------------------------------------------------------------
    # Guard 2b: Agent must be fully configured for outbound dialing
    #
    # Both elevenlabs_agent_id and elevenlabs_phone_number_id are nullable
    # on the Agent model. Without explicit guards HERE (before the lock and
    # before db.commit()), a None value would reach OutboundCallRequest
    # construction AFTER the pre-dial CallSession has been durably committed
    # — leaving a dangling 'dialing' session with no corresponding provider
    # call (the Pydantic ValidationError propagates out, violating the
    # "always returns DialResult, never raises" contract).
    #
    # BOTH guards are checked BEFORE Guard 3 (the lock) to ensure:
    #   1. No dangling dialing sessions are committed on config errors.
    #   2. No provider call is ever attempted for unconfigured agents.
    #   3. The error is surfaced to the operator as a controlled DialResult.
    #
    # Guard 2b-i: elevenlabs_agent_id (required by OutboundCallRequest.agent_id: str)
    # ------------------------------------------------------------------
    agent_elevenlabs_id = getattr(agent, "elevenlabs_agent_id", None)
    if not agent_elevenlabs_id:
        logger.error(
            "outbound_dial_blocked_missing_agent_id",
            lead_id=lead.id,
            agent_id=getattr(agent, "id", None),
        )
        return DialResult(
            status="failed",
            call_session_id=None,
            failure_code="agent_not_configured",
            error=(
                "Agent is not configured for outbound dialing: "
                "elevenlabs_agent_id is missing. "
                "Sync the agent with ElevenLabs first (POST /agents/{id}/sync)."
            ),
        )

    # ------------------------------------------------------------------
    # Guard 2b-ii: elevenlabs_phone_number_id (required by OutboundCallRequest.agent_phone_number_id: str)
    # ------------------------------------------------------------------
    agent_phone_number_id = getattr(agent, "elevenlabs_phone_number_id", None)
    if not agent_phone_number_id:
        logger.error(
            "outbound_dial_blocked_missing_phone_number_id",
            lead_id=lead.id,
            agent_id=getattr(agent, "id", None),
        )
        return DialResult(
            status="failed",
            call_session_id=None,
            failure_code="agent_not_configured",
            error=(
                "Agent is not configured for outbound dialing: "
                "elevenlabs_phone_number_id is missing. "
                "Set it via the Agent API or ELEVENLABS_PHONE_NUMBER_ID env var."
            ),
        )

    # ------------------------------------------------------------------
    # Guard 3 + Step 4: Concurrent call guard + ScheduledCall overlap guard
    # + CallSession creation + provider API call — all inside the lock.
    #
    # The per-lead asyncio.Lock is held through the ENTIRE critical section:
    # from the DB guard check, through CallSession creation and commit,
    # through the provider API call, until the final commit/rollback.
    #
    # WHY hold through provider call (not just through flush/commit):
    #   For single-process MVP with SQLite, flush() may be enough because
    #   all coroutines share the same DB connection. However, if the
    #   application ever uses independent AsyncSession objects (which
    #   can use separate DB transactions), a row flushed-but-not-committed
    #   may NOT be visible to a second session's SELECT within the same
    #   asyncio event loop tick — i.e., the second SELECT inside the lock
    #   could still see no active session, pass the guard, and then proceed
    #   to fire a second provider call.
    #
    #   Holding the lock through the provider API call eliminates this
    #   window entirely: any second concurrent coroutine for the same lead
    #   waits at the lock acquisition. By the time it acquires the lock
    #   and runs its SELECT, the first coroutine has already committed
    #   the dialing CallSession — the second SELECT finds it and rejects.
    #
    # Trade-off documented (MVP):
    #   This serializes concurrent calls per lead. For the manual-trigger MVP
    #   this is acceptable — concurrent triggers for the same lead should be
    #   rare and are already intended to be rejected. The ElevenLabs API call
    #   is fast (<500ms). Future: move to a distributed (Redis) lock with a
    #   commit-then-unlock protocol for multi-process deployments.
    #
    # Lock granularity: per lead_id — different leads can dial concurrently.
    # ------------------------------------------------------------------
    lead_lock = _get_lead_lock(lead.id)
    async with lead_lock:
        # Re-check for active session INSIDE the lock (no other coroutine
        # for this lead can hold the lock simultaneously)
        active_session = await _find_active_call_session(db, lead.id)
        if active_session is not None:
            logger.warning(
                "outbound_dial_blocked_concurrent",
                lead_id=lead.id,
                active_session_id=active_session.id,
                telephony_status=active_session.telephony_status,
            )
            return DialResult(
                status="failed",
                call_session_id=None,
                failure_code="concurrent_active_session",
                error=(
                    f"Lead already has an active call session "
                    f"(id={active_session.id}, status={active_session.telephony_status}). "
                    "Reject duplicate call attempt."
                ),
            )

        # ------------------------------------------------------------------
        # Guard 3b: ScheduledCall in_progress overlap guard
        #
        # Spec: outbound-call-trigger — Requirement: Concurrent Call Guard
        #   "The system MUST reject a trigger attempt if the lead already has
        #    an active CallSession or an in_progress ScheduledCall."
        #
        # This applies to BOTH manual triggers AND scheduler-triggered calls:
        # - Scheduler: two ticks could fire for the same lead → duplicate dials.
        # - Manual: operator triggers while a ScheduledCall is in_progress →
        #   would result in two simultaneous billed provider calls.
        #
        # For scheduled_call is not None: exclude the current ScheduledCall
        # from the check (we don't want to block ourselves).
        # For scheduled_call=None (manual): check all in_progress ScheduledCalls.
        # ------------------------------------------------------------------
        exclude_sc_id = scheduled_call.id if scheduled_call is not None else None
        overlapping_sc = await _find_in_progress_scheduled_call(
            db, lead.id, exclude_id=exclude_sc_id
        )
        if overlapping_sc is not None:
            logger.warning(
                "outbound_dial_blocked_scheduled_overlap",
                lead_id=lead.id,
                scheduled_call_id=getattr(scheduled_call, "id", None),
                overlapping_scheduled_call_id=overlapping_sc.id,
            )
            return DialResult(
                status="failed",
                call_session_id=None,
                failure_code="concurrent_scheduled_call",
                error=(
                    f"Lead already has an in_progress ScheduledCall "
                    f"(id={overlapping_sc.id}). "
                    "Reject call attempt to prevent double-charging."
                ),
            )

        # ------------------------------------------------------------------
        # Step 4: Create CallSession BEFORE API call (crash-safe, durably committed)
        #
        # Spec: outbound-call-trigger — Requirement: Call Attempt Persistence
        #   "a CallSession row with telephony_status='dialing' exists in the database
        #    AND the row is visible before the API response arrives."
        #
        # WHY commit() instead of flush() here:
        #   flush() makes the row visible within the SAME session object, but:
        #   - It is NOT durable across crashes between flush and the next commit.
        #   - It is NOT necessarily visible to independent DB connections or
        #     AsyncSession objects (which use separate transactions).
        #   A commit() writes the pre-dial record durably to storage BEFORE the
        #   provider is called, so a crash between commit and provider dispatch
        #   leaves a 'dialing' CallSession in the DB — operators can detect and
        #   investigate stuck sessions.
        #
        # SQLAlchemy session expiration after commit():
        #   By default, SQLAlchemy expires all session attributes after commit().
        #   Accessing call_session.id after commit would trigger lazy-loading (or
        #   raise in async context). We call db.refresh(call_session) immediately
        #   after the pre-dial commit to reload attributes from the DB.
        #
        # Still inside the lock — ensures the committed 'dialing' row is visible
        # to any second concurrent coroutine that acquires the lock next.
        # ------------------------------------------------------------------
        call_session = CallSession(
            id=str(uuid.uuid4()),
            client_id=client.id,
            lead_id=lead.id,
            agent_id=agent.id if agent is not None else None,
            status="initiated",
            telephony_provider="elevenlabs",
            telephony_status="dialing",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(call_session)
        await db.flush()  # assign DB-generated values if any (e.g. server defaults)
        # Durably commit the pre-dial record BEFORE calling the provider.
        await db.commit()
        # Refresh to reload session attributes expired by the commit().
        await db.refresh(call_session)

        call_session_id = call_session.id

        logger.info(
            "outbound_call_session_created",
            call_session_id=call_session_id,
            lead_id=lead.id,
            telephony_status="dialing",
        )

        # ------------------------------------------------------------------
        # Step 5: Build dynamic variables for the ElevenLabs agent
        # (inside lock — dynamic_vars fetch is cheap and fast)
        # ------------------------------------------------------------------
        try:
            from app.outbound.dynamic_vars import build_dynamic_variables

            dynamic_vars = await build_dynamic_variables(
                db=db,
                lead=lead,
                agent=agent,
                client=client,
            )
        except Exception as exc:
            logger.warning(
                "outbound_dynamic_vars_failed",
                call_session_id=call_session_id,
                error=str(exc),
            )
            dynamic_vars = {}  # proceed without dynamic vars — agent uses defaults

        # ------------------------------------------------------------------
        # Step 6: Call ElevenLabs API (with one transient retry)
        # Still inside the lock — provider call is held under lock to prevent
        # a second concurrent coroutine from passing the guard and making a
        # duplicate provider call while this one is in-flight.
        # ------------------------------------------------------------------
        el_service = ElevenLabsService(settings=settings)
        # Build the conversation_initiation_client_data payload.
        #
        # ElevenLabs requires:
        #   - "dynamic_variables": dict of template variables for {{var}} substitution
        #     in the agent's prompt. Sending a flat dict instead of this wrapper means
        #     template variables (e.g. {{lead_name}}) are never substituted.
        #   - "custom_llm_extra_body": dict forwarded verbatim by ElevenLabs to the
        #     Custom LLM endpoint as the `elevenlabs_extra_body` field. The Custom LLM
        #     handler (webhook.py) reads client_id and lead_id from this field to scope
        #     session creation and lead context resolution.
        _cicd: dict = {}
        if dynamic_vars:
            _cicd["dynamic_variables"] = dynamic_vars
        _cicd["custom_llm_extra_body"] = {
            "client_id": client.id,
            "lead_id": str(lead.id),
        }
        outbound_request = OutboundCallRequest(
            # Both agent_elevenlabs_id and agent_phone_number_id were validated
            # in Guard 2b (before the lock and before db.commit()) — they are
            # guaranteed to be non-None strings by the time we reach this point.
            agent_id=agent_elevenlabs_id,
            agent_phone_number_id=agent_phone_number_id,
            to=lead.phone,
            conversation_initiation_client_data=_cicd,
        )

        result = await el_service.initiate_outbound_call(outbound_request)

        # ------------------------------------------------------------------
        # Steps 7-9: Handle result, update CallSession in a second commit.
        #
        # The pre-dial commit (Step 4) created a durable 'dialing' record.
        # This second commit updates the telephony outcome fields after the
        # provider responded (or errored). The two-commit flow guarantees:
        #   1. Pre-dial: always durable before money is spent.
        #   2. Post-result: outcome fields (status, provider_call_id, metadata)
        #      are persisted after the provider responds.
        #
        # Still inside the lock — the result commit happens under the lock.
        # After commit, we return and the lock releases. Any waiting second
        # coroutine then acquires the lock, re-runs the SELECT, and finds
        # the committed 'dialing' / 'ringing' row.
        # ------------------------------------------------------------------
        if result.outcome == "accepted":
            call_session.provider_call_id = result.provider_call_id
            call_session.telephony_status = "ringing"
            # Store only safe allowlisted fields — strip PII and internal routing data
            safe_metadata = _extract_safe_provider_metadata(result.provider_metadata)
            call_session.provider_metadata = safe_metadata
            # Persist the ElevenLabs conversation_id so the custom-llm endpoint can
            # link an incoming conversation back to this CallSession (and its lead).
            # The outbound-call API returns conversation_id; it is the session key
            # custom-llm uses. Only set when present — never overwrite with None.
            _conversation_id = (safe_metadata or {}).get("conversation_id")
            if _conversation_id:
                call_session.elevenlabs_conversation_id = _conversation_id
            await db.commit()

            logger.info(
                "outbound_call_accepted",
                call_session_id=call_session_id,
                provider_call_id=result.provider_call_id,
            )

            # C3: Fire post-dial probe (fire-and-forget, 8s delay).
            # The probe captures SIP evidence without blocking the trigger response.
            # Spec: call-sip-observability — Requirement: Post-Dial Background Probe.
            _fire_probe(
                session_id=call_session_id,
                agent_id=agent_elevenlabs_id,
                to_number=lead.phone,
                settings=settings,
            )

            return DialResult(status="dialing", call_session_id=call_session_id)

        # --- Error path ---
        if result.error_category == "no_answer":
            # Provider-reported no answer (ring timeout, voicemail network response).
            # Distinct from system failure — do NOT retry (retrying a ring timeout is
            # wasteful and semantically wrong: the lead chose not to answer).
            # Spec: Live Status State Machine — ringing → no_answer.
            call_session.telephony_status = "no_answer"
            call_session.telephony_error = result.error_detail
            await db.commit()

            logger.info(
                "outbound_call_no_answer",
                call_session_id=call_session_id,
                error_detail=result.error_detail,
            )
            return DialResult(
                status="failed",
                call_session_id=call_session_id,
                error=result.error_detail,
            )

        if result.error_category == "permanent":
            # Permanent system error — no retry
            call_session.telephony_status = "failed"
            call_session.telephony_error = result.error_detail
            await db.commit()

            logger.error(
                "outbound_call_permanent_error",
                call_session_id=call_session_id,
                error_detail=result.error_detail,
            )
            return DialResult(
                status="failed",
                call_session_id=call_session_id,
                error=result.error_detail,
            )

        if result.error_category == "unknown":
            # Ambiguous side effect — the request was sent and the provider MAY have
            # already placed a real (billed) SIP call, but we never got the response
            # (read/write timeout). Retrying would dial a SECOND real call while the
            # first is potentially already ringing (observed: two outbound SIP
            # INVITEs to the same number). We therefore do NOT retry.
            #
            # The session is marked 'failed' (no provider_call_id captured) and left
            # for reconciliation: an inbound webhook (session_end / call status) or
            # the stale-session sweep resolves the true outcome. This preserves the
            # no-silent-failure invariant — the operator sees a failed row with an
            # explanatory telephony_error rather than an eternal 'dialing'.
            call_session.telephony_status = "failed"
            call_session.telephony_error = (
                f"ambiguous_timeout (provider may have placed a call; not retried): "
                f"{result.error_detail}"
            )
            await db.commit()

            logger.error(
                "outbound_call_ambiguous_timeout",
                call_session_id=call_session_id,
                error_detail=result.error_detail,
                note="request sent; not retrying to avoid a duplicate billed call",
            )

            # C3: Fire probe even on ambiguous timeout — it is the reconciliation
            # mechanism for sessions where the provider may have placed a call.
            # Spec: call-sip-observability — Requirement: Ambiguous ReadTimeout.
            _fire_probe(
                session_id=call_session_id,
                agent_id=agent_elevenlabs_id,
                to_number=lead.phone,
                settings=settings,
            )

            return DialResult(
                status="failed",
                call_session_id=call_session_id,
                error=call_session.telephony_error,
            )

        # Transient error — retry once
        call_session.telephony_status = "failed"
        call_session.telephony_error = f"attempt_1: {result.error_detail}"
        await db.flush()

        logger.warning(
            "outbound_call_transient_error_retrying",
            call_session_id=call_session_id,
            error_detail=result.error_detail,
            attempt=1,
        )

        # --- Retry attempt (still under lock — prevents duplicate second calls) ---
        retry_result = await el_service.initiate_outbound_call(outbound_request)

        if retry_result.outcome == "accepted":
            call_session.provider_call_id = retry_result.provider_call_id
            call_session.telephony_status = "ringing"
            # Store only safe allowlisted fields — strip PII and internal routing data
            safe_metadata = _extract_safe_provider_metadata(retry_result.provider_metadata)
            call_session.provider_metadata = safe_metadata
            # Persist the ElevenLabs conversation_id for custom-llm linkage (see the
            # first-attempt accepted branch above for rationale).
            _conversation_id = (safe_metadata or {}).get("conversation_id")
            if _conversation_id:
                call_session.elevenlabs_conversation_id = _conversation_id
            call_session.telephony_error = None  # clear first-attempt error on retry success
            await db.commit()

            logger.info(
                "outbound_call_retry_accepted",
                call_session_id=call_session_id,
                provider_call_id=retry_result.provider_call_id,
            )
            return DialResult(status="dialing", call_session_id=call_session_id)

        # Both attempts failed
        call_session.telephony_status = "recurrent_error"
        call_session.telephony_error = (
            f"attempt_1: {result.error_detail}; attempt_2: {retry_result.error_detail}"
        )
        await db.commit()

        logger.error(
            "outbound_call_recurrent_error",
            call_session_id=call_session_id,
            attempt_1=result.error_detail,
            attempt_2=retry_result.error_detail,
        )
        return DialResult(
            status="recurrent_error",
            call_session_id=call_session_id,
            error=call_session.telephony_error,
        )
    # Lock released here — all outcomes (accepted, failed, recurrent_error, retry)
    # return from inside the block, so this line is never reached in practice.
    # The unreachable guard below satisfies type checkers.
    raise AssertionError("Unreachable: all paths inside the lock must return")


# ---------------------------------------------------------------------------
# Safe provider metadata extraction
# ---------------------------------------------------------------------------

# Allowlisted fields from the ElevenLabs outbound-call API response.
# Only these are persisted in CallSession.provider_metadata.
# All other fields are discarded to prevent storing unexpected PII or
# internal provider routing data (SIP URIs, trace IDs, phone numbers, etc.).
#
# Spec: outbound-call-trigger — Scenario: Cost and billed seconds persisted when available
#   "both cost and billed_duration_seconds stored without transformation"
#
# NOTE: 'message' is intentionally excluded. ElevenLabs and downstream SIP
# providers may populate 'message' with free-form text that can contain PII:
# phone numbers, caller names, SIP addresses, routing annotations.
# Prefer not persisting free-form provider messages (WU2 re-review RE4).
_SAFE_PROVIDER_METADATA_FIELDS = frozenset({
    "call_id",                   # provider call identifier (also in provider_call_id)
    "conversation_id",           # ElevenLabs conversation id — links CallSession to
                                 # the custom-llm session (session key) and SIP lookup.
    "sip_call_id",               # SIP Call-ID (e.g. "otb_...") — SIP evidence linkage.
    "status",                    # initial call status from provider
    "duration_seconds",          # raw call duration (may differ from billed)
    "billed_duration_seconds",   # SPEC REQUIRED: billed call duration (cost reporting)
    "cost",                      # call cost in USD (cost reporting)
    # "message" excluded: free-form provider text — PII risk (WU2 re-review RE4)
})


def _extract_safe_provider_metadata(raw: dict | None) -> dict | None:
    """Extract only allowlisted fields from a raw provider API response.

    Drops all fields not in _SAFE_PROVIDER_METADATA_FIELDS — this prevents
    storing PII (phone numbers), routing data (SIP URIs), or internal provider
    identifiers that should not persist in Qora's database.

    Returns:
        dict with only safe fields present in raw, or None if raw is None/empty.
    """
    if not raw:
        return None if raw is None else {}
    safe = {k: v for k, v in raw.items() if k in _SAFE_PROVIDER_METADATA_FIELDS}
    return safe


async def _find_active_call_session(
    db: AsyncSession,
    lead_id: str,
) -> CallSession | None:
    """Return the first active CallSession for a lead, or None.

    Active = telephony_status in {dialing, ringing, in_call}.
    Spec: outbound-call-trigger — Requirement: Concurrent Call Guard
    """
    stmt = select(CallSession).where(
        CallSession.lead_id == lead_id,
        CallSession.telephony_status.in_(_ACTIVE_TELEPHONY_STATUSES),
    )
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------------------------------------------------------------------
# C3 — Post-dial probe helper
# ---------------------------------------------------------------------------


def _fire_probe(
    session_id: str,
    agent_id: str,
    to_number: str,
    settings,
) -> None:
    """Fire the post-dial SIP evidence probe as a background asyncio task.

    Design: probe.py — fire-and-forget, 8s delay, catches all exceptions.
    Spec: call-sip-observability — Requirement: Post-Dial Background Probe.

    The probe never blocks the trigger response — it runs independently.
    Failures inside the probe are logged and never propagated here.

    Args:
        session_id: CallSession UUID to enrich.
        agent_id: ElevenLabs agent ID for conversation filtering.
        to_number: E.164 phone number that was dialed (logging context).
        settings: Application settings with elevenlabs_api_key.
    """
    from app.outbound.probe import probe_call_evidence

    task = asyncio.create_task(
        probe_call_evidence(
            session_id=session_id,
            agent_id=agent_id,
            to_number=to_number,
            settings=settings,
        )
    )
    # Retain a strong reference so CPython's GC cannot cancel the task before
    # it completes. The done-callback discards it from the set upon completion
    # or cancellation, preventing unbounded growth.
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _find_in_progress_scheduled_call(
    db: AsyncSession,
    lead_id: str,
    exclude_id: str | None = None,
):
    """Return an in_progress ScheduledCall for lead_id, excluding the current one.

    Used to prevent two scheduler ticks from dialing the same lead concurrently.
    exclude_id should be the current ScheduledCall.id so we don't block ourselves.

    Returns None if no overlapping in_progress ScheduledCall exists.
    """
    from app.scheduler.models import ScheduledCall as ScheduledCallModel

    stmt = select(ScheduledCallModel).where(
        ScheduledCallModel.lead_id == lead_id,
        ScheduledCallModel.status == "in_progress",
    )
    if exclude_id is not None:
        stmt = stmt.where(ScheduledCallModel.id != exclude_id)

    result = await db.execute(stmt)
    return result.scalars().first()
