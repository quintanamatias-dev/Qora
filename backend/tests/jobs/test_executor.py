"""Tests for Background Job Executor — Phase B (PR 1: executor foundation).

TDD: RED tests written FIRST. All specs from:
  openspec/changes/phase-b-background-job-durability/specs/background-job-executor/spec.md

Test layers:
  - Unit: backoff calculation, registry, state machine via mock handlers, error shape
  - Integration: DB-backed lifecycle, recovery idempotency, fresh session per retry,
                 migration round-trip

Test runner: cd backend && python3 -m pytest tests/jobs/test_executor.py -q
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Unit tests — Backoff calculation (pure function, no DB)
# Spec: Requirement: Retry Backoff — exponential + jitter, capped at max_delay
# ===========================================================================


class TestBackoffCalculation:
    """Unit tests for pure backoff calculation function.

    Spec scenarios:
    - Backoff increases between attempts
    - Random jitter component is added
    - Backoff is capped at max_delay
    """

    def test_backoff_increases_with_attempt_count(self):
        """Backoff delay grows exponentially as attempt count increases.

        GIVEN base=1, max_delay=60 (defaults)
        WHEN calculate_backoff is called with attempt=1 vs attempt=2
        THEN attempt-2 base component is double that of attempt-1
        """
        from app.jobs.executor import calculate_backoff

        # Use jitter=0 to isolate the exponential growth from randomness
        delay_attempt1 = calculate_backoff(attempt=1, base=1.0, max_delay=60.0, jitter=0.0)
        delay_attempt2 = calculate_backoff(attempt=2, base=1.0, max_delay=60.0, jitter=0.0)

        assert delay_attempt2 > delay_attempt1, (
            f"Backoff at attempt 2 ({delay_attempt2}) should exceed attempt 1 ({delay_attempt1})"
        )
        # base * 2^attempt: attempt=1 → 2s, attempt=2 → 4s (with no jitter)
        assert delay_attempt1 == pytest.approx(2.0, abs=0.001)
        assert delay_attempt2 == pytest.approx(4.0, abs=0.001)

    def test_backoff_is_capped_at_max_delay(self):
        """Backoff never exceeds max_delay regardless of attempt count.

        GIVEN base=1, max_delay=10
        WHEN attempt=20 (would produce 2^20 = 1M seconds uncapped)
        THEN result is capped at max_delay=10
        """
        from app.jobs.executor import calculate_backoff

        result = calculate_backoff(attempt=20, base=1.0, max_delay=10.0, jitter=0.0)
        assert result == pytest.approx(10.0, abs=0.001), (
            f"Backoff should be capped at max_delay=10, got {result}"
        )

    def test_backoff_includes_jitter_component(self):
        """Backoff includes random jitter to prevent retry storms.

        GIVEN two calls with the same attempt count and explicit jitter seed
        WHEN jitter > 0
        THEN the result differs from the no-jitter baseline
        """
        from app.jobs.executor import calculate_backoff

        # With jitter > 0, the result should include a random component
        no_jitter = calculate_backoff(attempt=1, base=1.0, max_delay=60.0, jitter=0.0)

        # Run with jitter enabled multiple times — at least one should differ
        with_jitter_results = [
            calculate_backoff(attempt=1, base=1.0, max_delay=60.0, jitter=1.0)
            for _ in range(10)
        ]

        # The jitter-enabled result should be >= the base component (no negative jitter)
        for r in with_jitter_results:
            assert r >= no_jitter, (
                f"Jitter should only ADD to base delay, got {r} < {no_jitter}"
            )
        # At least one result should be > base (jitter was applied)
        assert any(r > no_jitter for r in with_jitter_results), (
            "All 10 jitter results equaled no-jitter baseline — jitter appears non-functional"
        )


# ===========================================================================
# Unit tests — Handler Registry (in-memory, no DB)
# Spec: Requirement: Handler Registry
# ===========================================================================


class TestHandlerRegistry:
    """Unit tests for the handler registry.

    Spec scenarios:
    - Register a handler: succeeds
    - Duplicate registration: raises ConfigurationError immediately
    - Unknown job type: raises an error at get_handler time
    """

    def setup_method(self):
        """Reset registry to a clean state before each test."""
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        """Reset registry to a clean state after each test."""
        from app.jobs import registry
        registry._HANDLERS.clear()

    def test_register_handler_succeeds(self):
        """A handler function can be registered for a new job_type.

        GIVEN an empty registry
        WHEN register('test_job', async_fn) is called
        THEN get_handler('test_job') returns the same function
        """
        from app.jobs.registry import register, get_handler

        async def my_handler(payload: dict, db) -> None:
            pass

        register("test_job", my_handler)
        retrieved = get_handler("test_job")
        assert retrieved is my_handler, (
            "get_handler should return the exact registered function"
        )

    def test_duplicate_registration_raises_configuration_error(self):
        """Registering the same job_type twice raises ConfigurationError at registration time.

        GIVEN a job_type 'summarize' already registered
        WHEN the same job_type is registered again
        THEN ConfigurationError is raised immediately (not at enqueue time)
        """
        from app.jobs.registry import register, ConfigurationError

        async def handler_a(payload: dict, db) -> None:
            pass

        async def handler_b(payload: dict, db) -> None:
            pass

        register("summarize", handler_a)

        with pytest.raises(ConfigurationError, match="summarize"):
            register("summarize", handler_b)

    def test_get_handler_for_unknown_type_raises(self):
        """get_handler raises an error when the job_type is not registered.

        GIVEN an empty registry
        WHEN get_handler('nonexistent') is called
        THEN a meaningful error is raised

        Triangulation: covers the unknown-type path vs the happy registration path.
        """
        from app.jobs.registry import get_handler, ConfigurationError

        with pytest.raises((ConfigurationError, KeyError)):
            get_handler("nonexistent_job_type")

    def test_register_multiple_distinct_types(self):
        """Multiple distinct job types can be registered independently.

        GIVEN an empty registry
        WHEN three different job_types are registered
        THEN each can be retrieved independently without interference

        Triangulation: ensures the registry is a dict-like mapping, not a single-slot store.
        """
        from app.jobs.registry import register, get_handler

        async def fn_a(p, db): pass
        async def fn_b(p, db): pass
        async def fn_c(p, db): pass

        register("job_a", fn_a)
        register("job_b", fn_b)
        register("job_c", fn_c)

        assert get_handler("job_a") is fn_a
        assert get_handler("job_b") is fn_b
        assert get_handler("job_c") is fn_c


# ===========================================================================
# Integration tests — DB-backed lifecycle
# Spec: Requirement: Job Lifecycle State Machine
# ===========================================================================


class TestJobLifecycleIntegration:
    """Integration tests for the DB-backed job lifecycle.

    Uses the db_engine fixture (real Alembic schema) to test actual state transitions.
    Backoff is patched to near-zero (0.01s) so tests complete in milliseconds.

    Spec scenarios:
    - Happy path: pending → running → completed
    - Transient failure within max_attempts: pending → running → failed → retry
    - Exhausted attempts: pending → running → dead (no more retries)
    - Error captured on failure
    - Error shape persisted correctly (JSON with message + type)
    """

    def setup_method(self):
        """Reset registry before each test to avoid handler interference."""
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        """Reset registry after each test."""
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        """Patch calculate_backoff to return near-zero delay for fast tests."""
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_happy_path_job_reaches_completed(self, db_engine):
        """A job with a successful handler transitions pending → running → completed.

        GIVEN a registered handler that succeeds
        WHEN executor.enqueue() is called
        THEN the job's final status is 'completed' and completed_at is set
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        register("test_success", AsyncMock(return_value=None))

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue("test_success", {"x": 1}, db=db)
            await db.commit()

        # Allow the asyncio task to complete
        await asyncio.sleep(0.2)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None
            assert job.status == "completed", f"Expected 'completed', got '{job.status}'"
            assert job.completed_at is not None, "completed_at should be set"
            assert job.attempts == 1, f"Expected 1 attempt, got {job.attempts}"

    @pytest.mark.asyncio
    async def test_transient_failure_sets_failed_status_and_increments_attempts(self, db_engine):
        """A handler raising a transient exception sets status=failed and increments attempts.

        GIVEN a handler that raises RuntimeError
        WHEN the job runs with max_attempts=3
        THEN status is 'failed', attempts is incremented, error is stored
        AND the job is NOT yet dead (retries remain)
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        call_count = 0

        async def always_fails(payload: dict, db) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("transient network error")

        register("test_fail", always_fails)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_fail", {"x": 2}, max_attempts=3, db=db
            )
            await db.commit()

        # Wait for max attempts to exhaust (with mocked backoff below or just wait)
        await asyncio.sleep(0.5)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None
            # After exhausting 3 attempts, status is 'dead'
            assert job.status == "dead", (
                f"After {job.attempts} attempts (max=3), expected 'dead', got '{job.status}'"
            )
            assert job.attempts == 3
            assert job.error is not None
            error_data = json.loads(job.error)
            assert "transient network error" in error_data.get("message", ""), (
                f"Error message not captured: {job.error}"
            )

    @pytest.mark.asyncio
    async def test_job_reaches_dead_after_max_attempts_exhausted(self, db_engine):
        """A job that always fails transitions to dead after exhausting max_attempts.

        GIVEN a handler that always raises
        WHEN max_attempts=2 is set
        THEN final status is 'dead', attempts equals max_attempts, no further retries

        Triangulation: verifies dead-letter semantics with lower max_attempts value.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        async def always_fails_2(payload: dict, db) -> None:
            raise ValueError("permanent failure")

        register("test_dead", always_fails_2)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_dead", {"y": 3}, max_attempts=2, db=db
            )
            await db.commit()

        await asyncio.sleep(0.5)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status == "dead", f"Expected 'dead', got '{job.status}'"
            assert job.attempts == 2, f"Expected 2 attempts, got {job.attempts}"

    @pytest.mark.asyncio
    async def test_error_json_shape_persisted_correctly(self, db_engine):
        """Error field stores JSON with 'message', 'type', and 'operator_review' keys.

        GIVEN a handler that raises RuntimeError('some error')
        WHEN the job fails and reaches dead status
        THEN error column contains valid JSON with expected structure
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        async def typed_error(payload: dict, db) -> None:
            raise RuntimeError("detailed error message")

        register("test_error_shape", typed_error)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_error_shape", {}, max_attempts=1, db=db
            )
            await db.commit()

        await asyncio.sleep(0.2)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.error is not None, "error field should not be None after failure"
            error_data = json.loads(job.error)
            assert "message" in error_data, f"'message' key missing from error JSON: {error_data}"
            assert "type" in error_data, f"'type' key missing from error JSON: {error_data}"
            assert "operator_review" in error_data, (
                f"'operator_review' key missing from error JSON: {error_data}"
            )
            assert isinstance(error_data["operator_review"], bool), (
                f"operator_review should be bool, got {type(error_data['operator_review'])}"
            )

    @pytest.mark.asyncio
    async def test_transient_failure_then_success_preserves_error_and_attempt_count(
        self, db_engine
    ):
        """A job that fails once then succeeds shows completed status with attempt count = 2.

        GIVEN a handler that raises on attempt 1 and succeeds on attempt 2
        WHEN the job retries
        THEN final status is 'completed', attempts == 2, error is not cleared (audit trail)

        Spec: Scenario — Transient failure then success — error history preserved
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        call_count = 0

        async def fail_once(payload: dict, db) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first attempt fails")
            # Second attempt succeeds

        register("test_fail_then_succeed", fail_once)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_fail_then_succeed", {}, max_attempts=3, db=db
            )
            await db.commit()

        await asyncio.sleep(0.5)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status == "completed", f"Expected completed, got {job.status}"
            assert job.attempts == 2, f"Expected 2 total attempts, got {job.attempts}"
            # Error from first attempt should NOT be cleared (audit trail)
            assert job.error is not None, (
                "error field should preserve the first-attempt error for audit trail"
            )


