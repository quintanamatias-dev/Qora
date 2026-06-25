# Background Job Executor Specification

## Purpose

Durable in-process job execution backed by a persistent `background_jobs` table.
Replaces ad-hoc `asyncio.create_task` fire-and-forget calls with a lifecycle-managed
executor that survives process restarts, captures errors, and retries failed work.

## Requirements

### Requirement: Job Enqueue

The system MUST insert a `background_jobs` row atomically before dispatching
any job coroutine. The row MUST capture `job_type`, `payload` (JSON), `status=pending`,
`attempts=0`, and `max_attempts` at enqueue time.

#### Scenario: Successful enqueue

- GIVEN a registered job type and a valid JSON payload
- WHEN `executor.enqueue(job_type, payload)` is called
- THEN a `background_jobs` row with `status=pending` is persisted before the coroutine starts
- AND the coroutine is dispatched asynchronously

#### Scenario: Enqueue with unknown job type

- GIVEN an unregistered `job_type` string
- WHEN `executor.enqueue(job_type, payload)` is called
- THEN the system MUST raise a configuration error and NOT insert a row

---

### Requirement: Job Lifecycle State Machine

The system MUST transition each job through the lifecycle:
`pending → running → completed | failed | dead`.
No other transitions are valid. The system MUST NOT skip states.

#### Scenario: Happy path completion

- GIVEN a job with `status=pending`
- WHEN the executor picks it up and the handler succeeds
- THEN `status` becomes `completed` and `completed_at` is set

#### Scenario: Transient failure within max_attempts

- GIVEN a job with `attempts < max_attempts` and a handler that raises a transient error
- WHEN the handler raises an exception
- THEN `status` is set to `failed`, `attempts` is incremented, and `error` stores the last error message
- AND the job is re-enqueued for retry with exponential backoff and jitter

#### Scenario: Exhausted attempts — dead-letter

- GIVEN a job where `attempts == max_attempts`
- WHEN the handler raises an exception on the final attempt
- THEN `status` becomes `dead` and `error` stores the final error message
- AND the system MUST NOT retry the job further

---

### Requirement: Retry Backoff

The system MUST apply exponential backoff with jitter between retry attempts.
The backoff MUST NOT exceed a configurable maximum delay.

#### Scenario: Backoff increases between attempts

- GIVEN a job that has failed once
- WHEN the executor schedules the next retry
- THEN the delay is exponentially longer than the previous attempt's delay
- AND a random jitter component is added to prevent retry storms

---

### Requirement: Error Visibility

The system MUST persist the last error message and current attempt count in the
`background_jobs` row after every failure. Error data MUST NOT be silently discarded.
If a later retry succeeds, `status` becomes `completed`, but historical error metadata
(attempt count, last error message stored during failed attempts) MUST remain accessible
via the row's audit fields.

#### Scenario: Error captured on failure

- GIVEN a handler that raises an exception with a descriptive message
- WHEN the job fails
- THEN `error` field stores the exception message and `attempts` reflects the attempt count

#### Scenario: Transient failure then success — error history preserved

- GIVEN a job that failed on attempt 1 with an error message
- WHEN attempt 2 succeeds
- THEN `status` becomes `completed`
- AND `attempts` reflects the total attempt count including the failed one
- AND the `error` field from the last failure is not cleared (preserves audit trail)

---

### Requirement: Startup Recovery

The system MUST execute a recovery sweep during process startup that re-enqueues
all `background_jobs` rows with `status IN ('pending', 'running')`.
The sweep MUST be idempotent — re-running it on already-enqueued jobs MUST NOT
cause duplicate execution.

#### Scenario: Recovery after crash

- GIVEN one or more jobs with `status=pending` or `status=running` in the DB
- WHEN `executor.recover()` is called at startup
- THEN each such job is re-enqueued for execution
- AND no job is executed more than once per recovery sweep

#### Scenario: Recovery with no incomplete jobs

- GIVEN no `pending` or `running` jobs exist in the DB
- WHEN `executor.recover()` is called
- THEN no jobs are enqueued and no errors are raised

---

### Requirement: Handler Registry

The system MUST maintain a registry mapping `job_type` strings to async handler
functions. Each handler MUST accept `payload: dict` and return `None`.
Registering an already-registered `job_type` MUST raise a configuration error at
registration time, not at enqueue time.

#### Scenario: Duplicate registration rejected

- GIVEN a `job_type` that is already registered
- WHEN the same `job_type` is registered again
- THEN the system raises a configuration error immediately

---

### Requirement: Fresh DB Session Per Retry

The system MUST use an independent database session for each job execution attempt.
A session opened for attempt N MUST NOT be reused for attempt N+1.

#### Scenario: Session isolation between retries

- GIVEN a job that failed on attempt 1 due to a DB error
- WHEN attempt 2 is dispatched
- THEN a new DB session is created for attempt 2, independent of the failed session
