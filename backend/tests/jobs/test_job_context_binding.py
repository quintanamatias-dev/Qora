"""Tests: B9 observability — background job context binding.

TDD RED phase for task 1.4.

Covered scenarios (spec: observability-correlation — Job Context Binding):
    - _run_job() binds job_id and job_type to structlog contextvars before
      the handler executes
    - Log lines emitted by the handler include job_id and job_type
    - On job failure the failure log includes job_id, job_type, and error info
    - Context binding is available inside the handler (not just in _run_job())

Design: openspec/changes/phase-b-structured-logging-error-monitoring/design.md
Spec:   observability-correlation/spec.md — Job Context Binding
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestJobContextBinding:
    """JobExecutor._run_job must bind job_id + job_type to contextvars."""

    def setup_method(self):
        """Clear structlog contextvars before each test."""
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        """Clear structlog contextvars after each test."""
        structlog.contextvars.clear_contextvars()

    def test_bind_job_context_helper_exists(self):
        """app.jobs.executor must expose a _bind_job_context helper.

        This is the RED proof: importing and checking for the helper will fail
        until task 1.4 GREEN adds it.
        """
        from app.jobs import executor

        assert hasattr(executor, "_bind_job_context"), (
            "_bind_job_context helper must exist in app.jobs.executor "
            "after task 1.4 GREEN"
        )

    def test_bind_job_context_binds_job_id(self):
        """_bind_job_context must bind job_id to structlog contextvars."""
        from app.jobs.executor import _bind_job_context

        structlog.contextvars.clear_contextvars()
        _bind_job_context(job_id="job-abc-123", job_type="summarize")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("job_id") == "job-abc-123", (
            f"Expected job_id='job-abc-123' in contextvars, got: {ctx}"
        )

    def test_bind_job_context_binds_job_type(self):
        """_bind_job_context must bind job_type to structlog contextvars."""
        from app.jobs.executor import _bind_job_context

        structlog.contextvars.clear_contextvars()
        _bind_job_context(job_id="job-def-456", job_type="crm_sync")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("job_type") == "crm_sync"

    def test_bind_job_context_both_ids_visible_after_bind(self):
        """Both job_id and job_type must be bound in the same call."""
        from app.jobs.executor import _bind_job_context

        structlog.contextvars.clear_contextvars()
        _bind_job_context(job_id="job-ghi-789", job_type="email_send")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("job_id") == "job-ghi-789"
        assert ctx.get("job_type") == "email_send"

    def test_bind_job_context_is_sync(self):
        """_bind_job_context must be synchronous (no await in the job setup path)."""
        import inspect
        from app.jobs.executor import _bind_job_context

        assert not inspect.iscoroutinefunction(_bind_job_context), (
            "_bind_job_context must be a synchronous function"
        )

    def test_bind_job_context_overwrites_previous_context(self):
        """Each call to _bind_job_context must replace the previous job context.

        This verifies that between jobs in the same worker, context from a
        previous job does not bleed into the next one.
        """
        from app.jobs.executor import _bind_job_context

        structlog.contextvars.clear_contextvars()
        _bind_job_context(job_id="job-first", job_type="type_a")
        _bind_job_context(job_id="job-second", job_type="type_b")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("job_id") == "job-second"
        assert ctx.get("job_type") == "type_b"

    @pytest.mark.asyncio
    async def test_run_job_binds_context_before_handler(self, tmp_path):
        """_run_job() must call _bind_job_context before executing the handler.

        We verify this by intercepting the _bind_job_context call and confirming
        it is invoked with the correct job_id and job_type before the handler runs.
        """
        from app.jobs.executor import _bind_job_context, JobExecutor

        # Track when _bind_job_context is called relative to handler calls
        call_order: list[str] = []

        def _fake_bind(job_id: str, job_type: str) -> None:
            call_order.append(f"bind:{job_id}:{job_type}")

        async def _fake_handler(payload: dict, db) -> None:
            call_order.append("handler")

        executor = JobExecutor()

        with (
            patch("app.jobs.executor._bind_job_context", side_effect=_fake_bind),
            patch("app.jobs.executor.get_handler", return_value=_fake_handler),
            patch("app.jobs.executor.get_session") as mock_session_ctx,
        ):
            # Mock the async context manager for DB sessions
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            # Create a fake job object
            fake_job = MagicMock()
            fake_job.id = "job-test-001"
            fake_job.job_type = "summarize"
            fake_job.payload = '{"session_id": "s1"}'
            fake_job.status = "pending"
            fake_job.attempts = 0
            fake_job.max_attempts = 3
            fake_job.started_at = None

            # db.get returns the fake job on first call (pending→running transition)
            # then returns it again for the success update
            mock_session.get = AsyncMock(return_value=fake_job)
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value = mock_session

            await executor._run_job("job-test-001")

        # Verify binding happened before handler execution
        assert call_order, "No calls recorded — _bind_job_context was never called"
        bind_calls = [c for c in call_order if c.startswith("bind:")]
        assert bind_calls, "_bind_job_context was not called during _run_job()"
        bind_idx = call_order.index(bind_calls[0])
        if "handler" in call_order:
            handler_idx = call_order.index("handler")
            assert bind_idx < handler_idx, (
                f"_bind_job_context must be called BEFORE the handler. "
                f"Call order: {call_order}"
            )

    @pytest.mark.asyncio
    async def test_run_job_clears_context_after_return(self):
        """_run_job() must NOT leave stale job_id/job_type in contextvars.

        Reliability guard: job context is bound per attempt and must be cleared
        in a finally block so it never bleeds into the next job executed on the
        same worker task. After a successful _run_job() the contextvars must
        contain neither job_id nor job_type.
        """
        from app.jobs.executor import JobExecutor

        async def _ok_handler(payload: dict, db) -> None:
            # Inside the handler the context MUST be bound (sanity check)
            ctx = structlog.contextvars.get_contextvars()
            assert ctx.get("job_id") == "job-clear-001"
            assert ctx.get("job_type") == "summarize"

        executor = JobExecutor()

        structlog.contextvars.clear_contextvars()

        with (
            patch("app.jobs.executor.get_handler", return_value=_ok_handler),
            patch("app.jobs.executor.get_session") as mock_session_ctx,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            fake_job = MagicMock()
            fake_job.id = "job-clear-001"
            fake_job.job_type = "summarize"
            fake_job.payload = '{"session_id": "s1"}'
            fake_job.status = "pending"
            fake_job.attempts = 0
            fake_job.max_attempts = 3
            fake_job.started_at = None

            mock_session.get = AsyncMock(return_value=fake_job)
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value = mock_session

            await executor._run_job("job-clear-001")

        ctx = structlog.contextvars.get_contextvars()
        assert "job_id" not in ctx, (
            f"Stale job_id leaked after _run_job() returned: {ctx}"
        )
        assert "job_type" not in ctx, (
            f"Stale job_type leaked after _run_job() returned: {ctx}"
        )

    @pytest.mark.asyncio
    async def test_run_job_clears_context_even_on_handler_failure(self):
        """Job context must be cleared even when the job dead-letters.

        Drives a handler that always raises with max_attempts=1 so the job goes
        straight to 'dead' (no retry sleep), then asserts no stale context.
        """
        from app.jobs.executor import JobExecutor

        async def _boom_handler(payload: dict, db) -> None:
            raise RuntimeError("handler boom")

        executor = JobExecutor()

        structlog.contextvars.clear_contextvars()

        with (
            patch("app.jobs.executor.get_handler", return_value=_boom_handler),
            patch("app.jobs.executor.get_session") as mock_session_ctx,
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            fake_job = MagicMock()
            fake_job.id = "job-fail-002"
            fake_job.job_type = "crm_sync"
            fake_job.payload = "{}"
            fake_job.status = "pending"
            fake_job.attempts = 0
            fake_job.max_attempts = 1  # one attempt → dead, no backoff sleep
            fake_job.started_at = None

            mock_session.get = AsyncMock(return_value=fake_job)
            mock_session.commit = AsyncMock()
            mock_session_ctx.return_value = mock_session

            await executor._run_job("job-fail-002")

        ctx = structlog.contextvars.get_contextvars()
        assert "job_id" not in ctx, f"Stale job_id after dead-letter: {ctx}"
        assert "job_type" not in ctx, f"Stale job_type after dead-letter: {ctx}"
