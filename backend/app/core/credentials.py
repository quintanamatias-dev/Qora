"""Centralized credential validation for Qora per-client integrations.

This module owns boot-time validation of tenant integration credentials —
the CRM secrets resolved via client_integrations/client_secrets (DB-backed,
client-integrations-secrets phase).

Design decisions:
  - Global Qora credentials (OPENAI_API_KEY, ELEVENLABS_API_KEY, QORA_API_KEY)
    are validated exclusively by Settings model_validator and keep their
    existing hard-fail (raise) behavior. They are NOT in scope here.
  - Per-client CRM credentials are validated here by recomputing every
    client_integrations row's status from the DB (design.md P3-D4) — no
    filesystem scanning, no sys.exit. A missing/invalid credential sets that
    row's status to degraded with a status_reason and logs at ERROR; startup
    continues regardless of any client's result, so one client's
    misconfiguration cannot take down every other client's calls.
  - The ALL_CAPS heuristic (shared with CRMConfig.resolve_api_key and
    resolve_client_secret) determines whether a secret name is an env var
    reference or a literal value. This module is the single source for that
    regex/helper (client-integrations-secrets task 7.1); other modules import
    it from here instead of redefining it.
  - Secret values are NEVER logged or included in error messages.

Spec reference:
  openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md
  openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
  openspec/changes/client-integrations-secrets/design.md — P3-D4
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------

# Keep this set in sync with _WEAK_PLACEHOLDERS in config.py.
# Source of truth: openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
WEAK_PLACEHOLDERS: frozenset[str] = frozenset({
    "change-me-before-production",
    "your-key-here",
    "todo",
    "replace_me",
    "xxx",
    "test",
    "changeme",
})

# ALL_CAPS_UNDERSCORES env var name pattern (mirrors CRMConfig heuristic).
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


def is_weak_placeholder(value: str) -> bool:
    """Return True if the value matches a known weak placeholder pattern.

    Comparison is case-insensitive. An empty string is NOT considered a
    placeholder — use a separate presence check before calling this.

    Args:
        value: The secret value to evaluate. Never logged.

    Returns:
        True if the value is a known placeholder; False otherwise.
    """
    return value.strip().lower() in WEAK_PLACEHOLDERS


def _looks_like_env_var_name(value: str) -> bool:
    """Return True if value matches the ALL_CAPS_UNDERSCORES env var name pattern."""
    return bool(_ENV_VAR_NAME_PATTERN.match(value))


# ---------------------------------------------------------------------------
# Boot validator (client-integrations-secrets P3-D4)
# ---------------------------------------------------------------------------


async def validate_all_integration_credentials(session: AsyncSession) -> None:
    """Recompute and persist every client_integrations row's status at boot.

    Replaces the former crm.yaml-scanning, sys.exit-on-missing-credential
    behavior: a missing/invalid per-client CRM credential sets that row's
    ``status`` to ``"degraded"`` with a ``status_reason`` naming the
    unresolved credential and logs at ERROR — it never calls ``sys.exit`` and
    never raises. Startup always continues once every row has been processed.

    Rows with ``enabled: false`` are set to ``"disabled"`` without an ERROR
    log (silently skipped, matching the previous behavior). Clients with no
    client_integrations row at all are never iterated (silently skipped).

    Qora-owned platform credentials (OPENAI_API_KEY, ELEVENLABS_API_KEY,
    QORA_API_KEY) are validated separately by ``Settings()``'s
    model_validator and keep their existing hard-fail (raise) behavior —
    this function does not touch them.

    Args:
        session: An active AsyncSession. This function commits the session
                 once every row has been processed.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.integrations.integration_store import recompute_and_persist_status  # noqa: PLC0415
    from app.tenants.models import ClientIntegration  # noqa: PLC0415

    result = await session.execute(select(ClientIntegration))
    rows = result.scalars().all()

    for row in rows:
        status, reason = await recompute_and_persist_status(session, row.client_id, row.provider)
        if status == "degraded":
            logger.error(
                "credentials: client integration degraded at boot",
                extra={"client_id": row.client_id, "provider": row.provider, "reason": reason},
            )

    await session.commit()

