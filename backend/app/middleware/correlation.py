"""QORA — Raw ASGI Correlation Middleware.

Generates or propagates an X-Request-ID header and binds it to structlog
contextvars so every log line for a request carries the same correlation ID.

Design decision: Raw ASGI (NOT BaseHTTPMiddleware) — BaseHTTPMiddleware breaks
contextvars in SSE/StreamingResponse because it wraps the response body in a
new task, losing the original contextvars. Raw ASGI preserves the contextvars
across the full request lifecycle including SSE generators.

Spec: sdd/b9-observability/spec — capability: correlation-middleware
"""

from __future__ import annotations

import time
import uuid
from typing import Awaitable, Callable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

# Maximum allowed length for a caller-supplied X-Request-ID value.
_MAX_REQUEST_ID_LEN = 128


def _parse_request_id(headers: dict[bytes, bytes]) -> str:
    """Extract and validate X-Request-ID from ASGI headers dict.

    Returns the caller-supplied value if valid, otherwise generates a UUID4.

    A value is invalid when:
    - Empty string
    - Length > _MAX_REQUEST_ID_LEN chars
    """
    raw = headers.get(b"x-request-id", b"")
    value = raw.decode("latin-1", errors="replace").strip()

    if value and len(value) <= _MAX_REQUEST_ID_LEN:
        return value

    return str(uuid.uuid4())


class CorrelationMiddleware:
    """Raw ASGI middleware: X-Request-ID generation + structlog contextvars binding.

    Responsibilities:
    1. Read or generate the X-Request-ID header for each incoming request.
    2. Bind request_id to structlog contextvars for the request's lifetime.
    3. Set X-Request-ID on the response headers.
    4. Log request_started and request_completed with method, path, status, latency.
    5. Clear structlog contextvars after the response is sent.

    This replaces the previous RequestLoggingMiddleware (BaseHTTPMiddleware) which
    broke contextvars propagation in voice webhook SSE streams.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Build a fast header lookup (lowercase keys)
        headers: dict[bytes, bytes] = {k.lower(): v for k, v in scope.get("headers", [])}

        request_id = _parse_request_id(headers)
        method = scope.get("method", "")
        path = scope.get("path", "")
        start_time = time.monotonic()

        # Bind to structlog contextvars for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger.info("request_started", method=method, path=path, request_id=request_id)

        # Intercept send to inject X-Request-ID into response headers
        status_code_holder: list[int] = [200]

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Inject X-Request-ID into response headers
                response_headers = list(message.get("headers", []))
                response_headers.append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
                message = {**message, "headers": response_headers}
                status_code_holder[0] = message.get("status", 200)

            await send(message)

            if message["type"] == "http.response.body" and not message.get("more_body", False):
                # Final body chunk — log completion and clear contextvars
                latency_ms = (time.monotonic() - start_time) * 1000
                logger.info(
                    "request_completed",
                    method=method,
                    path=path,
                    status_code=status_code_holder[0],
                    latency_ms=round(latency_ms, 2),
                    request_id=request_id,
                )
                structlog.contextvars.clear_contextvars()

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "request_error",
                method=method,
                path=path,
                latency_ms=round(latency_ms, 2),
                request_id=request_id,
                exc_info=True,
            )
            structlog.contextvars.clear_contextvars()
            raise
