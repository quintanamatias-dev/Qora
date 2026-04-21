# Delta Spec: qora-session-continuity

## Purpose

Closes the broken session lifecycle that causes every `CallSession` to be created with `lead_id=NULL` and `elevenlabs_conversation_id=NULL`. Covers five capabilities: frontend propagation of `lead_id`, `conversation_id` capture, backend persistence on session creation, reconciliation fallback on `/end`, and end-to-end memory cycle validation.

---

## CAP-1: Frontend Propagates lead_id via custom_llm_extra_body

### Requirement: REQ-1.1 — Include lead_id in WebSocket handshake

The frontend MUST include `custom_llm_extra_body: { lead_id: <lead_id> }` as a field of the `conversation_initiation_client_data` WebSocket message whenever a lead is selected.

#### Scenario: Lead selected — custom_llm_extra_body is sent

- GIVEN a lead with `lead_id = "lead-42"` is selected in the UI
- WHEN the frontend sends `conversation_initiation_client_data` via WebSocket
- THEN the message JSON MUST contain `custom_llm_extra_body.lead_id = "lead-42"`

#### Scenario: client_id NOT included in custom_llm_extra_body

- GIVEN a lead is selected and a `client_id` is available
- WHEN the frontend sends `conversation_initiation_client_data`
- THEN the message JSON MUST NOT contain `custom_llm_extra_body.client_id`
- AND the message MUST NOT trigger a `client_id_mismatch` backend log

#### Scenario: No lead selected (demo mode) — custom_llm_extra_body omitted or null

- GIVEN no lead is selected (demo mode)
- WHEN the frontend sends `conversation_initiation_client_data`
- THEN `custom_llm_extra_body` MAY be omitted entirely OR sent as `{ lead_id: null }`
- AND the backend MUST accept both forms without error

#### Scenario: Stale comment removed and replaced

- GIVEN the source file `backend/app/static/index.html`
- THEN the comment `// NOTE: do NOT include custom_llm_extra_body — ElevenLabs rejects it (1008)` MUST NOT exist
- AND a replacement comment citing `https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm.mdx` MUST be present

---

## CAP-2: Frontend Captures conversation_id and Uses It on /end

### Requirement: REQ-2.1 — Capture conversation_id from metadata event

The frontend MUST capture the `conversation_id` value from the `conversation_initiation_metadata_event` WebSocket message and store it in memory for the duration of the call (`currentSessionId`).

#### Scenario: Metadata event received — conversation_id captured

- GIVEN the WebSocket receives a message with `type = "conversation_initiation_metadata_event"`
- AND the message contains `conversation_id = "el-conv-abc123"`
- WHEN the frontend processes the message
- THEN `currentSessionId` MUST equal `"el-conv-abc123"`

### Requirement: REQ-2.2 — /end POST body includes conversation_id, client_id, lead_id

The frontend `/end` POST body MUST include `conversation_id`, `client_id`, and `lead_id`.

#### Scenario: /end body shape is correct

- GIVEN an active call with `currentSessionId = "el-conv-abc123"`, `client_id = "tenant-1"`, `lead_id = "lead-42"`
- WHEN the WebSocket closes and the frontend calls `POST /api/v1/calls/el-conv-abc123/end`
- THEN the request body MUST be `{ "reason": "<reason>", "conversation_id": "el-conv-abc123", "client_id": "tenant-1", "lead_id": "lead-42" }`

#### Scenario: currentSessionId is the conversation_id

- GIVEN the frontend captured `conversation_id = "el-conv-abc123"` from the metadata event
- WHEN `/end` is called
- THEN the URL path segment `{conversation_id}` MUST equal `currentSessionId` = `"el-conv-abc123"`

---

## CAP-3: Backend Persists elevenlabs_conversation_id on Session Creation

### Requirement: REQ-3.1 — conversation_id stored on CallSession at creation

When the custom-LLM webhook creates a new `CallSession`, it MUST pass the resolved `conversation_id` (from `body.conversation_id` OR `body.elevenlabs_extra_body.conversation_id`) as `elevenlabs_conversation_id` to `create_session()`.

### Requirement: REQ-3.2 — lead_id stored on CallSession at creation

When the custom-LLM webhook creates a new `CallSession`, it MUST pass `lead_id` resolved from `body.elevenlabs_extra_body.lead_id` as the `lead_id` argument to `create_session()`.

### Requirement: REQ-3.3 — Empty string coerced to NULL

If the resolved `conversation_id` or `lead_id` is an empty string `""`, the value MUST be coerced to `None`/`NULL` before being stored.