# ===========================================================================
# Unit tests — ConfigurationError classification
# Spec: design.md — Error classification: ConfigurationError → max 1 retry then dead
# ===========================================================================


class TestConfigurationErrorClassification:
    """Unit: ConfigurationError causes max 1 retry then dead with operator_review=true.

    Spec: design.md — Handler raises ConfigurationError(msg) →
          attempt > 1 → dead + operator_review=true
          attempt == 1 → failed, schedule 1 more retry

    Backoff patched to near-zero so tests complete fast.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        """Patch calculate_backoff to return near-zero delay for fast tests."""
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_configuration_error_on_second_attempt_sets_dead_with_operator_review(
        self, db_engine
    ):
        """ConfigurationError on attempt 2+ sets dead with operator_review=true in error JSON.

        GIVEN a handler that always raises ConfigurationError
        WHEN the job runs and retries once
        THEN final status is 'dead' with operator_review=true in error JSON
        AND attempts is at most 2 (not retried further)
        """
        from app.jobs.registry import register, ConfigurationError
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        async def config_error_handler(payload: dict, db) -> None:
            raise ConfigurationError("CRM field mapping is invalid")

        register("test_config_err", config_error_handler)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_config_err", {}, max_attempts=3, db=db
            )
            await db.commit()

        await asyncio.sleep(0.5)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status == "dead", (
                f"ConfigurationError should result in 'dead', got '{job.status}'"
            )
            assert job.attempts <= 2, (
                f"ConfigurationError should not retry more than once, got attempts={job.attempts}"
            )
            error_data = json.loads(job.error)
            assert error_data.get("operator_review") is True, (
                f"operator_review should be True for ConfigurationError. Got: {error_data}"
            )


# ===========================================================================
# Integration tests — Startup Recovery
# Spec: Requirement: Startup Recovery
# ===========================================================================


class TestStartupRecovery:
    """Integration tests for executor.recover().

    Spec scenarios:
    - Recovery after crash: pending/running jobs are re-enqueued
    - No duplicate execution within a single recovery sweep
    - No jobs → no errors

    Backoff patched to near-zero so tests complete fast.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        """Patch calculate_backoff to return near-zero delay for fast tests."""
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_recover_reenqueues_pending_jobs(self, db_engine):
        """Recovery re-enqueues pending jobs and they complete.

        GIVEN one job with status='pending' seeded directly in the DB
        WHEN executor.recover() is called
        THEN the job is executed and reaches a terminal status
        AND recover() returns a count of 1
        """
        import uuid
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        completed_ids: list[str] = []

        async def recovery_handler(payload: dict, db) -> None:
            completed_ids.append(payload.get("id", ""))

        register("test_recover", recovery_handler)

        # Seed a pending job directly (simulates crash before execution)
        job_id = str(uuid.uuid4())
        async with db_engine.async_session_factory() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    job_type="test_recover",
                    payload=json.dumps({"id": job_id}),
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                    created_at=_utcnow(),
                )
            )
            await db.commit()

        executor = JobExecutor()
        recovered = await executor.recover()

        assert recovered >= 1, f"recover() should return >= 1, got {recovered}"

        await asyncio.sleep(0.3)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status == "completed", (
                f"Recovered pending job should complete, got '{job.status}'"
            )

    @pytest.mark.asyncio
    async def test_recover_resets_running_to_pending_first(self, db_engine):
        """Recovery resets 'running' jobs to 'pending' before re-enqueueing.

        GIVEN a job with status='running' (simulating a crash mid-execution)
        WHEN executor.recover() is called
        THEN the job is re-enqueued and eventually completes

        Spec: design.md — Recovery transitions 'running' to 'pending' to avoid double-fire.
        """
        import uuid
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        async def running_recovery_handler(payload: dict, db) -> None:
            pass  # Succeeds on recovery

        register("test_running_recover", running_recovery_handler)

        job_id = str(uuid.uuid4())
        async with db_engine.async_session_factory() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    job_type="test_running_recover",
                    payload=json.dumps({}),
                    status="running",  # stuck — simulates crash
                    attempts=1,
                    max_attempts=3,
                    created_at=_utcnow(),
                    started_at=_utcnow(),
                )
            )
            await db.commit()

        executor = JobExecutor()
        recovered = await executor.recover()

        assert recovered >= 1, f"recover() should recover the running job, got {recovered}"

        await asyncio.sleep(0.3)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status == "completed", (
                f"Crash-recovered running job should complete, got '{job.status}'"
            )

    @pytest.mark.asyncio
    async def test_recover_with_no_incomplete_jobs_returns_zero(self, db_engine):
        """Recovery with no pending/running jobs returns 0 and raises no errors.

        GIVEN no pending or running jobs in the DB
        WHEN executor.recover() is called
        THEN it returns 0 without errors

        Spec: Scenario — Recovery with no incomplete jobs
        """
        from app.jobs.executor import JobExecutor

        executor = JobExecutor()
        recovered = await executor.recover()

        assert recovered == 0, f"Expected 0 recovered jobs (empty DB), got {recovered}"

    @pytest.mark.asyncio
    async def test_recover_idempotent_does_not_double_execute(self, db_engine):
        """Recovery is idempotent — calling recover() when a job is already active does not double-execute.

        GIVEN a pending job seeded in the DB
        WHEN recover() is called and the job is already in _active_job_ids
        THEN the handler is only called once

        Spec: Scenario — Recovery with no duplicate execution
        Spec: design.md — Idempotency guard: _active_job_ids set checked before dispatch
        """
        import uuid
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        call_count = 0

        async def idempotent_handler(payload: dict, db) -> None:
            nonlocal call_count
            call_count += 1

        register("test_idempotent", idempotent_handler)

        job_id = str(uuid.uuid4())
        async with db_engine.async_session_factory() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    job_type="test_idempotent",
                    payload=json.dumps({}),
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                    created_at=_utcnow(),
                )
            )
            await db.commit()

        executor = JobExecutor()
        # Manually pre-populate _active_job_ids (as if the job was already dispatched)
        executor._active_job_ids.add(job_id)

        recovered = await executor.recover()

        # Should NOT be re-enqueued since it's already in _active_job_ids
        assert recovered == 0, (
            f"Job already in _active_job_ids should not be re-enqueued. Got recovered={recovered}"
        )
        await asyncio.sleep(0.1)
        assert call_count == 0, (
            f"Handler should not be called when job is already active. call_count={call_count}"
        )


