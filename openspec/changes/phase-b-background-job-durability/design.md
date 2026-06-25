# Design: Phase B — Background Job Durability (B10)

## Technical Approach

DB-backed in-process job executor replacing high-risk post-call `asyncio.create_task` fire-and-forget calls. A new `background_jobs` SQLite table stores job lifecycle state. A `JobExecutor` singleton wraps enqueue → execute → retry → dead-letter with exponential backoff. On startup, `executor.recover()` re-enqueues incomplete jobs. Feature flag `ENABLE_JOB_EXECUTOR=false` keeps legacy paths as rollback. Transcript durability is deliberately gated: PR 3 MUST NOT add any new work to live call turn handlers; all new transcript reconciliation/finalization runs before call start, after normal call end, or after cut/disconnect handling.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Job ID strategy | UUID4 string PK (matches all existing Qora models) | Auto-increment, ULID | Consistent with `CallSession.id`, `Lead.id` pattern; no new dependencies |
| State machine | `pending → running → completed \| failed \| dead` | Add `retrying` state | Simpler; `failed` + re-enqueue achieves the same without extra state. `failed` is transient (will retry), `dead` is terminal |
| Retry backoff | `min(base * 2^attempt + jitter, max_delay)` with `base=1s`, `max_delay=60s` | Fixed delay, linear | Exponential+jitter prevents retry storms per spec; 60s cap keeps SQLite MVP responsive |
| Error classification | Handler raises `ConfigurationError(msg)` subclass → max 1 retry then `dead` with `operator_review=true` in error JSON; all other exceptions → transient (up to `max_attempts`) | Error codes enum | Minimizes handler burden — only CRM sync needs classification; others use default transient |
| DB session per attempt | Fresh `get_session()` context manager per retry | Shared session | Spec requirement; prevents poisoned session from blocking retries |
| Idempotency guard | `executor._active_job_ids: set[str]` in-memory set checked before dispatch; recovery resets `running → pending` then enqueues | DB lock/SELECT FOR UPDATE | Single-process; in-memory set is sufficient. Recovery transitions `running` to `pending` first to avoid double-fire |
| Feature flag | `Settings.enable_job_executor: bool = False` | Env-only, no flag | Pydantic-settings validated; call sites check `if settings.enable_job_executor:` with `else:` fallback to raw `create_task` |
| Error shape | JSON in TEXT column: `{"message": str, "type": str, "operator_review": bool}` | Plain string | Structured for B9 queries; `operator_review` flag distinguishes config errors from transient |
| Module location | `backend/app/jobs/` package | Flatten into `app/core/` | Keeps executor, models, registry, handlers co-located; mirrors `app/calls/`, `app/scheduler/` pattern |
| Transcript strategy | Off-call transcript reconciliation/finalization in PR 3 | Per-turn durable enqueue/write/buffer work from live SSE path | Protects real-time latency by adding zero new live-call work; accepts bounded transcript loss over call delay |

## Data Flow

### Enqueue + Execute

```
caller (close_session / summarizer)
  │
  ├─ executor.enqueue("summarize", {"session_id": sid}, max_attempts=3)
  │   ├─ INSERT background_jobs (status=pending) ← same DB commit as trigger
  │   ├─ _active_job_ids.add(job_id)
  │   └─ asyncio.create_task(_run_job(job_id))
  │
  └─ _run_job(job_id)
      ├─ UPDATE status=running, started_at=now, attempts+=1
      ├─ async with get_session() as db:
      │     await handler(payload, db)
      ├─ ✓ → UPDATE status=completed, completed_at=now
      ├─ ✗ ConfigurationError → attempt > 1? → dead + operator_review
      │                        └ attempt == 1? → failed, schedule 1 more retry
      └─ ✗ Other exception →
          ├─ UPDATE status=failed, error={message, type}
          ├─ attempts < max_attempts? → asyncio.sleep(backoff) → re-enqueue
          └─ attempts == max_attempts → UPDATE status=dead
```

