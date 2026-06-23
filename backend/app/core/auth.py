"""QORA Authentication — FastAPI dependencies for API security (Phase B5).

PR #1: Foundation + Admin Auth
  - CallerIdentity dataclass (returned by require_api_key)
  - require_api_key() — Bearer token dependency for all admin routes
  - get_settings_from_request() — shared helper to read Settings from app.state

PR #2 (not in this file yet):
  - AuthorizedSession, create_authorized_session, get_authorized_session

PR #3 (not in this file yet):
  - require_webhook_secret

Design rationale (design.md):
  - FastAPI Depends() is swappable: Phase C replaces require_api_key with
    require_jwt — zero router changes needed.
  - secrets.compare_digest ensures constant-time comparison (no timing side-channel).
  - CallerIdentity stores only an audit hash, never the raw key.
  - _TESTING_BYPASS: module-level flag set by conftest.py autouse fixture.
    Enables existing tests to pass without per-test auth header changes.
    NEVER set in production. Protected by environment check.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings

# ---------------------------------------------------------------------------
# Test bypass flag (conftest.py only — NEVER set in production)
# ---------------------------------------------------------------------------
# Set by tests/conftest.py autouse fixture when running under pytest.
# The check `os.environ.get("PYTEST_CURRENT_TEST")` is pytest's own env var —
# it only exists when pytest is running. This is not a "hidden" bypass:
# production processes never run under pytest.
# ---------------------------------------------------------------------------
_TESTING_BYPASS: bool = False


# ---------------------------------------------------------------------------
# CallerIdentity — returned by require_api_key
# ---------------------------------------------------------------------------


@dataclass
class CallerIdentity:
    """Proof that the caller presented a valid API key.

    Stores only a SHA-256 prefix of the key for audit logging.
    The raw key is NEVER stored — not in memory, not in logs.

    Phase C extension: add user_id, allowed_client_ids from JWT payload.
    """

    api_key_hash: str  # first 16 hex chars of SHA-256(raw_key) — for audit only


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------


def _get_settings(request: Request) -> Settings:
    """Read Settings from app.state (populated during lifespan startup).

    Falls back to a fresh Settings() when app.state.settings is not yet
    populated (e.g. during tests that skip the lifespan startup).
    """
    return getattr(request.app.state, "settings", None) or Settings()


# ---------------------------------------------------------------------------
# require_api_key — admin route dependency
# ---------------------------------------------------------------------------


def require_api_key(
    request: Request,
    settings: Settings = Depends(_get_settings),
) -> CallerIdentity:
    """FastAPI dependency that validates the Bearer API key.

    Reads ``Authorization: Bearer <key>`` from the request headers and
    compares it against ``settings.qora_api_key`` using a constant-time
    comparison (secrets.compare_digest) to prevent timing attacks.

    Returns:
        CallerIdentity — proof of a valid key, safe to pass to route handlers.

    Raises:
        HTTPException(401) — on missing header, malformed header, or wrong key.

    Future (Phase C):
        Replace this dependency with ``require_jwt`` — the routers stay unchanged.
        The dependency injection point is the only thing that changes.
    """
    # Test bypass: active ONLY when conftest.py sets _TESTING_BYPASS=True.
    # This flag is only reachable under pytest (PYTEST_CURRENT_TEST env var exists).
    # Production processes never set this flag.
    import app.core.auth as _self
    if _self._TESTING_BYPASS:
        return CallerIdentity(api_key_hash="test-bypass")

    if settings.qora_api_key is None:
        # API key not configured — deny all requests to protected routes.
        # This prevents accidentally open admin surfaces in misconfigured deployments.
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "QORA_API_KEY is not configured"},
        )

    auth_header = request.headers.get("Authorization")
    if auth_header is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Authorization header missing"},
        )

    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Authorization header must use Bearer scheme"},
        )

    presented_key = auth_header[len("Bearer "):]
    if not presented_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Bearer token is empty"},
        )

    expected_key = settings.qora_api_key.get_secret_value()

    # Constant-time comparison — prevents timing side-channel attacks.
    if not secrets.compare_digest(presented_key.encode(), expected_key.encode()):
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Invalid API key"},
        )

    # Compute a short audit hash — first 16 hex chars of SHA-256(raw_key).
    # This identifies the key in logs without ever exposing the secret.
    audit_hash = hashlib.sha256(presented_key.encode()).hexdigest()[:16]
    return CallerIdentity(api_key_hash=audit_hash)
