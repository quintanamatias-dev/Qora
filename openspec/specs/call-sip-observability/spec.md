# Call SIP Observability Specification

## Purpose

Defines asynchronous, diagnostic-only SIP observability for existing `CallSession`
fields. It covers the post-dial probe, bounded reconciliation sweep, safe SIP
normalization, ambiguity handling, rate-limit safety, and secret exclusion. It adds
no Telnyx webhook, database column, migration, or pagination-fetching behavior.

---

## Requirements

### Requirement: Safe SIP Normalization and Evidence Selection

The system MUST retain only these safe, normalized fields on `CallSession`:

| Field | Stored As |
|---|---|
| Provider SIP Call-ID when supplied as the structured `call_id` field | `sip_call_id` |
| Final SIP status code | `sip_status_code` |
| Final SIP reason phrase | `sip_reason` |
| Reconciliation write time | `reconciled_at` |
| Reconciliation path (`"probe"`, `"sweep"`, or parked `"unreconcilable"`) | `reconciliation_source` |

An upstream `raw_message` MAY be inspected transiently only when it is a string no
longer than 4096 characters. The normalizer considers only a valid SIP start line
and one valid `CSeq` header in the header section, and derives only method, status
code, safe reason phrase, CSeq, and a validated timestamp. No raw bodies,
authentication material, raw header fields, address fields, or phone fields are
retained, serialized, logged, or persisted. The bounded, validated protocol
identifiers and reason fields are allowed fields, not a general semantic-redaction
feature for arbitrary sensitive substrings they might contain. Oversized, malformed,
conflicting, or ambiguous raw input produces only unknown safe fields.

Final evidence MUST be selected without relying on provider response order. The
selector requires exactly one Call-ID across the message set, complete CSeq evidence
for every `INVITE`, and a single identical final (2xx–6xx) response for the greatest
`INVITE` CSeq. If those conditions are not met, the SIP call ID, status, and reason
are unknown.

#### Scenario: Raw SIP is normalized without retention

- GIVEN an upstream SIP message contains raw SIP with body, authentication, header, address, or phone data
- WHEN the probe or sweep processes it
- THEN only the bounded normalization fields may be used transiently
- AND no raw body, authentication material, raw header field, address field, or phone field is retained or written to the database

#### Scenario: Ambiguous final evidence is unknown

- GIVEN SIP messages lack a unique Call-ID, complete INVITE CSeqs, or one final response for the latest INVITE CSeq
- WHEN the probe or sweep selects evidence
- THEN `sip_call_id`, `sip_status_code`, and `sip_reason` are unknown
- AND no provider message order is used as a tie-breaker

#### Scenario: No SIP messages available — no reconciliation write

- GIVEN the ElevenLabs SIP messages API returns an empty list
- WHEN the probe or sweep processes the response
- THEN no observability columns are updated
- AND `reconciled_at` remains NULL

---

### Requirement: Existing CallSession Observability Fields