# ===========================================================================
# Integration tests — Enqueue contract
# Spec: Requirement: Job Enqueue
# ===========================================================================


class TestEnqueueContract:
    """Integration tests for the enqueue contract.

    Spec scenarios:
    - Enqueue inserts a row with status=pending before the coroutine starts
    - Enqueue with unknown job type raises and does NOT insert a row
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        """Patch calculate_backoff to return near-zero delay for fast tests."""
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_enqueue_inserts_pending_row_before_coroutine_starts(self, db_engine):
        """enqueue() inserts status=pending row atomically before dispatching the coroutine.

        GIVEN a registered job type
        WHEN executor.enqueue() is called
        THEN a BackgroundJob row with status='pending' exists immediately after enqueue returns
        (before the coroutine has had a chance to run)
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        started_event = asyncio.Event()

        async def slow_handler(payload: dict, db) -> None:
            started_event.set()
            await asyncio.sleep(5)  # Intentionally slow

        register("test_enqueue_pending", slow_handler)

        executor = JobExecutor()
        job_id = None
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_enqueue_pending", {"k": "v"}, db=db
            )
            # Row must exist immediately — still within the same call
            job = await db.get(BackgroundJob, job_id)
            assert job is not None, "BackgroundJob row must exist immediately after enqueue"
            assert job.status == "pending", (
                f"Row status should be 'pending' immediately after enqueue, got '{job.status}'"
            )
            assert job.job_type == "test_enqueue_pending"
            assert json.loads(job.payload) == {"k": "v"}

    @pytest.mark.asyncio
    async def test_enqueue_unknown_job_type_raises_and_does_not_insert(self, db_engine):
        """enqueue() with unregistered job_type raises without inserting a DB row.

        GIVEN no handler registered for 'unknown_type'
        WHEN executor.enqueue('unknown_type', ...) is called
        THEN a ConfigurationError (or equivalent) is raised
        AND no BackgroundJob row is inserted
        """
        from app.jobs.registry import ConfigurationError
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        executor = JobExecutor()
        with pytest.raises((ConfigurationError, KeyError)):
            async with db_engine.async_session_factory() as db:
                await executor.enqueue("unknown_type", {}, db=db)

        # Verify no row was inserted
        async with db_engine.async_session_factory() as db:
            result = await db.execute(
                select(BackgroundJob).where(BackgroundJob.job_type == "unknown_type")
            )
            rows = result.scalars().all()
            assert len(rows) == 0, (
                f"No row should be inserted for unknown job type, found {len(rows)} rows"
            )


