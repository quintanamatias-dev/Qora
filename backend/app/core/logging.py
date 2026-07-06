"""QORA — Structured logging setup using structlog.

Supports a LOG_FORMAT toggle:
- "json" (default): single-line JSON suitable for log aggregators and production.
- "console": human-readable colored output for local development.

Installs a stdlib ProcessorFormatter bridge on the root logger so that
uvicorn, SQLAlchemy, and any other stdlib-based libraries appear in the same
structured output stream.

Spec: sdd/b9-observability/spec — capability: structured-logging
"""

from __future__ import annotations

import logging
import sys

import structlog
import structlog.stdlib


_VALID_LOG_FORMATS = frozenset({"json", "console"})


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure structlog with optional LOG_FORMAT toggle and stdlib bridge.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format — "json" (default) or "console".

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
        logger_factory=structlog.PrintLoggerFactory(),
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

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove any existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
