"""QORA Authentication — FastAPI dependencies for API security (Phase B5).

PR #1: Foundation + Admin Auth
  - CallerIdentity dataclass (returned by require_api_key)
  - require_api_key() — Bearer token dependency for all admin routes
  - get_settings_from_request() — shared helper to read Settings from app.state

PR #2: Session Auth + Demo + Tool Scope
  - AuthorizedSession dataclass (per-call auth context, cached in session_store)
  - create_authorized_session() — factory; assigns scopes based on is_demo
  - get_authorized_session() — FastAPI dep for custom-LLM hot path (zero DB)

PR #3: Webhook Auth + CORS
  - require_webhook_secret() — optional X-Webhook-Secret dep for voice endpoints
    Disabled by default (QORA_WEBHOOK_AUTH_ENABLED=false).
    When enabled, validates X-Webhook-Secret header via constant-time comparison.

Design rationale (design.md):
  - FastAPI Depends() is swappable: Phase C replaces require_api_key with
    require_jwt — zero router changes needed.
  - secrets.compare_digest ensures constant-time comparison (no timing side-channel).
  - CallerIdentity stores only an audit hash, never the raw key.
  - AuthorizedSession is composed with ConversationState — same session_store,
    same composite key (client_id, conversation_id) — zero dual-lookup on hot path.
  - _TESTING_BYPASS: module-level flag set by conftest.py autouse fixture.
    Enables existing tests to pass without per-test auth header changes.
    NEVER set in production. Protected by environment check.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Literal

from fastapi import Body, Depends, HTTPException, Request

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


PrincipalRole = Literal["superadmin", "client"]
_PRINCIPAL_ROLES: frozenset[str] = frozenset({"superadmin", "client"})


@dataclass(frozen=True)
class CallerIdentity:
    """Authenticated principal for admin routes.

    Stores only a SHA-256 prefix of the credential for audit logging.
    The raw key is NEVER stored — not in memory, not in logs.

    Roles:
        superadmin — Qora operator; may access every tenant. The global
            QORA_API_KEY always resolves to this role.
        client — tenant user; may access only the tenants in ``client_ids``.
            Issued by the future user-auth layer (multi-tenant-auth).

    Routers never inspect the role directly: they depend on
    ``app.core.access.require_client_access`` / ``require_superadmin``.
    """

    api_key_hash: str  # first 16 hex chars of SHA-256(raw_key) — for audit only
    role: PrincipalRole = "superadmin"
    client_ids: frozenset[str] = frozenset()
    auth_method: Literal["api_key", "session"] = "api_key"
    email: str | None = None

    def __post_init__(self) -> None:
        if self.role not in _PRINCIPAL_ROLES:
            raise ValueError(f"Unknown principal role: {self.role!r}")
        # Normalise tenant ids once so every comparison is case-insensitive.
        object.__setattr__(self, "client_ids", frozenset(c.lower() for c in self.client_ids))

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    def can_access(self, client_id: str | None) -> bool:
        """Return True when this principal may read or write ``client_id`` data."""
        if self.is_superadmin:
            return True
        if not client_id:
            return False
        return client_id.lower() in self.client_ids


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


#: Cookie name for the opaque Qora session token (design.md §5).
SESSION_COOKIE_NAME = "qora_session"

#: Methods that mutate state and therefore require the CSRF header when
#: authenticated via the session cookie (design.md §6).
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _get_db_session():
    """FastAPI dependency that yields an async DB session for require_api_key.

    Wraps ``app.core.database.get_session`` (an ``@asynccontextmanager``) as an
    async-generator dependency so it is overridable via
    ``app.dependency_overrides`` the same way every router's local
    ``get_db_session`` helper is (see app/clients/router.py).

    Yields ``None`` when the DB engine has not been initialized (e.g. tests
    that build the app without running the lifespan). This dependency is only
    ever used by the session-cookie branch of ``require_api_key``, which is
    unreachable without a ``qora_session`` cookie — so an uninitialized DB
    never breaks the Bearer API-key path.
    """
    from app.core import database as db_module

    if db_module.async_session_factory is None:
        yield None
        return

    async with db_module.get_session() as session:
        yield session


async def require_api_key(
    request: Request,
    settings: Settings = Depends(_get_settings),
    db=Depends(_get_db_session),
) -> CallerIdentity:
    """FastAPI dependency that authenticates the caller (design.md §6).

    Order:
      1. _TESTING_BYPASS → superadmin (unchanged).
      2. Authorization header present → Bearer API-key check (unchanged, 401
         on any problem). Returns auth_method="api_key".
      3. Else qora_session cookie present → look up the session; missing,
         expired or revoked → 401. For unsafe methods, the X-Qora-Client:
         web header is required → 403 csrf_check_failed otherwise.
      4. Else → 401 authentication_required.

    Returns:
        CallerIdentity — proof of a valid credential, safe to pass to route handlers.

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

    auth_header = request.headers.get("Authorization")
    if auth_header is not None:
        return _require_bearer_api_key(auth_header, settings)

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        return await _require_session_cookie(request, db, session_token)

    raise HTTPException(
        status_code=401,
        detail={"error": "authentication_required", "message": "Authentication required"},
    )


