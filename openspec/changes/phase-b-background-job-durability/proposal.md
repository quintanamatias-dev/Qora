# Proposal: Phase B — Background Job Durability (B10)

## Intent

Post-call work (summarization, lead updates, auto-scheduling, CRM sync) runs as fire-and-forget `asyncio.create_task` coroutines. A process restart kills all in-flight tasks with no record of what was lost. Operators cannot audit failures. This creates a silent data-loss risk on every deployment or crash.

## Scope

### In Scope
- DB-backed `background_jobs` table with full lifecycle state (`pending → running → completed | failed | dead`)
- In-process `JobExecutor` with enqueue, retry/backoff, and dead-letter semantics
- Alembic migration for `background_jobs` table
- Startup recovery sweep: re-enqueue `pending`/`running` jobs on process start
- Wrap HIGH-risk tasks: post-call summarization, lead update, auto-scheduling, CRM sync
- Wrap MEDIUM-risk task: user-turn transcript persistence
- Persistent error storage per job (last error message + attempt count)
- Minimal internal API surface: query pending/failed jobs (consumed by B9)

### Out of Scope
- ElevenLabs agent sync — idempotent + manually retriggerable; stays fire-and-forget
- Lifespan sweep/scheduler/session-cleanup loops — DB-backed or restart-safe; no change
- Redis, external workers, or separate worker processes
- Priority queues or rate limiting
- Job scheduling/delay (handled by existing `ScheduledCall` model)
- Admin UI for job management (future operator tooling)

## Capabilities

### New Capabilities
- `background-job-executor`: DB-backed in-process job executor with enqueue, retry, backoff, dead-letter, and startup recovery
- `durable-post-call-pipeline`: Summarization, lead update, auto-scheduling, and CRM sync wrapped as durable jobs
- `durable-transcript-persistence`: User-turn persistence wrapped as durable job with configurable max_attempts

### Modified Capabilities
- None

## Approach

**Hybrid DB Job Table + In-Process Executor (Approach 3 from exploration).**

1. New `background_jobs` SQLite table (Alembic migration). Row inserted atomically with the triggering action (e.g., same DB commit as `close_session`).
2. `JobExecutor` singleton wraps `asyncio.create_task`: pre-insert row → execute handler → update status. Retry with exponential backoff + jitter. Hard cap: 3 attempts → `dead`.
3. On startup (`lifespan`), `executor.recover()` queries `WHERE status IN ('pending', 'running')` and re-enqueues.
4. Each job type registers a handler function; payload is JSON.
5. User-turn jobs use `max_attempts=2` (lower frequency risk vs write amplification tradeoff).
6. B9 reads the `background_jobs` table directly — B10 does not duplicate metrics logic.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/jobs/` | New | `executor.py`, `models.py`, `registry.py` — the job system module |
| `backend/app/jobs/handlers/` | New | Per-job-type handler functions |
| `backend/alembic/versions/` | New | Migration: `background_jobs` table |
| `backend/app/calls/service.py` | Modified | Replace `_schedule_summarize` / `schedule_user_turn_persist` with `executor.enqueue()` |
| `backend/app/summarizer.py` | Modified | Replace `_schedule_crm_sync` with `executor.enqueue()` |
| `backend/app/main.py` | Modified | Call `executor.recover()` in lifespan startup |
| `backend/app/core/database.py` | Modified | Expose session factory to executor for fresh sessions per retry |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SQLite write contention from user-turn jobs | Med | WAL mode already enabled; user-turn max_attempts=2 reduces retry amplification |
| Executor abstraction grows too large | Med | Hard line: executor module stays ≤ 150 lines; extract to library if exceeded |
| Retry storms on config/mapping failures | Med | Distinguish transient (retry 3×) vs configuration errors (retry 1×, mark `dead`, log operator review flag) |
| Migration ordering breaks startup | Low | Alembic migration runs before executor import; CI test validates migration sequence |
| Recovery sweep double-enqueues jobs | Low | Idempotency key on `job_id`; executor checks `status` before re-firing |

## Rollback Plan

1. Feature flag: `ENABLE_JOB_EXECUTOR=false` reverts all call sites to raw `create_task` (keep old code paths behind flag for one release).
2. Alembic downgrade migration drops `background_jobs` table (no FK dependencies).
3. No data migration needed on rollback — job rows are not referenced by other tables.

## Dependencies

- B10 must land **before** B9 (B9 consumes the job table for observability)
- Alembic migration infrastructure (Phase B DB Migration Foundation — already complete)
- No new external dependencies

## Success Criteria

- [ ] Process restart during active summarization re-runs the summary on next startup with no operator intervention
- [ ] CRM sync failures retry up to 3× with exponential backoff; permanently failed jobs appear in `dead` status with error stored
- [ ] Configuration/mapping CRM errors retry once, then reach `dead` state with an operator-review flag in `error` field
- [ ] User-turn transcript jobs survive a single retry; loss after 2 attempts is accepted and logged
- [ ] All `background_jobs` state transitions covered by unit tests (strict_tdd: `cd backend && python3 -m pytest tests/ -q`)
- [ ] `executor.recover()` integration test: seed `pending` jobs, restart executor, verify re-execution
- [ ] No regression in existing call flow tests