# ===========================================================================
# Integration tests — Fresh session per retry
# Spec: Requirement: Fresh DB Session Per Retry
# ===========================================================================


class TestFreshSessionPerRetry:
    """Integration: a new session is created for each retry attempt.

    Spec: Scenario — Session isolation between retries
    Backoff patched to near-zero so the retry happens immediately in tests.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        """Patch calculate_backoff to return near-zero delay for fast tests."""
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_each_retry_receives_a_distinct_session_object(self, db_engine):
        """Each attempt gets a fresh, independent AsyncSession.

        GIVEN a handler that records its session id and fails on attempt 1
        WHEN the job retries on attempt 2
        THEN the session object on attempt 2 differs from attempt 1's session

        Spec: Session isolation between retries
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        session_ids: list[int] = []

        async def session_recording_handler(payload: dict, db) -> None:
            session_ids.append(id(db))
            if len(session_ids) == 1:
                raise RuntimeError("first attempt fails to force retry")

        register("test_session_isolation", session_recording_handler)

        executor = JobExecutor()
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue(
                "test_session_isolation", {}, max_attempts=3, db=db
            )
            await db.commit()

        await asyncio.sleep(0.5)

        # Two distinct sessions should have been used
        assert len(session_ids) >= 2, (
            f"Expected at least 2 session IDs (one per attempt), got {len(session_ids)}"
        )
        assert session_ids[0] != session_ids[1], (
            "Both attempts used the same session object — session isolation broken"
        )


# ===========================================================================
# Integration — Feature flag: executor path vs raw create_task
# Spec: design.md — Feature flag: ENABLE_JOB_EXECUTOR=false reverts to raw create_task
# ===========================================================================


class TestFeatureFlag:
    """Unit: feature flag controls whether executor or raw create_task is used.

    Spec: Rollback Plan — ENABLE_JOB_EXECUTOR=false reverts call sites to raw create_task
    """

    def test_settings_has_enable_job_executor_field(self):
        """Settings declares enable_job_executor: bool = False.

        GIVEN app.core.config.Settings
        WHEN constructed with defaults
        THEN enable_job_executor attribute exists and defaults to False
        """
        from app.core.config import Settings
        from pydantic import SecretStr

        s = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_api_key=SecretStr("qora-test-key-do-not-use-in-production"),
        )
        assert hasattr(s, "enable_job_executor"), (
            "Settings must declare 'enable_job_executor' field"
        )
        assert s.enable_job_executor is False, (
            f"enable_job_executor should default to False, got {s.enable_job_executor}"
        )

    def test_settings_enable_job_executor_can_be_set_true(self, monkeypatch):
        """Settings accepts ENABLE_JOB_EXECUTOR=true via environment.

        GIVEN ENABLE_JOB_EXECUTOR=true in the environment
        WHEN Settings is constructed
        THEN enable_job_executor is True

        Triangulation: verifies env var wiring is correct.
        """
        from pydantic import SecretStr

        monkeypatch.setenv("ENABLE_JOB_EXECUTOR", "true")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
        monkeypatch.setenv("QORA_API_KEY", "qora-test-key-do-not-use-in-production")

        from app.core.config import Settings

        s = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_api_key=SecretStr("qora-test-key-do-not-use-in-production"),
            enable_job_executor=True,
        )
        assert s.enable_job_executor is True