def _require_bearer_api_key(auth_header: str, settings: Settings) -> CallerIdentity:
    """Bearer API-key check — unchanged behaviour from the pre-session dependency."""
    if settings.qora_api_key is None:
        # API key not configured — deny all requests to protected routes.
        # This prevents accidentally open admin surfaces in misconfigured deployments.
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "QORA_API_KEY is not configured"},
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
    return CallerIdentity(api_key_hash=audit_hash, auth_method="api_key")


async def _require_session_cookie(request: Request, db, session_token: str) -> CallerIdentity:
    """Cookie-based session check + CSRF header enforcement (design.md §6)."""
    import json

    from app.auth.sessions import lookup_session

    session_row = await lookup_session(db, session_token) if db is not None else None
    if session_row is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Session expired or invalid"},
        )

    if request.method in _UNSAFE_METHODS and request.headers.get("X-Qora-Client") != "web":
        raise HTTPException(
            status_code=403,
            detail={"error": "csrf_check_failed", "message": "Missing X-Qora-Client header"},
        )

    client_ids: frozenset[str] = frozenset(json.loads(session_row.client_ids))
    return CallerIdentity(
        api_key_hash=f"session:{session_row.id[:8]}",
        role=session_row.role,  # type: ignore[arg-type]
        client_ids=client_ids,
        auth_method="session",
        email=session_row.email,
    )


# ---------------------------------------------------------------------------
# AuthorizedSession — per-call auth context (PR #2)
# ---------------------------------------------------------------------------
# Design: composed with ConversationState via ConversationState.auth field.
# Keyed by (client_id, conversation_id) in session_store — zero dual-lookup.
# Created ONCE at session start (initiation webhook or demo session open).
# Read from session_store on every subsequent turn — ZERO DB / network calls.
# ---------------------------------------------------------------------------

#: Scopes granted to all sessions (demo and production).
#: "admin:write" and "admin:read" are intentionally NOT listed here.
_PIPELINE_SCOPES: frozenset[str] = frozenset({"pipeline:write", "pipeline:read"})


@dataclass
class AuthorizedSession:
    """Cached auth context for one voice call/session.

    Created once at session start. Read from session_store on every subsequent
    turn — zero DB or network calls per turn (mandatory fast path).

    Attributes:
        client_id: Tenant identifier. Must match every tool call's client_id.
        agent_id: Optional agent UUID.
        agent_slug: Optional agent slug (for skill routing).
        lead_id: Optional lead UUID — scope boundary for tool calls.
        session_id: call_sessions.id in SQLite.
        scopes: Frozenset of granted permission strings.
            - "pipeline:write" — transcript, call session, captured data, post-call
            - "pipeline:read"  — read own tenant data
            - "admin:write"    — create/update/delete clients, agents, leads (NOT demo)
            - "admin:read"     — list clients, agents, leads (NOT demo)
        is_demo: True when the session was started from the /demo button flow.
            Demo sessions never receive admin:write or admin:read.
        created_at: Monotonic timestamp of session creation (for TTL enforcement).
    """

    client_id: str
    agent_id: str | None
    agent_slug: str | None
    lead_id: str | None
    session_id: str
    scopes: frozenset[str]
    is_demo: bool = False
    created_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# create_authorized_session — factory
# ---------------------------------------------------------------------------


