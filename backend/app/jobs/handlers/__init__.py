"""Background job handler implementations.

Each module registers one or more handler functions via registry.register().
This package __init__ imports all handler modules so they auto-register on import.

PR 1 (executor foundation): no handlers registered yet — call sites are wired in PR 2.
PR 2 (post-call pipeline): summarize.py and crm_sync.py handlers are registered here.
"""
