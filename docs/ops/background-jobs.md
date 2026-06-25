# Background Jobs (B10) — Operator & Developer Guide

Qora's post-call pipeline — summarization, CRM sync, and transcript finalization — used to run as
fire-and-forget `asyncio.create_task` calls that vanished silently on failure or process restart.
B10 replaces that with a DB-backed executor: every job is a row in `background_jobs`, persisted
before the coroutine starts, retried with exponential backoff, and visible to operators without
log-diving.

---

## Feature flag

| Variable | Default | Effect |
|----------|---------|--------|
| `ENABLE_JOB_EXECUTOR` | `false` | **false** = legacy fire-and-forget path (no behavior change from pre-B10). **true** = durable executor active; jobs are written to DB, retried, and recovered on restart. |

Set in root `.env`:

```bash
ENABLE_JOB_EXECUTOR=true
```

No other secrets are required. The `background_jobs` table must exist (run the Alembic migration
before flipping the flag to `true`).

---

## Job types

| `job_type` | What it does | Trigger | `max_attempts` |
|------------|--------------|---------|----------------|
| `summarize` | Runs GPT-4o summarization and fact extraction for a completed call session. Uses `generate_summary_and_facts_durable()` — exceptions propagate so the executor can retry. | End of call (`close_session`) | 3 |
| `crm_sync` | Syncs lead data to the client's CRM (currently Airtable). Classifies errors into transient vs. configuration failures for different retry policies. | End of call | 3 |
| `transcript_flush` | Counts persisted transcript turns and stamps `transcript_finalized_at` + `transcript_turn_count` on the `CallSession` row. Off-call only — never enqueued during live SSE streaming. | End of call or `_reconcile_session` | 2 |

---

## Job lifecycle

```
pending → running → completed
                 ↘ failed → (retry) → running → ...
                                              ↘ dead
```

| Status | Meaning |
|--------|---------|
| `pending` | Row inserted; coroutine not yet started (or recovered after restart). |
| `running` | Handler is actively executing. |
| `completed` | Handler returned successfully. Terminal. |
| `failed` | Handler raised an exception; retry is scheduled if `attempts < max_attempts`. |
| `dead` | All retries exhausted, or a `ConfigurationError` reached the dead-letter threshold. Terminal. Requires operator review. |

The `error` column on `dead` and `failed` rows is a JSON object:

```json
{ "message": "...", "type": "ExceptionClassName", "operator_review": true }
```

`operator_review: true` is set only for `ConfigurationError` — auth failures, schema mismatches,
invalid CRM mappings. Transient errors (`operator_review: false`) are expected to resolve on retry.

---

## Error handling

**Transient errors** (network timeouts, 5xx, temporary DB failures):
- Executor retries up to `max_attempts`.
- Backoff: `min(1.0 × 2^attempt + jitter, 60s)`. Attempt 1 → ~2s, attempt 2 → ~4s, capped at 60s.
- After `max_attempts` retries: status becomes `dead`, `operator_review: false`.

**Configuration errors** (`ConfigurationError`, HTTP 400/401/403/404/422 from CRM adapter):
- Retried at most once (attempt 1 → `failed`, attempt 2 → `dead`).
- `operator_review: true` is written to `background_jobs.error`.
- Retrying more would not help — the underlying config needs fixing first.
- Examples: wrong Airtable API key, field mapping mismatch, invalid CRM endpoint URL.

**`transcript_flush` dead jobs** — accepted bounded loss, not operator-review (`max_attempts=2`).
The session remains identifiable via the `session_id` in the job payload.

---

## Startup recovery

On every server startup, `executor.recover()` runs automatically (wired in `main.py` lifespan):

1. Queries `background_jobs WHERE status IN ('pending', 'running')`.
2. Resets any `running` rows back to `pending` (prevents double-fire from crash mid-execution).
3. Creates asyncio tasks for all recovered jobs.

Jobs already dispatched in the current process (tracked in `_active_job_ids`) are skipped.
This means a clean restart will resume any incomplete work without duplicating in-flight jobs.

---

## Checking job status

`backend/app/jobs/queries.py` provides two internal helpers. These are **not** exposed via HTTP —
use them from admin scripts or a Python shell inside the container.

```python
from app.jobs.queries import get_failed_jobs, get_pending_jobs
from app.core.database import get_session

# Failed or dead jobs (most recent first)
async with get_session() as db:
    jobs = await get_failed_jobs(db)                        # all types
    jobs = await get_failed_jobs(db, job_type="crm_sync")  # filter by type

# Pending or running jobs (oldest first — queue depth)
async with get_session() as db:
    jobs = await get_pending_jobs(db)
    jobs = await get_pending_jobs(db, job_type="summarize")
```

Useful fields on each returned `BackgroundJob`:

| Field | What to check |
|-------|--------------|
| `id` | Job UUID — use to correlate with structured logs (`job_id` key). |
| `job_type` | Which handler ran. |
| `status` | Current state (`failed`, `dead`, etc.). |
| `attempts` | How many times the handler was called. |
| `error` | JSON string with `message`, `type`, `operator_review`. |
| `created_at` | When the job was enqueued. |
| `payload` | JSON with the job's input (`session_id`, `client_id`, `lead_id`). |

Or query the DB directly:

```sql
-- All dead jobs needing operator review
SELECT id, job_type, attempts, created_at, error
FROM background_jobs
WHERE status = 'dead'
ORDER BY created_at DESC;

-- CRM sync failures only
SELECT id, attempts, error
FROM background_jobs
WHERE job_type = 'crm_sync' AND status IN ('failed', 'dead')
ORDER BY created_at DESC;
```

---

## Rollback plan

If the executor causes issues after enabling:

1. Set `ENABLE_JOB_EXECUTOR=false` in `.env` and restart the app. The legacy fire-and-forget
   path takes over immediately — no data migration needed.
2. Rows already in `background_jobs` are left as-is (safe to ignore or inspect).
3. To fully remove the table: run `alembic downgrade <migration-before-B10>`.

---

## Important constraints

- **No live-call work.** The executor runs post-call jobs only. Never enqueue jobs from
  within live SSE streaming handlers or `schedule_user_turn_persist` / `_persist_user_turn`.
- **`transcript_flush` is off-call only.** It must be enqueued by `close_session()` or
  `_reconcile_session()` — after the call ends. Enqueuing it mid-call would race with active
  turn persistence and produce incorrect `transcript_turn_count` stamps.
- **Do not use `generate_summary_and_facts()`** (the legacy fire-and-forget variant) from inside
  any job handler. Use `generate_summary_and_facts_durable()` so failures propagate to the executor.
- **`queries.py` helpers are internal only.** The `error` column contains raw payload data
  (`client_id`, `lead_id`). Do not wire these helpers into a public HTTP endpoint without adding
  tenant-scoped filtering and auth middleware.
