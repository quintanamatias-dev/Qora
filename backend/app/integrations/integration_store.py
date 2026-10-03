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

        with self._lock:
            if config is not None:
                self._cache[cache_key] = (config, now)
            else:
                self._cache.pop(cache_key, None)

        return config

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


_default_store: IntegrationStore | None = None


def get_default_store() -> IntegrationStore:
    """Return the process-wide IntegrationStore singleton readers should use."""
    global _default_store
    if _default_store is None:
        _default_store = IntegrationStore()
    return _default_store
