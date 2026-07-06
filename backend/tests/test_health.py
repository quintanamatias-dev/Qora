"""Tests for enhanced health endpoint — B9 Observability PR2.

Spec: sdd/b9-observability/spec — capability: health-readiness

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after main.py health endpoint is enhanced.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Minimal test app helpers
# ---------------------------------------------------------------------------


def make_test_app() -> FastAPI:
    """Create a minimal app with the enhanced health endpoint logic."""
    from app.main import create_app

    return create_app()


# ---------------------------------------------------------------------------
# Task 5.2 — Basic health response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200_when_all_healthy():
    """Scenario: All dependencies healthy — returns HTTP 200 with status: healthy."""
    from app.core.health import check_health

    with (
        patch("app.core.health._check_database", new_callable=AsyncMock) as mock_db,
        patch("app.core.health._check_elevenlabs", new_callable=AsyncMock) as mock_el,
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0}
        mock_el.return_value = {"status": "ok", "latency_ms": 50.0}

        result = await check_health()

    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_returns_503_when_database_unreachable():
    """Scenario: Database unreachable — returns status: unhealthy."""
    from app.core.health import check_health

    with (
        patch("app.core.health._check_database", new_callable=AsyncMock) as mock_db,
        patch("app.core.health._check_elevenlabs", new_callable=AsyncMock) as mock_el,
    ):
        mock_db.return_value = {"status": "error", "latency_ms": 0.0, "error": "DB down"}
        mock_el.return_value = {"status": "ok", "latency_ms": 50.0}

        result = await check_health()

    assert result["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_detail_mode_returns_checks_object():
    """Scenario: detail=true — response includes checks.database and checks.elevenlabs."""
    from app.core.health import check_health

    with (
        patch("app.core.health._check_database", new_callable=AsyncMock) as mock_db,
        patch("app.core.health._check_elevenlabs", new_callable=AsyncMock) as mock_el,
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0}
        mock_el.return_value = {"status": "ok", "latency_ms": 50.0}

        result = await check_health(detail=True)

    assert "checks" in result
    assert "database" in result["checks"]
    assert "elevenlabs" in result["checks"]
    assert result["checks"]["database"]["status"] == "ok"
    assert "latency_ms" in result["checks"]["database"]


@pytest.mark.asyncio
async def test_health_partial_failure_returns_degraded_200():
    """Scenario: DB healthy, ElevenLabs unreachable — status: degraded, HTTP 200."""
    from app.core.health import check_health

    with (
        patch("app.core.health._check_database", new_callable=AsyncMock) as mock_db,
        patch("app.core.health._check_elevenlabs", new_callable=AsyncMock) as mock_el,
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0}
        mock_el.return_value = {"status": "error", "latency_ms": 0.0, "error": "timeout"}

        result = await check_health(detail=True)

    # EL down is non-critical: degraded but still HTTP 200
    assert result["status"] == "degraded"
    assert result["checks"]["elevenlabs"]["status"] == "error"
    assert result["checks"]["database"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_elevenlabs_timeout_reported_as_timeout():
    """Scenario: ElevenLabs check exceeds 3s timeout — error: 'timeout'."""
    from app.core.health import check_health

    with (
        patch("app.core.health._check_database", new_callable=AsyncMock) as mock_db,
        patch("app.core.health._check_elevenlabs", new_callable=AsyncMock) as mock_el,
    ):
        mock_db.return_value = {"status": "ok", "latency_ms": 5.0}
        mock_el.return_value = {"status": "error", "latency_ms": 3001.0, "error": "timeout"}

        result = await check_health(detail=True)

    assert result["checks"]["elevenlabs"]["error"] == "timeout"


@pytest.mark.asyncio
async def test_health_response_contains_no_connection_strings():
    """Scenario: DB error with connection string — error field is sanitized."""
    from app.core.health import _check_database

    with patch("app.core.health._get_db_session") as mock_session_ctx:
        # Simulate DB error with a password in the connection string
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=Exception("connection refused: sqlite+aiosqlite:///:password@host/db")
        )
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_cm

        result = await _check_database()

    assert result["status"] == "error"
    # The raw exception message must NOT appear in the error field
    assert "sqlite+aiosqlite" not in result.get("error", "")
    assert "password" not in result.get("error", "")


@pytest.mark.asyncio
async def test_health_db_check_latency_ms_is_non_negative():
    """Scenario: DB ping succeeds — latency_ms is a non-negative number."""
    from app.core.health import _check_database

    async def fake_execute(stmt):
        return MagicMock()

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())

    with patch("app.core.health._get_db_session") as mock_ctx:
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = mock_cm

        result = await _check_database()

    assert result["status"] == "ok"
    assert isinstance(result["latency_ms"], (int, float))
    assert result["latency_ms"] >= 0
