"""QORA — Observability: correlation middleware, canonical error handlers, Sentry.

This module is the single boundary concern module for B9 structured logging
and error monitoring. It is registered in main.py and provides:

  - CorrelationMiddleware: raw ASGI middleware that generates a UUID4
    request_id, binds it to structlog contextvars, and returns it as the
    X-Request-ID response header. Uses raw ASGI (not BaseHTTPMiddleware) so
    that contextvars survive StreamingResponse / SSE generators.

  - ErrorDetail / ErrorResponse: canonical Pydantic models for the unified
    error envelope {"error": {"code", "message", "request_id"}}.

  - handle_exception: global handler for unhandled Exception → 500.
  - handle_http_exception: global handler for HTTPException → canonical envelope.
  - handle_validation_error: global handler for RequestValidationError → 422.

  - init_sentry: initialize optional Sentry SDK in lifespan (env-gated on SENTRY_DSN).
  - sentry_before_send: PII filter registered as before_send callback.

Design: openspec/changes/phase-b-structured-logging-error-monitoring/design.md
Spec:   observability-correlation/spec.md, observability-error-handling/spec.md
        observability-sentry/spec.md
"""

from __future__ import annotations

import contextvars
import re
import uuid
from typing import Any, Callable

import sentry_sdk
import structlog
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# PII patterns for Sentry before_send filter
# ---------------------------------------------------------------------------

# Sensitive key names: any field whose key contains these substrings must be redacted.
_PII_KEY_PATTERNS: frozenset[str] = frozenset(
    {"key", "token", "secret", "password", "dsn"}
)

# E.164 phone number pattern (e.g. +15551234567)
_PHONE_PATTERN = re.compile(r"\+\d{7,15}")

# Sensitive content field names: transcripts and raw content bodies.
_CONTENT_KEY_PATTERNS: frozenset[str] = frozenset({"transcript", "content"})

# Sensitive HTTP header names: matched case-insensitively by EXACT name.
# These carry auth material or session identity and must always be redacted
# regardless of value, before any event leaves the process.
_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "xi-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-elevenlabs-signature",
    }
)

_REDACTED = "[REDACTED]"

# request.data may carry raw request bodies (JSON strings, transcripts, form
# payloads) of arbitrary type. We never attempt to selectively scrub it — any
# present value is replaced wholesale with this sentinel.
_FILTERED = "[Filtered]"


def _scrub_value(key: str, value: Any) -> Any:
    """Scrub a single value based on its parent key name.

    Returns _REDACTED if the key name matches a PII pattern,
    otherwise recursively scrubs nested dicts/lists and applies
    phone number redaction to string values.
    """
    key_lower = key.lower()

    # Redact by key name (API keys, tokens, secrets, passwords, DSNs, transcripts, content)
    if any(pattern in key_lower for pattern in _PII_KEY_PATTERNS):
        return _REDACTED
    if any(pattern in key_lower for pattern in _CONTENT_KEY_PATTERNS):
        return _REDACTED

    # Recursively scrub nested structures
    if isinstance(value, dict):
        return {k: _scrub_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(key, item) for item in value]

    # Redact E.164 phone numbers in string values
    if isinstance(value, str):
        return _PHONE_PATTERN.sub(_REDACTED, value)

    return value


def _scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub all fields in a dict for PII."""
    return {k: _scrub_value(k, v) for k, v in data.items()}


def _scrub_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive HTTP headers by exact (case-insensitive) name.

    Auth-bearing headers (Authorization, Cookie, Set-Cookie, X-API-Key,
    XI-API-Key, etc.) are replaced with _REDACTED wholesale. Remaining headers
    still pass through the generic PII scrubber so phone numbers / token-like
    key names are caught as well.
    """
    scrubbed: dict[str, Any] = {}
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() in _SENSITIVE_HEADERS:
            scrubbed[name] = _REDACTED
        else:
            scrubbed[name] = _scrub_value(str(name), value)
    return scrubbed


