"""Tests: B9 observability — LOG_FORMAT toggle and stdlib bridge.

TDD RED phase for task 1.2.

Covered scenarios:
    - LOG_FORMAT=json (default) produces machine-parseable output
    - LOG_FORMAT=console produces human-readable output (ConsoleRenderer)
    - Invalid LOG_FORMAT raises ValueError at settings construction
    - stdlib bridge routes a stdlib log through structlog without duplication
    - setup_logging accepts log_format parameter
    - structlog processors include merge_contextvars (correlation ID propagation)

Spec: observability-correlation/spec.md — Requirement: stdlib Logging Bridge
Design: design.md — Architecture Decision #3 (ProcessorFormatter) and #4 (LOG_FORMAT enum)
"""

from __future__ import annotations

import json
import logging
import sys
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from pydantic import SecretStr, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_API_KEY = "qora-test-key-do-not-use-in-production"


def _make_settings(**kwargs):
    """Instantiate Settings with required fields plus overrides."""
    from app.core.config import Settings

    defaults = dict(
        openai_api_key=SecretStr("qora-test-openai-key-not-a-secret"),
        elevenlabs_api_key=SecretStr("qora-test-elevenlabs-key-not-a-secret"),
        qora_api_key=SecretStr(_TEST_API_KEY),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Task 1.2 — Settings: LOG_FORMAT field
# ---------------------------------------------------------------------------


class TestLogFormatSetting:
    """Settings must expose log_format: Literal['json', 'console'] = 'json'."""

    def test_default_log_format_is_json(self):
        """When LOG_FORMAT is not set, settings.log_format must default to 'json'."""
        settings = _make_settings()
        assert settings.log_format == "json"

    def test_log_format_console_accepted(self):
        """LOG_FORMAT=console must be accepted without error."""
        settings = _make_settings(log_format="console")
        assert settings.log_format == "console"

    def test_log_format_json_accepted(self):
        """LOG_FORMAT=json must be accepted without error."""
        settings = _make_settings(log_format="json")
        assert settings.log_format == "json"

    def test_invalid_log_format_raises(self):
        """An unsupported LOG_FORMAT value must cause a validation error at construction."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(log_format="xml")

    def test_invalid_log_format_empty_raises(self):
        """Empty string for LOG_FORMAT must be rejected."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(log_format="")


# ---------------------------------------------------------------------------
# Task 1.2 — setup_logging: accepts log_format parameter
# ---------------------------------------------------------------------------


class TestSetupLoggingSignature:
    """setup_logging must accept a log_format keyword argument."""

    def test_setup_logging_accepts_log_format_json(self):
        """setup_logging(log_format='json') must not raise."""
        from app.core.logging import setup_logging

        # Must not raise — we just verify the call succeeds
        setup_logging(log_level="INFO", log_format="json")

    def test_setup_logging_accepts_log_format_console(self):
        """setup_logging(log_format='console') must not raise."""
        from app.core.logging import setup_logging

        setup_logging(log_level="INFO", log_format="console")

    def test_setup_logging_default_format_is_json(self):
        """setup_logging() without log_format must default to json (no exception)."""
        from app.core.logging import setup_logging

        setup_logging(log_level="INFO")  # should default to json


# ---------------------------------------------------------------------------
# Task 1.2 — LOG_FORMAT=json: structured output
# ---------------------------------------------------------------------------


class TestJsonRenderer:
    """When LOG_FORMAT=json, output must be machine-parseable JSON."""

    def test_json_renderer_produces_parseable_output(self, capsys):
        """A log event emitted after setup_logging(log_format='json') must be JSON."""
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="json")

        log = structlog.get_logger("test_json")
        log.info("hello_json", key="value")

        captured = capsys.readouterr()
        # Find any line that looks like JSON
        json_lines = [
            line for line in captured.out.splitlines()
            if line.strip().startswith("{")
        ]
        assert json_lines, (
            f"Expected at least one JSON line in stdout, got: {captured.out!r}"
        )
        parsed = json.loads(json_lines[-1])
        assert parsed.get("event") == "hello_json"
        assert parsed.get("key") == "value"

    def test_json_output_includes_level_field(self, capsys):
        """JSON output must include a 'level' field."""
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="json")
        structlog.get_logger("test_level").warning("check_level")

        captured = capsys.readouterr()
        json_lines = [l for l in captured.out.splitlines() if l.strip().startswith("{")]
        assert json_lines
        parsed = json.loads(json_lines[-1])
        assert "level" in parsed


