# Tasks: Phase B — Background Job Durability

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900-1,300 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 executor foundation → PR 2 post-call durability → PR 3 off-call transcript reconciliation |
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
| 3 | Off-call transcript reconciliation/finalization | PR 3 | Final slice; no new work is allowed in live user-turn handlers. |

## Phase 1: Executor Foundation (PR 1)

- [x] 1.1 RED: add `backend/tests/jobs/test_executor.py` for enqueue, lifecycle, retry/dead-letter, preserved error audit, and fresh-session scenarios.
- [x] 1.2 Create `backend/alembic/versions/*_add_background_jobs.py` and `backend/app/jobs/models.py` with lifecycle/error columns and indexes.
- [x] 1.3 Create `backend/app/jobs/registry.py` with handler registration, duplicate rejection, unknown-job `ConfigurationError`, and tests.
- [x] 1.4 Create `backend/app/jobs/executor.py` with enqueue, `_run_job`, backoff+jitter, recovery idempotency, and shutdown tracking.
- [x] 1.5 Wire `backend/app/core/config.py`, `backend/app/core/database.py`, and `backend/app/main.py` for `ENABLE_JOB_EXECUTOR`, ORM registration, startup recovery, and safe flag-off behavior.

## Phase 2: Durable Post-Call Pipeline (PR 2a — summarize only)

- [x] 2.1 RED: add tests for `backend/app/calls/service.py` enqueueing summary jobs before close response when the flag is on.
- [x] 2.2 Create `backend/app/jobs/handlers/summarize.py` to run existing summary, lead update, and auto-scheduling logic through the executor.
- [x] B1 Handler registration on normal app import path — `import app.jobs.handlers` in `backend/app/main.py`.
- [x] B2 Durable summarize handler uses `generate_summary_and_facts_durable()` (not fire-and-forget variant).
- [x] B4 `_run_summarizer(durable=True)` re-raises GPT failures so executor sees them for retry/dead-letter.
  - [x] 2.3 RED: add CRM transient/config error tests covering retry, `dead`, and `operator_review=true` error JSON. (PR 2b)
  - [x] 2.4 Create `backend/app/jobs/handlers/crm_sync.py` and modify `backend/app/summarizer.py` to enqueue durable CRM sync with legacy fallback. (PR 2b)

## Phase 3: Minimal Operator Surface (PR 2b)

  - [x] 3.1 Add a minimal internal query helper for `background_jobs` failed/dead rows (`backend/app/jobs/queries.py`).
  - [x] 3.2 Test that dead CRM and pipeline jobs are queryable with `job_type`, `attempts`, and structured `error` fields for B9.

## Phase 4: Off-Call Transcript Durability (PR 3, Last)

- [x] 4.1 RED: add tests proving `backend/app/calls/service.py::schedule_user_turn_persist` adds no executor enqueue, DB write, buffer mutation, or transcript reconciliation during live turns.
- [x] 4.2 Add call-boundary transcript reconciliation/finalization hooks in `backend/app/calls/service.py` for normal end and cut/disconnect only.
- [x] 4.3 Create `backend/app/jobs/handlers/transcript_flush.py` only for off-call transcript finalization, with `max_attempts=2` and session-identifiable failures.
- [x] 4.4 Add tests proving live turn handlers do not create per-turn durable job rows, while end/cut boundaries may enqueue off-call transcript finalization.

## Verification

- [x] 5.1 Run `cd backend && python3 -m pytest tests/ -q` after each PR slice.