def sentry_before_send(event: dict, hint: dict) -> dict | None:
    """Sentry before_send PII filter — scrubs events before transmission.

    Spec: observability-sentry — Requirement: PII Filter via before_send
      - Redacts API keys, tokens, secrets, passwords, DSNs in field names
      - Redacts E.164 phone numbers in field values
      - Redacts transcript/content fields
      - Redacts auth-bearing HTTP headers (Authorization, Cookie, Set-Cookie,
        X-API-Key, XI-API-Key, ...) by exact name
      - Replaces request.data wholesale with [Filtered] (raw bodies are never
        known-safe — they may carry transcripts, credentials, or PII of any type)
      - Returns None (drops event) if scrubbing itself fails (defense in depth)

    Design decision: best-effort recursive scrubber. On any exception during
    scrubbing, the entire event is dropped (None return) rather than
    transmitting a potentially partially-scrubbed or raw event.
    """
    try:
        if "extra" in event:
            event["extra"] = _scrub_dict(event["extra"])
        if "contexts" in event:
            event["contexts"] = _scrub_dict(event["contexts"])
        if "request" in event:
            request_data = event["request"]
            if isinstance(request_data, dict):
                # Raw request bodies are never known-safe: a JSON string body,
                # form payload, or transcript can carry credentials or PII of
                # any type. Replace any present request.data wholesale rather
                # than attempting selective scrubbing.
                if "data" in request_data:
                    request_data["data"] = _FILTERED
                if "headers" in request_data and isinstance(
                    request_data["headers"], dict
                ):
                    request_data["headers"] = _scrub_headers(request_data["headers"])
        if "user" in event and isinstance(event["user"], dict):
            event["user"] = _scrub_dict(event["user"])
        return event
    except Exception:
        # Defense in depth: drop the event rather than risk transmitting raw PII.
        logger.warning(
            "sentry_before_send_scrub_failed_dropping_event",
            exc_info=True,
        )
        return None


def init_sentry(dsn: str | None) -> None:
    """Initialize the Sentry SDK when a non-empty DSN is provided.

    Spec: observability-sentry — Requirement: Optional Sentry Initialization
      - Called in the application lifespan after settings are loaded.
      - No-op when DSN is None, empty, or whitespace-only.
      - Registers FastApiIntegration + StarletteIntegration.
      - Registers sentry_before_send as the before_send PII filter.
      - Logs confirmation WITHOUT including the DSN value.
      - Never aborts startup: an invalid DSN (e.g. malformed URL) is caught and
        logged WITHOUT the DSN value; the app continues with Sentry disabled.

    Design decision #5: lifespan placement — called after Settings load,
    before DB init so that DB init errors are captured if Sentry is active.
    """
    if not dsn or not dsn.strip():
        return

    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            before_send=sentry_before_send,
            # Disable automatic performance tracing — we only want error capture.
            traces_sample_rate=0.0,
            # Do not send PII (usernames, IPs) automatically.
            send_default_pii=False,
        )
    except Exception as exc:
        # Sentry is OPTIONAL: a misconfigured DSN must never take down the
        # service. Log the failure type WITHOUT the DSN value (it can embed a
        # secret key) and continue with Sentry disabled.
        logger.warning(
            "sentry_init_failed_continuing_disabled",
            error_type=type(exc).__name__,
        )
        return

    logger.info("sentry_initialized", dsn_configured=True)


# ---------------------------------------------------------------------------
# Canonical error models
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """Inner envelope for every error response.

    Spec: Canonical Error Response Schema
        code:        Machine-readable string (internal_error | http_error | validation_error)
        message:     Human-readable; never a stack trace
        request_id:  Correlation ID from structlog contextvars; null when not bound
    """

    code: str
    message: str
    request_id: str | None


class ErrorResponse(BaseModel):
    """Top-level error envelope shared by all three global exception handlers.

    Shape: {"error": {"code": ..., "message": ..., "request_id": ...}}
    """

    error: ErrorDetail


# ---------------------------------------------------------------------------
# Raw ASGI correlation middleware
# ---------------------------------------------------------------------------