# ---------------------------------------------------------------------------
# Task 1.2 — LOG_FORMAT=console: human-readable output
# ---------------------------------------------------------------------------


class TestConsoleRenderer:
    """When LOG_FORMAT=console, output must use ConsoleRenderer (not raw JSON)."""

    def test_console_renderer_output_is_not_raw_json(self, capsys):
        """Console output must NOT be a bare JSON object on each line."""
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="console")

        log = structlog.get_logger("test_console")
        log.info("hello_console")

        captured = capsys.readouterr()
        output = captured.out
        # Console renderer produces colored / aligned output, not raw '{"event":...}'
        # The simplest assertion: the raw event name appears somewhere in the output
        assert "hello_console" in output, (
            f"Expected event name in console output, got: {output!r}"
        )

    def test_console_renderer_does_not_produce_json(self, capsys):
        """Console output lines must not all be JSON-parseable."""
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="console")
        structlog.get_logger("test_notjson").info("test_event_console", x=1)

        captured = capsys.readouterr()
        all_lines = [l.strip() for l in captured.out.splitlines() if l.strip()]
        # At least one line must NOT be parseable as JSON (ConsoleRenderer uses
        # aligned text / ANSI codes, not bare JSON)
        non_json_lines = []
        for line in all_lines:
            try:
                json.loads(line)
            except (json.JSONDecodeError, ValueError):
                non_json_lines.append(line)
        assert non_json_lines, (
            "Console renderer must produce at least one non-JSON line"
        )


# ---------------------------------------------------------------------------
# Task 1.2 — stdlib bridge: no duplication, carries request_id
# ---------------------------------------------------------------------------


class TestStdlibBridge:
    """stdlib logging must be routed through structlog with no duplicate lines.

    Spec: observability-correlation/spec.md — Requirement: stdlib Logging Bridge
    Design: Decision #3 — structlog ProcessorFormatter via logging.config.dictConfig
    """

    def test_stdlib_bridge_does_not_duplicate_lines(self, capsys):
        """A message emitted via stdlib logging must appear exactly once.

        When both stdlib and structlog handlers are configured without bridging,
        each stdlib log line would appear twice (once via stdlib handler, once via
        structlog PrintLoggerFactory). The bridge must collapse this to one line.
        """
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="json")

        # Emit via stdlib (simulates uvicorn, SQLAlchemy output)
        stdlib_logger = logging.getLogger("uvicorn.test_bridge")
        stdlib_logger.info("stdlib_bridge_test_message_unique_12345")

        captured = capsys.readouterr()
        lines_with_message = [
            line for line in captured.out.splitlines()
            if "stdlib_bridge_test_message_unique_12345" in line
        ]
        assert len(lines_with_message) >= 1, (
            "stdlib message must appear in output (bridge must forward it)"
        )
        assert len(lines_with_message) == 1, (
            f"stdlib message must appear exactly once (no duplication), "
            f"got {len(lines_with_message)} occurrences: {lines_with_message}"
        )

    def test_stdlib_bridge_carries_correlation_context(self, capsys):
        """stdlib log emitted while request_id is bound must include request_id in output.

        Spec: Scenario: uvicorn access log carries request_id
        """
        from app.core.logging import setup_logging

        setup_logging(log_level="DEBUG", log_format="json")

        # Bind a fake request_id to simulate an active request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id="test-bridge-rid-abc123")

        try:
            stdlib_logger = logging.getLogger("uvicorn.test_context")
            stdlib_logger.info("stdlib_with_context_message")

            captured = capsys.readouterr()
            # Find lines containing our message
            lines_with_msg = [
                line for line in captured.out.splitlines()
                if "stdlib_with_context_message" in line
            ]
            assert lines_with_msg, "stdlib message must appear in output"
            # The line must contain the request_id from contextvars
            line = lines_with_msg[0]
            # Parse as JSON and check for request_id
            try:
                parsed = json.loads(line)
                assert parsed.get("request_id") == "test-bridge-rid-abc123", (
                    f"Expected request_id in stdlib log output, got: {parsed}"
                )
            except json.JSONDecodeError:
                # Non-JSON output (e.g. console mode) — just check the string
                assert "test-bridge-rid-abc123" in line
        finally:
            structlog.contextvars.clear_contextvars()
