"""Tests for PR2b — Durable CRM Sync Handler + Minimal Operator Visibility.

PR2b scope (tasks 2.3, 2.4, 3.1, 3.2):
  2.3 CRM error classification: transient → retry, config → dead + operator_review.
  2.4 crm_sync handler registered; summarizer._schedule_crm_sync uses executor (flag on).
  3.1 Minimal operator query helpers: get_failed_jobs, get_pending_jobs.
  3.2 Dead/failed jobs queryable with job_type, attempts, structured error fields.

Strict TDD: tests written FIRST against APIs that do NOT exist yet.
Test runner: cd backend && python3 -m pytest tests/jobs/test_crm_sync_pipeline.py -q

Excluded (PR2b boundary):
  - transcript/user-turn durability
  - public admin/API router
  - Redis or new services
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lead_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Task 2.3 — CRM sync handler error classification
# Spec: Transient errors retry; config/mapping/schema errors raise ConfigurationError.
# ===========================================================================


class TestCRMSyncHandlerErrorClassification:
    """Unit tests: crm_sync_handler must classify errors correctly.

    Transient errors (timeout, 5xx, network) → raise plain Exception → executor retries.
    Config errors (auth, schema, mapping) → raise ConfigurationError → dead + operator_review.

    Tests target app.jobs.handlers.crm_sync which does NOT exist yet (RED).
    """

    @pytest.mark.asyncio
    async def test_transient_error_propagates_as_plain_exception(self):
        """GIVEN crm_sync_service.sync_lead raises RuntimeError (transient)
        WHEN crm_sync_handler is called
        THEN RuntimeError propagates — executor applies full retry backoff.

        RED: crm_sync_handler does not exist yet.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(side_effect=RuntimeError("API timeout"))
            with pytest.raises(RuntimeError, match="API timeout"):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )

    @pytest.mark.asyncio
    async def test_configuration_error_propagates_as_configuration_error(self):
        """GIVEN crm_sync_service.sync_lead raises ConfigurationError
        WHEN crm_sync_handler is called
        THEN ConfigurationError propagates — executor dead-letters after 1 retry.

        RED: crm_sync_handler does not exist yet.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler
        from app.jobs.registry import ConfigurationError

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(
                side_effect=ConfigurationError("invalid field mapping")
            )
            with pytest.raises(ConfigurationError, match="invalid field mapping"):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )

    @pytest.mark.asyncio
    async def test_exception_with_config_type_name_reclassified_as_configuration_error(self):
        """GIVEN an adapter raises MappingError (type name in _CONFIG_ERROR_TYPE_NAMES)
        WHEN crm_sync_handler is called
        THEN ConfigurationError is raised (reclassified from MappingError).

        RED: crm_sync_handler does not exist yet.
        Triangulation: verifies type-name-based classification path.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler
        from app.jobs.registry import ConfigurationError

        class MappingError(Exception):
            pass

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(
                side_effect=MappingError("unknown source field: 'status_code_typo'")
            )
            with pytest.raises(ConfigurationError):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )

    @pytest.mark.asyncio
    async def test_success_calls_sync_lead_and_returns_normally(self):
        """GIVEN crm_sync_service.sync_lead completes without error
        WHEN crm_sync_handler is called with valid payload
        THEN sync_lead is called once with correct args and handler returns normally.

        RED: crm_sync_handler does not exist yet.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(return_value=None)
            # Must not raise
            await crm_sync_handler(
                {"client_id": "acme-corp", "lead_id": lead_id},
                mock_db,
            )
            mock_svc.sync_lead.assert_called_once_with(
                client_id="acme-corp",
                lead_id=lead_id,
                db_session=mock_db,
            )

    @pytest.mark.asyncio
    async def test_missing_payload_keys_raises_value_error(self):
        """GIVEN payload missing 'client_id' or 'lead_id'
        WHEN crm_sync_handler is called
        THEN ValueError is raised immediately (before DB access).

        RED: crm_sync_handler does not exist yet.
        Triangulation: missing-keys guard vs valid-payload path.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler

        mock_db = AsyncMock()

        with pytest.raises(ValueError, match="payload"):
            await crm_sync_handler({}, mock_db)

    @pytest.mark.asyncio
    async def test_http_400_reclassified_as_configuration_error(self):
        """GIVEN adapter raises an exception with .status_code == 400
        WHEN crm_sync_handler is called
        THEN ConfigurationError is raised (400 = bad request / schema mismatch).

        400 responses are permanent: retrying with the same payload won't fix them.
        Triangulation: extends HTTP status classification beyond 401/403/422.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler
        from app.jobs.registry import ConfigurationError

        class HttpError(Exception):
            def __init__(self, msg: str, status_code: int) -> None:
                super().__init__(msg)
                self.status_code = status_code

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(
                side_effect=HttpError("malformed CRM request", status_code=400)
            )
            with pytest.raises(ConfigurationError, match="HTTP 400"):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )

    @pytest.mark.asyncio
    async def test_http_404_reclassified_as_configuration_error(self):
        """GIVEN adapter raises an exception with .status_code == 404
        WHEN crm_sync_handler is called
        THEN ConfigurationError is raised (404 = wrong endpoint / config error).

        404 responses indicate a missing resource — typically a wrong CRM object ID
        or endpoint URL in crm.yaml. Retrying the same payload won't fix this.
        Triangulation: extends HTTP status classification beyond 401/403/422.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler
        from app.jobs.registry import ConfigurationError

        class HttpError(Exception):
            def __init__(self, msg: str, status_code: int) -> None:
                super().__init__(msg)
                self.status_code = status_code

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(
                side_effect=HttpError("CRM object not found", status_code=404)
            )
            with pytest.raises(ConfigurationError, match="HTTP 404"):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )

    @pytest.mark.asyncio
    async def test_http_500_not_reclassified_remains_transient(self):
        """GIVEN adapter raises an exception with .status_code == 500
        WHEN crm_sync_handler is called
        THEN the original exception propagates (500 = transient server error).

        Triangulation: ensures the 400/404 expansion does NOT absorb 5xx codes.
        """
        from app.jobs.handlers.crm_sync import crm_sync_handler
        from app.jobs.registry import ConfigurationError

        class HttpError(Exception):
            def __init__(self, msg: str, status_code: int) -> None:
                super().__init__(msg)
                self.status_code = status_code

        lead_id = _make_lead_id()
        mock_db = AsyncMock()

        with patch("app.jobs.handlers.crm_sync.crm_sync_service") as mock_svc:
            mock_svc.sync_lead = AsyncMock(
                side_effect=HttpError("internal server error", status_code=500)
            )
            with pytest.raises(HttpError):
                await crm_sync_handler(
                    {"client_id": "test-client", "lead_id": lead_id},
                    mock_db,
                )


