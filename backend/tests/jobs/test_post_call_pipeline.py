"""Tests for Durable Post-Call Summarization Pipeline — Phase B PR2a.

PR2a scope:
  2.1 close_session / _reconcile_session enqueue durable 'summarize' job (flag on)
      and fall back to legacy scheduling (flag off).
  2.2 summarize handler calls generate_summary_and_facts_durable.
  2.3 generate_summary_and_facts_durable propagates GPT failures to the executor.
  2.4 Handler is registered via the normal app import path (no false-pass pre-registration).

PR2b (excluded): crm_sync, operator visibility, transcript/user-turn.

Test runner: cd backend && python3 -m pytest tests/jobs/test_post_call_pipeline.py -q
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _sid() -> str:
    return str(uuid.uuid4())


def _make_mock_db() -> AsyncMock:
    """Return a minimal AsyncMock db that makes _run_summarizer happy.

    The summarizer executes two queries in order:
      1. transcript turns  (scalars().all())
      2. call session      (scalar_one_or_none())
    """
    mock_db = AsyncMock()

    fake_turn = MagicMock()
    fake_turn.role = "user"
    fake_turn.content = "Hola"
    fake_turn.timestamp = datetime.datetime.now(datetime.timezone.utc)

    fake_session = MagicMock()
    fake_session.id = _sid()
    fake_session.lead_id = None
    fake_session.client_id = None

    turns_result = MagicMock()
    turns_result.scalars.return_value.all.return_value = [fake_turn]

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = fake_session

    call_count = 0

    async def _execute(_query):
        nonlocal call_count
        call_count += 1
        return turns_result if call_count == 1 else session_result

    mock_db.execute = _execute
    mock_db.begin_nested = MagicMock()
    mock_db.begin_nested.return_value.__aenter__ = AsyncMock()
    mock_db.begin_nested.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_db.get = AsyncMock(return_value=None)
    return mock_db


async def _insert_call_session(db_engine, session_id: str, lead_id: str | None = None) -> None:
    """Insert a minimal CallSession row for integration tests."""
    from app.calls.models import CallSession

    async with db_engine.async_session_factory() as db:
        db.add(CallSession(
            id=session_id,
            client_id="test-client",
            lead_id=lead_id,
            status="initiated",
            agent_id="agent-1",
        ))
        await db.commit()


# ---------------------------------------------------------------------------
# 2.4 — Handler registration via the normal app import path
#
# Guard: tests MUST NOT pre-register 'summarize' before the import under test,
# or they can false-pass even if app.main stops importing app.jobs.handlers.
# ---------------------------------------------------------------------------


class TestSummarizeHandlerRegistration:
    """Prove that 'summarize' is registered by the app startup import path.

    setup_method clears the registry first (no pre-registration), then the
    test imports app.jobs.handlers and asserts the handler is present.
    """

    def setup_method(self):
        from app.jobs import registry
        self._snapshot: dict = dict(registry._HANDLERS)
        registry._HANDLERS.clear()

    def teardown_method(self):
        from app.jobs import registry
        registry._HANDLERS.clear()
        registry._HANDLERS.update(self._snapshot)

    def test_import_registers_summarize_without_pre_registration(self):
        """GIVEN the registry is empty (no pre-registration)
        WHEN app.jobs.handlers is imported (as app.main does at startup)
        THEN 'summarize' is present in the registry.

        Catches BLOCKER B1 regression: if app.main stops importing
        app.jobs.handlers, the registry stays empty and enqueue() raises
        ConfigurationError at runtime.
        """
        from app.jobs import registry

        assert "summarize" not in registry._HANDLERS, "precondition: registry must be empty"

        # Force re-execution of __init__ registration code (may be cached in sys.modules)
        cached = sys.modules.pop("app.jobs.handlers", None)
        try:
            import app.jobs.handlers  # noqa: F401 — registration side-effect
            assert "summarize" in registry._HANDLERS, (
                "'summarize' not registered after importing app.jobs.handlers. "
                "Check that app.main imports app.jobs.handlers at module level."
            )
        finally:
            if cached is not None:
                sys.modules["app.jobs.handlers"] = cached

    def test_app_main_source_imports_jobs_handlers(self):
        """GIVEN app/main.py source
        WHEN read as text
        THEN it contains 'import app.jobs.handlers'.

        Structural guard: catches if someone removes the import from main.py
        before the runtime error surfaces in production.
        """
        from pathlib import Path

        main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
        assert "app.jobs.handlers" in main_py.read_text(encoding="utf-8"), (
            "app/main.py must import app.jobs.handlers at module level."
        )


# ---------------------------------------------------------------------------
# 2.1 — close_session / _reconcile_session routing by flag
# ---------------------------------------------------------------------------


class TestCloseSessionSummarizeRouting:
    """close_session() enqueue branch (flag on) and legacy branch (flag off)."""

    @pytest.mark.asyncio
    async def test_flag_on_enqueues_summarize(self, db_engine):
        """GIVEN ENABLE_JOB_EXECUTOR=true
        WHEN close_session() is called
        THEN executor.enqueue('summarize', {session_id}) is called once.
        """
        from app.calls.service import close_session

        session_id = _sid()
        await _insert_call_session(db_engine, session_id)

        with patch("app.calls.service.settings") as ms, \
             patch("app.calls.service.executor") as me:
            ms.enable_job_executor = True
            me.enqueue = AsyncMock(return_value="job-id")

            async with db_engine.async_session_factory() as db:
                await close_session(db, session_id=session_id, closed_reason="test")

        # PR3 adds a second enqueue call ('transcript_flush'), so assert_called_once()
        # is no longer valid. Assert the first call is still 'summarize' with correct payload.
        assert me.enqueue.called, "executor.enqueue must be called at least once"
        first_call = me.enqueue.call_args_list[0]
        assert first_call.args[0] == "summarize"
        assert first_call.args[1]["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_flag_off_uses_legacy_schedule(self, db_engine):
        """GIVEN ENABLE_JOB_EXECUTOR=false
        WHEN close_session() is called
        THEN _schedule_summarize is called and executor.enqueue is NOT called.
        """
        from app.calls.service import close_session

        session_id = _sid()
        await _insert_call_session(db_engine, session_id)

        with patch("app.calls.service.settings") as ms, \
             patch("app.calls.service.executor") as me, \
             patch("app.calls.service._schedule_summarize") as msched:
            ms.enable_job_executor = False
            me.enqueue = AsyncMock()

            async with db_engine.async_session_factory() as db:
                await close_session(db, session_id=session_id, closed_reason="test")

        me.enqueue.assert_not_called()
        msched.assert_called_once_with(session_id)


class TestReconcileSessionSummarizeRouting:
    """_reconcile_session() enqueue branch (flag on) and legacy branch (flag off).

    Separate class because _reconcile_session() has its OWN enqueue call and
    its own legacy branch — a regression there would not be caught by the
    close_session() tests above.
    """

    @pytest.mark.asyncio
    async def test_flag_on_enqueues_summarize(self, db_engine):
        """GIVEN ENABLE_JOB_EXECUTOR=true and an orphan initiated session
        WHEN _reconcile_session() is called
        THEN executor.enqueue('summarize', {session_id}) is called once.
        """
        from app.calls.service import _reconcile_session

        session_id = _sid()
        lead_id = _sid()
        await _insert_call_session(db_engine, session_id, lead_id=lead_id)

        with patch("app.calls.service.settings") as ms, \
             patch("app.calls.service.executor") as me, \
             patch("app.calls.service._schedule_summarize") as msched:
            ms.enable_job_executor = True
            me.enqueue = AsyncMock(return_value="job-id")

            async with db_engine.async_session_factory() as db:
                result = await _reconcile_session(
                    db,
                    conversation_id="conv-test",
                    client_id="test-client",
                    lead_id=lead_id,
                    closed_reason="call_ended",
                    update_lead_counters=False,
                )

        assert result is not None, "_reconcile_session must return the reconciled session"
        # PR3 adds a second enqueue call ('transcript_flush'); assert first call is summarize.
        assert me.enqueue.called, "executor.enqueue must be called at least once"
        first_call = me.enqueue.call_args_list[0]
        assert first_call.args[0] == "summarize"
        assert first_call.args[1]["session_id"] == result.id
        msched.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_off_uses_legacy_schedule(self, db_engine):
        """GIVEN ENABLE_JOB_EXECUTOR=false and an orphan initiated session
        WHEN _reconcile_session() is called
        THEN _schedule_summarize is called and executor.enqueue is NOT called.
        """
        from app.calls.service import _reconcile_session

        session_id = _sid()
        lead_id = _sid()
        await _insert_call_session(db_engine, session_id, lead_id=lead_id)

        with patch("app.calls.service.settings") as ms, \
             patch("app.calls.service.executor") as me, \
             patch("app.calls.service._schedule_summarize") as msched:
            ms.enable_job_executor = False
            me.enqueue = AsyncMock()

            async with db_engine.async_session_factory() as db:
                result = await _reconcile_session(
                    db,
                    conversation_id="conv-legacy",
                    client_id="test-client",
                    lead_id=lead_id,
                    closed_reason="call_ended",
                    update_lead_counters=False,
                )

        assert result is not None
        msched.assert_called_once_with(result.id)
        me.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# 2.2 — summarize handler calls the durable variant
# ---------------------------------------------------------------------------


class TestSummarizeHandler:
    """Unit tests: summarize_handler must call generate_summary_and_facts_durable
    and propagate exceptions (not swallow them like the legacy fire-and-forget variant).
    """

    @pytest.mark.asyncio
    async def test_calls_durable_variant(self):
        """GIVEN a valid payload
        WHEN summarize_handler is called
        THEN generate_summary_and_facts_durable is called with (session_id, db).
        """
        from app.jobs.handlers.summarize import summarize_handler

        session_id = _sid()
        mock_db = AsyncMock()

        with patch(
            "app.summarizer.generate_summary_and_facts_durable",
            new_callable=AsyncMock,
        ) as mock_gsf:
            await summarize_handler({"session_id": session_id}, mock_db)
            mock_gsf.assert_called_once_with(session_id, mock_db)

    @pytest.mark.asyncio
    async def test_propagates_durable_failure(self):
        """GIVEN generate_summary_and_facts_durable raises RuntimeError
        WHEN summarize_handler is called
        THEN RuntimeError propagates (executor sees failure, applies retry).
        """
        from app.jobs.handlers.summarize import summarize_handler

        with patch(
            "app.summarizer.generate_summary_and_facts_durable",
            new_callable=AsyncMock,
            side_effect=RuntimeError("OpenAI timeout"),
        ):
            with pytest.raises(RuntimeError, match="OpenAI timeout"):
                await summarize_handler({"session_id": _sid()}, AsyncMock())

    @pytest.mark.asyncio
    async def test_raises_on_missing_session_id(self):
        """GIVEN a payload without 'session_id'
        WHEN summarize_handler is called
        THEN ValueError or KeyError is raised.
        """
        from app.jobs.handlers.summarize import summarize_handler

        with pytest.raises((ValueError, KeyError)):
            await summarize_handler({}, AsyncMock())


# ---------------------------------------------------------------------------
# 2.3 — GPT failure propagation through the durable path
# ---------------------------------------------------------------------------


class TestDurableGptFailurePropagation:
    """Verify the durable=True re-raise fix (BLOCKER B4).

    Without fix: _run_summarizer catches GPT exception, writes failed-analysis
    marker, returns None — executor marks job 'completed'. No retry, no alert.
    With fix: durable=True path re-raises → executor marks 'failed' → retries.
    """

    @pytest.mark.asyncio
    async def test_durable_variant_raises_on_gpt_failure(self):
        """GIVEN _call_gpt_summarize raises RuntimeError
        WHEN generate_summary_and_facts_durable() is called
        THEN RuntimeError propagates.
        """
        from app.summarizer import generate_summary_and_facts_durable

        with patch("app.summarizer._call_gpt_summarize",
                   side_effect=RuntimeError("OpenAI timeout")):
            with pytest.raises(RuntimeError, match="OpenAI timeout"):
                await generate_summary_and_facts_durable(_sid(), _make_mock_db())

    @pytest.mark.asyncio
    async def test_legacy_variant_does_not_raise_on_gpt_failure(self):
        """GIVEN _call_gpt_summarize raises RuntimeError
        WHEN generate_summary_and_facts() (legacy) is called
        THEN no exception is raised (fire-and-forget contract preserved).
        """
        from app.summarizer import generate_summary_and_facts

        with patch("app.summarizer._call_gpt_summarize",
                   side_effect=RuntimeError("OpenAI timeout")):
            await generate_summary_and_facts(_sid(), _make_mock_db())  # must not raise

    @pytest.mark.asyncio
    async def test_executor_marks_job_failed_on_gpt_error(self, db_engine):
        """Executor-level: when _call_gpt_summarize raises, the durable summarize
        job must reach status='failed' or 'dead', NOT 'completed'.

        Without BLOCKER B4 fix: executor marks 'completed'. With fix: marks 'failed'.
        """
        from app.jobs.registry import register
        from app.jobs.executor import JobExecutor
        from app.jobs.models import BackgroundJob
        from app.jobs.handlers.summarize import summarize_handler
        from app.calls.models import CallSession, TranscriptTurn
        from app.jobs import registry as _reg

        if "summarize" not in _reg._HANDLERS:
            register("summarize", summarize_handler)

        session_id = _sid()
        async with db_engine.async_session_factory() as db:
            db.add(CallSession(
                id=session_id, client_id="test-client", lead_id=None,
                status="completed", agent_id="agent-1",
            ))
            db.add(TranscriptTurn(
                id=_sid(), session_id=session_id, role="user",
                content="Me interesa un seguro.",
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            ))
            await db.commit()

        executor = JobExecutor()

        with patch("app.summarizer._call_gpt_summarize",
                   side_effect=RuntimeError("OpenAI API timeout")), \
             patch("app.summarizer._get_openai_client",
                   return_value=(AsyncMock(), "gpt-4o-mini")), \
             patch("app.jobs.executor.calculate_backoff", return_value=0.01):
            async with db_engine.async_session_factory() as db:
                job_id = await executor.enqueue(
                    "summarize", {"session_id": session_id},
                    max_attempts=2, db=db,
                )
                await db.commit()

            await asyncio.sleep(0.8)

        async with db_engine.async_session_factory() as db:
            job = await db.get(BackgroundJob, job_id)
            assert job is not None
            assert job.status in ("failed", "dead"), (
                f"BLOCKER B4: expected 'failed'/'dead', got '{job.status}'. "
                "Durable summarize job must propagate GPT errors to the executor."
            )
            assert job.error is not None, "error field must be populated"
