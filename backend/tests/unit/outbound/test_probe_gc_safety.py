"""Tests for probe task GC-safety — strong reference retention.

Spec: Resilience fix — probe task must not be silently cancelled by CPython GC.

The `_fire_probe` helper in outbound/service.py uses asyncio.create_task().
CPython only keeps a weak reference to bare tasks, so without explicit retention
the GC can cancel the task before it completes — a silent data-loss risk.

Fix: module-level `_background_tasks` set retains a strong reference while the
task is in-flight; a done-callback discards it upon completion.

Tests here verify:
  1. The `_background_tasks` set is populated while a probe task is in flight.
  2. The done-callback removes the task from the set after completion.
  3. The fix covers BOTH call sites in `_fire_probe`
     (accepted path + ambiguous-timeout path) — verified indirectly via
     the existing test_probe.py::TestServiceHookFiresProbe tests; here we
     focus exclusively on the reference-retention contract.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import SecretStr

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    s = MagicMock()
    s.elevenlabs_api_key = SecretStr("test-key")
    return s


# ---------------------------------------------------------------------------
# Tests: strong-reference retention
# ---------------------------------------------------------------------------


class TestProbeTaskGCSafety:
    """_fire_probe retains a strong reference to the probe task."""

    @pytest.mark.asyncio
    async def test_background_tasks_set_exists_on_module(self):
        """outbound.service exposes a module-level _background_tasks set.

        GIVEN the outbound.service module is imported
        WHEN _background_tasks is accessed
        THEN it is a set (the strong-reference registry).
        """
        from app.outbound import service as svc_module

        assert hasattr(svc_module, "_background_tasks"), (
            "outbound.service must expose a module-level _background_tasks set "
            "for strong-reference retention of fire-and-forget probe tasks"
        )
        assert isinstance(svc_module._background_tasks, set), (
            "_background_tasks must be a set, got "
            f"{type(svc_module._background_tasks).__name__!r}"
        )

    @pytest.mark.asyncio
    async def test_fire_probe_adds_task_to_background_tasks(self):
        """_fire_probe adds the created task to _background_tasks.

        GIVEN _fire_probe is called
        WHEN asyncio.create_task fires the probe coroutine
        THEN the resulting task is present in _background_tasks before it completes.

        Strategy: patch probe_call_evidence with a coroutine that blocks on an
        Event so we can inspect _background_tasks while the task is still live.
        """
        from app.outbound import service as svc_module

        # Clear the set before the test to avoid state from other tests.
        svc_module._background_tasks.clear()

        probe_started = asyncio.Event()
        probe_can_finish = asyncio.Event()

        async def _blocking_probe(**kwargs):
            probe_started.set()
            await probe_can_finish.wait()

        with patch(
            "app.outbound.service._fire_probe",
            wraps=lambda **kwargs: _patched_fire_probe(svc_module, _blocking_probe, **kwargs),
        ):
            # Call _fire_probe directly to inspect the internals.
            # We patch probe_call_evidence at the source used inside _fire_probe.
            pass

        # Alternative: call _fire_probe directly with a patched probe_call_evidence.
        svc_module._background_tasks.clear()

        with patch("app.outbound.probe.probe_call_evidence", side_effect=_blocking_probe):
            svc_module._fire_probe(
                session_id="sess-gc-test",
                agent_id="agent-gc",
                to_number="+14155550001",
                settings=_make_settings(),
            )

        # Give the event loop a chance to schedule the task and reach probe_started.
        await asyncio.sleep(0)

        # The task must be in the set while still in flight.
        assert len(svc_module._background_tasks) >= 1, (
            "_background_tasks must contain the probe task while it is still running. "
            "Without a strong reference CPython may GC the task before it completes."
        )

        # Unblock the probe so the event loop can clean up.
        probe_can_finish.set()
        # Drain the event loop so the done-callback runs.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_done_callback_removes_task_from_set_after_completion(self):
        """The done-callback removes the task from _background_tasks after it finishes.

        GIVEN a probe task is added to _background_tasks via _fire_probe
        WHEN the task completes
        THEN _background_tasks no longer contains it (no unbounded growth).
        """
        from app.outbound import service as svc_module

        svc_module._background_tasks.clear()

        completed = asyncio.Event()

        async def _fast_probe(**kwargs):
            # Completes immediately.
            completed.set()

        with patch("app.outbound.probe.probe_call_evidence", side_effect=_fast_probe):
            svc_module._fire_probe(
                session_id="sess-gc-cleanup",
                agent_id="agent-gc",
                to_number="+14155550002",
                settings=_make_settings(),
            )

        # Let the task run to completion and the done-callback execute.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(svc_module._background_tasks) == 0, (
            "_background_tasks must be empty after the probe task completes. "
            "The done-callback (set.discard) must remove finished tasks to prevent "
            "unbounded set growth."
        )

    @pytest.mark.asyncio
    async def test_multiple_concurrent_probes_all_retained(self):
        """Multiple concurrent probe tasks are all retained in _background_tasks.

        GIVEN two calls to _fire_probe before either probe completes
        WHEN _background_tasks is inspected
        THEN both tasks are present (no task is dropped between creation and registration).
        """
        from app.outbound import service as svc_module

        svc_module._background_tasks.clear()

        gate = asyncio.Event()

        async def _gated_probe(**kwargs):
            await gate.wait()

        with patch("app.outbound.probe.probe_call_evidence", side_effect=_gated_probe):
            svc_module._fire_probe(
                session_id="sess-gc-multi-1",
                agent_id="agent-gc",
                to_number="+14155550001",
                settings=_make_settings(),
            )
            svc_module._fire_probe(
                session_id="sess-gc-multi-2",
                agent_id="agent-gc",
                to_number="+14155550002",
                settings=_make_settings(),
            )

        await asyncio.sleep(0)

        assert len(svc_module._background_tasks) >= 2, (
            "Both concurrent probe tasks must be retained in _background_tasks. "
            f"Found {len(svc_module._background_tasks)} task(s)."
        )

        # Unblock both probes.
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # After both finish, the set must be empty.
        assert len(svc_module._background_tasks) == 0, (
            "_background_tasks must be empty after all concurrent probes complete."
        )


# ---------------------------------------------------------------------------
# Helper: not actually used (alternative approach in test above is direct)
# ---------------------------------------------------------------------------


def _patched_fire_probe(svc_module, probe_fn, **kwargs):
    """Not used directly — kept as documentation of the alternative approach."""
    pass
