# Tasks: Phase B — Background Job Durability

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1,300 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 executor foundation → PR 2 post-call durability → PR 3 gated no-delay transcript durability |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Durable job table, executor, registry, recovery tests | PR 1 | Foundation; no call-flow behavior change unless flag enabled. |
| 2 | Post-call summary/lead/scheduling/CRM jobs and error visibility | PR 2 | Depends on PR 1; includes CRM classification tests. |
| 3 | No-delay transcript/user-turn durability | PR 3 | Final gated review slice; user must review the live-call latency strategy before coding. |

## Phase 1: Executor Foundation (PR 1)

- [x] 1.1 RED: add `backend/tests/jobs/test_executor.py` for enqueue, lifecycle, retry/dead-letter, preserved error audit, and fresh-session scenarios.
- [x] 1.2 Create `backend/alembic/versions/*_add_background_jobs.py` and `backend/app/jobs/models.py` with lifecycle/error columns and indexes.
- [x] 1.3 Create `backend/app/jobs/registry.py` with handler registration, duplicate rejection, unknown-job `ConfigurationError`, and tests.
- [x] 1.4 Create `backend/app/jobs/executor.py` with enqueue, `_run_job`, backoff+jitter, recovery idempotency, and shutdown tracking.
- [x] 1.5 Wire `backend/app/core/config.py`, `backend/app/core/database.py`, and `backend/app/main.py` for `ENABLE_JOB_EXECUTOR`, ORM registration, startup recovery, and safe flag-off behavior.

## Phase 2: Durable Post-Call Pipeline (PR 2)

- [ ] 2.1 RED: add tests for `backend/app/calls/service.py` enqueueing summary jobs before close response when the flag is on.
- [ ] 2.2 Create `backend/app/jobs/handlers/summarize.py` to run existing summary, lead update, and auto-scheduling logic through the executor.
- [ ] 2.3 RED: add CRM transient/config error tests covering retry, `dead`, and `operator_review=true` error JSON.
- [ ] 2.4 Create `backend/app/jobs/handlers/crm_sync.py` and modify `backend/app/summarizer.py` to enqueue durable CRM sync with legacy fallback.

## Phase 3: Minimal Operator Surface (PR 2)

- [ ] 3.1 Add a minimal internal query helper or route for `background_jobs` failed/dead rows, scoped to existing admin/internal patterns.
- [ ] 3.2 Test that dead CRM and pipeline jobs are queryable with `job_type`, `attempts`, and structured `error` fields for B9.

## Phase 4: Gated Transcript Durability (PR 3, Last)

- [ ] 4.1 Review gate before coding: choose a no-delay transcript strategy for `backend/app/calls/service.py` that never awaits DB/job writes in the live call path.
- [ ] 4.2 RED: add tests proving `schedule_user_turn_persist` does not synchronously enqueue one durable job per turn and preserves streaming latency.
- [ ] 4.3 Create the approved deferred/coalesced transcript persistence path (for example `backend/app/jobs/handlers/transcript_flush.py`) with bounded retry and session-identifiable failures.

## Verification

- [ ] 5.1 Run `cd backend && python3 -m pytest tests/ -q` after each PR slice.