# ===========================================================================
# Task 2.4a — crm_sync handler registration
# Spec: 'crm_sync' must be registered in the handler registry on app import.
# ===========================================================================


class TestCRMSyncHandlerRegistration:
    """Prove 'crm_sync' is registered by importing app.jobs.handlers.

    setup_method clears the registry first; teardown_method restores it.
    This mirrors the TestSummarizeHandlerRegistration pattern from PR2a.
    """

    def setup_method(self):
        import sys
        from app.jobs import registry
        self._snapshot: dict = dict(registry._HANDLERS)
        registry._HANDLERS.clear()
        # Remove cached handlers module so __init__ runs again
        sys.modules.pop("app.jobs.handlers", None)
        sys.modules.pop("app.jobs.handlers.crm_sync", None)

    def teardown_method(self):
        import sys
        from app.jobs import registry
        registry._HANDLERS.clear()
        registry._HANDLERS.update(self._snapshot)
        # Restore module cache snapshot is not needed; registry state is fully restored

    def test_import_registers_crm_sync_handler(self):
        """GIVEN the registry is empty (no pre-registration)
        WHEN app.jobs.handlers is imported
        THEN 'crm_sync' is present in the registry.

        RED: app.jobs.handlers.__init__ does not register crm_sync yet.
        """
        from app.jobs import registry

        assert "crm_sync" not in registry._HANDLERS, (
            "Precondition: registry must be empty before import"
        )

        import app.jobs.handlers  # noqa: F401 — side-effect: registration

        assert "crm_sync" in registry._HANDLERS, (
            "'crm_sync' not registered after importing app.jobs.handlers. "
            "Add crm_sync registration to app/jobs/handlers/__init__.py."
        )


# ===========================================================================
# Task 2.4b — summarizer._schedule_crm_sync uses executor when flag is on
# Spec: CRM Sync Is Durable — executor.enqueue called when ENABLE_JOB_EXECUTOR=true.
# ===========================================================================


