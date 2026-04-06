"""QORA — Structured logging setup using structlog."""

from __future__ import annotations

import logging

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output.

    Processors:
    1. merge_contextvars — inject contextvars (session_id, etc.) into every log
    2. add_log_level — add "level" field
    3. StackInfoRenderer — include stack info when present
    4. set_exc_info — auto-attach exception info
    5. TimeStamper — ISO-8601 timestamp
    6. JSONRenderer — output as JSON line
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
