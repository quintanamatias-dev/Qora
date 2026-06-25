# Durable Transcript Persistence Specification

## Purpose

Transcript persistence must improve durability without adding latency to the live
voice path. The spec defines the boundary: during a call, Qora does only the
minimum indispensable work; durable transcript writes run off-call, non-blocking,
buffered, or otherwise outside the real-time response path.

## Requirements

### Requirement: Live Call Path Remains Non-Blocking

The system MUST NOT perform an awaited durable transcript write or one synchronous
durable job insert per user turn in the live call response path. Live turns MUST
continue using the already-available call context while transcript durability is
handled through a non-blocking, after-call, buffered, or equivalent minimal-write
strategy. The chosen strategy MUST preserve real-time latency over durability.

#### Scenario: Live user turn does not wait for durable storage

- GIVEN a user turn with a valid `session_id` and `messages` payload
- WHEN the voice endpoint starts streaming the agent response
- THEN the response path does not await transcript DB writes or durable job enqueue
- AND the turn remains available from live call context for the active request

#### Scenario: Durable transcript work is deferred safely

- GIVEN multiple user turns occur during an active call
- WHEN transcript durability is scheduled
- THEN the system uses a minimal-write strategy that avoids one blocking job row per turn
- AND any durable work runs outside the critical streaming path

---

### Requirement: Deferred Transcript Durability Uses Bounded Retries

Deferred transcript persistence SHOULD retry transient failures once
(`max_attempts=2`) before accepting bounded loss. Loss after 2 attempts MUST be
logged with the session ID but is not treated as a system error requiring operator
review.

#### Scenario: Deferred persistence succeeds on retry

- GIVEN deferred transcript persistence failed on attempt 1 due to a transient error
- WHEN `attempts < max_attempts`
- THEN the job or flush operation is retried after backoff
- AND durable transcript state is written if the retry succeeds

#### Scenario: Deferred persistence exhausts retries

- GIVEN deferred transcript persistence fails both attempts
- WHEN `attempts == max_attempts`
- THEN the durable work transitions to `dead` or an equivalent terminal failure state
- AND the failure is logged with the session ID and attempt count
- AND no operator-review flag is required (accepted loss)

---

### Requirement: In-Call Transcript Continuity

The system MUST NOT accept transcript turn loss that would cause the voice agent to
repeat itself or forget caller input within the same active call session. In-call
continuity MUST NOT depend on durable transcript writes completing during the call.

#### Scenario: Live context preserves in-call continuity

- GIVEN an active call session where deferred transcript durability is delayed or fails
- WHEN the next user turn is processed
- THEN the agent uses live request/session context instead of waiting for durable storage
- AND the call continues without added latency from durability recovery

#### Scenario: Failed deferred durability is isolated

- GIVEN deferred transcript durability reaches a terminal failure state
- WHEN subsequent calls or post-call work proceed
- THEN unrelated durable jobs are not blocked by the transcript failure

---

### Requirement: Transcript Job Visibility

Dead transcript durability work MUST be queryable from the `background_jobs` table
when the selected strategy uses the executor. Dead transcript work MUST record
`session_id` in the `error` or `payload` field so the affected session can be
identified.

#### Scenario: Dead transcript job is identifiable

- GIVEN deferred transcript durability with `status=dead`
- WHEN the `background_jobs` table is queried for dead transcript jobs
- THEN the row contains the `session_id` in the `payload` JSON field
- AND `job_type` identifies transcript durability and `error` contains the failure reason