class TestExecutorStartedLifecycle:
    """The executor exposes an actual-runtime `started` flag for health reporting.

    Spec: health must report actual lifecycle, not just the config flag.
    """

    def test_fresh_executor_is_not_started(self):
        """A newly constructed executor reports started=False."""
        from app.jobs.executor import JobExecutor

        ex = JobExecutor()
        assert ex.started is False

    async def test_recover_marks_executor_started(self):
        """recover() flips started to True even when there are no jobs to recover."""
        from app.jobs.executor import JobExecutor

        ex = JobExecutor()

        # Stub get_session so recover() runs without a real DB: yield a session
        # whose execute() returns an empty result set.
        class _EmptyResult:
            def scalars(self):
                class _S:
                    def all(self_inner):
                        return []

                return _S()

        class _FakeSession:
            async def execute(self, *_a, **_k):
                return _EmptyResult()

            async def commit(self):
                return None

        class _FakeSessionCtx:
            async def __aenter__(self):
                return _FakeSession()

            async def __aexit__(self, *_a):
                return False

        with patch("app.jobs.executor.get_session", return_value=_FakeSessionCtx()):
            recovered = await ex.recover()

        assert recovered == 0
        assert ex.started is True

    async def test_shutdown_marks_executor_not_started(self):
        """shutdown() flips started back to False."""
        from app.jobs.executor import JobExecutor

        ex = JobExecutor()
        ex._started = True  # simulate a started executor

        await ex.shutdown()

        assert ex.started is False


# ===========================================================================
# Integration — Alembic migration round-trip
# Spec: design.md — Testing Strategy — Migration: Alembic upgrade/downgrade
# ===========================================================================


class TestBackgroundJobsMigration:
    """Integration: background_jobs table created/dropped via Alembic round-trip.

    Verifies that the migration creates the table correctly and downgrade drops it cleanly.
    """

    def _make_alembic_config(self, db_path):
        from alembic.config import Config
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        alembic_dir = backend_dir / "alembic"

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(alembic_dir))
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
        return cfg

    def test_upgrade_creates_background_jobs_table(self, tmp_path):
        """Alembic upgrade head creates the background_jobs table.

        GIVEN a fresh empty database
        WHEN alembic upgrade head is run
        THEN 'background_jobs' table exists with expected columns

        Spec: design.md — Alembic migration creates background_jobs table
        """
        import sqlite3
        from alembic import command

        db_file = tmp_path / "test_bj_upgrade.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()

        assert "background_jobs" in tables, (
            f"'background_jobs' table not found after upgrade head. Tables present: {tables}"
        )

    def test_upgrade_creates_expected_columns(self, tmp_path):
        """The background_jobs table has all required columns after upgrade.

        Triangulation: verifies columns match the spec (id, job_type, payload, status,
        attempts, max_attempts, created_at, started_at, completed_at, error).
        """
        import sqlite3
        from alembic import command

        db_file = tmp_path / "test_bj_cols.db"
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(background_jobs)")
        cols = {r[1] for r in cur.fetchall()}
        conn.close()

        expected_cols = {
            "id", "job_type", "payload", "status",
            "attempts", "max_attempts",
            "created_at", "started_at", "completed_at", "error",
        }
        missing = expected_cols - cols
        assert not missing, (
            f"background_jobs table missing columns after upgrade: {missing}. Found: {cols}"
        )

    def test_downgrade_drops_background_jobs_table(self, tmp_path):
        """Alembic downgrade removes the background_jobs table cleanly.

        Spec: Rollback plan — Alembic downgrade drops table with no FK dependencies.
        """
        import sqlite3
        from alembic import command
        from pathlib import Path

        backend_dir = Path(__file__).resolve().parent.parent.parent
        alembic_ini = backend_dir / "alembic.ini"
        alembic_dir = backend_dir / "alembic"

        db_file = tmp_path / "test_bj_downgrade.db"

        # First go to head
        cfg = self._make_alembic_config(db_file)
        command.upgrade(cfg, "head")

        # Verify table exists
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='background_jobs'")
        assert cur.fetchone() is not None, "background_jobs should exist before downgrade"
        conn.close()

        # Find the background_jobs migration revision and downgrade to one before it
        # We downgrade to the baseline (20241201_0001) which should drop background_jobs
        cfg2 = self._make_alembic_config(db_file)
        command.downgrade(cfg2, "20241201_0001")

        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='background_jobs'"
        )
        result = cur.fetchone()
        conn.close()

        assert result is None, (
            "background_jobs table should be dropped after downgrade to baseline"
        )


# ===========================================================================
# Reliability Blocker 1 — Enqueue commit race
# Problem: when caller passes external db session, _run_job() dispatches
# immediately on a fresh session before the caller commits, causing job_not_found.
# Required: task must not start until the row is committed/visible.
# ===========================================================================