The implementation uses existing `CallSession` observability fields: nullable
`sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, and
`reconciliation_source`, plus `reconciliation_attempts`. Existing/inbound rows may
remain NULL where those fields are nullable. This observability repair MUST NOT add a
Telnyx webhook, database columns, or a schema migration.

---

### Requirement: Post-Dial Background Probe

After an accepted dial result or an ambiguous dial timeout, the system MUST fire an
isolated background task that waits a configurable delay (default 8 seconds) and
attempts to capture SIP diagnostics. The task MUST catch unhandled exceptions at its
boundary so it does not change call-trigger HTTP latency or outcome.

The probe MUST exit before API calls when `reconciled_at` is already set. It MUST use
the persisted `elevenlabs_conversation_id` as the exact, preferred lookup key when
present. Only when that ID is absent may it list recent agent conversations and select
exactly one candidate within the configured time window; zero or multiple candidates
are unknown and produce no write.

The probe MUST require a non-empty, complete SIP response before writing evidence. A
response with `has_more=True` or a non-empty `next_cursor` is incomplete: it is
unknown, no observability fields or reconciliation stamp are written, and no pagination request
is made by this implementation.

When the selected evidence shows a SIP 4xx/5xx routing failure and the conversation
also indicates a failed, ended, or done non-successful call, the transition to
`failed` with `outcome_reason="sip_routing_error"` and the probe evidence write MUST
be one atomic update. That update MUST be admitted only when the persisted
`telephony_status` is `dialing` or `ringing`; a concurrent connected or terminal state
is preserved without a probe write. Non-routing evidence is diagnostic and does not
change call state.

#### Scenario: Exact conversation ID is preferred

- GIVEN a session has `elevenlabs_conversation_id`
- WHEN the probe runs
- THEN it uses that ID directly rather than a time-based conversation list match

#### Scenario: Incomplete SIP page is not reconciled

- GIVEN the SIP response reports `has_more=True` or a `next_cursor`
- WHEN the probe runs
- THEN the evidence is unknown
- AND `reconciled_at` remains NULL
- AND the probe does not fetch another page

#### Scenario: Probe routing failure preserves concurrent state

- GIVEN a SIP routing failure is detected after the probe began
- AND the persisted session is no longer `dialing` or `ringing`
- WHEN the atomic probe update runs
- THEN no failure transition or probe reconciliation write occurs
- AND the persisted state is preserved

---

### Requirement: Bounded Background Reconciliation Sweep

The reconciliation sweep provides bounded diagnostic backfill only. It considers
unreconciled `failed` and `stale_in_call` sessions, plus `completed` sessions only
when they already have an exact `elevenlabs_conversation_id`; candidates are ordered
oldest first and limited by `reconciliation_sweep_cap` (default 10). Candidates at or
above `reconciliation_max_attempts` are excluded.

For each candidate, the sweep MUST prefer the exact stored conversation ID. It MAY
list recent conversations only when that ID is absent, and then MUST require exactly
one candidate within the configured time window. Empty or ambiguous fallback results
remain unreconciled. The sweep MUST not guess from phone-number or time proximity
alone when multiple matches exist.

The sweep MUST require a complete, non-empty SIP response. `has_more=True` or a
non-empty `next_cursor` means unknown evidence: it MUST not write fields or a reconciliation
stamp and MUST not fetch another page. A complete non-empty response may be stamped
as `"sweep"` even when its safe evidence selector returns unknown fields.

This backfill MUST NOT mutate `telephony_status`, terminal state, session-end evidence,
or outcome fields. On a per-session exception it increments
`reconciliation_attempts`; after the configured maximum it parks only the diagnostic
reconciliation with `reconciled_at` and `reconciliation_source="unreconcilable"`.

#### Scenario: Completed session receives diagnostic-only backfill

- GIVEN a completed session has an exact stored `elevenlabs_conversation_id` and no reconciliation stamp
- WHEN the bounded sweep finds complete SIP evidence
- THEN it may write observability diagnostics with `reconciliation_source="sweep"`
- AND its terminal status and outcome fields are unchanged

#### Scenario: Ambiguous fallback match is skipped

- GIVEN a candidate has no stored conversation ID and more than one recent conversation is within the match window
- WHEN the sweep runs
- THEN no SIP fields or reconciliation stamp are written
- AND no candidate is selected by provider response order

---

### Requirement: Ambiguous Dial Outcome Handling

A `failed` session with ambiguous dial-timeout evidence and no reconciliation stamp is
eligible for the bounded sweep under the ordinary failed-session rule. Reconciliation
MUST NOT dispatch a new outbound call. Whether evidence is found, unavailable, or
parked after the retry limit, it MUST NOT alter the session's telephony state or
existing error/outcome fields.

---

### Requirement: ElevenLabs API Client Methods

`ElevenLabsService` provides these async API methods using the existing
`ELEVENLABS_API_KEY` credential:

| Method | ElevenLabs Endpoint | Purpose |
|---|---|---|
| `list_recent_conversations(agent_id, time_window_seconds)` | `GET /convai/conversations` | List candidate conversations |
| `get_conversation_detail(conversation_id)` | `GET /convai/conversations/{id}` | Resolve stored conversation metadata for the probe |
| `get_sip_messages(conversation_id)` | `GET /convai/conversations/{id}/sip-messages` | Read one SIP message page for a conversation |
| `get_sip_messages_by_phone(phone_number_id)` | `GET /convai/phone-numbers/{id}/sip-messages` | Available phone-resource SIP lookup method |

On HTTP 429, these methods MUST apply existing exponential backoff with at least one
retry before propagating failure. Other non-2xx responses MUST raise the typed
`ElevenLabsAPIError`; callers catch and log them. The SIP methods do not currently
send a cursor or fetch additional pages.

---

### Requirement: Test Coverage — No Live SIP

SIP and conversation API paths MUST be covered with mocked HTTP responses; no test
may make a live HTTP call to ElevenLabs or Telnyx. Coverage MUST include safe bounded
raw-SIP normalization and exclusion, latest-INVITE-CSeq evidence selection, exact-ID
preference and ambiguity-safe fallback, incomplete-page no-stamp behavior, bounded
completed-session diagnostic backfill, and the probe's persisted-state atomic failure
guard.
