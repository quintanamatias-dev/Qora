# QORA Phase 2 — Memory and Persistence Specification

## Purpose

Closes the conversation lifecycle loop and adds cross-call memory. Covers three sub-phases:
Phase 2a (close the loop), Phase 2b (memory generation), Phase 2c (memory injection).

---

## Phase 2a — Close the Loop

### Requirement: CAP-1 User Turn Persistence

The system MUST persist every user utterance as a `TranscriptTurn` with `role="user"` after each SSE response cycle.

The source MUST be `body.messages[-1]` from the custom LLM webhook payload (last user message sent by ElevenLabs).

This persistence MUST be fire-and-forget — it MUST NOT block or delay the SSE stream response.

Both the user turn and the corresponding agent turn MUST be persisted for every conversation turn.

#### Scenario: User sends a message during active call

- GIVEN an active `CallSession` with a valid `session_id`
- WHEN the custom LLM webhook receives a request with `body.messages[-1]` containing the user utterance
- THEN a `TranscriptTurn` with `role="user"` and the utterance content MUST be persisted
- AND the SSE stream MUST not be delayed by the persistence operation

#### Scenario: Webhook payload has no user message

- GIVEN a webhook request where `body.messages` is empty or missing
- WHEN the system processes the request
- THEN no user `TranscriptTurn` is persisted
- AND the SSE stream MUST continue normally without error

#### Scenario: Both turns persisted per conversation round

- GIVEN a completed agent response for a user utterance
- WHEN the turn cycle completes
- THEN one `TranscriptTurn` with `role="user"` AND one with `role="agent"` MUST exist for that round

---

### Requirement: CAP-2 Call Session Lifecycle

**CAP-2a: End Endpoint**

The system MUST expose `POST /api/v1/calls/{conversation_id}/end`.

The endpoint MUST accept a body: `{ reason: "agent_goodbye" | "user_hangup" | "network_drop" | "timeout" | "reconnect_attempt" }`.

The endpoint MUST update `CallSession`: `status="completed"`, `ended_at`, `duration_seconds`, `billable_minutes`, `closed_reason`.

The endpoint MUST be idempotent: if the session is already `completed`, it MUST merge available data without returning an error.

`Lead.call_count` and `Lead.last_called_at` MUST be incremented/updated when the session closes — NOT during initiation.

#### Scenario: Frontend closes session normally

- GIVEN an active session with `status="initiated"`
- WHEN `POST /api/v1/calls/{id}/end` is called with `reason="agent_goodbye"`
- THEN `status` MUST become `"completed"`, `ended_at` and `duration_seconds` MUST be set
- AND `Lead.call_count` MUST increment by 1 and `Lead.last_called_at` MUST be set

#### Scenario: End called twice (idempotent)

- GIVEN a session already in `status="completed"`
- WHEN `POST /api/v1/calls/{id}/end` is called again
- THEN the response MUST be 200
- AND `Lead.call_count` MUST NOT be incremented a second time

**CAP-2b: ElevenLabs Post-Call Webhook**

The system MUST expose `POST /api/v1/calls/elevenlabs-postcall`.

This endpoint MUST receive the ElevenLabs conversation end payload.

This endpoint MUST act as a secondary source of truth: if session is already `completed`, it MUST merge transcript data from ElevenLabs if the ElevenLabs transcript has more turns than our stored transcript.

If the session is still `initiated`, the endpoint MUST close it (same logic as `/end` with `reason="network_drop"`).

#### Scenario: Post-call webhook closes an orphan session

- GIVEN a session with `status="initiated"` (frontend never called `/end`)
- WHEN the ElevenLabs post-call webhook fires with matching `conversation_id`
- THEN `status` MUST become `"completed"` and `Lead.call_count` MUST increment

#### Scenario: Post-call webhook arrives after frontend already closed

- GIVEN a session with `status="completed"`
- WHEN the ElevenLabs post-call webhook fires
- THEN the session MUST remain `completed`
- AND transcript turns from ElevenLabs MUST be merged if they contain more data

**CAP-2c: Background Sweeper**

The system MUST run a background sweeper that scans for `CallSession` records with `status="initiated"` where `started_at` is older than 10 minutes.

The sweeper MUST mark such sessions as `status="abandoned"` and set `ended_at` to the current time.