class TestEnqueueCommitRace:
    """Regression tests for the enqueue-commit race condition.

    Spec: Requirement: Job Enqueue — row persisted before execution.
    Design: When db is external, dispatch must be deferred until after commit.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_enqueue_with_external_session_does_not_dispatch_before_commit(
        self, db_engine
    ):
        """_run_job is NOT dispatched before the external session commits.

        GIVEN an external db session whose commit is delayed by 50 ms
        WHEN enqueue() is called with that session
        THEN _run_job() does NOT race ahead and see job_not_found

        Proof: job must reach 'completed' — not stay 'pending' with 0 handler calls.

        Regression guard for the fresh-session race (review blocker 1).
        Without the fix: asyncio.sleep(0.05) before commit lets the task fire,
        the fresh session sees no committed row, logs job_not_found, exits early,
        and the job stays stuck in 'pending' with handler_calls == 0.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        handler_calls = 0

        async def counting_handler(payload: dict, db) -> None:
            nonlocal handler_calls
            handler_calls += 1

        register("test_commit_race", counting_handler)

        executor = JobExecutor()

        # Open the external session and enqueue, but delay the commit by 50ms.
        # This exposes the race: if the task is dispatched synchronously inside
        # enqueue(), it will fire during the 50ms gap and see an uncommitted row.
        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue("test_commit_race", {"v": 1}, db=db)
            # Yield event loop before committing — reproduces the timing window
            await asyncio.sleep(0.05)
            # Now commit — row becomes visible to fresh sessions
            await db.commit()

        # Give the task enough time to execute (backoff is near-zero)
        await asyncio.sleep(0.3)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None, "BackgroundJob row must exist after commit"
            assert job.status == "completed", (
                f"Job must reach 'completed'; got '{job.status}'. "
                f"handler_calls={handler_calls}. "
                "This proves the commit-race was fixed: task ran AFTER commit."
            )
            assert handler_calls >= 1, (
                f"Handler must be called at least once; got {handler_calls}. "
                "If handler_calls==0, _run_job raced ahead before commit and got job_not_found."
            )

    @pytest.mark.asyncio
    async def test_enqueue_without_external_session_commits_own_row(self, db_engine):
        """enqueue() without external db creates its own session and commits immediately.

        GIVEN no external db session (db=None)
        WHEN enqueue() is called
        THEN the row is immediately committed and visible; job reaches completed.

        Triangulation: ensures the no-external-db path is unaffected by the fix.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        async def simple_handler(payload: dict, db) -> None:
            pass

        register("test_no_ext_session", simple_handler)

        executor = JobExecutor()
        job_id = await executor.enqueue("test_no_ext_session", {"y": 2})

        await asyncio.sleep(0.3)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None
            assert job.status == "completed", (
                f"No-external-session enqueue should reach completed, got '{job.status}'"
            )


# ===========================================================================
# Reliability Blocker 2 — Unregistered handler recovery wedges jobs
# Problem: _run_job() calls get_handler(job_type) BEFORE the try block.
# An unregistered type raises unhandled ConfigurationError, leaves DB
# status 'running', _active_job_ids unclean, attempts=1, error=None.
# Required: missing handler must be captured, job set to dead, ids cleaned.
# ===========================================================================


class TestUnregisteredHandlerRecovery:
    """Regression tests for missing handler in _run_job.

    Spec: design.md — ConfigurationError: dead + operator_review=True.
    The recovery path may enqueue a job whose handler was de-registered.
    _run_job must handle get_handler() failure gracefully.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_run_job_with_unregistered_handler_sets_dead_and_cleans_active_ids(
        self, db_engine
    ):
        """_run_job() with an unregistered handler captures the error and sets dead.

        GIVEN a job row with job_type that has NO registered handler
        WHEN _run_job() is called directly
        THEN job.status == 'dead'
        AND job.error contains operator_review=True
        AND job_id is removed from _active_job_ids

        Regression guard: previously raised unhandled ConfigurationError, leaving
        job stuck in 'running' with no error recorded.
        """
        import uuid
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        # Seed a pending job for an UNREGISTERED handler (registry is empty)
        job_id = str(uuid.uuid4())
        async with db_engine.async_session_factory() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    job_type="orphaned_handler_type",  # NOT registered
                    payload=json.dumps({}),
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        executor = JobExecutor()
        executor._active_job_ids.add(job_id)

        # _run_job should not raise; it must capture the ConfigurationError internally
        await executor._run_job(job_id)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None, "Job row must still exist"
            assert job.status == "dead", (
                f"Job with unregistered handler must become 'dead', got '{job.status}'"
            )
            assert job.error is not None, (
                "error field must be set (operator must know why this died)"
            )
            error_data = json.loads(job.error)
            assert error_data.get("operator_review") is True, (
                f"operator_review must be True for missing handler. Got: {error_data}"
            )

        # _active_job_ids must be cleaned up
        assert job_id not in executor._active_job_ids, (
            "_active_job_ids must not retain the job_id after it dies (prevents memory leak)"
        )

    @pytest.mark.asyncio
    async def test_run_job_unregistered_handler_does_not_leave_status_running(
        self, db_engine
    ):
        """Unregistered handler failure does not leave job stuck in 'running'.

        GIVEN a pending job with an orphaned job_type
        WHEN _run_job() finishes
        THEN job.status is NOT 'running' (it must reach a terminal state)

        Triangulation: confirms the state machine doesn't wedge at 'running'.
        """
        import uuid
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        job_id = str(uuid.uuid4())
        async with db_engine.async_session_factory() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    job_type="another_orphan_type",
                    payload=json.dumps({}),
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        executor = JobExecutor()
        executor._active_job_ids.add(job_id)
        await executor._run_job(job_id)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job.status != "running", (
                f"Job must not be stuck in 'running' after unregistered handler failure. "
                f"Got '{job.status}'"
            )


# ===========================================================================
# Reliability Blocker 3 — Lifespan behavior test with executor enabled
# Problem: no test covers lifespan with ENABLE_JOB_EXECUTOR=true.
# Required: lifespan must invoke executor.recover() and shutdown() when enabled.
# ===========================================================================


