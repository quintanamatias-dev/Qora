"""Background Job Executor package.

Provides durable in-process job execution backed by the background_jobs table.
Replaces high-risk post-call asyncio.create_task fire-and-forget calls.

Design: openspec/changes/phase-b-background-job-durability/design.md
"""
