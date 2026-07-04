"""QORA Outbound — Reconciliation sweep for stale outbound telephony sessions.

Background sweep that transitions CallSessions with stale active telephony
statuses (dialing, ringing, in_call) older than STALE_TELEPHONY_THRESHOLD_MINUTES
to either:
  - 'completed': if session_end_received=True (session-end webhook evidence)
  - 'stale_in_call': if no session-end evidence (operator review required)

FAS (False Answer Supervision) safety contract:
  - 'completed' is ONLY set when session_end_received IS TRUE.
    elevenlabs_conversation_id IS NOT NULL is NOT sufficient evidence — the
    conversation_id can be set by the outbound linkage webhook without the
    session-end webhook ever firing. session_end_received=True is the canonical
    evidence that the Custom LLM session-end webhook confirmed the call ended.
  - SIP-answered calls with no session-end evidence (billing artifact) stay as
    'stale_in_call' for operator visibility — NEVER auto-promoted to 'completed'.
  - 'stale_in_call' is distinct from 'no_answer': operator decides the outcome.

Design: design.md — Reconciliation Sweep (in_call timeout)
  "Background task (piggyback on existing scheduler tick interval):
   query CallSessions with telephony_status=in_call older than 30 minutes.
   If matching webhook evidence exists, mark completed.
   If not, mark stale_in_call and log for operator review."

The sweep covers all active telephony statuses to catch stuck dialing/ringing
sessions, not just in_call.

Usage (registered in main.py lifespan alongside stale_session_sweeper):
  from app.outbound.sweep import stale_outbound_telephony_sweeper
  sweeper_task = asyncio.create_task(stale_outbound_telephony_sweeper())
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession
from app.core.logging import get_logger

logger = get_logger(__name__)

# Active telephony statuses that can become stuck if a webhook never arrives.
# All three are potential stuck states:
#   dialing  — API call was made but ElevenLabs never confirmed (provider timeout)
#   ringing  — SIP INVITE sent but no answer or no webhook
#   in_call  — SIP 200 OK received but conversation webhook never fired (FAS scenario)
_STALE_TELEPHONY_STATUSES = frozenset({"dialing", "ringing", "in_call"})

# Sessions older than this ceiling are considered stale.
# Design decision: 30 minutes (design.md "30-min ceiling").
STALE_TELEPHONY_THRESHOLD_MINUTES = 30

# How often the background loop runs.
_SWEEP_INTERVAL_SECONDS = 300  # Every 5 minutes is sufficient for a 30-min threshold


async def sweep_stale_outbound_sessions(db: AsyncSession) -> int:
    """Find stale outbound telephony sessions and transition them.

    A session is stale if:
    - telephony_status is in {dialing, ringing, in_call}
    - started_at is older than STALE_TELEPHONY_THRESHOLD_MINUTES

    Transition logic (FAS-safe):
    - If session_end_received IS TRUE: → 'completed'
      (Session-end webhook confirmed; the call happened and ended normally)
    - If session_end_received IS NOT TRUE (False or None): → 'stale_in_call'
      (No session-end evidence; provider may have billed; operator must review)
      NOTE: elevenlabs_conversation_id IS NOT NULL alone is NOT sufficient —
      the session-end webhook must have fired (session_end_received=True).

    Commits only if sessions were swept (no unnecessary commits on idle runs).

    Args:
        db: Active async DB session.

    Returns:
        Number of sessions transitioned (0 if none found).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=STALE_TELEPHONY_THRESHOLD_MINUTES
    )

    result = await db.execute(
        select(CallSession).where(
            CallSession.telephony_status.in_(_STALE_TELEPHONY_STATUSES),
            CallSession.started_at < cutoff,
        )
    )
    stale_sessions = list(result.scalars().all())

    if not stale_sessions:
        return 0

    now = datetime.now(timezone.utc)
    swept_ids: list[str] = []
    completed_ids: list[str] = []
    stale_ids: list[str] = []

    for cs in stale_sessions:
        previous_status = cs.telephony_status

        # FAS evidence check: use session_end_received as completion evidence.
        # elevenlabs_conversation_id IS NOT NULL is NOT sufficient — it can be set
        # by the outbound linkage webhook without the session-end ever firing.
        # Only session_end_received=True (set by link_outbound_session_by_webhook or
        # update_telephony_status_on_session_end) is valid completion evidence.
        has_session_end_evidence = bool(cs.session_end_received)

        if has_session_end_evidence:
            # Session-end webhook confirmed — conversation happened, mark completed
            cs.telephony_status = "completed"
            completed_ids.append(cs.id)
        else:
            # No session-end evidence — mark stale for operator review
            # NEVER promote to 'completed' without session-end evidence (FAS)
            cs.telephony_status = "stale_in_call"
            stale_ids.append(cs.id)

        swept_ids.append(cs.id)

        logger.info(
            "outbound_sweep_session_transitioned",
            session_id=cs.id,
            previous_telephony_status=previous_status,
            new_telephony_status=cs.telephony_status,
            has_session_end_evidence=has_session_end_evidence,
            has_conversation_id=cs.elevenlabs_conversation_id is not None,
        )

    await db.commit()

    logger.info(
        "outbound_sweep_complete",
        swept_count=len(swept_ids),
        completed_count=len(completed_ids),
        stale_in_call_count=len(stale_ids),
        completed_ids=completed_ids,
        stale_ids=stale_ids,
        evidence_check="session_end_received",
    )

    return len(stale_sessions)


