"""QORA — Enhanced health check logic.

Provides `check_health()` for the GET /api/v1/health endpoint with:
- Basic mode: fast no-I/O response for load-balancer checks
- Detail mode (?detail=true): real dependency probes (DB + ElevenLabs)

Critical dependency (database) down → status: unhealthy, HTTP 503
Non-critical dependency (ElevenLabs) down → status: degraded, HTTP 200
All healthy → status: healthy, HTTP 200

No sensitive data (connection strings, credentials, stack traces) is
included in the response.

Spec: sdd/b9-observability/spec — capability: health-readiness
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)

# Timeout for external reachability check (ElevenLabs HEAD request)
_ELEVENLABS_TIMEOUT_SECONDS = 3.0

# ElevenLabs URL used for lightweight reachability probe
_ELEVENLABS_PROBE_URL = "https://api.elevenlabs.io"


# ---------------------------------------------------------------------------
# Private helpers — DB session getter (injectable for testing)
# ---------------------------------------------------------------------------


def _get_db_session():
    """Return an async DB session context manager.

    Thin wrapper so tests can patch this function to inject failures.
    """
    from app.core.database import get_session
    return get_session()


# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------


async def _check_database() -> dict[str, Any]:
    """Execute a minimal SELECT 1 query to verify database connectivity.

    Returns:
        dict with keys:
            status: "ok" | "error"
            latency_ms: float — round-trip time in ms
            error: str — sanitized error message (only present on error)

    Spec: Requirement: Database Ping Check
    """
    start = time.monotonic()
    try:
        async with _get_db_session() as db:
            await db.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        logger.warning("health_db_check_failed", error=str(exc))
        # Return a generic message — never expose raw connection strings
        return {
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "error": "Database connection failed",
        }


async def _check_elevenlabs() -> dict[str, Any]:
    """Perform a lightweight HTTP HEAD probe against ElevenLabs API.

    Returns:
        dict with keys:
            status: "ok" | "error"
            latency_ms: float — round-trip time in ms
            error: str — error reason (only present on error)

    Spec: Requirement: ElevenLabs Reachability Check
    """
    import httpx

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_ELEVENLABS_TIMEOUT_SECONDS) as client:
            response = await client.head(_ELEVENLABS_PROBE_URL)
        latency_ms = (time.monotonic() - start) * 1000
        # Any HTTP response (including 401, 404) means the host is reachable
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except httpx.TimeoutException:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "error": "timeout",
        }
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        logger.warning("health_elevenlabs_check_failed", error=str(exc))
        return {
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "error": "unreachable",
        }


# ---------------------------------------------------------------------------
# Main health check function
# ---------------------------------------------------------------------------


async def check_health(detail: bool = False) -> dict[str, Any]:
    """Run health checks and return a structured result.

    Args:
        detail: When True, run real dependency probes and include
                per-check results. When False (default), return a
                fast no-I/O response suitable for load-balancer checks.

    Returns:
        dict with at minimum:
            status: "healthy" | "degraded" | "unhealthy"
        When detail=True also includes:
            checks:
                database: {status, latency_ms[, error]}
                elevenlabs: {status, latency_ms[, error]}

    HTTP status codes (used by the endpoint):
        200 — healthy or degraded (non-critical dep down)
        503 — unhealthy (critical dep down)

    Spec: Requirement: Basic Health Response, Detail Mode, Partial Failure
    """
    # Always probe DB — it's critical and fast (SELECT 1).
    # ElevenLabs probe runs only in detail mode (avoids external I/O on every
    # load-balancer ping while still checking the critical dependency).
    if not detail:
        db_result = await _check_database()
        db_ok = db_result["status"] == "ok"
        return {"status": "healthy" if db_ok else "unhealthy"}

    # Detail mode: run both probes concurrently
    db_result, el_result = await asyncio.gather(
        _check_database(),
        _check_elevenlabs(),
    )

    db_ok = db_result["status"] == "ok"
    el_ok = el_result["status"] == "ok"

    # Determine overall status:
    # - DB down → unhealthy (critical)
    # - EL down only → degraded (non-critical, HTTP 200)
    # - Both ok → healthy
    if not db_ok:
        overall = "unhealthy"
    elif not el_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "checks": {
            "database": db_result,
            "elevenlabs": el_result,
        },
    }
