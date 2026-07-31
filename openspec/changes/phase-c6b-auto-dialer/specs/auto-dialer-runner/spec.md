# Auto-Dialer Runner Specification

## Purpose

Defines the observable behavior of the scheduler's automatic outbound dialer:
claiming due `ScheduledCall` rows, dialing them through the existing
`dial_outbound_call` seam, resolving completion from real call outcomes, and
recovering rows stranded by process crashes or lost webhook signals. Covers
both retry lanes — Qora-owned `tech_retry` and agent-scheduled recontacts
(`auto_retry`, `followup_tool`, `manual`).

## Requirements

### Requirement: Feature-Flag Gating

The system MUST gate the auto-dialer behind `enable_auto_dialer` (default
`False`), AND-composed with `enable_outbound_calls`. Startup MUST fail if
`enable_auto_dialer=True` while `enable_outbound_calls=False`. When
`enable_auto_dialer=False`, the scheduler tick MUST NOT query for dial
candidates — it MUST execute the same promote-only path as before this change.

#### Scenario: Flag off — promote-only path, no auto-dialer events

- GIVEN `enable_auto_dialer=False`
- WHEN a scheduler cycle runs with a due `ScheduledCall`
- THEN the row is promoted to `in_progress` via the existing promote path
- AND `scheduler_tick_promoted` fires
- AND no `auto_dialer_*` event fires

#### Scenario: Invalid combination fails at startup

- GIVEN `enable_auto_dialer=True` and `enable_outbound_calls=False`
- WHEN the application starts
- THEN startup MUST fail with an explicit configuration error
- AND the app MUST NOT boot into a state where the operator believes the
  dialer is running

### Requirement: Atomic Claim Semantics

A due `ScheduledCall` MUST be claimed by exactly one worker via an atomic
conditional transition (`pending → in_progress`, succeeding only when applied
to that one row). A lead MUST NOT have two concurrent active (`in_progress`)
`ScheduledCall` rows. Claim conflicts — a lost race or a second row for a
lead already active — MUST be logged and MUST NOT raise or abort the cycle.

#### Scenario: Two workers race to claim the same row

- GIVEN a due `pending` `ScheduledCall`
- WHEN two workers attempt to claim it concurrently
- THEN exactly one worker transitions it to `in_progress`
- AND the losing worker returns without dialing and logs
  `auto_dialer_claim_conflict`

#### Scenario: A lead already has an active row

- GIVEN a lead already has one `ScheduledCall` `in_progress`
- WHEN a second due row for the same lead is claimed
- THEN the second claim fails without raising
- AND the cycle continues to the next candidate

### Requirement: Dial-Time Re-Validation

Before dialing a claimed row, the system MUST re-check the client's
allowed-hours window and the lead's `do_not_call` flag — not only at
scheduling time.

#### Scenario: Claimed row now outside allowed hours

- GIVEN a claimed row becomes due to dial outside the client's allowed-hours
  window
- WHEN the dial step runs
- THEN the row is released back to `pending` with `scheduled_at` moved to the
  next allowed slot, and no dial is attempted
- AND `auto_dialer_dial_outside_allowed_hours` fires

#### Scenario: Lead marked do_not_call after scheduling

- GIVEN a lead's `do_not_call` flag was set true after the row was scheduled
- WHEN the dial step runs
- THEN the row is set to `cancelled` and no dial is attempted
- AND `auto_dialer_dial_skipped_do_not_call` fires

### Requirement: Bounded Sequential Concurrency

Dials MUST execute sequentially over one shared database session per cycle,
bounded by `auto_dialer_max_concurrent_dials` (default 1) via the claim batch
size. One dial raising an unexpected exception MUST NOT abort the remaining
claimed rows in the same cycle.

#### Scenario: One dial fails unexpectedly, others still run

- GIVEN a cycle has claimed three rows and the second raises an unexpected
  exception
- WHEN the cycle processes the batch
- THEN the second row is forced to `failed` and
  `auto_dialer_dial_unhandled_exception` fires
- AND the first and third rows still complete their own dial attempt

#### Scenario: Concurrency cap bounds the batch

- GIVEN `auto_dialer_max_concurrent_dials=1`
- WHEN more than one row is due in the same cycle
- THEN at most one row is claimed and dialed in that cycle

### Requirement: Technical-Retry Allowed-Hours Clamp

`schedule_tech_retry` MUST clamp its scheduled time to the client's
allowed-hours window, rolling forward to the next allowed slot when the
unclamped time falls outside it. Inside the window, the result MUST be
unchanged from the fixed 5-minute delay.

#### Scenario: Failure inside allowed hours — unchanged delay

- GIVEN a dial fails at 14:00 client-local time (inside the allowed window)
- WHEN `schedule_tech_retry` runs
- THEN the retry is scheduled for exactly 5 minutes later

#### Scenario: Failure outside allowed hours — rolled forward

- GIVEN a dial fails at 23:58 client-local time (outside the allowed window)
- WHEN `schedule_tech_retry` runs
- THEN the retry is scheduled for the next allowed-hours start time
- AND `tech_retry_deferred_to_allowed_hours` fires with the deferred-minutes
  count