### Transcript Durability (PR 3 Gate)

```
live SSE request
  │
  ├─ keep today's behavior only
  ├─ use current request/session messages for in-call continuity
  ├─ DO NOT add executor.enqueue(...)
  ├─ DO NOT add transcript DB writes
  ├─ DO NOT add in-memory durability buffers
  └─ DO NOT add reconciliation/finalization steps

call start / call end / cut-disconnect boundary
  │
  └─ run transcript reconciliation/finalization outside the live turn path
        ├─ compare existing persisted turns or final transcript snapshot
        ├─ enqueue at most off-call transcript_flush work if executor is enabled
        └─ retry bounded failures without affecting caller streaming latency
```

Tradeoff: this favors voice latency over strict per-turn durability. A crash during
an active call may lose transcript turns not covered by today's behavior, but PR 3
must not make every caller pay extra SQLite, enqueue, or buffer-update latency while
the agent is responding.

### Startup Recovery

```
lifespan startup
  │
  ├─ init_db(settings)
  ├─ executor.recover()
  │   ├─ SELECT * FROM background_jobs WHERE status IN ('pending','running')
  │   ├─ UPDATE running → pending (crash recovery reset)
  │   └─ for each: _active_job_ids.add(id), create_task(_run_job(id))
  └─ (continue lifespan: seed, sweeper, scheduler)
```

### CRM Error Classification Branch

```
crm_sync_handler(payload, db)
  │
  ├─ load CRM config → missing? → raise ConfigurationError
  ├─ call adapter.upsert(lead_data)
  │   ├─ Timeout/429/5xx → raise generic Exception (transient)
  │   └─ 401/schema mismatch → raise ConfigurationError
  └─ success → return
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/jobs/__init__.py` | Create | Package init |
| `backend/app/jobs/models.py` | Create | `BackgroundJob` SQLAlchemy model |
| `backend/app/jobs/executor.py` | Create | `JobExecutor` class: enqueue, _run_job, recover, backoff |
| `backend/app/jobs/registry.py` | Create | Handler registry + `ConfigurationError` exception |
| `backend/app/jobs/handlers/__init__.py` | Create | Package init, register all handlers |
| `backend/app/jobs/handlers/summarize.py` | Create | Wraps `generate_summary_and_facts` |
| `backend/app/jobs/handlers/crm_sync.py` | Create | Wraps `crm_sync_service.sync_lead` with error classification |
| `backend/app/jobs/handlers/transcript_flush.py` | Create | PR 3 only: handles off-call transcript reconciliation/finalization after normal end or cut/disconnect |
| `backend/alembic/versions/YYYYMMDD_NNNN_add_background_jobs.py` | Create | Migration: `background_jobs` table + indexes |
| `backend/app/core/config.py` | Modify | Add `enable_job_executor: bool = False` to Settings |
| `backend/app/main.py` | Modify | Import executor, call `executor.recover()` in lifespan after init_db, cancel on shutdown |
| `backend/app/calls/service.py` | Modify | `_schedule_summarize`: check flag and use `executor.enqueue()` or fallback; PR 3 may add call-boundary transcript finalization hooks but MUST NOT add work inside live user-turn handlers such as `schedule_user_turn_persist` |
| `backend/app/summarizer.py` | Modify | `_schedule_crm_sync`: check flag, use `executor.enqueue()` or fallback |
| `backend/app/core/database.py` | Modify | Add `import app.jobs.models` in `init_db` for ORM registration |

## Interfaces / Contracts

