"""QORA Outbound — Manual call trigger endpoint.

POST /api/v1/clients/{client_id}/leads/{lead_id}/call

Spec: outbound-call-trigger — Requirement: Manual Trigger Endpoint
  Auth: admin API key (require_api_key)
  Response 200: { "status": "dialing"|"failed"|"recurrent_error", "call_session_id": str }
  Response 403: feature flag off
  Response 404: lead or client not found
  Response 409: concurrent active call
  Response 422: invalid E.164 phone
  Response 429: cooldown active (rapid repeat from UI/operator)

Design: dial_outbound_call() is the sole dialing entry point; the router only
  handles HTTP plumbing, guards, and response shaping. No business logic here.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.states import CallStatus
from app.core.auth import require_api_key
from app.core.config import Settings
from app.core.logging import get_logger
from app.leads.service import get_lead
from app.outbound.service import dial_outbound_call
from app.tenants.service import get_client, get_default_agent

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Per-lead cooldown guard — prevent rapid repeated UI/operator trigger attempts.
#
# Problem: An operator double-clicks "Call Now", or the frontend sends two
# requests in quick succession due to a UI bug. Both could pass the active-session
# guard (neither has yet created a CallSession) and charge the operator twice.
#
# Solution: Track the last call attempt timestamp per lead_id in-process.
# If the same lead was attempted within OUTBOUND_CALL_COOLDOWN_SECONDS, return 429.
#
# This is separate from the concurrent-call guard (which checks telephony_status).
# The cooldown catches rapid failures + retriggers, not just active sessions.
#
# Memory: Regular dict. For MVP (single-process), safe. Future: move to Redis.
# ---------------------------------------------------------------------------
_LAST_CALL_ATTEMPT: dict[str, float] = {}  # lead_id → Unix timestamp

#: Default cooldown window in seconds. Configurable via Settings if needed.
_DEFAULT_COOLDOWN_SECONDS: int = 10


def _should_cooldown_reject(
    lead_id: str, cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS
) -> bool:
    """Return True if a call attempt for lead_id should be rejected due to cooldown.

    Returns True if the last attempt was within cooldown_seconds ago, False otherwise.
    """
    last_ts = _LAST_CALL_ATTEMPT.get(lead_id)
    if last_ts is None:
        return False
    return (time.monotonic() - last_ts) < cooldown_seconds


def _record_call_attempt(lead_id: str) -> None:
    """Record that a call attempt was made for lead_id (used to enforce cooldown)."""
    _LAST_CALL_ATTEMPT[lead_id] = time.monotonic()

router = APIRouter(
    prefix="/clients/{client_id}",
    tags=["outbound"],
    dependencies=[Depends(require_api_key)],
)


# ---------------------------------------------------------------------------
# DB and settings dependencies
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


async def get_settings(request: Request) -> Settings:
    """FastAPI dependency that returns app settings."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = Settings()
    return settings


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class CallTriggerResponse(BaseModel):
    """Response for POST /clients/{client_id}/leads/{lead_id}/call.

    status: "dialing"         — ElevenLabs API accepted, call is in progress
            "failed"          — Guards or API call failed (permanent, ambiguous
                                 timeout, or pre-check)
            "recurrent_error" — Two consecutive transient failures
    call_session_id: UUID of the created CallSession.
    error: Human-readable failure reason when status != "dialing". None on success.
        The frontend surfaces this instead of getting stuck on "Calling…" when a
        200 response carries a non-dialing status.
    """

    status: str
    call_session_id: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/leads/{lead_id}/call",
    response_model=CallTriggerResponse,
    summary="Trigger an outbound call to a lead",
    responses={
        200: {"description": "Call accepted or failed after attempt(s)"},
        403: {"description": "Feature flag off or unauthorized"},
        404: {"description": "Client or lead not found"},
        409: {"description": "Concurrent active call in progress"},
        422: {"description": "Invalid E.164 phone number"},
    },
)
async def trigger_outbound_call(
    client_id: str,
    lead_id: str,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> CallTriggerResponse:
    """Manually trigger an outbound call to a lead.

    Spec: outbound-call-trigger — Requirement: Manual Trigger Endpoint
    Requires: admin API key + ENABLE_OUTBOUND_CALLS=true

    Guards (in order):
      1. Feature flag: 403 if off
      2. Client exists: 404 if not found
      3. Lead exists + belongs to client: 404 if not found
      4. Phone E.164 validation: 422 if invalid
      5. Concurrent call guard: 409 if active session
      6. Agent resolved: 404 if no default agent configured

    All real telephony is delegated to dial_outbound_call().
    """
    # ------------------------------------------------------------------
    # Guard 1: Feature flag (fast path — check before any DB query)
    # ------------------------------------------------------------------
    if not settings.enable_outbound_calls:
        logger.info(
            "outbound_trigger_blocked_flag_off",
            client_id=client_id,
            lead_id=lead_id,
        )
        raise HTTPException(
            status_code=403,
            detail=(
                "Outbound calls are disabled. "
                "Set ENABLE_OUTBOUND_CALLS=true to enable real outbound dialing."
            ),
        )

    # ------------------------------------------------------------------
    # Guard 2: Client exists
    # ------------------------------------------------------------------
    client = await get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found.")

    # ------------------------------------------------------------------
    # Guard 3: Lead exists and belongs to this client
    # ------------------------------------------------------------------
    lead = await get_lead(db, lead_id)
    if lead is None or lead.client_id != client_id:
        raise HTTPException(
            status_code=404,
            detail=f"Lead '{lead_id}' not found for client '{client_id}'.",
        )

    # ------------------------------------------------------------------
    # Guard 3b: Cooldown guard — prevent rapid repeated UI/operator triggers.
    # Checked BEFORE phone validation to reject quickly without DB queries.
    # ------------------------------------------------------------------
    cooldown_seconds = getattr(settings, "outbound_call_cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS)
    if _should_cooldown_reject(lead_id, cooldown_seconds=cooldown_seconds):
        logger.warning(
            "outbound_trigger_cooldown_rejected",
            client_id=client_id,
            lead_id=lead_id,
            cooldown_seconds=cooldown_seconds,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Call attempt for lead '{lead_id}' rejected: cooldown active. "
                f"Wait {cooldown_seconds}s between call attempts to prevent duplicate charges."
            ),
        )

    # ------------------------------------------------------------------
    # Guard 4: Phone E.164 validation (early rejection before DB writes)
    # ------------------------------------------------------------------
    from app.outbound.phone import validate_e164

    try:
        validate_e164(lead.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )

    # ------------------------------------------------------------------
    # Guard 5 + 6: Concurrent call guard + agent resolution (inside dial_outbound_call)
    # Resolve default agent here so we can 404 before creating any CallSession
    # ------------------------------------------------------------------
    agent = await get_default_agent(db, client_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No default agent configured for client '{client_id}'. "
                "Create and configure an agent with elevenlabs_phone_number_id before dialing."
            ),
        )

    # ------------------------------------------------------------------
    # Guard 6a: Concurrent call guard (409 before any DB write)
    # Check for active session before delegating to dial_outbound_call
    # ------------------------------------------------------------------
    from app.calls.models import CallSession
    from sqlalchemy import select

    # Spec: call-state-machine — Requirement: Concurrency Guard Updated
    # Active set is {dialing, ringing, connected}; in_call is gone.
    # Spec: MODIFIED: Manual Trigger Endpoint — 409 body now includes active_session_id.
    _ACTIVE_STATUSES = {CallStatus.dialing, CallStatus.ringing, CallStatus.connected}
    stmt = select(CallSession).where(
        CallSession.lead_id == lead_id,
        CallSession.telephony_status.in_(_ACTIVE_STATUSES),
    )
    result = await db.execute(stmt)
    active_session = result.scalars().first()
    if active_session is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"Lead '{lead_id}' already has an active call. "
                    "Cannot start a duplicate call."
                ),
                "active_session_id": active_session.id,
                "telephony_status": active_session.telephony_status,
            },
        )

    # ------------------------------------------------------------------
    # Record the attempt timestamp for cooldown tracking
    # This must happen BEFORE the actual dial so that concurrent requests
    # (racing past the concurrent guard) are also blocked by cooldown.
    # ------------------------------------------------------------------
    _record_call_attempt(lead_id)

    # ------------------------------------------------------------------
    # Delegate to the central dialing function
    # ------------------------------------------------------------------
    dial_result = await dial_outbound_call(
        db=db,
        lead=lead,
        agent=agent,
        client=client,
        settings=settings,
        scheduled_call=None,  # manual trigger — no ScheduledCall reference
    )

    # ------------------------------------------------------------------
    # Map structured failure codes to HTTP status codes.
    #
    # Concurrent guard failures (both CallSession and ScheduledCall overlap)
    # must be externally visible as HTTP 409 — spec: "Concurrent Call Guard"
    # is an externally observable invariant, not an internal success detail.
    #
    # Using structured failure_code (not string-matching on error messages)
    # so this mapping is robust to error message wording changes.
    # ------------------------------------------------------------------
    _CONCURRENT_GUARD_CODES = {"concurrent_active_session", "concurrent_scheduled_call"}
    if dial_result.failure_code in _CONCURRENT_GUARD_CODES:
        raise HTTPException(
            status_code=409,
            detail=(
                dial_result.error
                or f"Concurrent call conflict for lead '{lead_id}'. "
                   "A call is already active or an in_progress ScheduledCall exists."
            ),
        )

    # Propagate the failure reason to the client for non-dialing outcomes so the
    # UI can render an error row instead of an eternal "Calling…" state. On a
    # 'dialing' success there is no error to surface.
    return CallTriggerResponse(
        status=dial_result.status,
        call_session_id=dial_result.call_session_id,
        error=dial_result.error if dial_result.status != "dialing" else None,
    )