The sweeper MUST NOT increment `Lead.call_count` for abandoned sessions.

#### Scenario: Stale session swept

- GIVEN a session with `status="initiated"` and `started_at` > 10 minutes ago
- WHEN the sweeper runs
- THEN `status` MUST become `"abandoned"` and `ended_at` MUST be set
- AND `Lead.call_count` MUST remain unchanged

#### Scenario: Recent session not swept

- GIVEN a session with `status="initiated"` and `started_at` < 10 minutes ago
- WHEN the sweeper runs
- THEN the session MUST remain `status="initiated"` and MUST NOT be modified

---

### Requirement: CAP-3 Frontend Reconnect

The frontend MUST call `POST /api/v1/calls/{id}/end` with `reason="user_hangup"` when the WebSocket closes with code 1000.

The frontend MUST call `POST /api/v1/calls/{id}/end` with `reason="network_drop"` when the WebSocket closes with any non-1000 code.

On a non-1000 close, the frontend MUST display a "Se perdió la conexión" message and a "Reconectar" button.

Reconnect MUST be user-initiated only — no automatic reconnect.

When the user clicks "Reconectar", the frontend MUST call `POST /api/v1/calls/{id}/end` with `reason="reconnect_attempt"` before starting a new session.

#### Scenario: Clean WebSocket close

- GIVEN an active call with a valid session
- WHEN the WebSocket closes with code 1000
- THEN `POST /end` MUST be called with `reason="user_hangup"`
- AND no reconnect UI is shown

#### Scenario: Network drop

- GIVEN an active call with a valid session
- WHEN the WebSocket closes with code 1006 (or any non-1000)
- THEN "Se perdió la conexión" message and "Reconectar" button MUST be displayed
- AND `POST /end` MUST be called with `reason="network_drop"`

#### Scenario: User clicks Reconectar

- GIVEN the reconnect UI is shown after a network drop
- WHEN the user clicks "Reconectar"
- THEN `POST /end` MUST be called with `reason="reconnect_attempt"` for the dropped session
- AND a new call session MUST be initiated

---

## Phase 2b — Memory Generation

### Requirement: CAP-4 Post-Call Summary and Fact Extraction

After a session closes (via any path: `/end`, ElevenLabs webhook, or sweeper), the system MUST asynchronously generate a call summary using GPT-4o-mini.

Summary generation MUST be non-blocking — it MUST NOT delay session close response or SSE stream.

The summary MUST be at most 150 tokens and stored in `CallSession.summary`.

The system MUST also extract structured facts in a single GPT-4o-mini call:

| Field | Type | Description |
|-------|------|-------------|
| `objections` | list[str] | Objections heard during the call |
| `interest_level` | int 0–100 | Estimated interest score |
| `current_insurance` | str \| null | Insurance carrier if mentioned |
| `next_action_suggested` | enum | `call_again`, `send_quote`, `wait`, `do_not_call` |
| `misc_facts` | dict | Other relevant extracted facts |

Extracted facts MUST be stored in `CallSession.extracted_facts` (JSON).

After extraction, the system MUST merge facts into the `Lead` record:
- `Lead.summary_last_call` ← current summary
- `Lead.objections_heard` ← union of all objections (not replaced, merged)
- `Lead.interest_level` ← latest extracted value
- `Lead.extracted_facts` ← merge (new non-null fields overwrite old)
- If `next_action_suggested == "do_not_call"` → `Lead.do_not_call = True`

If GPT-4o-mini fails, the failure MUST be logged but MUST NOT affect session close or any other operation.

#### Scenario: Summary generated after clean call end

- GIVEN a session closed via `/end` with at least 2 transcript turns
- WHEN the async summarizer runs
- THEN `CallSession.summary` MUST be populated within 60 seconds
- AND `CallSession.extracted_facts` MUST contain at least the `interest_level` field
- AND facts MUST be merged into the `Lead` record

#### Scenario: Summary skipped for abandoned session with no turns

- GIVEN a session swept as `abandoned` with 0 transcript turns
- WHEN the async summarizer is triggered
- THEN no GPT call MUST be made
- AND `CallSession.summary` MUST remain null

#### Scenario: Summarizer fails

