# Durable Post-Call Pipeline Specification

## Purpose

Post-call work — summarization, lead update, auto-scheduling, and CRM sync — MUST
survive process restarts. Each of these operations is wrapped as a durable job via
the background job executor so that a crash or deployment does not silently discard
business-critical call outcomes.

## Requirements

### Requirement: Post-Call Summarization Is Durable

The system MUST enqueue a durable job for post-call summarization when a call session
is closed. The job MUST be persisted before the session-close response is returned.

#### Scenario: Summarization survives process restart

- GIVEN a call session that has just closed and a summarization job in `pending` state
- WHEN the process restarts before the handler completes
- THEN `executor.recover()` re-enqueues the job on startup
- AND the summarization handler runs to completion on the next attempt

#### Scenario: Summarization failure is recorded

- GIVEN the summarization handler raises an exception on every attempt
- WHEN `max_attempts` is exhausted
- THEN the job reaches `dead` status with the error stored in the `background_jobs` row
- AND the failure is visible via the job table without operator log parsing

---

### Requirement: Lead Update Is Durable

The system MUST enqueue lead field updates (name, phone, status, interest, notes, etc.)
as part of the durable post-call pipeline. Lead updates MUST NOT be lost due to a
process restart or transient error.

#### Scenario: Lead update retry on transient failure

- GIVEN a lead update job that fails due to a transient DB error
- WHEN `attempts < max_attempts`
- THEN the job is retried with exponential backoff
- AND the lead update is applied on the successful retry

---

### Requirement: Auto-Scheduling Is Durable

The system MUST enqueue the auto-scheduling step (evaluation of scheduling rules
and creation of a `ScheduledCall` row) as a durable job. Auto-scheduling MUST be
attempted at least once after every call session close where scheduling rules are
configured for the agent.

#### Scenario: Auto-scheduling survives process restart

- GIVEN an auto-scheduling job with `status=pending` when the process restarts
- WHEN `executor.recover()` runs at startup
- THEN the auto-scheduling job is re-enqueued and the scheduling rules are evaluated

#### Scenario: Auto-scheduling no-op when no rules match

- GIVEN an auto-scheduling job that runs but no scheduling rules match the call outcome
- WHEN the handler completes
- THEN `status` becomes `completed` with no `ScheduledCall` row created
- AND no error is recorded

---

### Requirement: CRM Sync Is Durable With Error Classification

The system MUST enqueue CRM sync (e.g., Airtable upsert) as a durable job.
CRM sync MUST distinguish transient errors from configuration/mapping errors:

- **Transient errors** (timeouts, API rate limits, temporary outages): retry up to `max_attempts` (default 3) with exponential backoff.
- **Configuration errors** (schema mismatch, missing field mapping, authentication failure): retry at most once, then transition to `dead` with an operator-review flag stored in the `error` field.

#### Scenario: CRM sync retries on transient error

- GIVEN a CRM sync job and a transient API timeout on attempt 1
- WHEN `attempts < max_attempts`
- THEN the job is retried after backoff
- AND the sync is applied on the successful retry

#### Scenario: CRM sync dead-letters on config error

- GIVEN a CRM sync job and a schema-mapping error on attempt 1
- WHEN the error is classified as a configuration error
- THEN the job transitions to `dead` after at most 1 additional retry
- AND the `error` field contains an operator-review flag alongside the error message

#### Scenario: Permanently failed CRM sync is visible

- GIVEN a CRM sync job with `status=dead`
- WHEN an operator queries `background_jobs WHERE status='dead'`
- THEN the row is present with `job_type='crm_sync'`, `error` populated, and `attempts` recorded

---

### Requirement: Post-Call Pipeline Error Visibility

Each step of the post-call pipeline (summarization, lead update, auto-scheduling,
CRM sync) MUST record failure details in the `background_jobs` table. Failures MUST
NOT be visible only in application logs.

#### Scenario: All pipeline steps independently tracked

- GIVEN a call session close that triggers all four pipeline steps
- WHEN any individual step fails
- THEN only that step's job row transitions to `failed` or `dead`
- AND other pipeline step jobs are unaffected and continue independently
