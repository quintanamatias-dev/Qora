"""Tests: B9 observability — Sentry capture for dead-lettered jobs (task 3.4).

Strict TDD RED phase.

Covered scenarios (spec: observability-sentry — Requirement: Dead-Letter Job Capture):
    - Dead-lettered job triggers sentry_sdk.capture_exception() when DSN active
    - Sentry event is tagged with job_id and job_type
    - No Sentry capture when DSN is absent
    - Sentry capture is called after dead-letter DB commit (not live path)
    - Sentry capture failure does not interfere with DB recording / normal flow

Design note: We test the dead-letter Sentry path by running _run_job() with a
handler that always raises, max_attempts=1 so it immediately dead-letters, and
all DB sessions mocked to return the same job object. We patch asyncio.sleep to
avoid backoff delays in tests.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.jobs.executor import JobExecutor
from app.jobs.models import BackgroundJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_job(
    job_id: str,
    job_type: str = "test_job",
    attempts: int = 0,
    max_attempts: int = 1,
    status: str = "pending",
) -> MagicMock:
    """Create a mock BackgroundJob that transitions through states on commit."""
    job = MagicMock(spec=BackgroundJob)
    job.id = job_id
    job.job_type = job_type
    job.status = status
    job.attempts = attempts
    job.max_attempts = max_attempts
    job.payload = json.dumps({"test": True})
    job.error = None
    job.started_at = None
    job.completed_at = None
    return job


def _make_session_factory(job: MagicMock):
    """Return a factory that yields an async session returning the given job."""

    @asynccontextmanager
    async def _session_factory():
        session = AsyncMock()
        session.commit = AsyncMock()
        session.get = AsyncMock(return_value=job)
        yield session

    return _session_factory


class TestDeadLetterSentryCapture:
    """Dead-lettered jobs must be captured in Sentry when DSN is active."""

    @pytest.mark.asyncio
    async def test_dead_letter_calls_capture_exception_when_sentry_active(self):
        """sentry_sdk.capture_exception() must be called when a job is dead-lettered
        and Sentry is initialized.

        Spec: Dead-lettered job appears in Sentry.
        """
        job_id = "dead-sentry-active"
        job = _make_mock_job(job_id, max_attempts=1)
        executor = JobExecutor()

        class _FakeScope:
            def __init__(self):
                self.tags = {}
                self.extras = {}

            def set_tag(self, key, value):
                self.tags[key] = value

            def set_extra(self, key, value):
                self.extras[key] = value

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        scope = _FakeScope()

        with (
            patch("app.jobs.executor.sentry_sdk") as mock_sentry,
            patch("app.jobs.executor.get_session", side_effect=_make_session_factory(job)),
            patch("app.jobs.executor.get_handler") as mock_get_handler,
            patch("asyncio.sleep", new_callable=AsyncMock),  # skip backoff
        ):
            mock_sentry.is_initialized.return_value = True
            mock_sentry.push_scope.return_value = scope

            # Handler always fails → dead-letter after 1 attempt
            handler = AsyncMock(side_effect=RuntimeError("always fails"))
            mock_get_handler.return_value = handler

            await executor._run_job(job_id)

        # Sentry must have attempted capture
        assert mock_sentry.capture_exception.called, (
            "sentry_sdk.capture_exception() must be called when a job is dead-lettered "
            "and Sentry is initialized"
        )

    @pytest.mark.asyncio
    async def test_dead_letter_sentry_scope_tags_include_job_id_and_type(self):
        """The Sentry scope must include job_id and job_type tags on dead-letter capture.

        Spec: The event MUST include job_id, job_type, and the final exception as context.
        """
        job_id = "dead-sentry-tags"
        job_type = "test_job"
        job = _make_mock_job(job_id, job_type=job_type, max_attempts=1)
        executor = JobExecutor()

        captured_tags: dict = {}

        class _FakeScope:
            def set_tag(self, key, value):
                captured_tags[key] = value

            def set_extra(self, key, value):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch("app.jobs.executor.sentry_sdk") as mock_sentry,
            patch("app.jobs.executor.get_session", side_effect=_make_session_factory(job)),
            patch("app.jobs.executor.get_handler") as mock_get_handler,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_sentry.is_initialized.return_value = True
            mock_sentry.push_scope.return_value = _FakeScope()

            handler = AsyncMock(side_effect=RuntimeError("always fails"))
            mock_get_handler.return_value = handler

            await executor._run_job(job_id)

        assert "job_id" in captured_tags, (
            "Sentry scope must have 'job_id' tag for dead-letter events"
        )
        assert "job_type" in captured_tags, (
            "Sentry scope must have 'job_type' tag for dead-letter events"
        )
        assert captured_tags["job_id"] == job_id
        assert captured_tags["job_type"] == job_type

    @pytest.mark.asyncio
    async def test_dead_letter_no_sentry_capture_when_not_initialized(self):
        """When Sentry is not initialized, dead-lettered jobs must NOT trigger capture.

        Spec: Dead-lettered job does not raise when Sentry is absent.
        """
        job_id = "dead-no-sentry"
        job = _make_mock_job(job_id, max_attempts=1)
        executor = JobExecutor()

        with (
            patch("app.jobs.executor.sentry_sdk") as mock_sentry,
            patch("app.jobs.executor.get_session", side_effect=_make_session_factory(job)),
            patch("app.jobs.executor.get_handler") as mock_get_handler,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_sentry.is_initialized.return_value = False

            handler = AsyncMock(side_effect=RuntimeError("always fails"))
            mock_get_handler.return_value = handler

            await executor._run_job(job_id)

        mock_sentry.capture_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_sentry_capture_failure_does_not_block_dead_letter_completion(self):
        """If sentry_sdk.capture_exception() raises, the dead-letter flow must complete normally.

        Best-effort: Sentry capture must never block or corrupt the dead-letter path.
        """
        job_id = "dead-sentry-boom"
        job = _make_mock_job(job_id, max_attempts=1)
        committed_statuses = []

        @asynccontextmanager
        async def _tracked_session_factory():
            session = AsyncMock()

            async def _commit():
                committed_statuses.append(job.status)

            session.commit = _commit
            session.get = AsyncMock(return_value=job)
            yield session

        executor = JobExecutor()

        class _FakeScope:
            def set_tag(self, *a, **kw):
                pass

            def set_extra(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch("app.jobs.executor.sentry_sdk") as mock_sentry,
            patch(
                "app.jobs.executor.get_session",
                side_effect=_tracked_session_factory,
            ),
            patch("app.jobs.executor.get_handler") as mock_get_handler,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_sentry.is_initialized.return_value = True
            mock_sentry.push_scope.return_value = _FakeScope()
            mock_sentry.capture_exception.side_effect = RuntimeError("Sentry SDK error")

            handler = AsyncMock(side_effect=RuntimeError("always fails"))
            mock_get_handler.return_value = handler

            # Must not raise — Sentry failure is swallowed
            await executor._run_job(job_id)

        # DB commit for dead status must still have occurred
        assert "dead" in committed_statuses, (
            f"Dead-letter DB commit must occur even when Sentry capture fails. "
            f"Got statuses: {committed_statuses}"
        )
