"""QORA — Structured logging setup using structlog.

B9 update: adds LOG_FORMAT toggle (json|console) and stdlib logging bridge.

The stdlib bridge routes uvicorn, SQLAlchemy, and Alembic stdlib logging output
through the structlog processor chain so their log lines carry the active
correlation ID and are formatted consistently with application logs.

Design: openspec/changes/phase-b-structured-logging-error-monitoring/design.md
  - Architecture Decision #3: ProcessorFormatter for stdlib bridge
  - Architecture Decision #4: LOG_FORMAT as Literal enum in Settings
"""

from __future__ import annotations

import logging
import logging.config

import structlog


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure structlog with JSON or console output plus a stdlib bridge.

    Processors (applied in order):
    1. merge_contextvars    — inject contextvars (request_id, session_id, etc.)
    2. add_log_level        — add "level" field
    3. StackInfoRenderer    — include stack info when present
    4. set_exc_info         — auto-attach exception info
    5. TimeStamper          — ISO-8601 timestamp
    6. Renderer             — JSONRenderer (default) or ConsoleRenderer (console)

    stdlib bridge:
        A logging.config.dictConfig entry points all root-level stdlib loggers
        through structlog.stdlib.ProcessorFormatter so their output passes through
        the same processor chain and carries active contextvars (e.g. request_id).
        The stdlib root handler is the sole handler to prevent duplicate lines.

    Args:
        log_level:  Python logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: "json" (default, machine-parseable) or "console" (human-readable).
    """
    # Choose the final renderer based on log_format
    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    # Shared processor chain — used by both structlog and the stdlib bridge
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # ---------------------------------------------------------------------------
    # stdlib bridge — Design Decision #3
    # Route all stdlib loggers (uvicorn, SQLAlchemy, Alembic) through structlog.
    # We configure the root logger with a single StreamHandler that uses
    # structlog's ProcessorFormatter. Setting propagate=False on known noisy
    # loggers prevents their messages from also reaching the root handler.
    # ---------------------------------------------------------------------------
    formatter = structlog.stdlib.ProcessorFormatter(
        # foreign_pre_chain runs on messages that originate in stdlib logging
        # (before structlog's own processors). It normalises the record into
        # a structlog event dict that the processor chain can consume.
        foreign_pre_chain=shared_processors,
        processor=renderer,
    )

    # Configure the root stdlib logger to use only our ProcessorFormatter handler.
    # Using dictConfig keeps setup_logging() idempotent on repeated calls.
    logging.config.dictConfig(
        {
            "version": 1,
            # disable_existing_loggers=False preserves any loggers that were
            # created before setup_logging() was called (e.g. uvicorn.error).
            "disable_existing_loggers": False,
            "handlers": {
                "structlog_bridge": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "structlog_formatter",
                },
            },
            "formatters": {
                "structlog_formatter": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "foreign_pre_chain": shared_processors,
                    "processor": renderer,
                },
            },
            "root": {
                "handlers": ["structlog_bridge"],
                "level": log_level.upper(),
                # propagate is not applicable to root
            },
        }
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
