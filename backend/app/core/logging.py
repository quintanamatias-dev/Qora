"""QORA — Structured logging setup using structlog.

Supports a LOG_FORMAT toggle:
- "json" (default): single-line JSON suitable for log aggregators and production.
- "console": human-readable colored output for local development.

Installs a stdlib ProcessorFormatter bridge on the root logger so that
uvicorn, SQLAlchemy, and any other stdlib-based libraries appear in the same
structured output stream.

Transport
---------
Rendering happens on the calling thread (it is pure CPU work), but the actual
write()+flush() to stdout happens on a dedicated worker thread behind a bounded
``queue.Queue``. The asyncio event loop therefore never performs a synchronous
write to stdout: a stalled stdout pipe (for example Docker log-driver
backpressure) can no longer block the whole process.

Backpressure policy is DROP. When the bounded queue is full, the record is
discarded and the caller returns immediately; the loop never waits for logging
capacity. Losing log lines under extreme pressure is preferred over stalling a
real-time voice backend. Drops are counted — see ``get_dropped_record_count``.

Spec: sdd/b9-observability/spec — capability: structured-logging
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import queue
import sys
import threading
from typing import Any, TextIO

import structlog
import structlog.stdlib


_VALID_LOG_FORMATS = frozenset({"json", "console"})

# Bounded queue capacity. Large enough to absorb normal bursts, small enough
# that a permanently stalled sink cannot grow memory without limit.
DEFAULT_QUEUE_MAXSIZE = 10_000

# Name of the stdlib logger used as the sink for structlog's native chain.
# It does not propagate: its records carry an already-rendered line, so the
# root logger's ProcessorFormatter must never see them.
_SINK_LOGGER_NAME = "qora.log_sink"
_SINK_LOGGER = logging.getLogger(_SINK_LOGGER_NAME)

# Transport state. Guarded by _STATE_LOCK so repeated setup_logging() calls
# cannot stack listeners or handlers.
_STATE_LOCK = threading.Lock()
_listener: "_BoundedQueueListener | None" = None

# Drop accounting. A plain counter on purpose: reporting drops by logging
# would be self-defeating when the logging transport is the thing saturating.
_DROP_LOCK = threading.Lock()
_dropped_records = 0


def get_dropped_record_count() -> int:
    """Return the process-wide number of log records dropped by backpressure.

    Monotonic for the lifetime of the process; ``setup_logging`` does not reset
    it. Callers interested in a rate should sample it and take deltas.
    """
    with _DROP_LOCK:
        return _dropped_records


def _count_drop(amount: int = 1) -> None:
    global _dropped_records
    with _DROP_LOCK:
        _dropped_records += amount


class _DroppingQueueHandler(logging.handlers.QueueHandler):
    """QueueHandler that drops instead of blocking when the queue is full.

    ``QueueHandler.prepare`` formats the record on the calling thread, so the
    object that reaches the queue is a plain, already-rendered record. Only the
    write/flush is deferred to the listener thread.
    """

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            _count_drop()


class _BoundedQueueListener(logging.handlers.QueueListener):
    """QueueListener with a daemon worker and a bounded, guarded stop().

    The stdlib ``stop()`` uses an unbounded ``put_nowait`` for its sentinel and
    an unbounded ``join()``. Both can deadlock against a full queue or a sink
    that is wedged mid-write, which is exactly the failure this module exists
    to survive.
    """

    def start(self) -> None:
        self._thread = thread = threading.Thread(
            target=self._monitor,
            name="qora-log-writer",
            daemon=True,
        )
        thread.start()

    def enqueue_sentinel(self) -> None:
        # Make room for the sentinel if the queue is saturated: dropping a
        # record is always preferable to never shutting down.
        for _ in range(64):
            try:
                self.queue.put_nowait(self._sentinel)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    _count_drop()
                except queue.Empty:  # pragma: no cover - racy, retried below
                    pass

    def stop(self, timeout: float = 5.0) -> None:  # type: ignore[override]
        thread = self._thread
        if thread is None:
            return
        self.enqueue_sentinel()
        thread.join(timeout)
        self._thread = None


class _QueueLogger:
    """structlog logger that hands the rendered line to the logging queue.

    Deliberately not a writer: it performs an in-memory enqueue only.
    """

    __slots__ = ("name",)

    def __init__(self, name: str | None = None) -> None:
        self.name = name or "qora"

    def _emit(self, level: int, message: Any) -> None:
        _SINK_LOGGER.log(level, message)

    def debug(self, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(logging.DEBUG, message)

    def info(self, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(logging.INFO, message)

    def warning(self, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(logging.WARNING, message)

    def error(self, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(logging.ERROR, message)

    def critical(self, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(logging.CRITICAL, message)

    def log(self, level: int, message: Any = "", *args: Any, **kw: Any) -> None:
        self._emit(level, message)

    # Aliases structlog (or callers) may reach for.
    msg = info
    warn = warning
    exception = error
    fatal = critical
    failure = error

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<_QueueLogger(name={self.name!r})>"


class _QueueLoggerFactory:
    """structlog logger factory producing non-writing :class:`_QueueLogger`s."""

    def __call__(self, *args: Any) -> _QueueLogger:
        return _QueueLogger(args[0] if args else None)


def shutdown_logging(timeout: float = 5.0) -> None:
    """Stop the queue listener and detach its handlers.

    Drains whatever is already queued, then joins the worker thread so the
    process can exit and tests do not leak threads. Safe to call repeatedly.
    """
    global _listener

    with _STATE_LOCK:
        listener = _listener
        _listener = None

    for logger in (logging.getLogger(), _SINK_LOGGER):
        for handler in list(logger.handlers):
            if isinstance(handler, logging.handlers.QueueHandler):
                logger.removeHandler(handler)

    if listener is not None:
        listener.stop(timeout)
        for handler in listener.handlers:
            handler.close()


atexit.register(shutdown_logging)


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "json",
    *,
    stream: TextIO | None = None,
    queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
) -> None:
    """Configure structlog with optional LOG_FORMAT toggle and stdlib bridge.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format — "json" (default) or "console".
        stream: Sink the worker thread writes to. Defaults to ``sys.stdout``.
        queue_maxsize: Bounded capacity of the hand-off queue. Records are
            dropped once it is full — the caller is never made to wait.

    Raises:
        ValueError: When log_format is not "json" or "console".

    Processors (shared pre-processors):
    1. merge_contextvars — inject contextvars (request_id, session_id, etc.)
    2. add_log_level — add "level" field
    3. StackInfoRenderer — include stack info when present
    4. set_exc_info — auto-attach exception info
    5. TimeStamper — ISO-8601 timestamp
    6. JSONRenderer or ConsoleRenderer — output format

    Stdlib bridge:
    Attaches a ProcessorFormatter to the root logger so stdlib loggers
    (uvicorn, SQLAlchemy, etc.) are captured in the same output stream.
    """
    if log_format not in _VALID_LOG_FORMATS:
        raise ValueError(
            f"log_format must be one of {sorted(_VALID_LOG_FORMATS)}, got '{log_format}'. "
            "Set LOG_FORMAT=json for production or LOG_FORMAT=console for development."
        )

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared pre-processors applied before the final renderer.
    # Note: add_logger_name requires a stdlib Logger object — it is only included
    # in the stdlib bridge's foreign_pre_chain (not in the structlog native chain).
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        # NOT PrintLoggerFactory: that writes+flushes on the calling thread,
        # which in this app is the asyncio event loop.
        logger_factory=_QueueLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # ---------------------------------------------------------------------------
    # Stdlib bridge — redirect uvicorn, SQLAlchemy, etc. through structlog
    # ---------------------------------------------------------------------------
    # ProcessorFormatter wraps each stdlib log record with the shared processors
    # so that stdlib-logged lines appear in the same format as structlog lines.
    # Must be installed before uvicorn starts logging to avoid lost lines.
    # ---------------------------------------------------------------------------
    # The stdlib bridge foreign_pre_chain can use add_logger_name because
    # the stdlib logger records carry a .name attribute.
    stdlib_pre_chain: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=stdlib_pre_chain,
    )

    # ---------------------------------------------------------------------------
    # Non-blocking transport — bounded queue + writer thread
    # ---------------------------------------------------------------------------
    # Tear down any previous transport first so repeated configuration replaces
    # rather than stacks listeners and handlers.
    shutdown_logging()

    record_queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)

    # The only handler that actually touches the sink. It runs on the listener
    # thread. Records arrive already rendered, so the formatter is a passthrough.
    sink_handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    sink_handler.setFormatter(logging.Formatter("%(message)s"))

    listener = _BoundedQueueListener(record_queue, sink_handler)
    listener.start()

    # structlog native path: the rendered line is enqueued verbatim.
    native_handler = _DroppingQueueHandler(record_queue)
    native_handler.setFormatter(logging.Formatter("%(message)s"))
    _SINK_LOGGER.handlers.clear()
    _SINK_LOGGER.addHandler(native_handler)
    _SINK_LOGGER.setLevel(logging.DEBUG)  # structlog already filtered by level
    _SINK_LOGGER.propagate = False

    # stdlib bridge path: ProcessorFormatter renders on the calling thread,
    # then the rendered record is enqueued for the writer thread.
    bridge_handler = _DroppingQueueHandler(record_queue)
    bridge_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove any existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(bridge_handler)
    root_logger.setLevel(numeric_level)

    global _listener
    with _STATE_LOCK:
        _listener = listener


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