```python
# backend/app/jobs/models.py
class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[str]            # UUID4, PK
    job_type: Mapped[str]      # 'summarize' | 'crm_sync' | 'transcript_flush'
    payload: Mapped[str]       # JSON TEXT
    status: Mapped[str]        # 'pending' | 'running' | 'completed' | 'failed' | 'dead'
    attempts: Mapped[int]      # default 0
    max_attempts: Mapped[int]  # default 3
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    error: Mapped[str | None]  # JSON TEXT: {"message","type","operator_review"}

# backend/app/jobs/registry.py
class ConfigurationError(Exception): ...
HandlerFn = Callable[[dict, AsyncSession], Coroutine[Any, Any, None]]
def register(job_type: str, handler: HandlerFn) -> None: ...
def get_handler(job_type: str) -> HandlerFn: ...

# backend/app/jobs/executor.py
class JobExecutor:
    async def enqueue(self, job_type: str, payload: dict,
                      max_attempts: int = 3,
                      db: AsyncSession | None = None) -> str: ...
    async def recover(self) -> int: ...  # returns count recovered
    async def shutdown(self) -> None: ...  # drain active tasks
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | State machine transitions (pending→running→completed, →failed→dead) | Seed `BackgroundJob` rows, call `_run_job` with mock handlers, assert DB state. Strict TDD: red-green-refactor |
| Unit | Backoff calculation (exponential + jitter within bounds) | Pure function test, no DB |
| Unit | Handler registry (register, duplicate rejection, unknown type) | In-memory, no DB |
| Unit | Error classification (ConfigurationError vs generic → correct state) | Mock handler raises, assert `dead` + `operator_review` flag |
| Unit | Feature flag toggle (executor path vs raw create_task) | Patch `Settings.enable_job_executor`, assert correct dispatch |
| Unit | Error shape persisted correctly | Assert JSON structure in `error` column after failure |
| Unit | Transcript no-live-work guard | Assert live turn handlers do not add executor enqueue, DB writes, buffers, or per-turn durable jobs |
| Unit | Off-call transcript finalization | Assert normal end and cut/disconnect boundaries trigger bounded transcript reconciliation/finalization outside live turns |
| Integration | `executor.recover()`: seed pending/running jobs, recover, verify re-execution | Full DB via `db_engine` fixture, actual executor |
| Integration | Idempotency: recover same job twice, assert single execution | Track handler call count |
| Integration | Fresh session per retry: fail attempt 1 via DB error, succeed attempt 2 | Verify independent sessions |
| Integration | Migration: Alembic upgrade/downgrade round-trip | `apply_migrations` fixture (existing pattern) |

Test command: `cd backend && python3 -m pytest tests/ -q`

## Migration / Rollout

1. **Alembic migration** creates `background_jobs` table. Runs via `python scripts/migrate.py` before app startup (existing pattern). No FK to other tables — clean add/drop.
2. **Feature flag** `ENABLE_JOB_EXECUTOR=false` (default). Deploy migration + code with flag off → no behavior change. Flip to `true` when ready → all call sites switch to durable path. Legacy `create_task` paths preserved behind `else` branch for one release.
3. **Rollback**: set flag to `false`, Alembic downgrade drops table. No data dependencies.

## B9 Lifecycle Surface

B10 exposes these surfaces for B9 (observability) consumption:
- **Table queries**: `SELECT job_type, status, COUNT(*) FROM background_jobs GROUP BY 1,2` for dashboard metrics
- **Structured log events** (via structlog, already in use): `job_enqueued`, `job_started`, `job_completed`, `job_failed`, `job_dead`, `job_recovered`
- **Error field** JSON structure enables: failed-job rate by type, operator-review queue depth, p95 duration from `created_at → completed_at`

B9 reads only — B10 owns all writes to `background_jobs`.

## Open Questions

- [x] Transcript durability must not add live-call delay — confirmed by user; PR 3 remains gated for review
- [x] ElevenLabs sync stays fire-and-forget — confirmed out of scope
- [ ] Should `executor.shutdown()` attempt graceful drain of in-flight tasks on SIGTERM, or cancel immediately? (Current design: cancel like existing lifespan tasks. Drain adds complexity for MVP.)