def create_authorized_session(
    client_id: str,
    agent_id: str | None,
    lead_id: str | None,
    session_id: str,
    *,
    is_demo: bool = False,
    agent_slug: str | None = None,
) -> AuthorizedSession:
    """Create an AuthorizedSession with scopes derived from is_demo.

    Args:
        client_id: Tenant identifier.
        agent_id: Agent UUID (may be None for legacy callers).
        lead_id: Lead UUID being called (may be None if unknown at session start).
        session_id: call_sessions.id — may be empty string when not yet persisted.
        is_demo: When True, restricts scopes to pipeline only (no admin).
        agent_slug: Optional agent slug for skill routing.

    Returns:
        AuthorizedSession with appropriate scopes.

    Note:
        Both demo and production sessions receive pipeline:write + pipeline:read.
        Demo sessions NEVER receive admin:write or admin:read — this is the
        hard security boundary protecting tenant data from demo access.
    """
    return AuthorizedSession(
        client_id=client_id,
        agent_id=agent_id,
        agent_slug=agent_slug,
        lead_id=lead_id,
        session_id=session_id,
        scopes=_PIPELINE_SCOPES,  # same for demo and production
        is_demo=is_demo,
    )


# ---------------------------------------------------------------------------
# get_authorized_session — FastAPI dependency for custom-LLM hot path
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# require_webhook_secret — optional voice endpoint dependency (PR #3)
# ---------------------------------------------------------------------------


def require_webhook_secret(
    request: Request,
    settings: Settings = Depends(_get_settings),
) -> None:
    """FastAPI dependency that optionally validates ElevenLabs webhook secret.

    Disabled by default (QORA_WEBHOOK_AUTH_ENABLED=false) so that existing
    ElevenLabs agents continue to work without any reconfiguration.

    When QORA_WEBHOOK_AUTH_ENABLED=true:
    - Reads the ``X-Webhook-Secret`` header from the incoming request.
    - Falls back to ``Authorization: Bearer <token>`` if X-Webhook-Secret is
      absent (ElevenLabs Custom LLM sends the API key this way).
    - Compares it against ``settings.qora_webhook_secret`` using constant-time
      comparison (secrets.compare_digest) to prevent timing attacks.
    - Returns 401 when both headers are missing, the value is wrong, or the
      secret is not configured (fail-closed: enabled + unconfigured → deny all).

    ElevenLabs sends this header on every webhook call when configured in their
    dashboard. See: https://elevenlabs.io/docs/conversational-ai/customization/security

    Rollout:
    1. Set QORA_WEBHOOK_SECRET=<strong-random-value> in .env.
    2. Paste the same value into the ElevenLabs agent's "Webhook secret" field.
    3. Set QORA_WEBHOOK_AUTH_ENABLED=true.
    4. Restart backend. Existing agents with the secret configured will continue
       to work; agents without the secret will start returning 401.

    Returns:
        None — dependency succeeds silently when auth passes or is disabled.

    Raises:
        HTTPException(401) — when enabled and the header is missing or wrong.
    """
    if not settings.qora_webhook_auth_enabled:
        # Auth disabled (default) — no-op. Existing ElevenLabs agents unaffected.
        return None

    # Auth is enabled. Fail-closed: no configured secret → deny all requests.
    if settings.qora_webhook_secret is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_misconfigured",
                "message": (
                    "QORA_WEBHOOK_AUTH_ENABLED=true but QORA_WEBHOOK_SECRET is not configured. "
                    "Set QORA_WEBHOOK_SECRET to enable webhook authentication."
                ),
            },
        )

    # ElevenLabs sends secrets via two different mechanisms:
    # - Webhooks (post-call, initiation): X-Webhook-Secret header
    # - Custom LLM: Authorization: Bearer <api_key>
    # Accept either so the same dependency works for all ElevenLabs endpoints.
    presented_secret = request.headers.get("X-Webhook-Secret")
    if presented_secret is None:
        # Fallback: check Authorization: Bearer <token> (Custom LLM path)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            presented_secret = auth_header.removeprefix("Bearer ").strip()
    if presented_secret is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_required",
                "message": (
                    "X-Webhook-Secret header or Authorization: Bearer token "
                    "is required when webhook auth is enabled"
                ),
            },
        )

    expected_secret = settings.qora_webhook_secret.get_secret_value()

    # Constant-time comparison — prevents timing side-channel attacks.
    if not secrets.compare_digest(presented_secret.encode(), expected_secret.encode()):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_failed",
                "message": "Invalid webhook secret",
            },
        )

    return None


# ---------------------------------------------------------------------------
# require_elevenlabs_webhook_signature — HMAC auth for post-call webhook
# ---------------------------------------------------------------------------


