# Outbound Call Trigger Specification

## Purpose

Defines the observable behavior for manually triggering a real outbound call to a lead
from the Qora Leads list. Covers the feature flag guard, API endpoint contract,
call attempt persistence, live status state machine, failure classification, one-time
transient retry, provider metadata storage, FAS-safe semantics, and frontend UX.
Scheduler reuse is architecturally accommodated but not activated in this slice.

---

## Requirements

### Requirement: Feature Flag Guard

The system MUST gate all real telephony actions behind the `ENABLE_OUTBOUND_CALLS`
operator flag. When the flag is absent or `false`, no call MAY be placed and no charge
MAY be incurred.

#### Scenario: Flag off — trigger rejected

- GIVEN `ENABLE_OUTBOUND_CALLS=false` (or unset)
- WHEN `POST /clients/{client_id}/leads/{lead_id}/call` is received
- THEN the system returns HTTP 403
- AND no `CallSession` is created
- AND the ElevenLabs outbound API is not called

#### Scenario: Flag on — trigger proceeds

- GIVEN `ENABLE_OUTBOUND_CALLS=true` and a valid admin API key
- WHEN a valid trigger request arrives for an eligible lead
- THEN the system proceeds with E.164 validation and concurrent-call check

---

### Requirement: Manual Trigger Endpoint

The system MUST expose `POST /clients/{client_id}/leads/{lead_id}/call` protected by
admin API key authentication. The endpoint MUST validate the lead's phone number is
E.164-formatted before proceeding.

#### Scenario: Valid lead — call initiated

- GIVEN the feature flag is on and the lead has a valid E.164 phone number and no active call
- WHEN the endpoint is called with a valid admin API key
- THEN a `CallSession` is created with `telephony_status=dialing` before the ElevenLabs API is called
- AND the endpoint returns `{ status, call_session_id }` after the ElevenLabs call completes or errors

#### Scenario: Invalid phone number — rejected before any charge

- GIVEN the lead's `phone` field is not valid E.164
- WHEN the trigger endpoint is called
- THEN HTTP 422 is returned with a descriptive error
- AND no `CallSession` is created
- AND the ElevenLabs API is not called

#### Scenario: Unauthorized request

- GIVEN no admin API key or an invalid key in the request
- WHEN the trigger endpoint is called
- THEN HTTP 401 or 403 is returned
- AND no `CallSession` is created

---

### Requirement: Concurrent Call Guard

The system MUST reject a trigger attempt if the lead already has an active `CallSession`
or an `in_progress` `ScheduledCall`, preventing duplicate charges and overlapping sessions.

#### Scenario: Active session detected — rejected

- GIVEN a lead has a `CallSession` with `telephony_status` in `{dialing, ringing, in_call}`
- WHEN the trigger endpoint is called for the same lead
- THEN HTTP 409 is returned
- AND no new `CallSession` is created

#### Scenario: No active session — proceeds

- GIVEN the lead has no active `CallSession` and no `in_progress` `ScheduledCall`
- WHEN the trigger endpoint is called
- THEN the trigger proceeds normally

---

### Requirement: Call Attempt Persistence

The system MUST create a `CallSession` record before calling the ElevenLabs API. The
record MUST capture telephony metadata — `provider_call_id`, `telephony_provider`,
`telephony_status`, `telephony_error`, and `provider_metadata` — and update them on
API result or error.

#### Scenario: Pre-dial record created

- GIVEN a trigger request passes all guards
- WHEN the ElevenLabs API call is about to be dispatched
- THEN a `CallSession` row with `telephony_status=dialing` exists in the database
- AND the row is visible before the API response arrives

#### Scenario: Successful API response persisted

- GIVEN ElevenLabs returns a `provider_call_id` and optional `provider_metadata`
- WHEN the API response is processed
- THEN `CallSession.provider_call_id` is set
- AND `CallSession.provider_metadata` stores only safe/allowlisted provider fields
   (permitted: `call_id`, `status`, `duration_seconds`, `billed_duration_seconds`, `cost`;
    `message` and all other fields including PII and routing data are dropped —
    free-form provider messages may contain phone numbers, caller names, or SIP addresses)