#### Scenario: conversation_id available in extra_body — persisted on session

- GIVEN the custom-LLM webhook receives `elevenlabs_extra_body.conversation_id = "el-conv-abc123"`
- WHEN `create_session()` is called
- THEN `CallSession.elevenlabs_conversation_id` MUST equal `"el-conv-abc123"`

#### Scenario: lead_id available in extra_body — persisted on session

- GIVEN the custom-LLM webhook receives `elevenlabs_extra_body.lead_id = "lead-42"`
- WHEN `create_session()` is called
- THEN `CallSession.lead_id` MUST equal `"lead-42"`

#### Scenario: Empty string conversation_id coerced to NULL

- GIVEN the custom-LLM webhook receives `elevenlabs_extra_body.conversation_id = ""`
- WHEN `create_session()` is called
- THEN `CallSession.elevenlabs_conversation_id` MUST be `NULL`

#### Scenario: Empty string lead_id coerced to NULL

- GIVEN the custom-LLM webhook receives `elevenlabs_extra_body.lead_id = ""`
- WHEN `create_session()` is called
- THEN `CallSession.lead_id` MUST be `NULL`

#### Scenario: conversation_id and lead_id both null — session still created

- GIVEN the custom-LLM webhook receives `elevenlabs_extra_body.conversation_id = null` and `lead_id = null`
- WHEN `create_session()` is called
- THEN a `CallSession` MUST be created with `elevenlabs_conversation_id = NULL` and `lead_id = NULL`
- AND no error MUST be raised

---

## CAP-4: /end Endpoint Reconciles Orphan Sessions

### Requirement: CAP-2a (Modified from qora-phase2) — End Endpoint with Reconciliation Fallback

The system MUST expose `POST /api/v1/calls/{conversation_id}/end`.

The endpoint MUST accept a body: `{ reason: "agent_goodbye" | "user_hangup" | "network_drop" | "timeout" | "reconnect_attempt", conversation_id?: str, client_id?: str, lead_id?: str }`. The `client_id` and `lead_id` fields are optional and backward-compatible.

The endpoint MUST update `CallSession`: `status="completed"`, `ended_at`, `duration_seconds`, `billable_minutes`, `closed_reason`.

The endpoint MUST be idempotent: if the session is already `completed`, it MUST merge available data without returning an error.

`Lead.call_count` and `Lead.last_called_at` MUST be incremented/updated when the session closes — NOT during initiation.

**Reconciliation fallback (new)**: If the `{conversation_id}` path parameter does NOT match any `CallSession.elevenlabs_conversation_id`, AND the request body contains `client_id` and `lead_id`, the endpoint MUST attempt reconciliation:

1. Query `CallSession WHERE client_id = request.client_id AND lead_id = request.lead_id AND elevenlabs_conversation_id IS NULL AND status = 'initiated' AND started_at >= now() - 120s ORDER BY started_at DESC LIMIT 1`
2. If a match is found: set `elevenlabs_conversation_id = request_conversation_id`, `status = "completed"`, `closed_reason = request.reason`, `ended_at = now()`, compute `duration_seconds`.
3. If no match is found: return HTTP 404.

(Previously: endpoint looked up session only by `elevenlabs_conversation_id`; no fallback when not found.)

#### Scenario: /end happy path — direct match

- GIVEN a `CallSession` with `elevenlabs_conversation_id = "el-conv-abc123"` and `status = "initiated"`
- WHEN `POST /api/v1/calls/el-conv-abc123/end` is called with `reason = "agent_goodbye"`
- THEN response MUST be HTTP 200
- AND `CallSession.status` MUST equal `"completed"`, `ended_at` MUST be set, `duration_seconds` MUST be a positive integer

#### Scenario: Reconciliation happy path — no elevenlabs_conversation_id on session

- GIVEN a `CallSession` with `elevenlabs_conversation_id = NULL`, `lead_id = "lead-42"`, `client_id = "tenant-1"`, `status = "initiated"`, `started_at = now() - 30s`
- WHEN `POST /api/v1/calls/el-conv-abc123/end` is called with `{ reason: "agent_goodbye", client_id: "tenant-1", lead_id: "lead-42" }`
- THEN response MUST be HTTP 200
- AND `CallSession.elevenlabs_conversation_id` MUST equal `"el-conv-abc123"`
- AND `CallSession.status` MUST equal `"completed"`

#### Scenario: Reconciliation — no match returns 404

