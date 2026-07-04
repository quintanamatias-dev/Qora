"""QORA Outbound — FAS-safe webhook/session linkage.

Provides the canonical function for linking an ElevenLabs conversation webhook
event back to an outbound CallSession.

FAS (False Answer Supervision) safety contract:
  - Provider SIP acknowledgment (in_call) MUST NEVER automatically set
    telephony_status='completed'.
  - telephony_status='completed' is ONLY set by this function, called
    from the Custom LLM session-end webhook path.
  - 'stale_in_call' transitions are handled by the reconciliation sweep
    (app.outbound.sweep) — also never auto-completing.

ID linkage chain (design.md):
  CallSession.id (Qora UUID)
    ├── provider_call_id        (ElevenLabs call identifier from API response)
    ├── elevenlabs_conversation_id  (set by THIS function when webhook fires)
    └── lead_id                 (FK to leads table)

Lookup priority:
  1. Find by elevenlabs_conversation_id (fast path — already set on session)
  2. Fallback: find by provider_call_id (first-time linkage)
  3. Return None if neither finds a session (orphan webhook — log only)

Tenant/outbound scoping (WU2 Fix B2):
  Both lookup helpers accept an optional client_id to scope results to a
  specific tenant. When client_id is provided, the SQL query adds a WHERE
  clause on client_id to prevent cross-tenant session matching.
  Both helpers also filter to outbound sessions (telephony_status IS NOT NULL)
  to avoid linking inbound sessions via the outbound webhook path.

Session-end evidence (WU2 Fix B4):
  link_outbound_session_by_webhook() sets session_end_received=True on the
  CallSession after successful linkage. The reconciliation sweep reads this
  field as completion evidence — not merely elevenlabs_conversation_id presence.

Spec: outbound-call-trigger — Scenario: Webhook fires — completion confirmed
  GIVEN the Custom LLM webhook session-end fires with a matching conversation_id
  WHEN the session is linked via provider_call_id or conversation_id
  THEN telephony_status=completed is set
  AND elevenlabs_conversation_id is stored on the CallSession
  AND session_end_received is set to True
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession
from app.core.logging import get_logger

logger = get_logger(__name__)


async def link_outbound_session_by_webhook(
    db: AsyncSession,
    *,
    conversation_id: str,
    provider_call_id: str | None = None,
    client_id: str | None = None,
) -> CallSession | None:
    """Link an outbound CallSession to a webhook conversation event.

    Sets telephony_status='completed' ONLY when called — this is the sole
    mechanism for marking an outbound call as completed. Provider SIP state
    alone (in_call) never triggers this.

    Also sets session_end_received=True to record that the session-end webhook
    actually fired. The reconciliation sweep uses this as completion evidence.

    Lookup strategy:
      1. Primary: find by elevenlabs_conversation_id == conversation_id
         (Session was already linked in a prior turn or matched by conv_id)
      2. Fallback: find by provider_call_id (first-time linkage — conversation
         started but elevenlabs_conversation_id was not yet stored)
      3. If no session found: return None

    On success:
      - Sets telephony_status = 'completed' (FAS-safe — webhook = evidence)
      - Sets elevenlabs_conversation_id = conversation_id (if not already set)
      - Sets session_end_received = True (sweep evidence)
      - Commits the change (durable)

    On idempotent path (already completed):
      - Returns the session unchanged (telephony_status stays 'completed')

    Args:
        db: Active async DB session.
        conversation_id: ElevenLabs conversation ID from the webhook event.
        provider_call_id: Optional ElevenLabs call ID for fallback lookup.
            Provided when the webhook also carries the call identifier.
        client_id: Optional tenant ID to scope lookups. When provided, both
            primary and fallback lookups include client_id in the WHERE clause
            to prevent cross-tenant session matching (WU2 Fix B2).

    Returns:
        Updated CallSession, or None if no outbound session was found.
    """
    # ------------------------------------------------------------------
    # Step 1: Primary lookup — by elevenlabs_conversation_id
    # ------------------------------------------------------------------
    cs = await _find_by_conversation_id(db, conversation_id, client_id=client_id)

    # ------------------------------------------------------------------
    # Step 2: Fallback lookup — by provider_call_id
    # (Used when the session was created with a provider_call_id from the
    #  outbound API response, but elevenlabs_conversation_id was never set
    #  because no prior webhook had fired for this call)
    # ------------------------------------------------------------------
    if cs is None and provider_call_id is not None:
        cs = await _find_by_provider_call_id(db, provider_call_id, client_id=client_id)

    if cs is None:
        logger.warning(
            "outbound_webhook_session_not_found",
            conversation_id=conversation_id,
            provider_call_id=provider_call_id,
            client_id=client_id,
        )
        return None

    # ------------------------------------------------------------------
    # Idempotency check — already completed, return without re-mutating
    # ------------------------------------------------------------------
    if cs.telephony_status == "completed":
        logger.info(
            "outbound_webhook_linkage_idempotent",
            session_id=cs.id,
            conversation_id=conversation_id,
        )
        return cs

    # ------------------------------------------------------------------
    # Set webhook evidence fields
    # ------------------------------------------------------------------
    previous_status = cs.telephony_status

    # Store the conversation_id if not already set
    if cs.elevenlabs_conversation_id is None:
        cs.elevenlabs_conversation_id = conversation_id

    # Mark completed — webhook evidence is the ONLY path to this status
    cs.telephony_status = "completed"

    # Record that the session-end webhook fired (sweep evidence)
    cs.session_end_received = True

    await db.commit()

    logger.info(
        "outbound_webhook_session_linked",
        session_id=cs.id,
        conversation_id=conversation_id,
        provider_call_id=cs.provider_call_id,
        previous_telephony_status=previous_status,
        new_telephony_status="completed",
        session_end_received=True,
    )

    return cs


async def _find_by_conversation_id(
    db: AsyncSession,
    conversation_id: str,
    *,
    client_id: str | None = None,
) -> CallSession | None:
    """Find an outbound CallSession by elevenlabs_conversation_id.

    Scoped to outbound sessions (telephony_status IS NOT NULL) to avoid
    linking inbound sessions through the outbound webhook path.

    When client_id is provided, also filters by client_id to prevent
    cross-tenant session matching (WU2 Fix B2).

    Args:
        db: Active async DB session.
        conversation_id: ElevenLabs conversation ID to search for.
        client_id: Optional tenant scope. When provided, restricts to sessions
            belonging to this tenant only.
    """
    stmt = select(CallSession).where(
        CallSession.elevenlabs_conversation_id == conversation_id,
        CallSession.telephony_status.is_not(None),  # outbound sessions only
    )
    if client_id is not None:
        stmt = stmt.where(CallSession.client_id == client_id)

    result = await db.execute(stmt)
    return result.scalars().first()


async def _find_by_provider_call_id(
    db: AsyncSession,
    provider_call_id: str,
    *,
    client_id: str | None = None,
) -> CallSession | None:
    """Find an outbound CallSession by provider_call_id.

    This is the fallback path for first-time linkage: when ElevenLabs sends
    the session-end webhook and the session was created via the outbound API
    but the conversation_id was never matched/stored yet.

    Scoped to outbound sessions (telephony_status IS NOT NULL) to avoid
    matching inbound sessions that happen to have the same provider_call_id.

    When client_id is provided, also filters by client_id to prevent
    cross-tenant session matching (WU2 Fix B2).

    Args:
        db: Active async DB session.
        provider_call_id: ElevenLabs call ID to search for.
        client_id: Optional tenant scope. When provided, restricts to sessions
            belonging to this tenant only.
    """
    stmt = select(CallSession).where(
        CallSession.provider_call_id == provider_call_id,
        CallSession.telephony_status.is_not(None),  # outbound sessions only
    )
    if client_id is not None:
        stmt = stmt.where(CallSession.client_id == client_id)

    result = await db.execute(stmt)
    return result.scalars().first()


# Statuses that represent "no real conversation happened" — a session-end webhook
# arriving for these is out-of-order, duplicate, or stale and must NOT silently
# overwrite the diagnostic status with 'completed'.
# - no_answer:       Call was placed; the recipient never answered.
# - recurrent_error: Repeated provider-level errors; no conversation occurred.
#
# Statuses that are intentionally overwritten by session-end evidence:
# - failed:          Outbound API reported failure, but a conversation webhook arrived
#                    anyway (FAS scenario). The webhook is the ground truth.
# - stale_in_call:   Sweep marked session as stuck; a late webhook resolves it.
# - ringing/in_call: Normal in-progress → completed transition.
_TERMINAL_NO_CONVERSATION_STATUSES: frozenset[str] = frozenset(
    {"no_answer", "recurrent_error"}
)


def update_telephony_status_on_session_end(cs: CallSession) -> CallSession:
    """Update telephony_status to 'completed' when a session-end webhook fires.

    This is the synchronous helper called within close_session() (or close_session
    callers) to keep telephony_status in sync with session.status='completed'.

    Also sets session_end_received=True to record webhook evidence for the
    reconciliation sweep (WU2 Fix B4).

    FAS-safe contract:
    - Only updates telephony_status when the session has an outbound telephony_status
      (i.e., cs.telephony_status is NOT None — inbound sessions have NULL here).
    - Does NOT overwrite terminal no-conversation statuses (no_answer,
      recurrent_error): these are more informative than 'completed', and a
      session-end arriving for them is out-of-order or stale.
    - Does overwrite failed/stale_in_call: the session-end webhook is definitive
      evidence that a real conversation occurred regardless of prior provider state.
    - Idempotent: already-completed stays completed.
    - session_end_received=True is always set when telephony_status is not None —
      the webhook fired, even if we preserve the existing terminal status.

    Args:
        cs: CallSession ORM instance (may be a mock in tests).

    Returns:
        The same cs instance with telephony_status updated (for chaining).
    """
    # Only outbound sessions have a telephony_status. Inbound sessions have NULL.
    if cs.telephony_status is not None:
        # Always record that the session-end webhook fired — the sweep reads this.
        cs.session_end_received = True

        # Guard: preserve terminal no-conversation statuses. An out-of-order or
        # duplicate session-end webhook must not silently flip these to 'completed'.
        if cs.telephony_status in _TERMINAL_NO_CONVERSATION_STATUSES:
            logger.info(
                "outbound_session_end_status_preserved",
                session_id=cs.id,
                telephony_status=cs.telephony_status,
                reason="terminal_no_conversation_status_preserved",
            )
            return cs

        if cs.telephony_status != "completed":
            cs.telephony_status = "completed"
    return cs