### Requirement: Outcome-Driven Completion

A `ScheduledCall` MUST reach `completed` only when the linked `CallSession`
resolves to a terminal telephony status: `completed` or `voicemail` map to
`completed`; `no_answer`, `failed`, `recurrent_error`, `stale_in_call` map to
`failed`. Resolution MUST read the telephony status after any
voicemail-heuristic rewrite, and MUST be idempotent — a session already
resolved MUST NOT be resolved a second time.

#### Scenario: Real conversation completes

- GIVEN a claimed row's linked `CallSession` resolves with
  `telephony_status=completed`
- WHEN resolution runs
- THEN the `ScheduledCall` is set to `completed`

#### Scenario: Voicemail heuristic rewrites status before resolution

- GIVEN a `CallSession` is initially `completed` but the voicemail heuristic
  rewrites it to `voicemail` first
- WHEN resolution runs
- THEN the `ScheduledCall` reads the post-heuristic value and is set to
  `completed`, not left unresolved from the pre-heuristic value

#### Scenario: Resolution runs twice for the same session

- GIVEN a `CallSession`'s resolution has already resolved its `ScheduledCall`
- WHEN the same session is closed a second time
- THEN the second resolution is a no-op

### Requirement: Tech-Retry Cancellation on Successful Conversation

When a session resolves to `completed` (per the mapping above), a pending
`tech_retry` `ScheduledCall` for the same lead MUST be cancelled. A pending
`tech_retry` MUST be left untouched when the session resolves to `failed`. A
`tech_retry` already claimed (`in_progress`) MUST NOT be cancelled.

#### Scenario: Successful call cancels the parked retry

- GIVEN a lead has a pending `tech_retry` row and a separate call for that
  lead resolves to `completed`
- WHEN resolution runs
- THEN the pending `tech_retry` is set to `cancelled`
- AND `tech_retry_cancelled_by_successful_call` fires

#### Scenario: Failed call does not cancel the parked retry

- GIVEN a lead has a pending `tech_retry` row and a separate call for that
  lead resolves to `failed`
- WHEN resolution runs
- THEN the pending `tech_retry` remains `pending`, untouched

#### Scenario: In-progress tech_retry is never cancelled

- GIVEN a lead's `tech_retry` row is already `in_progress` (claimed)
- WHEN a separate call for that lead resolves to `completed`
- THEN the `in_progress` `tech_retry` is left unchanged — it resolves through
  its own dial outcome or the reaper

### Requirement: Stranded-Row Recovery — Never Dialed

A row `in_progress` with no `outcome_session_id` past a claim timeout MUST be
released to `pending` (attempts remaining) or set to `failed` (attempts
exhausted). A row aged beyond the stranded-row cap MUST be set to `failed`
regardless of remaining attempts. A released row's `scheduled_at` MUST be
re-clamped to the allowed-hours window only when the clamp moves it forward.

#### Scenario: Never-dialed row with attempts remaining is released

- GIVEN a row is `in_progress`, has no `outcome_session_id`, and is past the
  claim timeout, with attempts remaining
- WHEN the reaper runs
- THEN the row is released to `pending`
- AND `scheduled_call_reaped_stale` fires with `requeued=true`

#### Scenario: Never-dialed row with attempts exhausted is failed

- GIVEN the same condition but attempts are exhausted
- WHEN the reaper runs
- THEN the row is set to `failed`
- AND `scheduled_call_reap_exhausted` fires

#### Scenario: Release inside allowed hours keeps original schedule

- GIVEN a stranded row is released during the client's allowed-hours window
- WHEN the release clamp is applied
- THEN `scheduled_at` is left unchanged, not reset forward

#### Scenario: Row aged past the stranded cap is failed regardless of attempts

- GIVEN a row has been `in_progress` beyond the age-out cap
- WHEN the reaper runs
- THEN the row is set to `failed` even if attempts remain

### Requirement: Stranded-Row Recovery — Dialed, No Completion Signal

A row `in_progress` with an `outcome_session_id` set MUST be resolved from its
linked `CallSession`'s terminal telephony status, using the same mapping as
outcome-driven completion. A non-terminal status MUST be left untouched. A
missing linked `CallSession` MUST be treated as a recovery failure.

#### Scenario: Linked session has reached a terminal status

- GIVEN a claimed row's linked `CallSession` has a terminal
  `telephony_status`
- WHEN the reaper runs
- THEN the row is resolved via the shared mapping table

#### Scenario: Linked session is missing

- GIVEN a claimed row's `outcome_session_id` points at a `CallSession` that
  no longer exists
- WHEN the reaper runs
- THEN the row is set to `failed`
- AND `scheduled_call_reap_session_missing` fires

### Requirement: Rollout Gate

`enable_auto_dialer` MUST remain `False` in every environment until the
stranded-row reaper — covering both recovery classes above — ships and runs.

#### Scenario: Flag stays off before full recovery coverage ships

- GIVEN only claim-and-dial and outcome-driven completion have shipped
- WHEN deployment configuration is reviewed
- THEN `enable_auto_dialer` MUST be `False` in every environment
