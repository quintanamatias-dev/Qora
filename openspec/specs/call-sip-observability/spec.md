# Call SIP Observability Specification

## Purpose

Defines behavior for capturing, storing, and surfacing ElevenLabs/Telnyx SIP
observability fields on `CallSession`. Covers the post-dial background probe,
background reconciliation sweep, structured-field-only extraction, idempotency
guards, ambiguous-state handling, rate-limit safety, and secret-exclusion rules.

---

## Requirements

### Requirement: Structured-Field-Only SIP Extraction

The system MUST extract only the following structured fields from ElevenLabs SIP
message responses:

| Field | Source | Stored As |
|---|---|---|
| SIP Call-ID (`otb_...`) | `Call-ID` header | `CallSession.sip_call_id` |
| Provider conversation ID | ElevenLabs conversation metadata | `CallSession.elevenlabs_conversation_id` (existing) |
| Telnyx Session ID / Leg ID | Structured SIP header or provider metadata | `CallSession.sip_call_id` (best available) |
| Final SIP status code | Last SIP response status line | `CallSession.sip_status_code` |
| Final SIP reason phrase | Last SIP response reason | `CallSession.sip_reason` |
| Reconciliation timestamp | System clock at write time | `CallSession.reconciled_at` |
| Reconciliation source | Literal `"probe"` or `"sweep"` | `CallSession.reconciliation_source` |

The system MUST NOT persist raw SIP message bodies, `Proxy-Authorization` headers,
`Authorization` headers, SIP digest responses, `From`/`To` URI userinfo components
(phone numbers embedded in SIP URIs), or any credential material extracted from SIP
messages.

#### Scenario: Safe fields extracted — secrets excluded

- GIVEN an ElevenLabs SIP messages API response containing a `Call-ID` header,
  a `Proxy-Authorization` header, and a final `404 Not Found` status
- WHEN the probe or sweep processes the response
- THEN `sip_call_id` is set to the `Call-ID` value
- AND `sip_status_code` is set to `404`
- AND `sip_reason` is set to `"Not Found"`
- AND the `Proxy-Authorization` header value is NOT stored anywhere
- AND no raw SIP message body is written to the database

#### Scenario: No SIP messages available — no partial write

- GIVEN the ElevenLabs SIP messages API returns an empty list
- WHEN the probe or sweep processes the response
- THEN no observability columns are updated
- AND `reconciled_at` remains NULL

---

### Requirement: CallSession Schema — Nullable Observability Columns

The system MUST add five nullable columns to `CallSession` via a backward-compatible
Alembic migration:

| Column | Type | Default |
|---|---|---|
| `sip_call_id` | `VARCHAR` nullable | NULL |
| `sip_status_code` | `INTEGER` nullable | NULL |
| `sip_reason` | `VARCHAR` nullable | NULL |
| `reconciled_at` | `TIMESTAMP WITH TIME ZONE` nullable | NULL |
| `reconciliation_source` | `VARCHAR` nullable (`"probe"` \| `"sweep"`) | NULL |

No existing `CallSession` columns MAY be removed or made non-nullable by this migration.
The migration MUST be reversible via `alembic downgrade` using `DROP COLUMN` only.

#### Scenario: Migration applies without data loss

- GIVEN existing `CallSession` rows with no SIP fields
- WHEN the Alembic migration runs
- THEN all five new columns exist with NULL values for all pre-existing rows
- AND no existing rows are modified in any other way

#### Scenario: Downgrade removes columns safely

- GIVEN the migration has been applied
- WHEN `alembic downgrade` is run to the prior revision
- THEN the five columns are dropped
- AND no other columns or rows are affected

---

### Requirement: Post-Dial Background Probe

After `initiate_outbound_call()` resolves (whether successful or timed out), the
system MUST fire a background task (`asyncio.create_task`) that:

