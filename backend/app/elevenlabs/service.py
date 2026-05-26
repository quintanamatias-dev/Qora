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

from app.core.logging import get_logger
from app.elevenlabs.models import SoftTimeoutConfig, SyncResult  # noqa: F401 — re-exported

logger = get_logger(__name__)

_ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
_REQUEST_TIMEOUT_SECONDS = 10.0


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
