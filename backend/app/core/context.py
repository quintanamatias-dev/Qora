"""QORA — Structlog context binding helpers for voice sessions and background jobs.

Provides pure helper functions that bind call-specific metadata to structlog
contextvars so that all log lines emitted within a request or job carry the
relevant identifiers automatically.

Usage:
    # In voice webhook handler:
    bind_voice_context(call_session_id="cs_abc", conversation_id="cv_xyz")

    # In job executor:
    bind_job_context(job_id="job_123", job_type="post_call_analysis")

    # Clear at end of scope (usually automatic via CorrelationMiddleware):
    structlog.contextvars.clear_contextvars()

Spec: sdd/b9-observability/spec — capability: structured-logging
  - Requirement: Voice Session Context Binding
  - Requirement: Job Context Binding
"""

from __future__ import annotations

import structlog


def bind_voice_context(call_session_id: str, conversation_id: str) -> None:
    """Bind voice session identifiers to structlog contextvars.

    After this call, every log line emitted in the same async context will
    carry ``call_session_id`` and ``conversation_id`` fields automatically.

    Args:
        call_session_id: ElevenLabs call session ID (e.g. ``cs_abc``).
        conversation_id: ElevenLabs conversation ID (e.g. ``cv_xyz``).

    Spec: Requirement: Voice Session Context Binding
    """
    structlog.contextvars.bind_contextvars(
        call_session_id=call_session_id,
        conversation_id=conversation_id,
    )


def bind_job_context(job_id: str, job_type: str) -> None:
    """Bind background job identifiers to structlog contextvars.

    After this call, every log line emitted in the same async context will
    carry ``job_id`` and ``job_type`` fields automatically.

    Args:
        job_id:   Background job UUID (e.g. ``job_123``).
        job_type: Registered job type string (e.g. ``post_call_analysis``).

    Spec: Requirement: Job Context Binding
    """
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        job_type=job_type,
    )
