# Exploration: Background Job Durability (B10)

## Current State

Qora runs as a single-process FastAPI application (single container, `restart: unless-stopped`). All background work uses raw `asyncio.create_task()` fire-and-forget coroutines — no job queue, no persistence layer for pending work, no retry infrastructure beyond ad-hoc single-retry logic.

### Inventory of In-Process Background Tasks

| # | Task | Location | Trigger | Durability Risk |
|---|------|----------|---------|-----------------|
| 1 | **Post-call summarization** | `app/calls/service.py:688` (`_schedule_summarize`) | Session close (`close_session`) | **HIGH** — GPT-4o analysis + fact extraction + lead update. If process restarts mid-flight, the call has no summary, no updated lead facts, no CRM sync. |
| 2 | **CRM sync** | `app/summarizer.py:1105` (`_schedule_crm_sync`) | End of summarizer pipeline | **HIGH** — Airtable upsert for lead data. Chained from summarizer; if summarizer task is lost, CRM sync never fires. Own independent failure = silent data gap. |
| 3 | **User turn persistence** | `app/calls/service.py:802` (`schedule_user_turn_persist`) | Every custom-LLM SSE request | **MEDIUM** — Individual transcript turns. Has 1-retry with 0.5s backoff. High frequency (every turn). Loss = incomplete transcript. |
| 4 | **ElevenLabs agent sync** | `app/agents/router.py:273,408` | Agent create/update with `elevenlabs_agent_id` | **LOW** — Admin-triggered, idempotent. User can manually re-trigger via `/sync-elevenlabs` endpoint. |
| 5 | **Stale session sweeper** | `app/sweeper.py:88` (`stale_session_sweeper`) | Lifespan loop, 60s interval | **LOW** — Periodic cleanup. Restarts naturally resume the loop. Missed sweep = 60s delay at most. |
| 6 | **Scheduler tick** | `app/scheduler/service.py:540` (`scheduler_tick`) | Lifespan loop, 60s interval | **LOW** — Marks due `ScheduledCall` rows as `in_progress`. DB-backed state; missed tick = 60s delay. |
| 7 | **Session store cleanup** | `app/main.py:113` (`_session_store_cleanup_task`) | Lifespan loop, 60s interval | **NONE** — In-memory cache cleanup. No durable state involved. |

### Business Flow Dependencies

```
Call ends → close_session()
  ├─ [fire-and-forget] _schedule_summarize(session_id)
  │   ├─ GPT-4o parallel dimension analysis (10 calls)
  │   ├─ Lead field updates (name, phone, status, interest, notes, etc.)
  │   ├─ auto_schedule() → ScheduledCall row (if rules match)
  │   └─ [fire-and-forget] _schedule_crm_sync(client_id, lead_id)
  │       └─ Airtable upsert
  └─ Response to webhook caller (immediate)

SSE turn → custom_llm_route()
  └─ [fire-and-forget] schedule_user_turn_persist(session_id, messages)
      └─ DB insert transcript turn (1 retry)
```

### Durability Risks Today

1. **Process restart loses all in-flight tasks** — Docker `restart: unless-stopped` restarts the container, but all `asyncio.create_task` coroutines are gone. No record of what was pending.

2. **No record of pending work** — Summarization has no "pending" state in the DB. If the process dies between `close_session` commit and `_summarize_in_background` completion, there is no way to know which sessions need re-summarization.

3. **Chained fire-and-forget amplifies loss** — CRM sync is chained from summarizer. If summarizer task dies, CRM sync never starts. Two business-critical operations lost from a single task failure.

4. **No dead-letter / failure tracking** — Failed tasks log warnings but have no persistent failure record. Operators cannot audit what was lost.

5. **Graceful shutdown is correct but insufficient** — `main.py` cancels the three lifespan loops on shutdown, but does NOT track or drain ad-hoc `create_task` coroutines. Mid-flight summarizations are killed.

## Affected Areas

- `app/calls/service.py` — `_schedule_summarize`, `_summarize_in_background`, `schedule_user_turn_persist`, `_persist_user_turn`
- `app/summarizer.py` — `_schedule_crm_sync`, `_run_crm_sync_in_background`, `generate_summary_and_facts`
- `app/agents/router.py` — ElevenLabs sync fire-and-forget calls
- `app/elevenlabs/service.py` — `sync_to_elevenlabs` background helper
- `app/main.py` — Lifespan startup/shutdown, background loop tasks
- `app/sweeper.py` — Stale session sweeper loop
- `app/scheduler/service.py` — Scheduler tick loop
- `app/core/database.py` — Session factory used by background tasks

## Approaches

### 1. **DB-Backed Job Table + Recovery Sweep** — SQLite job queue with startup recovery

Insert a row into a `background_jobs` table BEFORE firing the task. Task marks it complete on success, failed on error. On startup, a recovery sweep re-enqueues incomplete jobs.

- Pros:
  - Zero new dependencies (SQLite + Alembic already available)
  - Atomic with existing DB transactions (job row inserted in same commit as session close)
  - Simple mental model: job table is the audit trail
  - Startup recovery is deterministic — query `WHERE status IN ('pending', 'running')`
  - Fully testable with existing SQLite test infrastructure
  - B9 (observability) can query the job table for metrics/alerts
- Cons:
  - Manual implementation of retry logic, dead-letter handling
  - SQLite write contention under high concurrency (mitigated by WAL mode already enabled)
  - No priority queues or rate limiting built-in
- Effort: **Medium**

