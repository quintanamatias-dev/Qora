"""Background job handler implementations.

Each module registers one or more handler functions via registry.register().
This package __init__ imports all handler modules so they auto-register on import.

PR 1 (executor foundation): no handlers registered yet — call sites are wired in PR 2.
PR 2a (durable post-call summarize): summarize.py handler is registered here.
PR 2b (durable CRM sync + operator visibility): crm_sync.py handler is registered here.
PR 3 (off-call transcript durability): transcript_flush.py handler is registered here.

Import order matters: each module calls registry.register() at import time.
Duplicate registration raises ConfigurationError immediately (fail-fast).
"""

from __future__ import annotations

from app.jobs.registry import register
from app.jobs.handlers.summarize import summarize_handler
from app.jobs.handlers.crm_sync import crm_sync_handler
from app.jobs.handlers.transcript_flush import transcript_flush_handler

# Register handlers at import time.
# ConfigurationError is raised immediately on duplicate registration (fail-fast).
register("summarize", summarize_handler)
register("crm_sync", crm_sync_handler)
register("transcript_flush", transcript_flush_handler)

__all__ = ["summarize_handler", "crm_sync_handler", "transcript_flush_handler"]
