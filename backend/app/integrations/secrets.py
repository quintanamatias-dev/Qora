"""Secret resolution for per-client integration credentials (client-integrations-secrets, P3-D3).

resolve_client_secret implements the transitional DB -> env -> None order:
an encrypted client_secrets row (decrypted via the configured master key)
takes precedence over the legacy environment variable fallback. Never
raises on a missing/undecryptable secret or an absent master key \u2014 callers
(IntegrationStore, dispatcher) are responsible for handling a None result,
e.g. by marking the integration degraded. No secret value is ever logged.
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credentials import _looks_like_env_var_name
from app.core.crypto import get_secret_crypto
from app.tenants.models import ClientSecret

logger = logging.getLogger(__name__)


async def resolve_client_secret(session: AsyncSession, client_id: str, name: str) -> str | None:
    """Resolve a client's secret value: DB (decrypted) -> legacy env var -> None.

    `name` serves double duty: it is the `client_secrets.name` lookup key, and
    — when no DB row resolves it — it is checked against the ALL_CAPS
    env-var-name pattern and looked up directly in os.environ. Callers pass
    an integration's `legacy_env_var_name` (or any other secret name sharing
    this convention) as `name` to get both resolution paths.

    When QORA_SECRETS_MASTER_KEY is not configured, the DB step is skipped
    entirely and resolution falls straight to the env var.
    """
    crypto = get_secret_crypto()
    if crypto is not None:
        result = await session.execute(
            select(ClientSecret).where(
                ClientSecret.client_id == client_id, ClientSecret.name == name
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            try:
                return crypto.decrypt(row.ciphertext)
            except InvalidToken:
                logger.warning(
                    "resolve_client_secret: stored secret failed to decrypt, "
                    "falling back to env var",
                    extra={"client_id": client_id, "secret_name": name},
                )

    if _looks_like_env_var_name(name):
        value = os.environ.get(name)
        if value is not None:
            logger.warning(
                "resolve_client_secret: resolved via legacy env var fallback",
                extra={"client_id": client_id, "secret_name": name},
            )
            return value

    return None