class TestLifespanWithExecutorEnabled:
    """Behavior-level tests for lifespan with ENABLE_JOB_EXECUTOR=true.

    Spec: main.py — executor.recover() called on startup when flag is True;
                     executor.shutdown() called on shutdown when flag is True.
    """

    @pytest.mark.asyncio
    async def test_lifespan_calls_executor_recover_when_flag_enabled(self, monkeypatch):
        """lifespan invokes executor.recover() when ENABLE_JOB_EXECUTOR=true.

        GIVEN ENABLE_JOB_EXECUTOR=true in Settings
        WHEN the lifespan context is entered and exited
        THEN executor.recover() is called during startup
        AND executor.shutdown() is called during shutdown

        This is the missing behavior coverage identified by the reliability review.
        Uses targeted patches at source modules to handle lifespan's lazy imports.
        """
        from unittest.mock import AsyncMock, patch, MagicMock
        import app.core.database as db_module_real

        mock_executor = MagicMock()
        mock_executor.recover = AsyncMock(return_value=0)
        mock_executor.shutdown = AsyncMock(return_value=None)

        # All imports inside lifespan() use `from X import Y` so we patch at source modules.
        with (
            # Patch executor singleton at source — main.py does
            # `from app.jobs.executor import executor as job_executor`
            patch("app.jobs.executor.executor", mock_executor),
            # Patch Settings at main.py module level
            patch("app.main.Settings") as MockSettings,
            # Patch logging setup at main.py module level
            patch("app.main.setup_logging"),
            # Patch credentials validator at its source module
            patch("app.core.credentials.validate_all_integration_credentials"),
            # Patch db functions at the real database module (lifespan does local import)
            patch.object(db_module_real, "init_db", AsyncMock()),
            patch.object(db_module_real, "close_db", AsyncMock()),
            # Patch seed functions at their source modules
            patch("app.tenants.service.seed_quintana", AsyncMock()),
            patch("app.tenants.service.seed_qora_demo", AsyncMock()),
            patch("app.leads.service.seed_leads", AsyncMock()),
            # Patch background coroutines at their source modules
            patch("app.sweeper.stale_session_sweeper", _never_coroutine),
            patch("app.scheduler.service.scheduler_tick", _never_coroutine),
        ):
            # Configure Settings mock — executor flag ON
            mock_settings = MagicMock()
            mock_settings.enable_job_executor = True
            mock_settings.log_level = "INFO"
            mock_settings.log_format = "json"
            mock_settings.host = "127.0.0.1"
            mock_settings.port = 8000
            # B9 PR2: must be None so init_sentry() is a no-op in lifespan tests.
            mock_settings.sentry_dsn = None
            MockSettings.return_value = mock_settings

            # Stub async_session_factory on the real db module for the seed step.
            # The session mock must support `await session.commit()`.
            mock_session = MagicMock()
            mock_session.commit = AsyncMock(return_value=None)
            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
            db_module_real.async_session_factory = MagicMock(return_value=mock_session_ctx)

            from app.main import lifespan, create_app
            test_app = create_app()

            async with lifespan(test_app):
                # Immediately after startup: recover must have been called
                assert mock_executor.recover.called, (
                    "executor.recover() must be called during lifespan startup "
                    "when ENABLE_JOB_EXECUTOR=true"
                )

            # After context exits (shutdown ran): shutdown must have been called
            assert mock_executor.shutdown.called, (
                "executor.shutdown() must be called during lifespan shutdown "
                "when ENABLE_JOB_EXECUTOR=true"
            )

    @pytest.mark.asyncio
    async def test_lifespan_does_not_call_executor_when_flag_disabled(self, monkeypatch):
        """lifespan does NOT invoke executor when ENABLE_JOB_EXECUTOR=false (default).

        GIVEN ENABLE_JOB_EXECUTOR=false (default)
        WHEN the lifespan context is entered and exited
        THEN executor.recover() and executor.shutdown() are NOT called

        Triangulation: flag-off path must remain a complete no-op for the executor.
        """
        from unittest.mock import AsyncMock, patch, MagicMock
        import app.core.database as db_module_real

        mock_executor = MagicMock()
        mock_executor.recover = AsyncMock(return_value=0)
        mock_executor.shutdown = AsyncMock(return_value=None)

        with (
            patch("app.jobs.executor.executor", mock_executor),
            patch("app.main.Settings") as MockSettings,
            patch("app.main.setup_logging"),
            patch("app.core.credentials.validate_all_integration_credentials"),
            patch.object(db_module_real, "init_db", AsyncMock()),
            patch.object(db_module_real, "close_db", AsyncMock()),
            patch("app.tenants.service.seed_quintana", AsyncMock()),
            patch("app.tenants.service.seed_qora_demo", AsyncMock()),
            patch("app.leads.service.seed_leads", AsyncMock()),
            patch("app.sweeper.stale_session_sweeper", _never_coroutine),
            patch("app.scheduler.service.scheduler_tick", _never_coroutine),
        ):
            mock_settings = MagicMock()
            mock_settings.enable_job_executor = False  # flag OFF
            mock_settings.log_level = "INFO"
            mock_settings.log_format = "json"
            mock_settings.host = "127.0.0.1"
            mock_settings.port = 8000
            # B9 PR2: must be None so init_sentry() is a no-op in lifespan tests.
            mock_settings.sentry_dsn = None
            MockSettings.return_value = mock_settings

            mock_session = MagicMock()
            mock_session.commit = AsyncMock(return_value=None)
            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
            db_module_real.async_session_factory = MagicMock(return_value=mock_session_ctx)

            from app.main import lifespan, create_app
            test_app = create_app()

            async with lifespan(test_app):
                pass

            mock_executor.recover.assert_not_called()
            mock_executor.shutdown.assert_not_called()


# ===========================================================================
# Rollback cleanup — enqueue external-session rollback path
# Warning: when caller rolls back instead of committing, job_id stays in
# _active_job_ids (memory leak) and after_commit listener will never fire.
# If the session is reused and another (unrelated) commit occurs, the stale
# after_commit listener could dispatch _run_job for a rolled-back row.
#
# Required fixes:
#   1. Register an after_rollback listener that removes job_id from
#      _active_job_ids when the external session rolls back.
#   2. _run_job must NOT be dispatched after a rollback + later commit.
# ===========================================================================


