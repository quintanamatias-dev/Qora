"""Tests for voice session and job context binding — B9 Observability PR2.

Spec: sdd/b9-observability/spec — capability: structured-logging
  - Requirement: Voice Session Context Binding
  - Requirement: Job Context Binding

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after webhook.py and executor.py are modified.
"""

from __future__ import annotations

import pytest
import structlog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_ctx():
    """Clear structlog contextvars before and after each test."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


# ---------------------------------------------------------------------------
# Task 5.3 — Voice session context binding
# ---------------------------------------------------------------------------


def test_bind_voice_context_binds_call_session_id():
    """Scenario: bind_voice_context binds call_session_id to structlog contextvars."""
    from app.core.context import bind_voice_context

    bind_voice_context(call_session_id="cs_abc", conversation_id="cv_xyz")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("call_session_id") == "cs_abc"


def test_bind_voice_context_binds_conversation_id():
    """Scenario: bind_voice_context binds conversation_id to structlog contextvars."""
    from app.core.context import bind_voice_context

    bind_voice_context(call_session_id="cs_def", conversation_id="cv_123")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("conversation_id") == "cv_123"


def test_bind_voice_context_context_cleared_does_not_leak():
    """Scenario: After clear_contextvars, previous voice context is gone."""
    from app.core.context import bind_voice_context

    bind_voice_context(call_session_id="cs_leak", conversation_id="cv_leak")
    structlog.contextvars.clear_contextvars()

    ctx = structlog.contextvars.get_contextvars()
    assert "call_session_id" not in ctx
    assert "conversation_id" not in ctx


# ---------------------------------------------------------------------------
# Task 5.3 — Job context binding
# ---------------------------------------------------------------------------


def test_bind_job_context_binds_job_id():
    """Scenario: bind_job_context binds job_id to structlog contextvars."""
    from app.core.context import bind_job_context

    bind_job_context(job_id="job_123", job_type="post_call_analysis")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("job_id") == "job_123"


def test_bind_job_context_binds_job_type():
    """Scenario: bind_job_context binds job_type to structlog contextvars."""
    from app.core.context import bind_job_context

    bind_job_context(job_id="job_456", job_type="post_call_analysis")

    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("job_type") == "post_call_analysis"


def test_bind_job_context_new_job_does_not_carry_previous_context():
    """Scenario: After clear, next job context does not see previous job's values."""
    from app.core.context import bind_job_context

    bind_job_context(job_id="job_first", job_type="analysis")
    structlog.contextvars.clear_contextvars()

    bind_job_context(job_id="job_second", job_type="summary")
    ctx = structlog.contextvars.get_contextvars()

    assert ctx.get("job_id") == "job_second"
    assert ctx.get("job_type") == "summary"
    # Old job_id must not be visible
    assert ctx.get("job_id") != "job_first"