- GIVEN a session that has closed
- WHEN the GPT-4o-mini call fails (timeout or API error)
- THEN the error MUST be logged
- AND the session MUST remain `status="completed"` without summary
- AND `Lead.call_count` MUST NOT be reversed

#### Scenario: Lead flags do_not_call

- GIVEN a completed call where the lead expressed they do not want to be called again
- WHEN fact extraction runs and `next_action_suggested = "do_not_call"`
- THEN `Lead.do_not_call` MUST be set to `True`

---

### Requirement: CAP-5 New Model Fields

**CallSession additions** — the system MUST add:

| Field | Type | Nullable |
|-------|------|----------|
| `summary` | Text | Yes |
| `closed_reason` | String | Yes |
| `total_user_turns` | Int | Yes |
| `total_agent_turns` | Int | Yes |
| `extracted_facts` | JSON | Yes |

**Lead additions** — the system MUST add:

| Field | Type | Default | Nullable |
|-------|------|---------|----------|
| `summary_last_call` | Text | null | Yes |
| `objections_heard` | JSON | null | Yes |
| `interest_level` | Int 0–100 | null | Yes |
| `extracted_facts` | JSON | null | Yes |
| `do_not_call` | Bool | False | No |
| `next_action` | String | null | Yes |
| `next_action_at` | DateTime | null | Yes |

#### Scenario: Session closed with new fields populated

- GIVEN a session closed via `/end`
- THEN `closed_reason` MUST match the reason provided
- AND `total_user_turns` and `total_agent_turns` MUST reflect the actual turn counts

#### Scenario: Lead model persists do_not_call default

- GIVEN a newly created lead
- THEN `do_not_call` MUST default to `False`

---

## Phase 2c — Memory Injection

### Requirement: CAP-6 Conversation History Injection

During the initiation webhook, the system MUST load the last 3 completed `CallSession` records for the current lead, ordered by `ended_at` descending, filtering `status IN ("completed")`.

The system MUST format these sessions as a human-readable `call_history` string.

The system MUST format confirmed lead facts as a `confirmed_facts` string.

The system MUST inject the following `dynamic_variables` into the ElevenLabs initiation payload:

| Variable | Type | Fallback |
|----------|------|---------|
| `call_history` | str | `""` (empty string) |
| `confirmed_facts` | str | `""` (empty string) |
| `is_returning_caller` | bool | `false` |
| `call_number` | int | `1` |

When the lead has no prior completed sessions, all variables MUST use their fallback values — no error MUST be raised.

The `prompt.md` templates MUST be updated to use `{{call_history}}` and `{{confirmed_facts}}` variables.

#### Scenario: First call to a lead

- GIVEN a lead with `call_count = 0` and no completed sessions
- WHEN the initiation webhook runs
- THEN `is_returning_caller = false`, `call_number = 1`
- AND `call_history = ""` and `confirmed_facts = ""`
- AND the agent MUST start with a clean greeting

#### Scenario: Second call — history exists

- GIVEN a lead with 1 prior completed session with a summary
- WHEN the initiation webhook runs
- THEN `is_returning_caller = true`, `call_number = 2`
- AND `call_history` MUST contain the prior session summary
- AND the agent MUST be able to reference the previous call

#### Scenario: Lead with known insurance from prior call

- GIVEN a lead whose `extracted_facts` contains `current_insurance = "La Caja"`
- WHEN the initiation webhook runs
- THEN `confirmed_facts` MUST contain the insurance carrier information
- AND the agent MUST be able to reference it in the greeting

#### Scenario: Lead marked do_not_call

- GIVEN a lead with `do_not_call = True`
- WHEN the outbound dialer attempts to initiate a call
- THEN the call MUST NOT be initiated
- AND an appropriate status MUST be returned to the caller

#### Scenario: ElevenLabs post-call webhook merge

- GIVEN a session in `status="completed"` with 5 transcript turns
- WHEN the ElevenLabs post-call webhook fires with 8 turns for the same conversation
- THEN the additional 3 turns MUST be persisted as `TranscriptTurn` records
- AND summary regeneration MUST be triggered with the full transcript

---

## RFC 2119 Keywords

- **MUST / SHALL**: Absolute requirement — implementation is non-compliant if not met
- **MUST NOT / SHALL NOT**: Absolute prohibition
- **SHOULD**: Recommended; exceptions allowed with documented justification
- **MAY**: Optional