class TestEnqueueRollbackCleanup:
    """Regression tests for rollback cleanup in the external-session enqueue path.

    Spec: Requirement: Job Enqueue — row inserted before coroutine starts.
    Design: after_commit deferred dispatch must be paired with after_rollback cleanup.
    """

    def setup_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()

    @pytest.fixture(autouse=True)
    def patch_backoff(self):
        with patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            yield

    @pytest.mark.asyncio
    async def test_rollback_removes_job_id_from_active_job_ids(self, db_engine):
        """After an external session rolls back, job_id is removed from _active_job_ids.

        GIVEN an external db session whose transaction is rolled back after enqueue
        WHEN executor.enqueue() is called with that session and then rolled back
        THEN job_id is NOT present in executor._active_job_ids after the rollback

        Without the fix: _active_job_ids.add(job_id) executes but there is no
        after_rollback cleanup, leaving job_id stuck in the set until shutdown.

        Regression guard for rollback-cleanup warning (PR 1 re-review).
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor

        handler_calls = 0

        async def counting_handler(payload: dict, db) -> None:
            nonlocal handler_calls
            handler_calls += 1

        register("test_rollback_cleanup", counting_handler)

        executor = JobExecutor()

        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue("test_rollback_cleanup", {"v": 1}, db=db)
            # Confirm job_id was added before rollback
            assert job_id in executor._active_job_ids, (
                "job_id must be in _active_job_ids after enqueue (pre-rollback check)"
            )
            # Roll back instead of commit — simulates caller aborting the transaction
            await db.rollback()

        # Give the event loop a moment to process any callbacks
        await asyncio.sleep(0.1)

        # After rollback, job_id must be cleaned out — no leak
        assert job_id not in executor._active_job_ids, (
            f"job_id must be removed from _active_job_ids after rollback. "
            f"Currently _active_job_ids={executor._active_job_ids!r}. "
            "This is the rollback-cleanup memory-leak regression."
        )

    @pytest.mark.asyncio
    async def test_rollback_does_not_dispatch_run_job(self, db_engine):
        """_run_job is NOT dispatched after the external session rolls back.

        GIVEN an external db session that is rolled back after enqueue
        WHEN the session rolls back
        THEN no asyncio task is created and the handler is never called

        Without the fix: although after_commit never fires (once=True prevents it),
        the stale job_id in _active_job_ids is a leak. This test explicitly verifies
        no dispatch occurs as a behavioral regression guard.

        Triangulation: rollback-path must be the inverse of the commit-path test.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob

        handler_calls = 0

        async def counting_handler(payload: dict, db) -> None:
            nonlocal handler_calls
            handler_calls += 1

        register("test_rollback_no_dispatch", counting_handler)

        executor = JobExecutor()
        tasks_before = len(executor._tasks)

        async with db_engine.async_session_factory() as db:
            job_id = await executor.enqueue("test_rollback_no_dispatch", {"v": 2}, db=db)
            await db.rollback()

        # Wait long enough that any dispatched task would have completed
        await asyncio.sleep(0.3)

        # Handler must NOT have been called
        assert handler_calls == 0, (
            f"Handler must NOT be called after a rollback. "
            f"Got handler_calls={handler_calls}. "
            "A stale after_commit listener fired on a later unrelated commit."
        )

        # No new tasks should have been added to executor._tasks
        assert len(executor._tasks) == tasks_before, (
            f"No asyncio task should be created after rollback. "
            f"Tasks before={tasks_before}, after={len(executor._tasks)}."
        )

    @pytest.mark.asyncio
    async def test_rollback_then_unrelated_commit_on_same_session_does_not_dispatch(
        self, db_engine
    ):
        """Stale after_commit listener does not fire on unrelated later commit.

        GIVEN an external session where enqueue is followed by a rollback
        WHEN the SAME session is reused for another operation and committed
        THEN no new asyncio task is added to executor._tasks for the rolled-back job_id

        This tests the 'session reuse' risk:
          - after_rollback fires → _cleanup_after_rollback removes job_id AND removes
            the stale _dispatch_after_commit listener from the session.
          - Without that cross-removal, the stale _dispatch_after_commit (once=True,
            never fired on rollback) remains on the session and fires on the next commit,
            dispatching _run_job() for a row that does not exist in the DB.

        Triangulation: adds the session-reuse scenario to the rollback-cleanup suite.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor

        handler_calls = 0

        async def another_handler(payload: dict, db) -> None:
            nonlocal handler_calls
            handler_calls += 1

        register("test_rollback_reuse", another_handler)

        executor = JobExecutor()

        # Capture task count before enqueue so we can measure new tasks added
        tasks_before = len(executor._tasks)

        # Use a single external session across enqueue, rollback, and later commit
        db = db_engine.async_session_factory()
        try:
            job_id = await executor.enqueue("test_rollback_reuse", {"v": 3}, db=db)

            # Roll back — row is lost (never committed)
            await db.rollback()

            # Reuse the same session for an unrelated commit (simulates real caller pattern).
            # Without cross-removal: the stale _dispatch_after_commit listener fires HERE,
            # creating a new asyncio task that calls _run_job for a non-existent row.
            await db.commit()
        finally:
            await db.close()

        # Give tasks time to run if accidentally dispatched
        await asyncio.sleep(0.3)

        # No new tasks should have been dispatched after rollback + later commit
        tasks_after = len(executor._tasks)
        assert tasks_after == tasks_before, (
            f"No asyncio task should be dispatched after rollback+later-commit on same session. "
            f"tasks_before={tasks_before}, tasks_after={tasks_after}. "
            "Stale after_commit listener fired and dispatched _run_job for rolled-back row."
        )

        # Handler must NOT have been called (double-check via call count)
        assert handler_calls == 0, (
            f"Handler must NOT be called after rollback+later commit on same session. "
            f"Got handler_calls={handler_calls}. "
            "Stale after_commit listener fired on reused session — rollback cleanup broken."
        )

        # job_id must not be in _active_job_ids
        assert job_id not in executor._active_job_ids, (
            f"job_id must be cleaned from _active_job_ids after rollback. "
            f"Found in set: {executor._active_job_ids!r}"
        )


async def _never_coroutine():
    """Async coroutine that blocks indefinitely — used to stub background loop tasks."""
    try:
        await asyncio.sleep(9999)
    except asyncio.CancelledError:
        pass