# ---------------------------------------------------------------------------
# C3 — SIP Observability reconciliation pass
# ---------------------------------------------------------------------------

# Sessions eligible for reconciliation by telephony_status.
# We reconcile sessions that are in a terminal-ish state but have not yet
# captured SIP evidence. 'failed' includes ambiguous_timeout sessions.
_RECONCILIATION_CANDIDATE_STATUSES = frozenset({"failed", "stale_in_call"})

# How close (in seconds) a conversation's start time must be to the session's
# started_at to be considered a match. 60 seconds gives reasonable tolerance
# for SIP setup time and ElevenLabs internal processing delay.
_SWEEP_MATCH_WINDOW_SECONDS = 60

# Time window passed to list_recent_conversations for each candidate session.
_SWEEP_CONVERSATION_WINDOW_SECONDS = 300  # 5 min window around session start


async def reconcile_unreconciled_sessions(
    db: AsyncSession,
    settings: Any,
) -> int:
    """Reconcile sessions with missing SIP evidence by polling ElevenLabs.

    Spec: call-sip-observability — Requirement: Background Reconciliation Sweep.

    Candidate sessions:
      - telephony_status IN ('failed', 'stale_in_call')
      - reconciled_at IS NULL
      - reconciliation_attempts < settings.reconciliation_max_attempts
      - Ordered oldest-first (started_at ASC)
      - Limited to settings.reconciliation_sweep_cap per cycle

    For each candidate:
      1. Call list_recent_conversations(agent_id, window).
      2. Check for unambiguous match (exactly one conversation within _SWEEP_MATCH_WINDOW_SECONDS).
         - Ambiguous (multiple close matches): log WARNING, skip, leave reconciled_at NULL.
         - No match: log INFO, skip.
         - Unambiguous: proceed to get_sip_messages.
      3. Write sip_call_id, sip_status_code, sip_reason, reconciled_at='sweep'.
      4. NEVER change telephony_status — reconciliation is read-only for call state.

    Retry cap (resilience fix):
      On each failed attempt (API error or exception), reconciliation_attempts is
      incremented. When it reaches settings.reconciliation_max_attempts (default 5),
      the session is parked: reconciled_at is set with reconciliation_source='unreconcilable'.
      Parked sessions are excluded from future candidate queries (reconciled_at IS NOT NULL).
      A distinct ERROR-level log event surfaces parked sessions for operator attention.

    API errors on individual sessions are caught and logged — sweep continues.
    The cap (reconciliation_sweep_cap) prevents rate-limit exposure.

    Args:
        db: Active async DB session.
        settings: Application settings with elevenlabs_api_key, reconciliation_sweep_cap,
                  and reconciliation_max_attempts.

    Returns:
        Number of sessions successfully reconciled (SIP evidence written).
        Does NOT count sessions parked as unreconcilable.
    """
    from app.elevenlabs.service import ElevenLabsService

    cap = getattr(settings, "reconciliation_sweep_cap", 10)
    max_attempts = getattr(settings, "reconciliation_max_attempts", 5)

    # Query eligible sessions: failed or stale_in_call with reconciled_at IS NULL
    # AND attempts below the cap. Oldest-first so longest-waiting sessions resolve first.
    stmt = (
        select(CallSession)
        .where(
            CallSession.telephony_status.in_(_RECONCILIATION_CANDIDATE_STATUSES),
            CallSession.reconciled_at.is_(None),
            CallSession.reconciliation_attempts < max_attempts,
        )
        .order_by(CallSession.started_at.asc())
        .limit(cap)
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    if not candidates:
        return 0

    el_service = ElevenLabsService(settings=settings)
    reconciled_count = 0
    needs_commit = False

    for cs in candidates:
        try:
            reconciled = await _reconcile_one_session(db, cs, el_service)
            if reconciled:
                reconciled_count += 1
                needs_commit = True
        except Exception as exc:
            # Increment the attempt counter on failure. This is the only mutation
            # allowed on failed reconciliation — telephony_status is NEVER changed.
            cs.reconciliation_attempts = (cs.reconciliation_attempts or 0) + 1
            needs_commit = True

            logger.warning(
                "reconciliation_sweep_session_error",
                session_id=cs.id,
                error=str(exc),
                error_type=type(exc).__name__,
                reconciliation_attempts=cs.reconciliation_attempts,
                max_attempts=max_attempts,
            )

            # Park the session when the attempt limit is reached so it is excluded
            # from future sweep cycles. Surface at ERROR level for operator visibility.
            if cs.reconciliation_attempts >= max_attempts:
                cs.reconciled_at = datetime.now(timezone.utc)
                cs.reconciliation_source = "unreconcilable"
                logger.error(
                    "reconciliation_session_parked_unreconcilable",
                    session_id=cs.id,
                    telephony_status=cs.telephony_status,
                    reconciliation_attempts=cs.reconciliation_attempts,
                    last_error=str(exc),
                    last_error_type=type(exc).__name__,
                    note=(
                        "Session has exhausted reconciliation_max_attempts and will no "
                        "longer be retried. Operator review required to investigate the "
                        "ElevenLabs API errors and determine whether SIP evidence exists."
                    ),
                )

            # Continue to the next candidate — do not let one failure stop the sweep

    if needs_commit:
        await db.commit()

    if reconciled_count > 0:
        logger.info(
            "reconciliation_sweep_complete",
            reconciled_count=reconciled_count,
            total_candidates=len(candidates),
        )

    return reconciled_count


async def _reconcile_one_session(
    db: AsyncSession,
    cs: CallSession,
    el_service: Any,
) -> bool:
    """Attempt to reconcile a single CallSession with SIP evidence.

    Returns True if SIP evidence was successfully written, False otherwise.
    May raise exceptions — caller (reconcile_unreconciled_sessions) handles them.
    """
    agent_id = cs.agent_id
    if not agent_id:
        logger.info(
            "reconciliation_skip_no_agent_id",
            session_id=cs.id,
        )
        return False

    session_ts = cs.started_at.timestamp() if cs.started_at else 0.0

    # Step 1: List recent conversations for this agent
    conv_list = await el_service.list_recent_conversations(
        agent_id=agent_id,
        time_window_seconds=_SWEEP_CONVERSATION_WINDOW_SECONDS,
    )

    if not conv_list.conversations:
        logger.info(
            "reconciliation_no_conversations",
            session_id=cs.id,
            agent_id=agent_id,
        )
        return False

    # Step 2: Check for unambiguous match within the time window
    matches = [
        conv for conv in conv_list.conversations
        if conv.start_time_unix_secs is not None
        and abs(conv.start_time_unix_secs - session_ts) <= _SWEEP_MATCH_WINDOW_SECONDS
    ]

    if len(matches) == 0:
        logger.info(
            "reconciliation_no_match",
            session_id=cs.id,
            agent_id=agent_id,
            conversation_count=len(conv_list.conversations),
        )
        return False

    if len(matches) > 1:
        # Ambiguous: multiple conversations within the match window
        # Spec: Ambiguous sweep match — safe skip.
        logger.warning(
            "reconciliation_ambiguous_match",
            session_id=cs.id,
            agent_id=agent_id,
            candidate_count=len(matches),
            candidate_ids=[m.conversation_id for m in matches],
        )
        return False

    # Exactly one match — proceed
    best_conv = matches[0]

    # Step 3: Fetch SIP messages
    sip_response = await el_service.get_sip_messages(
        conversation_id=best_conv.conversation_id
    )

    if not sip_response.sip_messages:
        logger.info(
            "reconciliation_no_sip_messages",
            session_id=cs.id,
            conversation_id=best_conv.conversation_id,
        )
        return False

    # Step 4: Extract safe fields and write to CallSession
    # (Never changes telephony_status — reconciliation is read-only for call state)
    from app.outbound.probe import _extract_sip_fields

    sip_call_id, sip_status_code, sip_reason = _extract_sip_fields(
        sip_response.sip_messages
    )

    cs.sip_call_id = sip_call_id
    cs.sip_status_code = sip_status_code
    cs.sip_reason = sip_reason
    cs.reconciled_at = datetime.now(timezone.utc)
    cs.reconciliation_source = "sweep"
    # telephony_status is intentionally NOT changed here

    logger.info(
        "reconciliation_evidence_written",
        session_id=cs.id,
        conversation_id=best_conv.conversation_id,
        sip_call_id=sip_call_id,
        sip_status_code=sip_status_code,
        sip_reason=sip_reason,
    )

    return True


async def stale_outbound_telephony_sweeper(settings: Any = None) -> None:
    """Background loop: sweep stale outbound telephony sessions periodically.

    Runs every _SWEEP_INTERVAL_SECONDS seconds. Registered in main.py lifespan
    alongside the existing stale_session_sweeper.

    In each sweep cycle:
      1. Transition stale active sessions (dialing/ringing/in_call > 30 min).
      2. Run SIP observability reconciliation for failed/stale_in_call sessions
         with reconciled_at IS NULL (C3 addition).

    Any exception during a sweep run is caught and logged — the loop
    continues regardless so a single DB hiccup doesn't kill the background task.

    Args:
        settings: Application settings (required for C3 reconciliation).
                  If None, reconciliation pass is skipped.
    """
    from app.core.database import get_session as db_session

    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            async with db_session() as db:
                # Pass 1: stale status transitions (existing behavior — FAS-safe)
                count = await sweep_stale_outbound_sessions(db)
                if count > 0:
                    logger.info(
                        "outbound_sweeper_run_complete",
                        swept=count,
                    )

                # Pass 2: SIP observability reconciliation (C3 addition)
                if settings is not None:
                    reconciled = await reconcile_unreconciled_sessions(db, settings=settings)
                    if reconciled > 0:
                        logger.info(
                            "outbound_reconciliation_run_complete",
                            reconciled=reconciled,
                        )
        except Exception as exc:
            logger.warning(
                "outbound_sweeper_run_failed",
                error=str(exc),
            )