- AND `telephony_status` is updated to `ringing` or the provider-reported equivalent

#### Scenario: Cost and billed seconds persisted when available

- GIVEN the ElevenLabs response includes `cost` and `billed_duration_seconds`
- WHEN the response is persisted
- THEN both values are stored in `provider_metadata` without transformation

---

### Requirement: Live Status State Machine

A `CallSession` MUST progress through a defined set of telephony status values:
`dialing → ringing → in_call → completed | no_answer | failed | recurrent_error`.
Transitions MUST be driven by observable provider or webhook events. No status MUST
skip ahead without a corresponding event.

| From | To | Trigger |
|------|----|---------|
| `dialing` | `ringing` | ElevenLabs API accepted; SIP INVITE sent |
| `ringing` | `in_call` | SIP 200 OK received from provider |
| `in_call` | `completed` | Conversation webhook session-end fired |
| `ringing` | `no_answer` | Provider reports no answer / ring timeout |
| `dialing` | `dialing` | First transient error is logged; one retry begins without an intermediate durable state change |
| `dialing` | `ringing` | Retry accepted by ElevenLabs |
| `dialing` | `recurrent_error` | Second transient error after retry; both error details are persisted |
| `dialing` | `failed` | Permanent / non-retryable error |

#### Scenario: Happy path transitions

- GIVEN a call is triggered and ElevenLabs accepts it
- WHEN SIP 200 OK arrives and the conversation completes normally
- THEN `CallSession.telephony_status` progresses: `dialing → ringing → in_call → completed`

#### Scenario: No-answer — distinct from failure

- GIVEN the provider reports no answer (ring timeout, voicemail network response)
- WHEN the status is resolved
- THEN `telephony_status` is set to `no_answer`
- AND no automatic retry is initiated

---

### Requirement: Failure Classification and One-Time Retry

The system MUST classify failures as transient (network/system errors, rate limits,
provider timeouts) or permanent (invalid parameters, auth errors, lead not found).
A transient failure on the first attempt MUST trigger one automatic retry. A second
consecutive transient failure MUST result in `recurrent_error` status. Permanent
failures MUST NOT be retried.

#### Scenario: Transient error — retried once

- GIVEN the ElevenLabs API returns a transient error (5xx, timeout, rate limit)
- WHEN the first attempt fails
- THEN `telephony_status=dialing` remains durably active while the first error is logged
- AND the system initiates exactly one retry without an intermediate failed-state write
- AND an accepted retry clears any retryable error, while a second transient failure persists both error details

#### Scenario: Second transient failure — recurrent_error

- GIVEN a retry was already performed after the first transient failure
- WHEN the retry also returns a transient error
- THEN `telephony_status=recurrent_error` is set
- AND no further automatic retry is attempted
- AND `telephony_error` preserves the cause of both failures

#### Scenario: Permanent error — no retry

- GIVEN the ElevenLabs API returns a permanent error (4xx non-rate-limit, invalid agent ID)
- WHEN the error is classified
- THEN `telephony_status=failed` is set immediately
- AND no retry is attempted

---

### Requirement: FAS-Safe Semantics

The system MUST store provider-reported telephony state separately from evidence of
a real human conversation. Provider SIP acknowledgment (`in_call`) MUST NEVER
automatically set `telephony_status=completed`. A `completed` status MUST require
evidence from the Custom LLM webhook conversation session-end callback.

#### Scenario: SIP answer without conversation webhook

- GIVEN the provider reports SIP 200 OK (`in_call`)
- WHEN no conversation session-end webhook arrives within the call window
- THEN `telephony_status` remains `in_call` (or transitions to a provider-reported end state)
- AND `telephony_status` is NEVER set to `completed` without the webhook evidence
- AND `CallSession.elevenlabs_conversation_id` remains unset or partial until the webhook fires

#### Scenario: Webhook fires — completion confirmed

- GIVEN the Custom LLM webhook session-end fires with a matching `conversation_id`
- WHEN the session is linked to the `CallSession` via `provider_call_id` or `conversation_id`
- THEN `telephony_status=completed` is set
- AND `elevenlabs_conversation_id` is stored on the `CallSession`

