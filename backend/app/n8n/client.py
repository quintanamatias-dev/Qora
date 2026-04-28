"""QORA n8n — Async HTTP client for firing webhook triggers to n8n.

Responsibilities:
- Build N8nTriggerPayload with session_id, client_id, and current UTC timestamp
- Sign the request body with HMAC-SHA256 using N8N_WEBHOOK_SECRET
- POST to N8N_WEBHOOK_URL with a 5-second timeout
- Swallow all errors (log warning, return None) — fire-and-forget
- No-op when N8N_ENABLED=False
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
import structlog

from app.n8n.schemas import N8nTriggerPayload

logger = structlog.get_logger(__name__)

_stdlib_logger = logging.getLogger(__name__)


def _get_settings():
    """Return application Settings instance.

    Extracted as a separate function so tests can patch it easily.
    """
    from app.core.config import Settings

    return Settings()


def _build_signature(secret: str, body_bytes: bytes) -> str:
    """Compute HMAC-SHA256 signature for the given body.

    Args:
        secret: The webhook secret key (plaintext).
        body_bytes: Raw request body bytes to sign.

    Returns:
        Hex-encoded HMAC-SHA256 digest.
    """
    return hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()


async def trigger_n8n_webhook(session_id: str, client_id: str) -> None:
    """Fire-and-forget POST to the n8n webhook trigger URL.

    When N8N_ENABLED=False, returns immediately without making any HTTP call.
    On success (2xx), returns None silently.
    On non-2xx or network error: logs a warning and returns None.
    MUST NOT raise — any exception is caught and logged.

    Args:
        session_id: UUID of the call session to analyze.
        client_id: UUID of the client (for extraction config lookup in n8n).
    """
    settings = _get_settings()

    # Feature flag — zero-impact when disabled
    if not settings.n8n_enabled:
        return None

    # Build payload
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = N8nTriggerPayload(
        session_id=session_id,
        client_id=client_id,
        timestamp=timestamp,
    )
    body_bytes = json.dumps(payload.model_dump()).encode("utf-8")

    # Compute HMAC signature for outbound authentication
    secret = settings.n8n_webhook_secret.get_secret_value()
    signature = _build_signature(secret, body_bytes)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.n8n_webhook_url,
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                },
                timeout=settings.n8n_timeout_seconds,
            )
        if not response.is_success:
            logger.warning(
                "n8n_webhook_non_2xx",
                session_id=session_id,
                status_code=response.status_code,
                url=settings.n8n_webhook_url,
            )
    except Exception as exc:
        logger.warning(
            "n8n_webhook_error",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
            url=settings.n8n_webhook_url,
        )

    return None