- GIVEN no `CallSession` exists matching `(client_id="tenant-1", lead_id="lead-42", status="initiated", elevenlabs_conversation_id IS NULL)`
- WHEN `POST /api/v1/calls/unknown-conv/end` is called with `{ client_id: "tenant-1", lead_id: "lead-42" }`
- THEN response MUST be HTTP 404

#### Scenario: Reconciliation — session outside 120s window rejected

- GIVEN a `CallSession` with `elevenlabs_conversation_id = NULL`, `status = "initiated"`, `started_at = now() - 200s`
- WHEN reconciliation is attempted with matching `client_id` and `lead_id`
- THEN the session MUST NOT be selected
- AND response MUST be HTTP 404

#### Scenario: Reconciliation does not steal another tenant's session

- GIVEN a `CallSession` belonging to `client_id = "tenant-A"` with `status = "initiated"`, `elevenlabs_conversation_id = NULL`
- WHEN `POST /end` is called with `client_id = "tenant-B"` and matching `lead_id`
- THEN the `tenant-A` session MUST NOT be modified
- AND response MUST be HTTP 404

#### Scenario: Reconciliation only targets status="initiated" sessions

- GIVEN a `CallSession` with `elevenlabs_conversation_id = NULL`, `status = "completed"`, matching `client_id` and `lead_id`, within 120s
- WHEN reconciliation is attempted
- THEN the `completed` session MUST NOT be selected
- AND response MUST be HTTP 404

#### Scenario: Lead.call_count incremented exactly once on reconciliation

- GIVEN a successful reconciliation match
- WHEN the session is completed via reconciliation
- THEN `Lead.call_count` MUST be incremented by exactly 1
- AND `Lead.last_called_at` MUST be updated

#### Scenario: Reconciliation emits structured log event

- GIVEN a successful reconciliation
- WHEN the session is completed via reconciliation
- THEN a structured log entry with `event = "end_session_reconciled"` MUST be emitted
- AND the log MUST include fields: `reconciled_session_id`, `client_id`, `lead_id`, `conversation_id`, `age_seconds`

---

## CAP-5: End-to-End Memory Cycle

### Requirement: REQ-5.1 — Second call returns call_history from first call

When a second call for the same lead is initiated AFTER a first call completed and the summarizer ran, the initiation webhook MUST return `call_history` containing the first call's summary and `is_returning_caller = true`.

### Requirement: REQ-5.2 — Full cycle links all stages

The full cycle MUST be: call 1 initiated → `/end` completes (direct or reconciliation) → summarizer runs → `Lead.summary_last_call` populated → call 2 initiated → initiation webhook loads call 1 data → `dynamic_variables` include memory fields.

#### Scenario: First call — no history

- GIVEN a lead with no prior completed sessions
- WHEN the initiation webhook runs for the first call
- THEN `call_history` MUST equal `""`
- AND `is_returning_caller` MUST equal `false`
- AND `call_number` MUST equal `1`

#### Scenario: Second call — history present after first call completes

- GIVEN call 1 for `lead_id = "lead-42"` completed and summarizer ran, storing `CallSession.summary = "Cliente interesado en cobertura básica"` and `Lead.summary_last_call` is populated
- WHEN the initiation webhook runs for call 2
- THEN `call_history` MUST contain the text from `Lead.summary_last_call`
- AND `is_returning_caller` MUST equal `true`
- AND `call_number` MUST equal `2`

---

## Open Questions for Design

1. **Does ElevenLabs auto-inject `conversation_id` into `elevenlabs_extra_body`?** The docs indicate `custom_llm_extra_body` fields are forwarded verbatim as `elevenlabs_extra_body`. However, `conversation_id` might be auto-injected by EL at the top level independently. Design must verify empirically: if EL already provides it, the frontend need not send it; if not, REQ-2.1 is the only source of truth for reconciliation.

2. **Reconciliation window (120s) — is it configurable?** The spec uses 120s as a constant. Design must decide whether to make it an environment variable (e.g. `RECONCILIATION_WINDOW_SECONDS`) or hard-code it. Concurrent calls for the same lead within the window would be incorrectly matched — the window should be as tight as feasible.

3. **`EndSessionRequest` schema backward compatibility**: Adding optional `client_id` and `lead_id` fields must not break existing callers. Design must confirm that the Pydantic model defaults to `None` for these fields and that existing `/end` integrations (ElevenLabs post-call webhook) are not affected.

4. **Who increments `Lead.call_count` when reconciliation matches but session was already partially updated?** Edge case: if `/end` is called twice and the first call initiates reconciliation successfully, the second call must be idempotent (no double increment). The existing idempotency logic (CAP-2a scenario "End called twice") must extend to reconciled sessions.