---

### Requirement: Scheduler Reuse Contract

The shared `dial_outbound_call(lead, agent, scheduled_call=None)` function MUST serve as
the sole entry point for dialing, accepting an optional `ScheduledCall` reference.
The manual trigger endpoint MUST call this function with `scheduled_call=None`.
The future scheduler tick MUST be able to call it with a `ScheduledCall` reference
without duplicating any business logic.

#### Scenario: Manual call — no ScheduledCall reference

- GIVEN a manual trigger with no associated `ScheduledCall`
- WHEN `dial_outbound_call` is invoked
- THEN `scheduled_call=None` is passed
- AND the function behaves identically except it does not update a `ScheduledCall` record

#### Scenario: Function signature is scheduler-compatible

- GIVEN the `dial_outbound_call` function exists
- WHEN the future scheduler tick calls it with a valid `ScheduledCall` instance
- THEN the function accepts the parameter without modification
- AND the `ScheduledCall` state can be updated by the same code path

---

### Requirement: Frontend Call Trigger UX

The Leads list MUST display a green "Call Now" button per row, positioned after the
`next_action` column. Before dispatching the call, the UI MUST show a confirmation
dialog warning the operator the call is real and incurs cost. After confirmation, the
UI MUST display an optimistic "Calling…" badge and refresh call history on the next poll.

#### Scenario: Confirmation dialog shown

- GIVEN the operator clicks "Call Now" for a lead
- WHEN the button is clicked
- THEN a confirmation dialog appears warning about real cost (~$0.21/min)
- AND the call is not dispatched until the operator confirms

#### Scenario: Optimistic badge after dispatch

- GIVEN the operator confirms the call
- WHEN `POST /leads/{id}/call` returns success
- THEN a "Calling…" badge appears on the lead row
- AND call history refreshes on the next polling cycle

#### Scenario: Error displayed on failure

- GIVEN the trigger endpoint returns an error (403, 409, 422)
- WHEN the response is received by the frontend
- THEN a user-readable error message is displayed
- AND no "Calling…" badge is shown
### Requirement: Strict Canonical Destination Guard

Before any manual or scheduled outbound dial path creates a `CallSession` or contacts a provider, the shared outbound guard MUST approve the stored lead phone only when it is already the exact canonical E.164 output of the approved phone-normalization policy under explicit `AR` context. The guard MUST enforce the Argentina-only mobile and fixed-line destination policy and reject malformed, unsupported, incomplete, or ambiguous stored values.

The guard MUST NOT normalize, repair, convert domestic `15` notation, infer an area code or mobile token, or backfill legacy storage at dial time. A rejected manual trigger MUST retain the existing HTTP 422 behavior. A rejected scheduled path MUST not create a session or provider request and MUST use its established failure handling without introducing or changing retry behavior.

#### Scenario: Manual trigger rejects a legacy noncanonical value before session creation

- GIVEN outbound calls are otherwise permitted and a lead stores synthetic legacy phone `011 15 5555-0101`
- WHEN a manual outbound trigger is requested
- THEN the endpoint returns HTTP 422
- AND no `CallSession` is created
- AND no provider request is made
- AND the stored phone remains `011 15 5555-0101`

#### Scenario: Scheduled path rejects an ambiguous stored value without dialing

- GIVEN a scheduled outbound path reaches its shared dial guard for a lead storing synthetic `011 5555-0101`
- WHEN the guard evaluates the value under explicit `AR` context
- THEN the value is rejected as ambiguous
- AND no `CallSession` is created
- AND no provider request is made
- AND the path does not add or alter retry behavior

#### Scenario: Canonical eligible number proceeds to existing guards

- GIVEN a lead stores synthetic canonical mobile `+5491155550101` and the required feature, authorization, concurrency, and consent guards pass
- WHEN manual or scheduled outbound evaluates the shared destination guard
- THEN the guard permits the existing outbound flow to continue unchanged
- AND that permission is a numbering-format classification, not a guarantee of subscriber assignment or reachability
