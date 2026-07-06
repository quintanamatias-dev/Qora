"""Tests for LOG_FORMAT toggle and stdlib bridge — B9 Observability PR1.

Spec: sdd/b9-observability/spec — capability: structured-logging

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after backend/app/core/logging.py is updated.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_structlog():
    """Reset structlog to unconfigured state between tests.

    Also restores root logger handlers and level to prevent test isolation leakage:
    setup_logging() installs a ProcessorFormatter on the root logger and sets its
    level to INFO — both must be undone to avoid affecting subsequent tests that
    use stdlib loggers.
    """
    structlog.reset_defaults()
    # Restore root logger to clean state so other tests' stdlib loggers work normally
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)  # Restore to default WARNING level


# ---------------------------------------------------------------------------
# Task 1.2 — LOG_FORMAT toggle
# ---------------------------------------------------------------------------


def test_log_format_json_produces_json_lines(tmp_path, monkeypatch):
    """Scenario: LOG_FORMAT=json — output is single-line JSON with required fields."""
    from app.core.logging import setup_logging

    _reset_structlog()
    setup_logging(log_level="INFO", log_format="json")

    log = structlog.get_logger("test_json")
    # Capture output by configuring a StringIO stream
    buf = io.StringIO()
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=buf),
    )
    log.info("test_event", key="value")
    output = buf.getvalue().strip()

    # Must be valid JSON
    data = json.loads(output)
    assert "timestamp" in data
    assert "level" in data
    assert data["event"] == "test_event"
    assert data["key"] == "value"

    _reset_structlog()


def test_log_format_console_produces_non_json(monkeypatch):
    """Scenario: LOG_FORMAT=console — output is NOT valid JSON."""
    from app.core.logging import setup_logging

    _reset_structlog()
    buf = io.StringIO()
    setup_logging(log_level="DEBUG", log_format="console")

    # Reconfigure with the buffer so we can capture output
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=buf),
    )

    log = structlog.get_logger("test_console")
    log.info("console_event", color="test")
    output = buf.getvalue().strip()

    # Must have output
    assert output, "console format should produce output"

    # Must NOT be JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(output)

    _reset_structlog()


def test_log_format_invalid_raises_value_error():
    """Scenario: LOG_FORMAT=xml raises ValueError at setup time."""
    from app.core.logging import setup_logging

    _reset_structlog()
    with pytest.raises(ValueError, match="log_format"):
        setup_logging(log_level="INFO", log_format="xml")

    _reset_structlog()


def test_log_format_default_is_json():
    """Scenario: calling setup_logging without log_format defaults to json."""
    from app.core.logging import setup_logging
    import inspect

    sig = inspect.signature(setup_logging)
    default = sig.parameters.get("log_format")
    assert default is not None, "setup_logging must have a log_format parameter"
    assert default.default == "json", (
        f"Default log_format should be 'json', got: {default.default!r}"
    )


# ---------------------------------------------------------------------------
# Task 1.2 — Stdlib bridge
# ---------------------------------------------------------------------------


def test_setup_logging_installs_stdlib_bridge():
    """Scenario: setup_logging installs a structlog ProcessorFormatter on root logger.

    After setup_logging(), stdlib loggers should route through structlog's
    ProcessorFormatter rather than a raw StreamHandler.
    """
    from app.core.logging import setup_logging
    import structlog.stdlib

    _reset_structlog()
    # Clear any existing root handlers
    root = logging.getLogger()
    root.handlers.clear()

    setup_logging(log_level="INFO", log_format="json")

    root = logging.getLogger()
    # Root logger must have at least one handler
    assert len(root.handlers) >= 1, "Root logger should have a handler after setup_logging"

    # At least one handler should use structlog's ProcessorFormatter
    has_processor_formatter = any(
        isinstance(h.formatter, structlog.stdlib.ProcessorFormatter)
        for h in root.handlers
        if hasattr(h, "formatter")
    )
    assert has_processor_formatter, (
        "Root logger should have a ProcessorFormatter from structlog to bridge stdlib logs"
    )

    _reset_structlog()


def test_stdlib_logger_captured_via_bridge():
    """Scenario: a stdlib logger's output is captured through the structlog bridge."""
    from app.core.logging import setup_logging

    _reset_structlog()
    root = logging.getLogger()
    root.handlers.clear()

    buf = io.StringIO()
    setup_logging(log_level="DEBUG", log_format="json")

    # Replace the root handler's stream to capture output
    for handler in root.handlers:
        if hasattr(handler, "stream"):
            handler.stream = buf

    stdlib_logger = logging.getLogger("uvicorn.access")
    stdlib_logger.info("test_bridge_message")

    output = buf.getvalue().strip()
    assert output, "stdlib logger output should be captured by structlog bridge"

    _reset_structlog()


# ---------------------------------------------------------------------------
# Task 1.2 — Settings field
# ---------------------------------------------------------------------------


def test_settings_has_log_format_field():
    """Scenario: Settings has a log_format field defaulting to 'json'."""
    from app.core.config import Settings
    from pydantic import SecretStr

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("test-key"),
    )
    assert hasattr(settings, "log_format"), "Settings must have log_format field"
    assert settings.log_format == "json", f"Default log_format should be 'json', got: {settings.log_format!r}"


def test_settings_log_format_can_be_console(monkeypatch):
    """Scenario: Settings.log_format=console is accepted."""
    from app.core.config import Settings
    from pydantic import SecretStr

    monkeypatch.setenv("LOG_FORMAT", "console")
    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("test-key"),
    )
    assert settings.log_format == "console"