1. Waits a configurable delay (default 8 seconds).
2. Calls `list_recent_conversations` + `get_sip_messages` on the ElevenLabs API.
3. Matches by `agent_id` + `to_number` + closest `created_at` within a 60-second window.
4. On match: writes SIP observability fields and sets `reconciliation_source="probe"`.
5. On no match or any exception: logs the outcome and exits without error propagation.

The probe MUST be fully isolated: any unhandled exception MUST be caught at the task
boundary and logged; it MUST NOT affect the call trigger HTTP response status or latency.

The probe is idempotent: if `reconciled_at` is already set on the `CallSession`, the
probe MUST exit immediately without making any ElevenLabs API calls.

#### Scenario: Successful probe capture

- GIVEN a call was triggered and ElevenLabs has a matching recent conversation
- WHEN the probe fires 8 seconds after dial
- THEN `sip_call_id`, `sip_status_code`, `sip_reason`, and `reconciled_at` are written
- AND `reconciliation_source` is set to `"probe"`
- AND the call trigger response is not delayed by the probe's execution

#### Scenario: Probe exception — call trigger unaffected

- GIVEN the ElevenLabs API returns a 500 error during probe execution
- WHEN the probe task encounters the exception
- THEN the exception is caught and logged at WARNING level or above
- AND the call trigger endpoint returns its response with normal latency
- AND `reconciled_at` remains NULL (sweep will retry)

#### Scenario: Probe skipped — already reconciled

- GIVEN `CallSession.reconciled_at` is not NULL when the probe fires
- WHEN the probe checks the idempotency guard
- THEN no ElevenLabs API calls are made
- AND the session is left unchanged

---

### Requirement: Background Reconciliation Sweep

The existing stale-session sweep MUST be extended to reconcile sessions where
`reconciled_at IS NULL`. For each candidate session the sweep MUST:

1. Call `list_recent_conversations` filtered by `agent_id` and the session's time window.
2. Match the conversation by `to_number` + closest `created_at` timestamp.
3. On unambiguous match: fetch SIP messages, write observability fields, set
   `reconciliation_source="sweep"` and `reconciled_at` to current UTC time.
4. On ambiguous match (multiple conversations for same number within window): log the
   ambiguity at WARNING level, skip the write, and leave `reconciled_at` NULL for the
   next sweep cycle.
5. On no match: log at INFO level; leave `reconciled_at` NULL.

Candidate sessions MUST be limited to those with `telephony_status IN ('failed',
'stale_in_call')` OR `session_end_received=True` with no existing SIP evidence.

The sweep MUST cap ElevenLabs API calls at a configurable maximum per cycle (default: 10
sessions). Sessions beyond the cap are deferred to the next sweep cycle.

The sweep MUST NOT alter `telephony_status` based on reconciliation evidence alone.
Reconciliation is read-only for call state.

#### Scenario: Unambiguous sweep match — evidence written

- GIVEN a `CallSession` with `telephony_status='failed'` and `reconciled_at IS NULL`
- AND ElevenLabs returns exactly one matching conversation for that agent + number + window
- WHEN the sweep processes the session
- THEN SIP observability fields are written
- AND `reconciliation_source` is set to `"sweep"`
- AND `telephony_status` is NOT changed

#### Scenario: Ambiguous sweep match — safe skip

- GIVEN two calls to the same number were made within the time window
- WHEN the sweep tries to match conversations
- THEN both conversation candidates are logged at WARNING level
- AND no SIP fields are written for that session
- AND `reconciled_at` remains NULL

#### Scenario: Sweep rate-limit cap respected

- GIVEN 15 unreconciled sessions are eligible
- WHEN the sweep runs with a cap of 10
- THEN exactly 10 sessions are processed (the oldest eligible first)
- AND the remaining 5 sessions are left for the next sweep cycle

---

### Requirement: Ambiguous ReadTimeout / Unknown State Handling

