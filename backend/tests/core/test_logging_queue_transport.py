"""Tests for the non-blocking queue transport behind structlog.

The event loop must never perform the synchronous write()+flush() to stdout.
A stalled stdout pipe (Docker log-driver backpressure) would otherwise block
the whole process, not just one request.

Policy under test:
- The calling thread enqueues; a worker thread writes.
- The bounded queue DROPS records when full; callers never block.
- Drops are counted so the policy is observable.
- Output format, level filtering and the stdlib bridge are unchanged.
- setup_logging() is idempotent: no stacked handlers or listener threads.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import threading

import structlog

from app.core.logging import (
    get_dropped_record_count,
    setup_logging,
    shutdown_logging,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StalledStream:
    """A sink whose write() blocks until an externally controlled gate opens.

    Models a stalled stdout pipe. ``timeout`` is a safety valve so a failing
    test cannot hang the suite forever.
    """

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.entered = threading.Event()

    def write(self, data: str) -> int:
        self.entered.set()
        self._gate.wait(timeout=30.0)
        return len(data)

    def flush(self) -> None:
        return None


def _teardown() -> None:
    shutdown_logging()
    structlog.reset_defaults()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# The calling thread must not write directly
# ---------------------------------------------------------------------------


def test_logger_factory_is_not_print_logger_factory() -> None:
    """The configured factory must not write+flush on the calling thread."""
    try:
        setup_logging(log_level="INFO", log_format="json")

        factory = structlog.get_config()["logger_factory"]
        assert not isinstance(factory, structlog.PrintLoggerFactory), (
            "PrintLoggerFactory writes and flushes on the calling thread; "
            "the event loop must hand off to a worker instead."
        )
    finally:
        _teardown()


def test_root_handler_is_a_queue_handler() -> None:
    """The stdlib bridge must also hand off instead of writing inline."""
    import logging.handlers

    try:
        setup_logging(log_level="INFO", log_format="json")

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.handlers.QueueHandler)
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# A stalled sink must not block the event loop
# ---------------------------------------------------------------------------


async def test_logging_from_event_loop_does_not_block_on_stalled_sink() -> None:
    """A stalled downstream sink must not stall the asyncio event loop."""
    gate = threading.Event()
    stream = _StalledStream(gate)
    try:
        setup_logging(
            log_level="INFO",
            log_format="json",
            stream=stream,
            queue_maxsize=256,
        )
        log = structlog.get_logger("stalled_sink")

        heartbeats = 0

        async def beat() -> None:
            nonlocal heartbeats
            for _ in range(200):
                heartbeats += 1
                await asyncio.sleep(0)

        async def emit() -> None:
            for index in range(50):
                log.info("stalled_sink_event", index=index)
                await asyncio.sleep(0)

        # A blocking transport would never let these finish.
        await asyncio.wait_for(asyncio.gather(emit(), beat()), timeout=10.0)

        # The loop stayed responsive while the sink was stuck mid-write.
        assert heartbeats == 200
        assert stream.entered.is_set(), "worker thread should be stuck in write()"
    finally:
        gate.set()
        _teardown()


# ---------------------------------------------------------------------------
# Backpressure policy: DROP, never block
# ---------------------------------------------------------------------------


async def test_full_queue_drops_records_and_caller_returns() -> None:
    """When the bounded queue is full, records are dropped, not awaited."""
    gate = threading.Event()
    stream = _StalledStream(gate)
    try:
        setup_logging(
            log_level="INFO",
            log_format="json",
            stream=stream,
            queue_maxsize=4,
        )
        log = structlog.get_logger("drop_policy")

        before = get_dropped_record_count()

        async def emit() -> None:
            for index in range(500):
                log.info("drop_policy_event", index=index)

        await asyncio.wait_for(emit(), timeout=10.0)

        after = get_dropped_record_count()
        assert after > before, (
            "a bounded queue with a stalled sink must drop records; "
            f"counter went {before} -> {after}"
        )
    finally:
        gate.set()
        _teardown()


# ---------------------------------------------------------------------------
# Format is unchanged — transport change only
# ---------------------------------------------------------------------------


def test_json_format_is_unchanged_through_the_queue() -> None:
    """JSON mode still renders the same single-line JSON fields."""
    buf = io.StringIO()
    try:
        setup_logging(log_level="INFO", log_format="json", stream=buf)
        structlog.get_logger("fmt_json").info("queued_event", key="value")

        # stop() drains the queue before joining the worker.
        shutdown_logging()

        payload = json.loads(buf.getvalue().strip())
        assert payload["event"] == "queued_event"
        assert payload["key"] == "value"
        assert payload["level"] == "info"
        assert "timestamp" in payload
    finally:
        _teardown()


def test_console_format_is_unchanged_through_the_queue() -> None:
    """Console mode still renders human-readable, non-JSON output."""
    buf = io.StringIO()
    try:
        setup_logging(log_level="DEBUG", log_format="console", stream=buf)
        structlog.get_logger("fmt_console").info("console_event", color="test")

        shutdown_logging()

        output = buf.getvalue().strip()
        assert output, "console format should produce output"
        assert "console_event" in output
        try:
            json.loads(output)
        except (json.JSONDecodeError, ValueError):
            pass
        else:  # pragma: no cover - defensive
            raise AssertionError("console output must not be JSON")
    finally:
        _teardown()


def test_level_filtering_still_applies_through_the_queue() -> None:
    """Records below the configured level never reach the sink."""
    buf = io.StringIO()
    try:
        setup_logging(log_level="WARNING", log_format="json", stream=buf)
        log = structlog.get_logger("fmt_level")
        log.info("below_threshold")
        log.warning("above_threshold")

        shutdown_logging()

        output = buf.getvalue()
        assert "below_threshold" not in output
        assert "above_threshold" in output
    finally:
        _teardown()


def test_stdlib_bridge_still_renders_through_the_queue() -> None:
    """uvicorn/SQLAlchemy style stdlib records still reach the same sink."""
    buf = io.StringIO()
    try:
        setup_logging(log_level="DEBUG", log_format="json", stream=buf)
        logging.getLogger("uvicorn.access").info("bridged_message")

        shutdown_logging()

        payload = json.loads(buf.getvalue().strip())
        assert payload["event"] == "bridged_message"
        assert payload["logger"] == "uvicorn.access"
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# Idempotence — no stacked handlers or listener threads
# ---------------------------------------------------------------------------


def test_setup_logging_twice_does_not_stack_handlers_or_listeners() -> None:
    """Repeated configuration must replace, not accumulate, the transport."""
    baseline = threading.active_count()
    try:
        setup_logging(log_level="INFO", log_format="json", stream=io.StringIO())
        setup_logging(log_level="INFO", log_format="json", stream=io.StringIO())
        setup_logging(log_level="INFO", log_format="json", stream=io.StringIO())

        root = logging.getLogger()
        assert len(root.handlers) == 1, (
            f"root logger accumulated handlers: {root.handlers!r}"
        )
        assert threading.active_count() <= baseline + 1, (
            "each setup_logging() call must stop the previous listener thread"
        )
    finally:
        _teardown()


def test_shutdown_logging_is_idempotent_and_leaks_no_threads() -> None:
    """shutdown_logging() must be safe to call repeatedly."""
    baseline = threading.active_count()

    setup_logging(log_level="INFO", log_format="json", stream=io.StringIO())
    shutdown_logging()
    shutdown_logging()

    assert threading.active_count() == baseline
    _teardown()
