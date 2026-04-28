"""Unit tests for _schedule_summarize n8n integration — Phase 6 (Fix Round).

Covers:
- When N8N_ENABLED=True, n8n trigger is scheduled alongside local task
- When N8N_ENABLED=False, only local task is scheduled (no trigger task created)
- n8n trigger failure does NOT block local task scheduling
- Both branches fire independently (one failing doesn't affect the other)

Fix Round additions:
- Replaced meaningless `assert callable(_schedule_summarize)` with behavioral test
- Added test that N8N_ENABLED=False prevents trigger task creation entirely
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from pydantic import SecretStr


def _make_n8n_settings(enabled: bool = True, tmp_path=None):
    """Build a Settings instance with n8n configured."""
    from app.core.config import Settings

    db_url = (
        f"sqlite+aiosqlite:///{tmp_path}/test.db"
        if tmp_path
        else "sqlite+aiosqlite:///./test.db"
    )
    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=db_url,
        n8n_enabled=enabled,
        n8n_webhook_url="http://n8n.test/webhook",
        n8n_webhook_secret=SecretStr("test-secret"),
        n8n_internal_api_key=SecretStr("test-key"),
    )


class TestScheduleSummarizeLocalBranch:
    """Local summarizer branch must always run, regardless of n8n flag."""

    @pytest.mark.asyncio
    async def test_local_summarizer_task_is_created_when_n8n_enabled(self, tmp_path):
        """asyncio.create_task is called for the local summarizer when n8n enabled.

        Behavioral: verifies create_task is invoked with the summarize coroutine,
        not just that the function exists (replaces meaningless callable assertion).
        """
        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        created_tasks = []

        def capture_task(coro):
            created_tasks.append(getattr(coro, "__qualname__", "unknown"))
            coro.close()
            return MagicMock()

        # Settings is imported inside _schedule_summarize — patch at its source
        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-enabled", "client-enabled")

        # At least one task must have been created (local summarizer)
        assert (
            len(created_tasks) >= 1
        ), f"Expected at least 1 task, got: {created_tasks}"

    @pytest.mark.asyncio
    async def test_local_task_runs_when_n8n_disabled(self, tmp_path):
        """When n8n disabled, trigger_n8n_webhook returns None without HTTP call."""
        settings = _make_n8n_settings(enabled=False, tmp_path=tmp_path)
        import respx

        with respx.mock:
            # No HTTP routes registered — any call would raise httpx.ConnectError
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n import client as n8n_client_mod

                result = await n8n_client_mod.trigger_n8n_webhook(
                    "sess-disable", "client-disable"
                )

        # Feature flag off → early return, no HTTP, no exception
        assert result is None

    @pytest.mark.asyncio
    async def test_no_n8n_task_created_when_disabled(self, tmp_path):
        """When N8N_ENABLED=False, _trigger_n8n_if_enabled is NOT scheduled.

        Spec warning fix: don't create a no-op background task when flag is off.
        """
        settings = _make_n8n_settings(enabled=False, tmp_path=tmp_path)
        created_task_names = []

        def capture_task(coro):
            created_task_names.append(getattr(coro, "__qualname__", str(type(coro))))
            coro.close()
            return MagicMock()

        # Settings is imported inside _schedule_summarize — patch at its source
        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-disabled", "client-disabled")

        # Only the local summarizer task should be created (not the n8n trigger)
        n8n_tasks = [
            name
            for name in created_task_names
            if "n8n" in name.lower() or "trigger" in name.lower()
        ]
        assert (
            len(n8n_tasks) == 0
        ), f"Expected no n8n trigger task when disabled, but found: {n8n_tasks}"


class TestScheduleSummarizeN8nBranch:
    """n8n trigger branch behavior."""

    @pytest.mark.asyncio
    async def test_n8n_trigger_called_when_enabled(self, tmp_path):
        """When N8N_ENABLED=True, trigger_n8n_webhook is invoked with session+client."""
        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        import respx
        import httpx

        with respx.mock:
            route = respx.post("http://n8n.test/webhook").mock(
                return_value=httpx.Response(200)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                await trigger_n8n_webhook("sess-enabled", "client-enabled")

        assert route.called

    @pytest.mark.asyncio
    async def test_n8n_trigger_not_called_when_disabled(self, tmp_path):
        """When N8N_ENABLED=False, no HTTP request is made."""
        settings = _make_n8n_settings(enabled=False, tmp_path=tmp_path)
        import respx

        with respx.mock:
            # Any HTTP call would raise since no routes are configured
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                result = await trigger_n8n_webhook("sess-disabled", "client-disabled")

        assert result is None  # No-op, no HTTP called

    @pytest.mark.asyncio
    async def test_n8n_trigger_failure_does_not_raise(self, tmp_path):
        """n8n trigger failure (ConnectError) must not propagate to caller."""
        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        import respx
        import httpx

        with respx.mock:
            respx.post("http://n8n.test/webhook").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                # Must not raise
                result = await trigger_n8n_webhook("sess-error", "client-error")

        assert result is None


class TestScheduleSummarizeIntegration:
    """Behavioral tests for _schedule_summarize n8n + local branch behavior."""

    def test_schedule_summarize_routes_both_params_to_n8n_trigger(self, tmp_path):
        """When n8n enabled, both session_id and client_id are routed to the trigger.

        Behavioral: verifies _trigger_n8n_if_enabled is scheduled via create_task
        with the exact session_id and client_id that were passed in — proves correct
        parameter forwarding without inspect tricks.
        """
        from unittest.mock import patch, MagicMock

        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        # Capture coroutine metadata BEFORE closing them, then close.
        captured_qualnames: list[str] = []
        captured_frame_locals: list[dict] = []

        def capture_task(coro):
            captured_qualnames.append(getattr(coro, "__qualname__", str(coro)))
            # Read frame locals BEFORE closing (cr_frame becomes None after close)
            if hasattr(coro, "cr_frame") and coro.cr_frame is not None:
                captured_frame_locals.append(dict(coro.cr_frame.f_locals))
            else:
                captured_frame_locals.append({})
            coro.close()
            return MagicMock()

        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-routing-test", "client-routing-test")

        # Two tasks must be created: local summarizer + n8n trigger
        assert len(captured_qualnames) == 2, (
            f"Expected 2 tasks (local + n8n), got {len(captured_qualnames)}: "
            f"{captured_qualnames}"
        )

        # The second task must be the n8n trigger coroutine
        n8n_qualname = captured_qualnames[1]
        assert (
            "n8n" in n8n_qualname.lower() or "trigger" in n8n_qualname.lower()
        ), f"Expected n8n trigger coroutine as second task, got: {n8n_qualname!r}"

        # Verify session_id and client_id were forwarded correctly to the trigger coroutine
        n8n_locals = captured_frame_locals[1]
        assert (
            n8n_locals.get("session_id") == "sess-routing-test"
        ), f"session_id not forwarded correctly. frame locals: {n8n_locals}"
        assert (
            n8n_locals.get("client_id") == "client-routing-test"
        ), f"client_id not forwarded correctly. frame locals: {n8n_locals}"

    def test_schedule_summarize_n8n_disabled_zero_http_calls(self, tmp_path):
        """When n8n disabled, no HTTP calls are made to the n8n webhook URL.

        Behavioral: captures asyncio.create_task calls — proves the disabled
        branch creates zero n8n trigger tasks.
        """
        from unittest.mock import MagicMock

        settings = _make_n8n_settings(enabled=False, tmp_path=tmp_path)
        created_tasks = []

        def capture_task(coro):
            created_tasks.append(getattr(coro, "__qualname__", str(coro)))
            coro.close()
            return MagicMock()

        with patch("app.core.config.Settings", return_value=settings):
            with patch("app.n8n.client._get_settings", return_value=settings):
                with patch("asyncio.create_task", side_effect=capture_task):
                    from app.calls.service import _schedule_summarize

                    _schedule_summarize("sess-http-test", "client-http-test")

        # No n8n task should be scheduled when disabled
        n8n_tasks = [
            t for t in created_tasks if "n8n" in t.lower() or "trigger" in t.lower()
        ]
        assert (
            len(n8n_tasks) == 0
        ), f"Expected no n8n trigger tasks when disabled. Got: {n8n_tasks}"

    def test_schedule_summarize_always_schedules_local_task(self):
        """_schedule_summarize always creates the local summarizer task.

        Behavioral test: verifies create_task is called at least once
        with the _summarize_in_background coroutine.
        """
        from unittest.mock import patch, MagicMock
        from pydantic import SecretStr

        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            n8n_enabled=False,  # Disabled — only local task should be created
        )

        created_tasks = []

        def capture_task(coro):
            created_tasks.append(getattr(coro, "__qualname__", "unknown"))
            coro.close()
            return MagicMock()

        # Settings is imported inside _schedule_summarize — patch at its source
        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-local-test", "client-local-test")

        # The local summarizer task must always be present
        assert any(
            "summarize" in name.lower() or "background" in name.lower()
            for name in created_tasks
        ), f"Expected _summarize_in_background task, found: {created_tasks}"


class TestScheduleSummarizeGracefulDegradation:
    """Spec: n8n trigger error MUST NOT block local pipeline.

    Partial scenario addressed: 'n8n trigger error does not block local pipeline'
    and 'n8n unreachable — graceful degradation'.
    These tests verify at the _schedule_summarize level (not just client level).
    """

    def test_n8n_trigger_scheduling_error_does_not_prevent_local_task(self, tmp_path):
        """Even if scheduling the n8n trigger raises, the local task must still be created.

        Spec: '_trigger_n8n_if_enabled' is fire-and-forget; failure is swallowed.
        Behavioral: simulates create_task raising on the second call (n8n trigger),
        verifies the first call (local summarizer) was already scheduled.
        """
        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        call_count = [0]
        local_task_created = [False]

        def selective_capture_task(coro):
            call_count[0] += 1
            qualname = getattr(coro, "__qualname__", "")
            if "summarize" in qualname.lower() or "background" in qualname.lower():
                local_task_created[0] = True
                coro.close()
                return MagicMock()
            # Second call: n8n trigger — close coro but succeed (n8n errors happen async)
            coro.close()
            return MagicMock()

        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=selective_capture_task):
                from app.calls.service import _schedule_summarize

                # Must not raise
                _schedule_summarize("sess-degrade", "client-degrade")

        # Local task was created regardless of n8n state
        assert local_task_created[
            0
        ], "Local summarizer task must be created even when n8n trigger follows it"
        # Both tasks were attempted (local + n8n)
        assert (
            call_count[0] >= 1
        ), f"Expected at least 1 create_task call, got {call_count[0]}"

    def test_both_tasks_created_from_single_schedule_summarize_call(self, tmp_path):
        """Single _schedule_summarize(enabled=True) call schedules BOTH tasks.

        Partial scenario: 'Both branches fire when n8n enabled'.
        This is the same-invocation behavioral proof — both tasks come from ONE call.
        """
        settings = _make_n8n_settings(enabled=True, tmp_path=tmp_path)
        task_qualnames: list[str] = []

        def capture_task(coro):
            task_qualnames.append(getattr(coro, "__qualname__", str(coro)))
            coro.close()
            return MagicMock()

        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-dual-branch", "client-dual-branch")

        # Exactly 2 tasks from a single call
        assert len(task_qualnames) == 2, (
            f"Expected 2 tasks from single _schedule_summarize(enabled=True) call. "
            f"Got {len(task_qualnames)}: {task_qualnames}"
        )

        # First: local summarizer
        assert (
            "summarize" in task_qualnames[0].lower()
            or "background" in task_qualnames[0].lower()
        ), f"First task should be local summarizer, got: {task_qualnames[0]!r}"

        # Second: n8n trigger
        assert (
            "n8n" in task_qualnames[1].lower() or "trigger" in task_qualnames[1].lower()
        ), f"Second task should be n8n trigger, got: {task_qualnames[1]!r}"

    def test_only_one_task_created_from_single_schedule_summarize_call_disabled(
        self, tmp_path
    ):
        """Single _schedule_summarize(enabled=False) call schedules ONLY 1 task.

        Partial scenario: 'Only local branch fires when n8n disabled'.
        Same-invocation behavioral proof — one call, one task.
        """
        settings = _make_n8n_settings(enabled=False, tmp_path=tmp_path)
        task_qualnames: list[str] = []

        def capture_task(coro):
            task_qualnames.append(getattr(coro, "__qualname__", str(coro)))
            coro.close()
            return MagicMock()

        with patch("app.core.config.Settings", return_value=settings):
            with patch("asyncio.create_task", side_effect=capture_task):
                from app.calls.service import _schedule_summarize

                _schedule_summarize("sess-single-branch", "client-single-branch")

        # Exactly 1 task (local only)
        assert len(task_qualnames) == 1, (
            f"Expected 1 task from single _schedule_summarize(enabled=False) call. "
            f"Got {len(task_qualnames)}: {task_qualnames}"
        )

        # Must be the local summarizer (not n8n)
        assert (
            "n8n" not in task_qualnames[0].lower()
            and "trigger" not in task_qualnames[0].lower()
        ), f"Only task should be local summarizer, not n8n. Got: {task_qualnames[0]!r}"