class TestScheduleCRMSyncDurableRouting:
    """Unit tests: _schedule_crm_sync routes by ENABLE_JOB_EXECUTOR flag.

    Flag on  → executor.enqueue('crm_sync', {client_id, lead_id}, db=db)
    Flag off → legacy asyncio.create_task (fire-and-forget, no executor)

    RED: _schedule_crm_sync does not use the executor yet.
    """

    @pytest.mark.asyncio
    async def test_flag_on_calls_executor_enqueue(self):
        """GIVEN ENABLE_JOB_EXECUTOR=true
        WHEN _schedule_crm_sync is called
        THEN executor.enqueue('crm_sync', payload, db=...) is awaited once.

        RED: summarizer._schedule_crm_sync does not use executor yet.
        """
        from app.summarizer import _schedule_crm_sync

        mock_db = AsyncMock()

        with patch("app.summarizer.settings") as mock_settings, \
             patch("app.summarizer.executor") as mock_executor:
            mock_settings.enable_job_executor = True
            mock_executor.enqueue = AsyncMock(return_value="crm-job-id")

            await _schedule_crm_sync(
                client_id="test-client",
                lead_id="lead-abc",
                db=mock_db,
            )

        mock_executor.enqueue.assert_called_once()
        args, kwargs = mock_executor.enqueue.call_args
        assert args[0] == "crm_sync", (
            f"enqueue must be called with job_type='crm_sync', got '{args[0]}'"
        )
        payload = args[1]
        assert payload["client_id"] == "test-client"
        assert payload["lead_id"] == "lead-abc"

    @pytest.mark.asyncio
    async def test_flag_off_does_not_call_executor(self):
        """GIVEN ENABLE_JOB_EXECUTOR=false
        WHEN _schedule_crm_sync is called
        THEN executor.enqueue is NOT called (legacy create_task path).

        Triangulation: flag-off path must preserve legacy behavior.

        Implementation note: create_task receives a coroutine object. The mock
        must close it immediately to avoid RuntimeWarning: coroutine was never
        awaited. We use a side_effect that closes the coroutine and returns a
        no-op sentinel instead of letting the GC complain.
        """
        from app.summarizer import _schedule_crm_sync

        mock_db = AsyncMock()

        def _close_coro_and_return_none(coro, **kwargs):
            # Close the coroutine to prevent "coroutine was never awaited" warning.
            coro.close()
            return MagicMock()

        with patch("app.summarizer.settings") as mock_settings, \
             patch("app.summarizer.executor") as mock_executor, \
             patch("app.summarizer.asyncio") as mock_asyncio:
            mock_settings.enable_job_executor = False
            mock_executor.enqueue = AsyncMock()
            mock_asyncio.create_task = MagicMock(side_effect=_close_coro_and_return_none)

            await _schedule_crm_sync(
                client_id="test-client",
                lead_id="lead-abc",
                db=mock_db,
            )

        mock_executor.enqueue.assert_not_called()


# ===========================================================================
# Tasks 3.1 / 3.2 — Minimal operator visibility helpers
# Spec: Failures MUST NOT be visible only in application logs.
#       Dead/failed jobs must be queryable with job_type, attempts, error fields.
# ===========================================================================