When a `CallSession` has `telephony_error LIKE '%ambiguous_timeout%'` and
`reconciled_at IS NULL`, the sweep MUST treat it as a reconciliation candidate and
attempt to discover provider evidence.

The system MUST NOT dispatch a new outbound call as a result of reconciliation.
If no provider evidence is found after sweep attempts, the session MUST remain
in its current terminal state (`failed`) and be visible to operators via the admin API
with the original `telephony_error` intact.

#### Scenario: Ambiguous timeout — provider evidence found by sweep

- GIVEN a `CallSession` with `telephony_error='ambiguous_timeout (...)'`
- AND ElevenLabs has a matching conversation with SIP 487 status
- WHEN the sweep processes the session
- THEN `sip_status_code=487`, `sip_reason`, and `reconciled_at` are written
- AND `telephony_error` retains its original value (not overwritten)
- AND no new call is dispatched

#### Scenario: Ambiguous timeout — no provider evidence found

- GIVEN a `CallSession` with `telephony_error='ambiguous_timeout (...)'`
- AND ElevenLabs returns no matching conversations for that agent + number + window
- WHEN the sweep processes the session
- THEN no SIP fields are written
- AND `telephony_status` and `telephony_error` remain unchanged
- AND the session remains visible to operators with its existing error text

---

### Requirement: ElevenLabs API Client Methods

The system MUST implement four new async methods on `ElevenLabsService`:

| Method | ElevenLabs Endpoint | Purpose |
|---|---|---|
| `list_recent_conversations(agent_id, time_window_seconds)` | `GET /conversational_ai/conversations` | Find conversations matching a time window |
| `get_conversation_detail(conversation_id)` | `GET /conversations/{id}` | Full conversation metadata |
| `get_sip_messages(conversation_id)` | `GET /conversations/{id}/sip_messages` | SIP message sequence for a conversation |
| `get_sip_messages_by_phone(phone_number_id)` | `GET /phone_numbers/{id}/sip_messages` | Fallback SIP lookup by phone ID |

All four methods MUST use the existing `ELEVENLABS_API_KEY` credential. No new secrets
or credentials are required.

On HTTP 429 from any of these endpoints, the method MUST apply exponential backoff with
at least one retry before propagating the error to the caller.

On any other non-2xx response, the method MUST raise a typed exception (not return None
silently) so callers can log and handle the failure explicitly.

#### Scenario: Rate-limit — exponential backoff applied

- GIVEN the ElevenLabs API returns HTTP 429
- WHEN `list_recent_conversations` is called
- THEN the method waits and retries at least once with exponential backoff
- AND only raises after exhausting retries

#### Scenario: Non-429 error — typed exception raised

- GIVEN the ElevenLabs API returns HTTP 404
- WHEN `get_sip_messages` is called
- THEN a typed exception is raised
- AND the caller (probe or sweep) catches it and logs it

---

### Requirement: Test Coverage — No Live SIP

All new code paths that call ElevenLabs SIP or conversation APIs MUST be covered by
unit or integration tests using mocked HTTP responses. No test in the suite MAY make a
live HTTP call to ElevenLabs or Telnyx.

Tests MUST cover:

- Probe fires and writes correct fields on successful ElevenLabs match
- Probe catches exception and does not propagate it
- Probe exits early when `reconciled_at` is already set
- Sweep writes fields on unambiguous match
- Sweep skips and logs on ambiguous match
- Sweep respects the per-cycle API call cap
- Migration applies and downgrades cleanly (SQLite in-memory acceptable)
- Structured-field extraction excludes `Proxy-Authorization` and raw bodies

#### Scenario: Mocked ElevenLabs probe test

- GIVEN a mocked `list_recent_conversations` returning a matching conversation
- AND a mocked `get_sip_messages` returning a `Call-ID`, `404`, and reason
- WHEN the probe runs against the mocked responses
- THEN `CallSession.sip_call_id`, `sip_status_code`, and `sip_reason` are set correctly
- AND no real HTTP call is made
