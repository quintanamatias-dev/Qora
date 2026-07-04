"""QORA Outbound — Post-dial SIP evidence probe.

Background fire-and-forget task that captures ElevenLabs/Telnyx SIP identifiers
and final SIP status codes into CallSession after a dial attempt.

Design decisions (from design.md):
  - Isolated in probe.py (independently testable; rollback = delete file)
  - Uses its own DB session via async_session_factory (independent of request session)
  - Fire-and-forget: any exception is caught at the outer boundary; never propagates
  - Idempotent: if reconciled_at is already set, exits immediately without API calls
  - 8-second default delay to allow ElevenLabs SIP state to settle after INVITE

Usage:
    import asyncio
    from app.outbound.probe import probe_call_evidence
    asyncio.create_task(probe_call_evidence(
        session_id=call_session.id,
        agent_id=agent.elevenlabs_agent_id,
        to_number=lead.phone,
        settings=settings,
    ))

Spec: call-sip-observability — Requirement: Post-Dial Background Probe
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Probe delay in seconds — allows ElevenLabs SIP state to settle after INVITE.
# The default 8 seconds is a heuristic: SIP responses for outbound calls typically
# arrive within 1-5 seconds after the INVITE is accepted. 8 seconds gives headroom
# without meaningfully delaying the probe's capture window.
# Override in tests by passing delay=0.
_DEFAULT_PROBE_DELAY_SECONDS = 8

# Conversation matching time window (seconds) for list_recent_conversations.
# We look back from started_at to find conversations initiated around that time.
_PROBE_CONVERSATION_WINDOW_SECONDS = 120

# How far from started_at a conversation can be and still be considered a match.
# Within this window + a small buffer for processing time.
_MATCH_WINDOW_SECONDS = 60


# Module-level reference patched in tests and set at runtime.
# Set by the application lifespan or imported lazily from app.core.database.
async_session_factory: Any = None


async def probe_call_evidence(
    session_id: str,
    agent_id: str,
    to_number: str,
    settings: Any,
    delay: float = _DEFAULT_PROBE_DELAY_SECONDS,
) -> None:
    """Capture SIP evidence for a CallSession asynchronously.

    Fire-and-forget: called via asyncio.create_task. Never raises — all exceptions
    are caught at the outer boundary so the call trigger HTTP response is unaffected.

    Flow:
      1. Wait `delay` seconds to allow ElevenLabs SIP state to settle.
      2. Open its own DB session — request session may be closed by this point.
      3. Load CallSession; if reconciled_at is already set, exit (idempotent guard).
      4. Call list_recent_conversations(agent_id, window) to find matching conversations.
      5. Match by closest start_time_unix_secs to the session's started_at.
      6. Call get_sip_messages(conversation_id) for the matched conversation.
      7. Extract the final SIP response (last status_code + reason_phrase) and Call-ID.
      8. Write sip_call_id, sip_status_code, sip_reason, reconciled_at='probe', commit.

    Args:
        session_id: UUID of the CallSession to enrich.
        agent_id: ElevenLabs agent ID used to filter conversations.
        to_number: E.164 phone number that was dialed (call context; never logged — PII).
        settings: Application settings (must have elevenlabs_api_key).
        delay: Seconds to wait before probing (default 8; set to 0 in tests).

    Returns:
        None — always. Never raises.
    """
    try:
        await asyncio.sleep(delay)
        await _run_probe(session_id, agent_id, to_number, settings)
    except Exception as exc:
        # Outer boundary: catch ALL exceptions so this never affects the HTTP caller.
        logger.warning(
            "probe_call_evidence_unhandled_error",
            session_id=session_id,
            agent_id=agent_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def _run_probe(
    session_id: str,
    agent_id: str,
    to_number: str,
    settings: Any,
) -> None:
    """Inner probe logic — runs after the delay. May raise (caught by probe_call_evidence)."""
    from app.calls.models import CallSession
    from app.elevenlabs.service import ElevenLabsService

    # Resolve the session factory (lazy import at runtime, injected in tests)
    factory = _resolve_session_factory()
    if factory is None:
        logger.error("probe_no_session_factory", session_id=session_id)
        return

    async with factory() as db:
        cs: CallSession | None = await db.get(CallSession, session_id)
        if cs is None:
            logger.warning("probe_session_not_found", session_id=session_id)
            return

        # Idempotency guard: already reconciled → skip all API calls
        if cs.reconciled_at is not None:
            logger.info(
                "probe_already_reconciled",
                session_id=session_id,
                reconciled_at=cs.reconciled_at.isoformat() if hasattr(cs.reconciled_at, "isoformat") else str(cs.reconciled_at),
                source=cs.reconciliation_source,
            )
            return

        el_service = ElevenLabsService(settings=settings)

        # Step 1: List recent conversations for this agent
        try:
            conv_list = await el_service.list_recent_conversations(
                agent_id=agent_id,
                time_window_seconds=_PROBE_CONVERSATION_WINDOW_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "probe_list_conversations_failed",
                session_id=session_id,
                agent_id=agent_id,
                error=str(exc),
            )
            return

        if not conv_list.conversations:
            logger.info(
                "probe_no_conversations_found",
                session_id=session_id,
                agent_id=agent_id,
            )
            return

        # Step 2: Match by closest start_time_unix_secs to started_at
        session_ts = cs.started_at.timestamp() if cs.started_at else 0.0
        best_conv = _find_best_match(
            conv_list.conversations, session_ts, session_id=session_id, agent_id=agent_id
        )

        if best_conv is None:
            logger.info(
                "probe_no_matching_conversation",
                session_id=session_id,
                agent_id=agent_id,
            )
            return

        # Step 3: Fetch SIP messages for the matched conversation
        try:
            sip_response = await el_service.get_sip_messages(
                conversation_id=best_conv.conversation_id
            )
        except Exception as exc:
            logger.warning(
                "probe_get_sip_messages_failed",
                session_id=session_id,
                conversation_id=best_conv.conversation_id,
                error=str(exc),
            )
            return

        if not sip_response.sip_messages:
            logger.info(
                "probe_no_sip_messages",
                session_id=session_id,
                conversation_id=best_conv.conversation_id,
            )
            return

        # Step 4: Extract SIP fields — allowlist only (spec: Structured-Field-Only)
        sip_call_id, sip_status_code, sip_reason = _extract_sip_fields(
            sip_response.sip_messages
        )

        # Step 5: Write to CallSession and commit
        cs.sip_call_id = sip_call_id
        cs.sip_status_code = sip_status_code
        cs.sip_reason = sip_reason
        cs.reconciled_at = datetime.now(timezone.utc)
        cs.reconciliation_source = "probe"

        await db.commit()

        logger.info(
            "probe_evidence_captured",
            session_id=session_id,
            conversation_id=best_conv.conversation_id,
            sip_call_id=sip_call_id,
            sip_status_code=sip_status_code,
            sip_reason=sip_reason,
        )


def _find_best_match(
    conversations: list,
    session_ts: float,
    session_id: str | None = None,
    agent_id: str | None = None,
):
    """Find the single unambiguous conversation closest to the session's started_at.

    Mirrors the sweep's ambiguity handling (_reconcile_one_session): if more than
    one conversation falls within _MATCH_WINDOW_SECONDS, the match is ambiguous —
    log a warning and return None so the sweep can reconcile it later.

    Args:
        conversations: List of ConversationSummary objects.
        session_ts: Unix timestamp of the CallSession started_at.
        session_id: CallSession id for logging context (optional).
        agent_id: ElevenLabs agent id for logging context (optional).

    Returns:
        The single ConversationSummary within _MATCH_WINDOW_SECONDS, or None if
        there is no match or the match is ambiguous (multiple candidates).
    """
    matches = [
        conv for conv in conversations
        if conv.start_time_unix_secs is not None
        and abs(conv.start_time_unix_secs - session_ts) <= _MATCH_WINDOW_SECONDS
    ]

    if len(matches) == 0:
        return None

    if len(matches) > 1:
        # Ambiguous: multiple conversations within the match window.
        # Spec: Ambiguous match — safe skip; let the sweep reconcile later.
        logger.warning(
            "probe_ambiguous_match",
            session_id=session_id,
            agent_id=agent_id,
            candidate_count=len(matches),
            candidate_ids=[m.conversation_id for m in matches],
        )
        return None

    return matches[0]


def _extract_sip_fields(sip_messages: list) -> tuple[str | None, int | None, str | None]:
    """Extract Call-ID, final status code, and reason phrase from SIP messages.

    Spec: Structured-Field-Only SIP Extraction — only allowlisted fields.

    Extracts:
      - call_id: from the first message that has one (stable across the dialog)
      - sip_status_code + sip_reason: from the LAST message with a status_code
        (final SIP response in the dialog)

    Never returns raw SIP bodies, Proxy-Authorization, or URI userinfo.

    Args:
        sip_messages: List of SipMessage objects from ElevenLabsService.

    Returns:
        Tuple of (call_id, status_code, reason_phrase) — all may be None.
    """
    call_id: str | None = None
    status_code: int | None = None
    reason_phrase: str | None = None

    for msg in sip_messages:
        # Extract Call-ID from first message that has it (stable across dialog)
        if call_id is None and msg.call_id:
            call_id = msg.call_id

        # Track the final response: keep updating as we iterate (last wins)
        if msg.status_code is not None:
            status_code = msg.status_code
            reason_phrase = msg.reason_phrase

    return call_id, status_code, reason_phrase


def _resolve_session_factory():
    """Resolve the async session factory.

    At runtime: import lazily from app.core.database.
    In tests: the module-level async_session_factory is patched directly.
    """
    global async_session_factory

    if async_session_factory is not None:
        return async_session_factory

    # Lazy import at runtime — avoids circular imports at module load time
    try:
        from app.core.database import async_session_factory as factory
        return factory
    except (ImportError, AttributeError):
        return None
