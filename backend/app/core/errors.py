"""QORA — Canonical Error Envelope and Global Exception Handlers.

Normalizes all HTTP error responses into a consistent shape:
    {"error": {"code": <int>, "message": <str>, "request_id": <str>}}

Replaces ad-hoc `detail` shapes and raw Starlette 500 HTML pages.

Spec: sdd/b9-observability/spec — capability: canonical-error-envelope
"""

from __future__ import annotations

import json

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Envelope model
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    """Canonical error response envelope."""

    class ErrorDetail(BaseModel):
        code: int
        message: str
        request_id: str | None = None

    error: ErrorDetail


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------


def _normalize_detail(detail: str | dict | list | None) -> str:
    """Normalize an HTTPException detail value to a plain string.

    - str: returned as-is
    - dict: extract 'error' or 'message' key; fallback to JSON serialization
    - list: JSON-serialized as a compact string
    - None / other: "Internal server error"
    """
    if isinstance(detail, str):
        return detail

    if isinstance(detail, dict):
        # Prefer 'error' key (Qora's most common dict detail shape)
        if "error" in detail and isinstance(detail["error"], str):
            return detail["error"]
        # Then try 'message' key
        if "message" in detail and isinstance(detail["message"], str):
            return detail["message"]
        # Fallback: JSON-serialize the whole dict
        return json.dumps(detail)

    if isinstance(detail, list):
        return json.dumps(detail)

    return "Internal server error"


def build_error_response(
    status_code: int,
    detail: str | dict | list | None,
    request_id: str | None,
) -> JSONResponse:
    """Build a JSONResponse with the canonical error envelope.

    Args:
        status_code: HTTP status code for the response.
        detail: Raw exception detail (string, dict, or list).
        request_id: Current request correlation ID from structlog contextvars.
                    Defaults to empty string when not available.

    Returns:
        JSONResponse with body: {"error": {"code": ..., "message": ..., "request_id": ...}}
    """
    message = _normalize_detail(detail)
    envelope = {
        "error": {
            "code": status_code,
            "message": message,
            "request_id": request_id if request_id is not None else "",
        }
    }
    return JSONResponse(status_code=status_code, content=envelope)


def _get_request_id(request: Request) -> str:
    """Extract request_id from structlog contextvars or return empty string."""
    import structlog.contextvars

    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id", "")


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI/Starlette HTTPException — return canonical envelope."""
    request_id = _get_request_id(request)
    logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
        path=request.url.path,
    )
    return build_error_response(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic v2 RequestValidationError — return canonical 422 envelope."""
    request_id = _get_request_id(request)

    # Build a human-readable summary from validation errors
    errors = exc.errors()
    messages = []
    for err in errors:
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "validation error")
        messages.append(f"{loc}: {msg}" if loc else msg)
    detail = "; ".join(messages) if messages else "Validation error"

    logger.warning(
        "validation_error",
        detail=detail,
        request_id=request_id,
        path=request.url.path,
    )
    return build_error_response(
        status_code=422,
        detail=detail,
        request_id=request_id,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled Python exceptions — return 500 canonical envelope."""
    request_id = _get_request_id(request)
    logger.exception(
        "unhandled_exception",
        error_type=type(exc).__name__,
        request_id=request_id,
        path=request.url.path,
    )
    return build_error_response(
        status_code=500,
        detail="Internal server error",
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_error_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on a FastAPI application.

    Must be called after app creation and before the first request.
    Typically called in create_app() in main.py.
    """
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
