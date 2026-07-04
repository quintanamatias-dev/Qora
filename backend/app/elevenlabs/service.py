"""QORA ElevenLabs Service — programmatic agent configuration.

Provides ElevenLabsService.sync_soft_timeout() which sends a partial PATCH
to the ElevenLabs ConvAI agent API to configure soft timeout settings.

Design decisions (from design.md):
- Per-call httpx.AsyncClient (matches webhook.py get_signed_url pattern — infrequent calls)
- 1 retry on 5xx responses, no retry on 4xx or timeout
- 10-second request timeout
- Structured logging on error (http_status, elevenlabs_agent_id)
- Never raises to the caller — always returns SyncResult
- Skips (no HTTP call) when elevenlabs_agent_id is None
- Skips (no HTTP call) when all soft_timeout fields are None
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

import asyncio

from app.core.logging import get_logger
from app.elevenlabs.models import (  # noqa: F401 — re-exported
    SoftTimeoutConfig,
    SyncResult,
    OutboundCallRequest,
    OutboundCallResult,
    ConversationListResponse,
    SipMessagesResponse,
)

logger = get_logger(__name__)

_ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
_REQUEST_TIMEOUT_SECONDS = 10.0

# The outbound-call API can hold the HTTP connection open while it creates and
# rings the SIP call. A short read timeout (10s) fires WHILE the call is already
# ringing, producing an ambiguous side-effect (see initiate_outbound_call). We use
# a longer read timeout for the dial so we normally receive the real provider
# response (call_id / no_answer) instead of an ambiguous timeout. Connect stays
# short — connect failures are safe to fail fast on.
_OUTBOUND_CONNECT_TIMEOUT_SECONDS = 10.0
_OUTBOUND_READ_TIMEOUT_SECONDS = 45.0
_OUTBOUND_CALL_TIMEOUT = httpx.Timeout(
    _OUTBOUND_READ_TIMEOUT_SECONDS,
    connect=_OUTBOUND_CONNECT_TIMEOUT_SECONDS,
)
_OUTBOUND_CALL_URL = f"{_ELEVENLABS_BASE_URL}/convai/sip-trunk/outbound-call"


class ElevenLabsService:
    """Handles programmatic configuration of ElevenLabs ConvAI agents.

    Injected via FastAPI Depends() in the agents router:
        service = Depends(get_elevenlabs_service)
    """

    def __init__(self, settings) -> None:
        self._settings = settings

    async def sync_soft_timeout(self, agent) -> SyncResult:
        """Send a partial PATCH to configure soft timeout on an ElevenLabs agent.

        Sends ONLY the soft_timeout_config block — never a full agent body.

        Skip conditions (no HTTP call):
        - agent.elevenlabs_agent_id is None
        - all of soft_timeout_seconds, soft_timeout_message, soft_timeout_use_llm are None

        Retry: exactly one retry on 5xx responses.
        Timeout: 10 seconds per attempt.
        On failure: logs structured error, returns SyncResult(outcome="error").
        Never raises to caller.
        """
        # Guard: no ElevenLabs agent binding
        if agent.elevenlabs_agent_id is None:
            return SyncResult(outcome="skipped")

        # Guard: all soft timeout fields are None → nothing to configure
        if (
            agent.soft_timeout_seconds is None
            and agent.soft_timeout_message is None
            and agent.soft_timeout_use_llm is None
        ):
            return SyncResult(outcome="skipped")

        url = f"{_ELEVENLABS_BASE_URL}/convai/agents/{agent.elevenlabs_agent_id}"
        payload = _build_soft_timeout_payload(
            timeout_seconds=agent.soft_timeout_seconds,
            message=agent.soft_timeout_message,
            use_llm_generated_message=agent.soft_timeout_use_llm,
        )
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

        return await _patch_with_retry(
            url=url,
            payload=payload,
            headers=headers,
            elevenlabs_agent_id=agent.elevenlabs_agent_id,
        )


    async def initiate_outbound_call(
        self,
        request: OutboundCallRequest,
    ) -> OutboundCallResult:
        """POST to ElevenLabs SIP trunk outbound-call API.

        Args:
            request: OutboundCallRequest with agent_id, agent_phone_number_id,
                     to (E.164), and optional conversation_initiation_client_data.

        Returns:
            OutboundCallResult — never raises.

        Error classification (Design: failure-classification decision tree):
            - HTTP 5xx, 429                            → error_category='transient'
            - HTTP 4xx (not 429)                      → error_category='permanent'
            - Connect errors (DNS, refused, connect
              timeout — request never reached provider) → error_category='transient'
            - Read/Write/Pool timeout (request WAS sent;
              provider may have already placed the SIP call) → error_category='unknown'
              (side effect ambiguous — MUST NOT be retried, else a second real
               billed call is dialed while the first is already ringing)
            - 2xx with status='no_answer'/'ring_timeout' in body
                                                       → error_category='no_answer'
              (provider-reported no answer: distinct from system failure, not retried)

        No retry is performed here — retry logic lives in dial_outbound_call()
        in app.outbound.service so the CallSession state is updated between attempts.

        Spec: outbound-call-trigger — Requirement: Live Status State Machine
          ringing → no_answer when provider reports no answer / ring timeout.
        """
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

        payload = {
            "agent_id": request.agent_id,
            "agent_phone_number_id": request.agent_phone_number_id,
            # ElevenLabs SIP trunk outbound-call API requires "to_number" (not "to").
            # Sending "to" causes an HTTP 422 permanent error and the call is never placed.
            # Verified against ElevenLabs ConvAI outbound-call API docs (2026-07-04).
            "to_number": request.to,
        }
        if request.conversation_initiation_client_data is not None:
            payload["conversation_initiation_client_data"] = (
                request.conversation_initiation_client_data
            )

        try:
            async with httpx.AsyncClient(timeout=_OUTBOUND_CALL_TIMEOUT) as client:
                response = await client.post(
                    _OUTBOUND_CALL_URL, json=payload, headers=headers
                )

            if response.is_success:
                # Defensive JSON parse — a 2xx with a non-JSON body (e.g. proxy error
                # page, maintenance HTML) must NOT silently transition the session to
                # 'ringing'. Treat malformed JSON as a permanent provider failure so
                # the CallSession stays in 'failed' rather than 'ringing' without a
                # trackable provider_call_id.
                try:
                    body: dict = response.json() if response.content else {}
                except Exception as json_exc:
                    error_detail = f"json_parse_error: {type(json_exc).__name__}: {json_exc}"
                    logger.error(
                        "elevenlabs_outbound_malformed_response",
                        error=error_detail,
                        http_status=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                    )
                    return OutboundCallResult(
                        outcome="error",
                        error_detail=error_detail,
                        error_category="permanent",
                    )

                # The ElevenLabs SIP trunk outbound-call API does NOT return a
                # "call_id" field. On success it returns "conversation_id" and
                # "sip_call_id" (verified against live API, 2026-07-04):
                #   {"success": true, "conversation_id": "...", "sip_call_id": "otb_..."}
                # We accept any of call_id / conversation_id / sip_call_id (in that
                # priority order) as the provider linkage identifier. The first
                # non-empty value wins. A response with NONE of these means Qora
                # cannot track/reconcile the call — treating it as 'accepted' would
                # create a billed call with no linkage, so classify as permanent
                # failure instead.
                provider_call_id: str | None = None
                provider_call_id_field: str | None = None
                for _field in ("call_id", "conversation_id", "sip_call_id"):
                    _value = body.get(_field) or None
                    if _value:
                        provider_call_id = _value
                        provider_call_id_field = _field
                        break

                if not provider_call_id:
                    error_detail = (
                        "provider_response_missing_call_id: ElevenLabs returned 2xx "
                        "but no call_id / conversation_id / sip_call_id in response "
                        "body — cannot link to CallSession"
                    )
                    logger.error(
                        "elevenlabs_outbound_missing_call_id",
                        http_status=response.status_code,
                        response_keys=list(body.keys()),
                    )
                    return OutboundCallResult(
                        outcome="error",
                        error_detail=error_detail,
                        error_category="permanent",
                    )

                logger.info(
                    "elevenlabs_outbound_provider_call_id_resolved",
                    provider_call_id_field=provider_call_id_field,
                    has_conversation_id=bool(body.get("conversation_id")),
                )

                # Detect provider-reported no_answer before accepting.
                # ElevenLabs may return 2xx with a status field indicating the
                # call was placed but the lead did not pick up (ring timeout,
                # voicemail network response, etc.). These are not system errors
                # and must NOT be retried — they map to telephony_status='no_answer'.
                _NO_ANSWER_STATUSES = {"no_answer", "ring_timeout", "no_pickup"}
                provider_status: str = body.get("status", "")
                if provider_status.lower() in _NO_ANSWER_STATUSES:
                    error_detail = (
                        f"no_answer: provider reported status={provider_status!r} "
                        f"(lead did not pick up or ring timeout)"
                    )
                    logger.info(
                        "elevenlabs_outbound_no_answer",
                        provider_status=provider_status,
                        provider_call_id=provider_call_id,
                    )
                    return OutboundCallResult(
                        outcome="error",
                        error_detail=error_detail,
                        error_category="no_answer",
                    )

                return OutboundCallResult(
                    outcome="accepted",
                    provider_call_id=provider_call_id,
                    provider_metadata=body,
                )

            # Classify error category
            status_code = response.status_code
            error_detail = f"http_status={status_code}"

            if status_code == 429 or status_code >= 500:
                # 429 rate-limit and 5xx server errors → transient (retry eligible)
                logger.warning(
                    "elevenlabs_outbound_transient_error",
                    http_status=status_code,
                )
                return OutboundCallResult(
                    outcome="error",
                    error_detail=error_detail,
                    error_category="transient",
                )
            else:
                # 4xx (non-429) → permanent (do not retry)
                logger.error(
                    "elevenlabs_outbound_permanent_error",
                    http_status=status_code,
                )
                return OutboundCallResult(
                    outcome="error",
                    error_detail=error_detail,
                    error_category="permanent",
                )

        except httpx.ConnectTimeout as exc:
            # Connect timeout: the TCP/TLS connection was never established, so the
            # request body never reached ElevenLabs. No SIP call could have been
            # placed → safe to retry. Classify as transient (same as ConnectError).
            error_detail = f"network_error={type(exc).__name__}: {exc}"
            logger.error(
                "elevenlabs_outbound_network_error",
                error=str(exc),
                error_category="transient",
            )
            return OutboundCallResult(
                outcome="error",
                error_detail=error_detail,
                error_category="transient",
            )

        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            # Read/Write/Pool timeout: the request was (or may have been) fully sent
            # and we simply did not receive the response in time. ElevenLabs can
            # accept the request and start ringing a SIP call while the HTTP call
            # stays open past our timeout. The side effect is AMBIGUOUS — a real
            # call may already be in progress. Retrying here would place a SECOND
            # billed call (observed: two outbound SIP INVITEs to the same number).
            # Classify as 'unknown' so dial_outbound_call() does NOT retry; the
            # session is marked 'failed' pending reconciliation via webhook/sweep.
            error_detail = f"read_timeout={type(exc).__name__}: {exc}"
            logger.error(
                "elevenlabs_outbound_ambiguous_timeout",
                error=str(exc),
                error_category="unknown",
                note="request sent; provider may have placed the call — not retrying",
            )
            return OutboundCallResult(
                outcome="error",
                error_detail=error_detail,
                error_category="unknown",
            )

        except httpx.NetworkError as exc:
            # Non-timeout network errors (ConnectError, connection reset before send,
            # DNS failure). These generally mean the request did not reach the
            # provider → safe to retry. Classify as transient.
            error_detail = f"network_error={type(exc).__name__}: {exc}"
            logger.error(
                "elevenlabs_outbound_network_error",
                error=str(exc),
                error_category="transient",
            )
            return OutboundCallResult(
                outcome="error",
                error_detail=error_detail,
                error_category="transient",
            )

        except httpx.TimeoutException as exc:
            # Fallback for any other timeout subclass not caught above. Treat
            # conservatively as ambiguous (do not retry) — a timeout after send is
            # never safe to blindly retry for a side-effecting dial.
            error_detail = f"timeout={type(exc).__name__}: {exc}"
            logger.error(
                "elevenlabs_outbound_ambiguous_timeout",
                error=str(exc),
                error_category="unknown",
            )
            return OutboundCallResult(
                outcome="error",
                error_detail=error_detail,
                error_category="unknown",
            )

    # ---------------------------------------------------------------------------
    # C3 — Call SIP Observability API methods
    # ---------------------------------------------------------------------------

    async def list_recent_conversations(
        self,
        agent_id: str,
        time_window_seconds: int = 120,
    ) -> ConversationListResponse:
        """List recent conversations for an agent within a time window.

        GET /conversational_ai/conversations?agent_id={agent_id}

        Spec: call-sip-observability — Requirement: ElevenLabs API Client Methods.

        On HTTP 429: exponential backoff with at least one retry.
        On non-2xx (not 429): raises ElevenLabsAPIError.
        On timeout: raises httpx.TimeoutException (caller handles).

        Args:
            agent_id: ElevenLabs agent identifier to filter conversations.
            time_window_seconds: Time window in seconds to include (for caller context).

        Returns:
            ConversationListResponse with parsed ConversationSummary objects.

        Raises:
            ElevenLabsAPIError: On non-2xx HTTP response (after retries on 429).
        """
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key}
        url = f"{_ELEVENLABS_BASE_URL}/conversational_ai/conversations"
        params = {"agent_id": agent_id}

        response = await _get_with_429_backoff(
            url=url,
            headers=headers,
            params=params,
        )
        return ConversationListResponse(**response.json())

    async def get_conversation_detail(
        self,
        conversation_id: str,
    ) -> dict:
        """Get full detail for a specific ElevenLabs conversation.

        GET /conversational_ai/conversations/{conversation_id}

        Returns raw dict of safe fields. Callers extract what they need.

        Raises:
            ElevenLabsAPIError: On non-2xx response.
        """
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key}
        url = f"{_ELEVENLABS_BASE_URL}/conversational_ai/conversations/{conversation_id}"

        response = await _get_with_429_backoff(url=url, headers=headers)
        return response.json()

    async def get_sip_messages(
        self,
        conversation_id: str,
    ) -> SipMessagesResponse:
        """Get SIP message sequence for an ElevenLabs conversation.

        GET /conversational_ai/conversations/{conversation_id}/sip_messages

        Spec: call-sip-observability — SIP field extraction, allowlist only.
        The SipMessagesResponse Pydantic model enforces the allowlist —
        raw bodies and credential fields are never captured.

        Raises:
            ElevenLabsAPIError: On non-2xx response.
        """
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key}
        url = (
            f"{_ELEVENLABS_BASE_URL}/conversational_ai/conversations"
            f"/{conversation_id}/sip_messages"
        )

        response = await _get_with_429_backoff(url=url, headers=headers)
        return SipMessagesResponse(**response.json())

    async def get_sip_messages_by_phone(
        self,
        phone_number_id: str,
    ) -> SipMessagesResponse:
        """Get SIP messages by ElevenLabs phone number resource ID.

        GET /convai/phone_numbers/{phone_number_id}/sip_messages

        Fallback SIP lookup when conversation_id is not available.

        Raises:
            ElevenLabsAPIError: On non-2xx response.
        """
        api_key = self._settings.elevenlabs_api_key.get_secret_value()
        headers = {"xi-api-key": api_key}
        url = f"{_ELEVENLABS_BASE_URL}/convai/phone_numbers/{phone_number_id}/sip_messages"

        response = await _get_with_429_backoff(url=url, headers=headers)
        return SipMessagesResponse(**response.json())


# ---------------------------------------------------------------------------
# C3 — Shared HTTP helper with 429 backoff
# ---------------------------------------------------------------------------


class ElevenLabsAPIError(Exception):
    """Raised when ElevenLabs returns a non-2xx, non-429 response.

    Spec: call-sip-observability — Non-429 error — typed exception raised.

    Attributes:
        status_code: HTTP status code from the response.
        detail: Response body text for logging purposes (never contains credentials).
    """

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ElevenLabs API error {status_code}: {detail}")


_MAX_429_RETRIES = 3
_BACKOFF_BASE_SECONDS = 1.0


async def _get_with_429_backoff(
    url: str,
    headers: dict,
    params: dict | None = None,
) -> httpx.Response:
    """Execute GET request with exponential backoff on HTTP 429.

    Spec: call-sip-observability — Rate-limit — exponential backoff applied.

    Retries up to _MAX_429_RETRIES times on 429 with exponential delay.
    Raises ElevenLabsAPIError on non-2xx, non-429 response.
    Raises ElevenLabsAPIError after exhausting 429 retries.
    Propagates httpx.TimeoutException / httpx.NetworkError to the caller.

    Args:
        url: Full URL to GET.
        headers: Request headers (must include xi-api-key).
        params: Optional query parameters.

    Returns:
        httpx.Response on success (2xx).

    Raises:
        ElevenLabsAPIError: On non-2xx or exhausted 429 retries.
        httpx.TimeoutException: On request timeout (caller decides handling).
        httpx.NetworkError: On network failure (caller decides handling).
    """
    last_status: int | None = None

    # Open a single client outside the retry loop so 429 retries reuse the same
    # TCP connection instead of opening a new one per attempt.
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
        for attempt in range(_MAX_429_RETRIES + 1):
            response = await client.get(url, headers=headers, params=params)

            if response.is_success:
                return response

            if response.status_code == 429:
                last_status = 429
                if attempt < _MAX_429_RETRIES:
                    wait = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                    logger.warning(
                        "elevenlabs_api_rate_limited",
                        url=url,
                        attempt=attempt,
                        retry_after_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Exhausted retries
                raise ElevenLabsAPIError(
                    status_code=429,
                    detail=f"Rate limited after {_MAX_429_RETRIES} retries",
                )

            # Non-2xx, non-429 → raise typed error immediately
            raise ElevenLabsAPIError(
                status_code=response.status_code,
                detail=response.text[:200],  # Truncated — no credential leakage risk at this length
            )

    # Should never be reached, but satisfy type checkers
    raise ElevenLabsAPIError(status_code=last_status or 0, detail="Unexpected loop exit")


def _build_soft_timeout_payload(
    timeout_seconds: float | None,
    message: str | None,
    use_llm_generated_message: bool | None,
) -> dict:
    """Build the partial PATCH body for soft_timeout_config.

    Field names verified against real ElevenLabs API (2026-05-24):
    - timeout_seconds, message, use_llm_generated_message
    """
    config = SoftTimeoutConfig(
        timeout_seconds=timeout_seconds,
        message=message,
        use_llm_generated_message=use_llm_generated_message,
    )
    return config.to_patch_payload()


async def _patch_with_retry(
    url: str,
    payload: dict,
    headers: dict,
    elevenlabs_agent_id: str,
) -> SyncResult:
    """Execute PATCH with exactly one retry on 5xx or timeout.

    Returns SyncResult — never raises.
    """
    last_error: str | None = None

    for attempt in range(2):  # attempt 0, then attempt 1 (one retry)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.patch(url, json=payload, headers=headers)

            if response.is_success:
                return SyncResult(outcome="synced")

            # 5xx → retry; 4xx → do not retry (treat as error immediately)
            last_error = f"http_status={response.status_code}"
            if response.status_code < 500:
                # 4xx — no point retrying; log and return error immediately
                logger.error(
                    "elevenlabs_sync_failed",
                    http_status=response.status_code,
                    elevenlabs_agent_id=elevenlabs_agent_id,
                    attempt=attempt,
                )
                return SyncResult(outcome="error", error_detail=last_error)

            # 5xx — log and continue to retry (unless this was already the last attempt)
            logger.warning(
                "elevenlabs_sync_5xx",
                http_status=response.status_code,
                elevenlabs_agent_id=elevenlabs_agent_id,
                attempt=attempt,
            )

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = f"network_error={type(exc).__name__}: {exc}"
            logger.error(
                "elevenlabs_sync_error",
                error=str(exc),
                elevenlabs_agent_id=elevenlabs_agent_id,
                attempt=attempt,
            )
            # Do not retry on timeout/network error — return error immediately
            return SyncResult(outcome="error", error_detail=last_error)

    # Both 5xx attempts exhausted
    logger.error(
        "elevenlabs_sync_failed",
        http_status=last_error,
        elevenlabs_agent_id=elevenlabs_agent_id,
        attempt="final",
    )
    return SyncResult(outcome="error", error_detail=last_error)


# ---------------------------------------------------------------------------
# Background helper — called via asyncio.create_task from router
# ---------------------------------------------------------------------------


async def sync_to_elevenlabs(agent_id: str, settings) -> None:
    """Load agent from DB, call ElevenLabsService, update sync status.

    Uses its own DB session (independent of the request session which may be closed).
    Never raises — all errors are logged and written to elevenlabs_sync_status.

    Design: background_task_db_session — own session via get_session() context manager
    (same pattern as db_session() in webhook.py).
    """
    from app.core.database import async_session_factory
    from app.tenants.service import get_agent

    if async_session_factory is None:
        logger.error("sync_to_elevenlabs_no_db", agent_id=agent_id)
        return

    # Load agent with its own session
    async with async_session_factory() as session:
        agent = await get_agent(session, agent_id)
        if agent is None:
            logger.warning("sync_to_elevenlabs_agent_not_found", agent_id=agent_id)
            return

        service = ElevenLabsService(settings=settings)
        result = await service.sync_soft_timeout(agent)

        # Update sync status based on outcome
        if result.outcome == "synced":
            agent.elevenlabs_sync_status = "synced"
            agent.elevenlabs_last_synced_at = datetime.now(tz=timezone.utc)
            await session.commit()
        elif result.outcome == "error":
            agent.elevenlabs_sync_status = "error"
            await session.commit()
        # "skipped" → no update (status remains NULL or unchanged)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_elevenlabs_service(request) -> ElevenLabsService:
    """FastAPI dependency returning an ElevenLabsService from app settings."""
    return ElevenLabsService(settings=request.app.state.settings)
