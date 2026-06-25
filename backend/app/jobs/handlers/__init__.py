"""Background job handler implementations.

Each module registers one or more handler functions via registry.register().
This package __init__ imports all handler modules so they auto-register on import.

PR 1 (executor foundation): no handlers registered yet — call sites are wired in PR 2.
PR 2a (durable post-call summarize): summarize.py handler is registered here.
PR 2b (operator visibility + CRM): crm_sync.py will be registered in a later PR.

Import order matters: each module calls registry.register() at import time.
Duplicate registration raises ConfigurationError immediately (fail-fast).
"""

from __future__ import annotations

from app.jobs.registry import register
from app.jobs.handlers.summarize import summarize_handler

# Register handlers at import time.
# ConfigurationError is raised immediately on duplicate registration (fail-fast).
register("summarize", summarize_handler)

__all__ = ["summarize_handler"]