class CorrelationMiddleware:
    """Raw ASGI middleware that binds a UUID4 request_id to every request.

    Design decision #1: raw ASGI instead of BaseHTTPMiddleware.
    BaseHTTPMiddleware leaks contextvars across StreamingResponse / SSE
    boundaries (confirmed in proposal risk). This implementation copies the
    current context before processing each scope and runs the inner app
    inside that copied context, matching Starlette's ServerErrorMiddleware
    pattern.

    Behaviour:
    - Generates a fresh UUID4 for every HTTP request.
    - Binds it to structlog contextvars under key "request_id".
    - Sets the X-Request-ID response header to the same value.
    - Clears the bound request_id after the response completes.
    - Ignores any caller-supplied X-Request-ID (always generates own).
    - Only runs for HTTP and WebSocket scopes (passes others through unchanged).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Generate a fresh UUID4 for this request — ignore any caller-supplied value.
        request_id = str(uuid.uuid4())

        # Copy the current context so that structlog contextvars are isolated
        # per request and do not bleed between concurrent requests.
        ctx = contextvars.copy_context()

        # Inner coroutine that runs the application inside the copied context.
        # We use ctx.run() so that all contextvars operations (bind, clear)
        # in _run_in_context() are scoped to this request's copy of the context.
        async def _run_in_context() -> None:
            # Bind request_id to structlog contextvars at the start of the request.
            structlog.contextvars.bind_contextvars(request_id=request_id)

            # Track whether the ASGI response has begun. Once the first
            # http.response.start has been sent we must NOT emit a second
            # response — doing so would corrupt an in-flight SSE/streaming body.
            response_started = False

            # Wrap the send callable to inject X-Request-ID into response headers.
            async def send_with_request_id(message: Any) -> None:
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    headers = list(message.get("headers", []))
                    headers.append(
                        (b"x-request-id", request_id.encode("latin-1"))
                    )
                    message = {**message, "headers": headers}
                await send(message)

            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                # Unhandled exception propagated past every inner handler.
                #
                # Why this lives here: Starlette's ServerErrorMiddleware — which
                # hosts the catch-all Exception handler — sits OUTSIDE this
                # middleware in the stack. If we let the exception escape, the
                # canonical 500 is produced out here, where request_id is no
                # longer bound and the X-Request-ID header is never injected.
                # Probe confirmed: 500 responses lost both the header and the
                # body request_id.
                #
                # Fix: build the canonical 500 inside this still-bound context
                # (request_id present) and emit it through send_with_request_id
                # (header present). Only safe when the response has not started;
                # mid-stream we re-raise so the SSE body is never corrupted.
                if scope["type"] != "http" or response_started:
                    raise
                request = Request(scope, receive)
                response = await handle_exception(request, exc)
                await response(scope, receive, send_with_request_id)
            finally:
                # Clear only the keys we bound so we do not clobber other
                # contextvars (e.g. job_id or call_session_id) that might
                # have been bound by inner middleware or handlers.
                structlog.contextvars.unbind_contextvars("request_id")

        # Run the inner coroutine inside the copied context.
        # contextvars.Context.run() is synchronous; we need to run an async
        # coroutine inside it. We do this by calling ctx.run on a sync wrapper
        # that schedules the coroutine. However, the recommended pattern for
        # ASGI middleware is to use asyncio.ensure_future / TaskGroup with a
        # context copy. The simplest and correct approach is to use
        # contextvars.copy_context() and run_sync_in_executor, but for async
        # we can use the pattern below: create a Task bound to the copied context.
        import asyncio

        loop = asyncio.get_event_loop()
        # Create a task that runs within the copied context.
        # This ensures that structlog.contextvars operations inside _run_in_context
        # are scoped to the copied context and do not affect the outer context.
        task = loop.create_task(_run_in_context(), context=ctx)
        await task


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


def _redact_validation_errors(errors: list[Any]) -> list[dict[str, Any]]:
    """Strip user-submitted ``input`` values from Pydantic v2 validation errors.

    Pydantic v2 ``exc.errors()`` entries echo back the raw submitted value under
    the top-level ``input`` key, and may also nest an ``input`` inside ``ctx``.
    Those values can carry PII or secrets (passwords, tokens, API keys), so they
    must never reach structured logs or the HTTP response body.

    Returns a new list of error dicts with every ``input`` key removed
    (top-level and inside ``ctx``). ``loc``, ``msg``, ``type``, and ``url`` are
    preserved for developer tooling.
    """
    redacted: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            redacted.append(error)
            continue
        clean = {k: v for k, v in error.items() if k != "input"}
        ctx = clean.get("ctx")
        if isinstance(ctx, dict):
            clean["ctx"] = {k: v for k, v in ctx.items() if k != "input"}
        redacted.append(clean)
    return redacted


def _get_active_request_id() -> str | None:
    """Return the active request_id from structlog contextvars, or None."""
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id")


# Live voice/SSE/custom-LLM request paths. Under live calls the user constraint
# is that NOTHING in the request path may add latency, so synchronous Sentry
# capture must be skipped for 500s on these paths (errors are still logged with
# request_id + canonical envelope). The voice router is mounted at
# /api/v1/voice (initiation + custom-llm streaming); the bare /voice prefix is
# matched too so tests and any re-mounts are covered.
_LIVE_PATH_PREFIXES: tuple[str, ...] = ("/api/v1/voice", "/voice")


def _is_live_path(path: str) -> bool:
    """Return True when ``path`` is a latency-sensitive live voice/SSE path.

    Used to gate synchronous Sentry capture out of the live turn path. The
    canonical 500 response and structured error log are unaffected.
    """
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _LIVE_PATH_PREFIXES
    )


async def handle_exception(request: Request, exc: Exception) -> JSONResponse:
    """Global handler for unhandled Exception → HTTP 500.

    Spec: Requirement: Global Exception Handler — Unhandled Exception
    - Returns HTTP 500 with canonical schema.
    - Includes request_id from active contextvars.
    - Logs the full exception at ERROR level with exc_info=True.
    - Does NOT include stack traces in the response body.
    - Captures exception in Sentry (when DSN is configured) with request_id tag,
      EXCEPT on live voice/SSE/custom-LLM paths where synchronous capture is
      skipped to keep zero added latency in the live turn path.
      Capture is best-effort: failures are swallowed so the 500 response is always returned.
    """
    request_id = _get_active_request_id()
    path = request.url.path

    logger.error(
        "unhandled_exception",
        method=request.method,
        path=path,
        status_code=500,
        request_id=request_id,
        exc_info=True,
    )

    # B9 PR2 — Optional Sentry capture (spec: observability-sentry Unhandled Exception Capture).
    # Only captures when Sentry is initialized (DSN was set at startup).
    # Skipped on live voice/SSE/custom-LLM paths: the user constraint is that
    # nothing in a live call may add request-path latency. The 500 is still
    # logged above with request_id and returned with the canonical envelope.
    # Best-effort: any failure here must NOT prevent the 500 response from being sent.
    if not _is_live_path(path) and sentry_sdk.is_initialized():
        try:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("request_id", request_id or "")
                sentry_sdk.capture_exception(exc)
        except Exception:
            # Sentry capture failure must never break the error response path.
            logger.debug("sentry_capture_exception_failed", exc_info=True)

    body = ErrorResponse(
        error=ErrorDetail(
            code="internal_error",
            message="An unexpected error occurred. Please try again later.",
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=500,
        content=body.model_dump(),
    )


async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Global handler for HTTPException → canonical schema preserving status code.

    Spec: Requirement: Global Exception Handler — HTTPException
    - Wraps exc.detail into canonical error schema.
    - Preserves the original HTTP status code.
    - Logs at WARNING level for 4xx, ERROR level for 5xx; no exc_info for 4xx.

    Security: for 5xx HTTPExceptions the raw ``exc.detail`` is NEVER returned in
    the client-facing response body — it may carry sensitive internal details
    (DB errors, upstream payloads, stack-derived strings). The real detail is
    still logged as structured metadata for operators; the client receives a
    generic "Internal server error" message. 4xx detail is preserved unchanged
    because those are caller-actionable messages by contract.
    """
    request_id = _get_active_request_id()

    detail_message = (
        exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    )

    if exc.status_code >= 500:
        logger.error(
            "http_exception",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            request_id=request_id,
            detail=detail_message,
            exc_info=True,
        )
        # Never echo internal 5xx detail to clients — return a generic message.
        client_message = "Internal server error"
    else:
        logger.warning(
            "http_exception",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            request_id=request_id,
        )
        client_message = detail_message

    body = ErrorResponse(
        error=ErrorDetail(
            code="http_error",
            message=client_message,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=dict(exc.headers) if exc.headers else None,
    )


async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Global handler for Pydantic RequestValidationError → HTTP 422.

    Spec: Requirement: Global Exception Handler — RequestValidationError
    - Returns HTTP 422.
    - Wraps Pydantic validation detail into canonical error schema.
    - Includes raw Pydantic errors list under "details" key for developer tooling.
    """
    request_id = _get_active_request_id()

    # Redact user-submitted ``input`` values before they reach logs or the
    # response body. Pydantic v2 echoes raw input (and a nested ctx.input),
    # which may contain PII or secrets.
    errors = _redact_validation_errors(exc.errors())
    if errors:
        first = errors[0]
        loc = " → ".join(str(p) for p in first.get("loc", []))
        msg = first.get("msg", "Validation failed")
        summary = f"{loc}: {msg}" if loc else msg
    else:
        summary = "Request validation failed"

    logger.warning(
        "validation_error",
        method=request.method,
        path=request.url.path,
        status_code=422,
        request_id=request_id,
        errors=errors,
    )

    body = ErrorResponse(
        error=ErrorDetail(
            code="validation_error",
            message=summary,
            request_id=request_id,
        )
    )
    # Include raw Pydantic errors under a top-level "details" key for developer tooling.
    # This is in addition to the canonical "error" envelope (spec: SHOULD be included).
    response_content = body.model_dump()
    response_content["details"] = errors

    return JSONResponse(
        status_code=422,
        content=response_content,
    )
