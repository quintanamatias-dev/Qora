"""Tests: B9 observability — health endpoint detail mode (task 4.1).

Strict TDD RED phase.

Covered scenarios (spec: observability-health-readiness):

    Liveness (existing behavior preserved):
        - GET /api/v1/health (no ?detail=true) returns 200 with status/uptime/version
        - No DB ping or job executor check on liveness-only call

    Detail mode:
        - GET /api/v1/health?detail=true returns 200 with db and job_executor fields
        - db='ok' when DB ping succeeds
        - db='error' with db_error message when DB unreachable
        - db='timeout' when DB ping exceeds 2s timeout
        - job_executor='running' when executor is active
        - job_executor='stopped' when ENABLE_JOB_EXECUTOR=false

    Schema contract:
        - Exact fields: status, uptime, version, db, db_error (conditional), job_executor
        - No extra undocumented fields at top level

    Auth:
        - Endpoint reachable without Authorization header (no auth required)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient from the production app factory."""
    _app = create_app()
    return TestClient(_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Liveness-only (existing behavior preserved)
# ---------------------------------------------------------------------------


class TestHealthLiveness:
    """GET /api/v1/health (no ?detail=true) must return unchanged liveness response."""

    def test_liveness_returns_200(self, client: TestClient):
        """Liveness call without ?detail=true must return 200."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_liveness_body_contains_status(self, client: TestClient):
        """Liveness response must include a 'status' field."""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "status" in body, f"Expected 'status' in liveness response: {body}"

    def test_liveness_body_contains_uptime(self, client: TestClient):
        """Liveness response must include an uptime field (seconds since startup)."""
        response = client.get("/api/v1/health")
        body = response.json()
        # The spec uses 'uptime' but existing endpoint uses 'uptime_seconds'.
        # Either is acceptable; we just need SOME uptime field.
        has_uptime = "uptime" in body or "uptime_seconds" in body
        assert has_uptime, f"Expected uptime field in liveness response: {body}"

    def test_liveness_body_contains_version(self, client: TestClient):
        """Liveness response must include a 'version' field."""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "version" in body, f"Expected 'version' in liveness response: {body}"

    def test_liveness_no_db_field(self, client: TestClient):
        """Liveness response must NOT include 'db' (no DB ping without ?detail=true)."""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "db" not in body, (
            f"Liveness response must not include 'db' — no DB ping without ?detail=true: {body}"
        )

    def test_liveness_no_job_executor_field(self, client: TestClient):
        """Liveness response must NOT include 'job_executor' without ?detail=true."""
        response = client.get("/api/v1/health")
        body = response.json()
        assert "job_executor" not in body, (
            f"Liveness response must not include 'job_executor' without ?detail=true: {body}"
        )

    def test_liveness_reachable_without_auth(self, client: TestClient):
        """Health endpoint must not require Authorization header."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Detail mode — happy path
# ---------------------------------------------------------------------------


class TestHealthDetail:
    """GET /api/v1/health?detail=true returns DB and job executor status."""

    def test_detail_returns_200(self, client: TestClient):
        """?detail=true must return 200 even when dependencies are healthy."""
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            # Mock a successful DB ping
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")
        assert response.status_code == 200

    def test_detail_includes_db_field(self, client: TestClient):
        """?detail=true response must include a 'db' field."""
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")
        assert "db" in response.json(), (
            f"?detail=true response must include 'db': {response.json()}"
        )

    def test_detail_db_ok_when_ping_succeeds(self, client: TestClient):
        """db='ok' when the DB ping returns successfully."""
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=MagicMock())
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        body = response.json()
        assert body.get("db") == "ok", (
            f"db field must be 'ok' when DB ping succeeds, got: {body.get('db')}"
        )

    def test_detail_includes_job_executor_field(self, client: TestClient):
        """?detail=true response must include a 'job_executor' field."""
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        assert "job_executor" in response.json(), (
            f"?detail=true response must include 'job_executor': {response.json()}"
        )

    def test_detail_reachable_without_auth(self, client: TestClient):
        """?detail=true must not require Authorization header."""
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get(
                "/api/v1/health?detail=true",
                # No Authorization header
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Detail mode — degraded states
# ---------------------------------------------------------------------------


class TestHealthDetailDegraded:
    """?detail=true reports degraded states accurately."""

    def test_detail_db_error_when_db_unreachable(self, client: TestClient):
        """db='error' with db_error message when DB ping raises an exception.

        Spec: DB unreachable returns degraded status — response is still 200.
        """
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(
                side_effect=Exception("connection refused")
            )
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        assert response.status_code == 200
        body = response.json()
        assert body.get("db") == "error", (
            f"db must be 'error' when DB ping raises, got: {body.get('db')}"
        )
        assert body.get("db_error") is not None, (
            "db_error field must be present and non-empty when db='error'"
        )
        assert len(body["db_error"]) > 0, "db_error message must not be empty"
        # Security: the auth-exempt detailed health view must NOT leak the raw
        # exception string (DB driver internals, paths, connection details).
        # It returns a coarse, fixed marker instead.
        assert body["db_error"] == "unavailable", (
            f"db_error must be a coarse sanitized marker, got: {body['db_error']!r}"
        )
        assert "connection refused" not in body["db_error"], (
            "db_error must not leak the raw exception string"
        )

    def test_detail_db_error_response_still_200(self, client: TestClient):
        """A DB error must not cause the health endpoint itself to return 5xx.

        Spec: the response status is 200 (the endpoint itself is healthy).
        """
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(side_effect=Exception("db down"))
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        assert response.status_code == 200

    def test_detail_db_timeout_when_ping_slow(self, client: TestClient):
        """db='timeout' when the DB ping does not respond within 2 seconds.

        Spec: DB ping times out — response includes db='timeout'.
        """
        async def _slow_execute(*args, **kwargs):
            # Simulate a slow query that exceeds the 2-second timeout
            await asyncio.sleep(10.0)

        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = _slow_execute
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            # Patch asyncio.wait_for to raise TimeoutError immediately.
            # We must close the passed coroutine so it is not left unawaited
            # (otherwise pytest emits a RuntimeWarning: coroutine was never awaited).
            original_wait_for = asyncio.wait_for

            async def _fake_wait_for(coro, timeout):
                coro.close()
                raise asyncio.TimeoutError()

            with patch("asyncio.wait_for", side_effect=_fake_wait_for):
                response = client.get("/api/v1/health?detail=true")

        body = response.json()
        assert body.get("db") == "timeout", (
            f"db must be 'timeout' on DB ping timeout, got: {body.get('db')}"
        )

    def test_detail_job_executor_stopped_when_flag_disabled(self, client: TestClient):
        """job_executor='stopped' when ENABLE_JOB_EXECUTOR=false.

        Spec: ENABLE_JOB_EXECUTOR=false or executor not started → job_executor='stopped'.
        """
        with (
            patch("app.core.database.engine") as mock_engine,
            patch("app.jobs.executor.executor") as mock_exec,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            # Simulate executor not started (no active tasks)
            mock_exec._active_job_ids = set()
            mock_exec._tasks = set()
            mock_exec.started = False

            # Patch settings to disable executor
            with patch("app.main.Settings") as MockSettings:
                mock_settings = MagicMock()
                mock_settings.enable_job_executor = False
                MockSettings.return_value = mock_settings

                response = client.get("/api/v1/health?detail=true")

        body = response.json()
        # When ENABLE_JOB_EXECUTOR=false, job_executor must be EXACTLY 'stopped'.
        assert body.get("job_executor") == "stopped", (
            f"job_executor must be exactly 'stopped' when disabled, got: {body.get('job_executor')}"
        )

    def test_detail_job_executor_running_when_flag_enabled(self, client: TestClient):
        """job_executor='running' (exact) when ENABLE_JOB_EXECUTOR=true.

        Spec: ENABLE_JOB_EXECUTOR=true and executor started → job_executor='running'.
        """
        with (
            patch("app.core.database.engine") as mock_engine,
            patch("app.jobs.executor.executor") as mock_exec,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            mock_exec._active_job_ids = set()
            mock_exec._tasks = set()
            # Executor actually started at runtime (recover() ran, no shutdown).
            mock_exec.started = True

            with patch("app.main.Settings") as MockSettings:
                mock_settings = MagicMock()
                mock_settings.enable_job_executor = True
                MockSettings.return_value = mock_settings

                response = client.get("/api/v1/health?detail=true")

        body = response.json()
        assert body.get("job_executor") == "running", (
            f"job_executor must be exactly 'running' when enabled, got: {body.get('job_executor')}"
        )

    def test_detail_job_executor_stopped_when_flag_enabled_but_not_started(
        self, client: TestClient
    ):
        """job_executor='stopped' when flag is ON but the executor never started.

        Reporting must reflect actual runtime lifecycle, not just the config flag:
        if startup failed before recover() (or shutdown() already ran), the
        executor is not actually running and health must not claim otherwise.
        """
        with (
            patch("app.core.database.engine") as mock_engine,
            patch("app.jobs.executor.executor") as mock_exec,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            mock_exec._active_job_ids = set()
            mock_exec._tasks = set()
            # Flag is enabled but the executor never reached the started state.
            mock_exec.started = False

            with patch("app.main.Settings") as MockSettings:
                mock_settings = MagicMock()
                mock_settings.enable_job_executor = True
                MockSettings.return_value = mock_settings

                response = client.get("/api/v1/health?detail=true")

        body = response.json()
        assert body.get("job_executor") == "stopped", (
            "job_executor must be 'stopped' when the executor has not started, "
            f"even with the flag enabled, got: {body.get('job_executor')}"
        )


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


class TestHealthDetailSchema:
    """?detail=true response must conform to the documented JSON schema."""

    def test_detail_schema_has_all_required_fields_when_healthy(
        self, client: TestClient
    ):
        """Detail response includes status, uptime/uptime_seconds, version, db, job_executor.

        Spec: Detail response matches schema contract.
        """
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=MagicMock())
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        body = response.json()
        assert "status" in body
        assert "version" in body
        has_uptime = "uptime" in body or "uptime_seconds" in body
        assert has_uptime, f"Missing uptime field: {list(body.keys())}"
        assert "db" in body
        assert "job_executor" in body

    def test_detail_no_extra_undocumented_fields(self, client: TestClient):
        """Top-level response must only contain documented fields.

        Spec: No extra undocumented fields appear at the top level.
        Allowed: status, uptime/uptime_seconds, version, db, db_error, job_executor
        """
        with (
            patch("app.core.database.engine") as mock_engine,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=MagicMock())
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)
            mock_engine.connect.return_value = mock_conn

            response = client.get("/api/v1/health?detail=true")

        body = response.json()
        allowed_fields = {
            "status", "uptime", "uptime_seconds", "version",
            "db", "db_error", "job_executor",
        }
        extra = set(body.keys()) - allowed_fields
        assert not extra, (
            f"Unexpected extra fields in detail response: {extra}"
        )
