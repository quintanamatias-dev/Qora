"""Background Job Handler Registry.

Maps job_type strings to async handler functions.
Provides ConfigurationError for both duplicate registration and unknown type lookup.

Design: openspec/changes/phase-b-background-job-durability/design.md
Spec:   openspec/changes/phase-b-background-job-durability/specs/background-job-executor/spec.md

Handler signature:
    async def my_handler(payload: dict, db: AsyncSession) -> None: ...
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigurationError(Exception):
    """Raised for configuration/mapping errors that should not be retried extensively.

    When a handler raises ConfigurationError, the job is retried at most once
    then moved to 'dead' status with operator_review=True in the error JSON.
    This distinguishes schema/auth/config failures from transient network errors.

    Also raised by the registry for:
    - Duplicate handler registration (at registration time, not enqueue time)
    - Attempting to get_handler for an unregistered job_type
    """


# ---------------------------------------------------------------------------
# Handler type alias
# ---------------------------------------------------------------------------

HandlerFn = Callable[[dict, AsyncSession], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Module-level registry (singleton mapping)
# ---------------------------------------------------------------------------

#: Mapping from job_type string to async handler callable.
#: Populated by register() calls — typically done at import time in handlers/__init__.py.
_HANDLERS: dict[str, HandlerFn] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(job_type: str, handler: HandlerFn) -> None:
    """Register an async handler for the given job_type.

    Args:
        job_type: Unique string identifier for this job kind (e.g. 'summarize').
        handler: Async callable with signature (payload: dict, db: AsyncSession) -> None.

    Raises:
        ConfigurationError: If job_type is already registered. Fails at registration
            time (not at enqueue time) so misconfiguration is caught early.

    Spec: Requirement: Handler Registry — Duplicate registration rejected at registration time.
    """
    if job_type in _HANDLERS:
        raise ConfigurationError(
            f"Job type '{job_type}' is already registered. "
            "Each job_type may only have one handler. "
            "Unregister the existing handler before re-registering."
        )
    _HANDLERS[job_type] = handler


def get_handler(job_type: str) -> HandlerFn:
    """Return the registered handler for job_type.

    Args:
        job_type: The job type string to look up.

    Returns:
        The registered async handler callable.

    Raises:
        ConfigurationError: If job_type is not registered in the registry.

    Spec: Requirement: Job Enqueue — Enqueue with unknown job type raises and does not insert.
    """
    if job_type not in _HANDLERS:
        raise ConfigurationError(
            f"No handler registered for job_type '{job_type}'. "
            "Register a handler via registry.register() before enqueueing jobs of this type."
        )
    return _HANDLERS[job_type]