class TestOperatorJobQueryHelpers:
    """Integration tests: get_failed_jobs and get_pending_jobs query helpers.

    Uses the real DB (db_engine fixture) to insert BackgroundJob rows and
    verify that the query helpers return the correct rows with filtering.

    RED: app.jobs.queries does not exist yet.
    """

    @pytest.mark.asyncio
    async def test_get_failed_jobs_returns_dead_and_failed_rows(self, db_engine):
        """GIVEN dead and failed background_jobs rows
        WHEN get_failed_jobs(db) is called
        THEN both 'dead' and 'failed' rows are returned; 'completed' rows excluded.

        RED: app.jobs.queries.get_failed_jobs does not exist yet.
        """
        from app.jobs.models import BackgroundJob
        from app.jobs.queries import get_failed_jobs

        now = _utcnow()
        dead_id = str(uuid.uuid4())
        failed_id = str(uuid.uuid4())
        completed_id = str(uuid.uuid4())

        async with db_engine.async_session_factory() as db:
            db.add(BackgroundJob(
                id=dead_id, job_type="crm_sync",
                payload=json.dumps({"client_id": "c1", "lead_id": "l1"}),
                status="dead", attempts=2, max_attempts=3, created_at=now,
                error=json.dumps({
                    "message": "auth failure",
                    "type": "ConfigurationError",
                    "operator_review": True,
                }),
            ))
            db.add(BackgroundJob(
                id=failed_id, job_type="summarize",
                payload=json.dumps({"session_id": "s1"}),
                status="failed", attempts=1, max_attempts=3, created_at=now,
                error=json.dumps({
                    "message": "OpenAI timeout",
                    "type": "RuntimeError",
                    "operator_review": False,
                }),
            ))
            db.add(BackgroundJob(
                id=completed_id, job_type="summarize",
                payload=json.dumps({"session_id": "s2"}),
                status="completed", attempts=1, max_attempts=3, created_at=now,
            ))
            await db.commit()

        async with db_engine.async_session_factory() as db:
            rows = await get_failed_jobs(db)

        returned_ids = {r.id for r in rows}
        assert dead_id in returned_ids, "dead job must be in get_failed_jobs result"
        assert failed_id in returned_ids, "failed job must be in get_failed_jobs result"
        assert completed_id not in returned_ids, (
            "completed job must NOT be in get_failed_jobs result"
        )

    @pytest.mark.asyncio
    async def test_get_failed_jobs_with_job_type_filter(self, db_engine):
        """GIVEN dead jobs from two different job types
        WHEN get_failed_jobs(db, job_type='crm_sync') is called
        THEN only crm_sync rows are returned.

        Triangulation: job_type filter must work correctly.
        """
        from app.jobs.models import BackgroundJob
        from app.jobs.queries import get_failed_jobs

        now = _utcnow()
        crm_dead_id = str(uuid.uuid4())
        sum_dead_id = str(uuid.uuid4())

        async with db_engine.async_session_factory() as db:
            db.add(BackgroundJob(
                id=crm_dead_id, job_type="crm_sync",
                payload=json.dumps({"client_id": "c1", "lead_id": "l1"}),
                status="dead", attempts=2, max_attempts=3, created_at=now,
                error=json.dumps({"message": "err", "type": "ConfigurationError", "operator_review": True}),
            ))
            db.add(BackgroundJob(
                id=sum_dead_id, job_type="summarize",
                payload=json.dumps({"session_id": "s1"}),
                status="dead", attempts=3, max_attempts=3, created_at=now,
                error=json.dumps({"message": "gpt err", "type": "RuntimeError", "operator_review": False}),
            ))
            await db.commit()

        async with db_engine.async_session_factory() as db:
            rows = await get_failed_jobs(db, job_type="crm_sync")

        assert all(r.job_type == "crm_sync" for r in rows), (
            "job_type filter must return only crm_sync rows"
        )
        assert any(r.id == crm_dead_id for r in rows)

    @pytest.mark.asyncio
    async def test_get_failed_jobs_error_shape_accessible(self, db_engine):
        """GIVEN a dead crm_sync job with structured error JSON
        WHEN get_failed_jobs is called
        THEN error JSON is parseable and contains operator_review, type, message.

        Spec: operator must see structured error fields — not just log messages.
        """
        from app.jobs.models import BackgroundJob
        from app.jobs.queries import get_failed_jobs

        now = _utcnow()
        job_id = str(uuid.uuid4())
        error_payload = {
            "message": "schema mismatch: unknown field 'lead_status_v2'",
            "type": "ConfigurationError",
            "operator_review": True,
        }

        async with db_engine.async_session_factory() as db:
            db.add(BackgroundJob(
                id=job_id, job_type="crm_sync",
                payload=json.dumps({"client_id": "acme", "lead_id": "l99"}),
                status="dead", attempts=2, max_attempts=3, created_at=now,
                error=json.dumps(error_payload),
            ))
            await db.commit()

        async with db_engine.async_session_factory() as db:
            rows = await get_failed_jobs(db, job_type="crm_sync")

        target = next((r for r in rows if r.id == job_id), None)
        assert target is not None

        parsed = json.loads(target.error)
        assert parsed["operator_review"] is True
        assert parsed["type"] == "ConfigurationError"
        assert "schema mismatch" in parsed["message"]

    @pytest.mark.asyncio
    async def test_get_pending_jobs_returns_pending_and_running_rows(self, db_engine):
        """GIVEN pending and running background_jobs rows
        WHEN get_pending_jobs(db) is called
        THEN both 'pending' and 'running' rows are returned.

        RED: app.jobs.queries.get_pending_jobs does not exist yet.
        Triangulation: pending helper vs failed helper.
        """
        from app.jobs.models import BackgroundJob
        from app.jobs.queries import get_pending_jobs

        now = _utcnow()
        pending_id = str(uuid.uuid4())
        running_id = str(uuid.uuid4())
        dead_id = str(uuid.uuid4())

        async with db_engine.async_session_factory() as db:
            db.add(BackgroundJob(
                id=pending_id, job_type="crm_sync",
                payload=json.dumps({"client_id": "c1", "lead_id": "l1"}),
                status="pending", attempts=0, max_attempts=3, created_at=now,
            ))
            db.add(BackgroundJob(
                id=running_id, job_type="summarize",
                payload=json.dumps({"session_id": "s1"}),
                status="running", attempts=1, max_attempts=3, created_at=now,
            ))
            db.add(BackgroundJob(
                id=dead_id, job_type="crm_sync",
                payload=json.dumps({"client_id": "c2", "lead_id": "l2"}),
                status="dead", attempts=3, max_attempts=3, created_at=now,
                error=json.dumps({"message": "err", "type": "RuntimeError", "operator_review": False}),
            ))
            await db.commit()

        async with db_engine.async_session_factory() as db:
            rows = await get_pending_jobs(db)

        returned_ids = {r.id for r in rows}
        assert pending_id in returned_ids, "pending job must appear in get_pending_jobs"
        assert running_id in returned_ids, "running job must appear in get_pending_jobs"
        assert dead_id not in returned_ids, "dead job must NOT appear in get_pending_jobs"
