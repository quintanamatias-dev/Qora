"""In-process cache + DB-backed read path for per-client CRM integration config.

IntegrationStore.get() replaces CRMConfigLoader's filesystem read with a
client_integrations row, returning the same CRMConfig shape readers already
consume (design.md P3-D5) so phase 4's reader cutover is mechanical. A
write-through cache keyed by (client_id, provider) plus a short TTL safety
net avoids a DB round-trip on every voice-turn read; invalidate() is called
by every write-path endpoint after a successful UPSERT.

API key resolution is NOT performed here — callers needing the literal
secret call CRMConfig.resolve_api_key_async() (or resolve_client_secret
directly) separately, on demand.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.crm_config import ConfigValidationError, CRMConfig
from app.tenants.models import ClientIntegration

_DEFAULT_TTL_SECONDS = 30.0


class IntegrationStore:
    """Single read path for per-client CRM config (P3-D5)."""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[CRMConfig, float]] = {}
        self._lock = threading.Lock()

    async def get(
        self, session: AsyncSession, client_id: str, provider: str = "airtable"
    ) -> CRMConfig | None:
        """Return the CRMConfig for (client_id, provider), cache-first.

        None when no row exists for this (client_id, provider) or the
        integration is disabled — the same semantics as a missing crm.yaml
        today.
        """
        cache_key = (client_id, provider)
        now = time.monotonic()

        with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            config, cached_at = cached
            if now - cached_at < self._ttl_seconds:
                return config

        config = await self._load_from_db(session, client_id, provider)

        # Cache misses too (negative cache): a client without a CRM must not
        # open a DB session on every voice turn. Writes call invalidate().
        with self._lock:
            self._cache[cache_key] = (config, now)

        return config

    def peek_cached(
        self, client_id: str, provider: str = "airtable"
    ) -> tuple[bool, CRMConfig | None]:
        """Return (hit, config) from the in-memory cache only — no DB access.

        Used by true hot-path callers (e.g. the per-turn voice webhook) that
        must not pay for a DB session open just to serve a cache hit. ``hit``
        is False on a cold cache or an expired TTL window; callers must then
        fall back to :meth:`get` with a real session.
        """
        cache_key = (client_id, provider)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
        if cached is None:
            return False, None
        config, cached_at = cached
        if now - cached_at >= self._ttl_seconds:
            return False, None
        return True, config

    def invalidate(self, client_id: str) -> None:
        """Drop every cached entry for this client, across all providers.

        Synchronous; called by every write-path endpoint after a successful
        UPSERT.
        """
        with self._lock:
            stale_keys = [key for key in self._cache if key[0] == client_id]
            for key in stale_keys:
                del self._cache[key]

    async def _load_from_db(
        self, session: AsyncSession, client_id: str, provider: str
    ) -> CRMConfig | None:
        result = await session.execute(
            select(ClientIntegration).where(
                ClientIntegration.client_id == client_id,
                ClientIntegration.provider == provider,
            )
        )
        row = result.scalar_one_or_none()
        if row is None or not row.enabled:
            return None

        payload = json.loads(row.config)
        payload.setdefault("provider", row.provider)
        payload.setdefault("enabled", row.enabled)

        try:
            return CRMConfig.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            raise ConfigValidationError(
                f"Invalid client_integrations config for client {client_id!r} "
                f"provider {provider!r}: {exc}"
            ) from exc


async def recompute_and_persist_status(
    session: AsyncSession, client_id: str, provider: str = "airtable"
) -> tuple[str, str | None]:
    """Compute and persist a client_integrations row's status (design.md's
    BOOT VALIDATION data flow, reused by every write-path endpoint).

    "disabled" when the row's enabled flag is False; otherwise "ok" when the
    integration's credential resolves (CRMConfig.resolve_api_key_async),
    "degraded" with a status_reason naming the unresolved credential when it
    does not. Returns (status, status_reason) for the caller to echo back
    without a second DB read; the row itself is updated in-place but NOT
    committed -- the caller's existing transaction controls the commit.
    """
    result = await session.execute(
        select(ClientIntegration).where(
            ClientIntegration.client_id == client_id,
            ClientIntegration.provider == provider,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return "disabled", None

    now = datetime.now(timezone.utc)

    if not row.enabled:
        row.status = "disabled"
        row.status_reason = None
        row.last_checked_at = now
        return row.status, row.status_reason

    payload = json.loads(row.config)
    payload.setdefault("provider", row.provider)
    payload.setdefault("enabled", row.enabled)
    config = CRMConfig.model_validate(payload)

    resolved = await config.resolve_api_key_async(session, client_id)
    if resolved is not None:
        row.status = "ok"
        row.status_reason = None
    else:
        credential_name = config.legacy_env_var_name or "api_key"
        row.status = "degraded"
        row.status_reason = f"Credential '{credential_name}' could not be resolved"
    row.last_checked_at = now

    return row.status, row.status_reason


_default_store: IntegrationStore | None = None


def get_default_store() -> IntegrationStore:
    """Return the process-wide IntegrationStore singleton readers should use."""
    global _default_store
    if _default_store is None:
        _default_store = IntegrationStore()
    return _default_store