async def require_elevenlabs_webhook_signature(
    request: Request,
    settings: Settings = Depends(_get_settings),
) -> None:
    """FastAPI dependency that validates ElevenLabs HMAC webhook signatures.

    ElevenLabs post-call webhooks use HMAC-SHA256 authentication, NOT plain
    text secrets. The signature is sent in the ``ElevenLabs-Signature`` header
    with the format: ``v0=<hmac-sha256-hex>,t=<unix-timestamp>``.

    The HMAC is computed over: ``{timestamp}.{raw_body}``
    using ``QORA_WEBHOOK_SECRET`` as the HMAC key.

    This is fundamentally different from ``require_webhook_secret`` (which
    does plain-text comparison against ``X-Webhook-Secret`` / Bearer). Using
    the wrong dependency on the post-call endpoint causes 401 on every webhook
    call because the plain-text comparison always fails against an HMAC value.

    When ``QORA_WEBHOOK_AUTH_ENABLED=false``, this dependency is a no-op
    (same behavior as require_webhook_secret for operational consistency).

    Fallback: if the ``ElevenLabs-Signature`` header is absent but
    ``X-Webhook-Secret`` is present, falls back to plain-text comparison for
    backward compatibility during migration.

    Returns:
        None — dependency succeeds silently when auth passes or is disabled.

    Raises:
        HTTPException(401) — when enabled and the signature is missing, invalid,
            or the HMAC does not match.
    """
    if not settings.qora_webhook_auth_enabled:
        return None

    # Fail-closed: auth enabled but secret not configured → deny all.
    if settings.qora_webhook_secret is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_misconfigured",
                "message": (
                    "QORA_WEBHOOK_AUTH_ENABLED=true but QORA_WEBHOOK_SECRET is not configured. "
                    "Set QORA_WEBHOOK_SECRET to enable webhook authentication."
                ),
            },
        )

    expected_secret = settings.qora_webhook_secret.get_secret_value()

    # Check for ElevenLabs-Signature header (HMAC path)
    sig_header = request.headers.get("ElevenLabs-Signature") or request.headers.get(
        "elevenlabs-signature"
    )

    if sig_header is None:
        # Fallback: plain X-Webhook-Secret for backward compatibility.
        presented_secret = request.headers.get("X-Webhook-Secret")
        if presented_secret is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "webhook_auth_required",
                    "message": (
                        "ElevenLabs-Signature header or X-Webhook-Secret header "
                        "is required when webhook auth is enabled"
                    ),
                },
            )
        # Plain-text comparison fallback
        if not secrets.compare_digest(presented_secret.encode(), expected_secret.encode()):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "webhook_auth_failed",
                    "message": "Invalid webhook secret",
                },
            )
        return None

    # Parse the ElevenLabs-Signature header.
    # Expected format: "v0=<hex>,t=<timestamp>" (fields may be in any order,
    # separated by commas).
    v0_hash: str | None = None
    timestamp: str | None = None
    for part in sig_header.split(","):
        part = part.strip()
        if part.startswith("v0="):
            v0_hash = part[3:]
        elif part.startswith("t="):
            timestamp = part[2:]

    if v0_hash is None or timestamp is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_failed",
                "message": (
                    "ElevenLabs-Signature header format is invalid. "
                    "Expected: v0=<hmac-sha256>,t=<timestamp>"
                ),
            },
        )

    # Read raw body for HMAC computation.
    # FastAPI has already cached the body in request._body when the endpoint
    # declared a Pydantic body parameter (via Request.body() caching).
    # We explicitly call request.body() here which returns the cached bytes.
    try:
        raw_body = await request.body()
    except Exception:
        raw_body = b""

    # Compute HMAC-SHA256 of "{timestamp}.{raw_body}"
    message = f"{timestamp}.".encode() + raw_body
    computed = _hmac.new(
        expected_secret.encode(),
        message,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks.
    if not secrets.compare_digest(computed, v0_hash):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "webhook_auth_failed",
                "message": "Invalid ElevenLabs webhook signature",
            },
        )

    return None


def get_authorized_session(
    client_id: str,
    conversation_id: str,
    request: Request,
) -> AuthorizedSession:
    """FastAPI dependency for the per-turn custom-LLM hot path.

    Reads the AuthorizedSession from the in-memory session_store.
    ZERO DB or network calls — this is the mandatory fast path.

    Args:
        client_id: Tenant identifier (from URL path).
        conversation_id: ElevenLabs conversation ID (from request body).
        request: FastAPI Request (unused but required by Depends pattern).

    Returns:
        AuthorizedSession for this call.

    Raises:
        HTTPException(401): When no session is found or session has no auth.
    """
    from app.voice.session import session_store

    state = session_store.get((client_id, conversation_id))
    if state is None or state.auth is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "session_not_found",
                "message": (
                    "No authorized session found for this conversation. "
                    "Session may have expired or was never established."
                ),
            },
        )
    return state.auth
