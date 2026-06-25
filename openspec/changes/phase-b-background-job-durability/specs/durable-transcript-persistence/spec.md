# Durable Transcript Persistence Specification

## Purpose

Transcript persistence must improve durability without changing the live voice
turn path. During an active call, Qora MUST NOT add new transcript durability
work beyond behavior that already exists today. New durability, reconciliation,
or finalization work MUST run before the call starts, after the call ends, or
after a cut/disconnect is detected.

## Requirements

### Requirement: No New Live-Call Transcript Work

The system MUST NOT add any new transcript durability write, executor enqueue,
buffer update, reconciliation step, or durable job insert to live user-turn
handlers. Live turns MUST continue using the already-existing request/session
context and today's transcript scheduling behavior only. New durable transcript
work MUST happen outside the live turn path.

#### Scenario: Live user turn path remains unchanged

- GIVEN a user turn with a valid `session_id` and `messages` payload
- WHEN the voice endpoint starts streaming the agent response
- THEN no new executor enqueue, DB write, buffer mutation, or reconciliation step is added
- AND the turn remains available from existing live call context for the active request

#### Scenario: Per-turn durable jobs are forbidden during live calls

- GIVEN multiple user turns occur during an active call
- WHEN each live turn handler executes
- THEN the system does not create one durable job row per turn
- AND the system does not synchronously or asynchronously enqueue transcript durability work from that handler

#### Scenario: New transcript durability runs off-call

- GIVEN a call ends normally or is cut/disconnected
- WHEN transcript reconciliation or finalization is triggered
- THEN durable transcript work runs after the live turn path has ended
- AND no caller-facing streaming latency is introduced

---

### Requirement: Off-Call Transcript Durability Uses Bounded Retries

Off-call transcript persistence SHOULD retry transient failures once
(`max_attempts=2`) before accepting bounded loss. Loss after 2 attempts MUST be
logged with the session ID but is not treated as a system error requiring operator
review.

#### Scenario: Off-call persistence succeeds on retry

- GIVEN off-call transcript persistence failed on attempt 1 due to a transient error
- WHEN `attempts < max_attempts`
- THEN the job or flush operation is retried after backoff
- AND durable transcript state is written if the retry succeeds

#### Scenario: Off-call persistence exhausts retries

- GIVEN off-call transcript persistence fails both attempts
- WHEN `attempts == max_attempts`
- THEN the durable work transitions to `dead` or an equivalent terminal failure state
- AND the failure is logged with the session ID and attempt count
- AND no operator-review flag is required (accepted loss)

---

### Requirement: In-Call Transcript Continuity

The system MUST NOT accept transcript turn loss that would cause the voice agent to
repeat itself or forget caller input within the same active call session. In-call
continuity MUST NOT depend on any new durable transcript work during the call.

#### Scenario: Live context preserves in-call continuity

- GIVEN an active call session where off-call transcript durability is delayed or fails
- WHEN the next user turn is processed
- THEN the agent uses live request/session context instead of waiting for durable storage
- AND the call continues without added latency from durability recovery

#### Scenario: Failed deferred durability is isolated

- GIVEN off-call transcript durability reaches a terminal failure state
- WHEN subsequent calls or post-call work proceed
- THEN unrelated durable jobs are not blocked by the transcript failure

---

### Requirement: Transcript Job Visibility

Dead off-call transcript durability work MUST be queryable from the `background_jobs` table
when the selected off-call strategy uses the executor. Dead transcript work MUST record
`session_id` in the `error` or `payload` field so the affected session can be
identified.

#### Scenario: Dead transcript job is identifiable

- GIVEN deferred transcript durability with `status=dead`
- WHEN the `background_jobs` table is queried for dead transcript jobs
- THEN the row contains the `session_id` in the `payload` JSON field
- AND `job_type` identifies transcript durability and `error` contains the failure reason