### 2. **Lightweight Task Queue Library (ARQ / SAQ)** — Redis-backed or in-process async queue

Use a library like [ARQ](https://github.com/samuelcolvin/arq) or [SAQ](https://github.com/tobymao/saq) for structured async job execution with retry, backoff, and result tracking.

- Pros:
  - Battle-tested retry/backoff/dead-letter semantics
  - Built-in worker health monitoring
  - Priority queues and rate limiting
- Cons:
  - Requires Redis (new infrastructure dependency) — conflicts with SQLite-only MVP
  - ARQ workers run in separate processes (architecture change)
  - SAQ can use SQLite but is less mature
  - Adds operational complexity (Redis monitoring, connection management)
  - Breaks the single-container deployment model unless embedded
- Effort: **High**

### 3. **Hybrid: DB Job Table + In-Process Executor** — Best of both without new infra

Same as Approach 1, but with a structured in-process executor that wraps `asyncio.create_task` with: (a) pre-insert job row, (b) post-completion status update, (c) configurable retry with exponential backoff, (d) startup recovery sweep.

- Pros:
  - All Approach 1 benefits
  - Structured executor API prevents ad-hoc `create_task` drift
  - Retry logic is centralized, not per-task
  - Migration path to external queue later (swap executor backend)
  - Single module to test and audit
- Cons:
  - Still in-process (no separate worker isolation)
  - Must handle DB session lifecycle carefully (each retry needs fresh session)
  - More code than Approach 1 (executor abstraction layer)
- Effort: **Medium**

## Recommendation

**Approach 3: Hybrid DB Job Table + In-Process Executor.**

Rationale:
1. **Fits the stack** — SQLite + single container + no new dependencies. This is an MVP, not a distributed system.
2. **Solves the real risks** — The core problem is "restart loses work." A DB row inserted atomically with the triggering action (session close) guarantees recoverability. The executor provides structured retry without scattering backoff logic across 4 different modules.
3. **Upgrade path** — The executor interface (`enqueue(job_type, payload)`) can later be backed by Redis/ARQ without changing callers.
4. **B9 synergy** — The job table is a natural observability surface. Structured logging (B9) can emit job lifecycle events. A dashboard query like `SELECT job_type, status, COUNT(*) FROM background_jobs GROUP BY 1, 2` gives instant operational visibility.
5. **Review budget** — Approach 3 can be delivered in ~300-400 lines of new code (model + executor + migration + recovery sweep), well within the 400-line PR budget.

### Implementation Sketch

```
background_jobs table:
  id          TEXT PK (uuid4)
  job_type    TEXT NOT NULL  -- 'summarize' | 'crm_sync' | 'user_turn' | 'elevenlabs_sync'
  payload     TEXT NOT NULL  -- JSON (e.g. {"session_id": "..."})
  status      TEXT NOT NULL  -- 'pending' | 'running' | 'completed' | 'failed' | 'dead'
  attempts    INTEGER DEFAULT 0
  max_attempts INTEGER DEFAULT 3
  created_at  DATETIME
  started_at  DATETIME
  completed_at DATETIME
  error       TEXT           -- last error message
  
Executor API:
  await job_executor.enqueue("summarize", {"session_id": sid})  # inserts row + fires task
  await job_executor.recover()  # startup: re-enqueue pending/running jobs
```

### What NOT to Build (MVP Scope Guard)

- No priority queues — all jobs are equal priority for now
- No rate limiting — current volume doesn't warrant it
- No separate worker process — stays in-process
- No job scheduling/delay — that's already handled by `ScheduledCall`
- No Redis — SQLite is sufficient at current scale

## Relationship to B9 (Structured Logging + Error Monitoring)

B10 should land BEFORE B9. The job table gives B9 concrete events to observe:

| B10 Provides | B9 Consumes |
|---|---|
| `background_jobs` table with lifecycle timestamps | Query for failed-job rate, p95 duration, dead-letter count |
| Structured log events: `job_enqueued`, `job_started`, `job_completed`, `job_failed`, `job_dead` | Log aggregation rules, alerting thresholds |
| `job_executor.recover()` at startup | Startup recovery event visible in monitoring |

B9 should NOT duplicate job tracking — it should read from the `background_jobs` table and the structured log events that B10 emits.

## Risks

1. **SQLite write contention** — High-frequency user-turn jobs (every SSE turn) add write pressure. Mitigated by WAL mode (already enabled) and the fact that job rows are small. Monitor via B9.
2. **Executor complexity creep** — The abstraction must stay thin. If it grows beyond ~150 lines, it's overbuilt for SQLite MVP.
3. **Retry storms** — Exponential backoff with jitter is essential. A hard cap of 3 attempts with a `dead` terminal state prevents infinite loops.
4. **Migration ordering** — The Alembic migration for `background_jobs` must land before the executor code that references it. Standard Alembic sequential ordering handles this.
5. **User turn volume** — At scale, persisting a job row per user turn may be excessive. Consider: user turns could remain raw `create_task` (accepted loss) or batch multiple turns into one job. Decision should be explicit in the proposal.

## Ready for Proposal

Yes — the exploration covers all five questions from the task. The recommended approach (DB Job Table + In-Process Executor) is concrete enough for a proposal that defines scope, acceptance criteria, and rollback plan. The orchestrator should confirm with the user:

- Whether user-turn persistence should be included in the job system (higher write volume) or left as raw `create_task` (accepted risk of occasional turn loss).
- Whether the ElevenLabs sync (already idempotent + manually retriggerable) needs job durability or can stay fire-and-forget.
