# Telephony Provider Decision Specification

## Purpose

Defines what must be true for Qora to select and validate an outbound telephony path for
Phase C. C1 produces a documented, evidence-backed decision — not a dialer implementation.
The ElevenLabs Conversational AI pipeline and Qora's Custom LLM webhook contract remain
unchanged until an explicit later phase changes them.

---

## Requirements

### Requirement: Pipeline Preservation

The ElevenLabs Conversational AI pipeline (STT → Custom LLM webhook → TTS) and Qora's
existing browser demo, scheduler, and local workflows MUST remain fully operational
throughout and after C1. No production code, DB migration, or persisted configuration MAY
be changed by this phase.

#### Scenario: Existing demo unaffected

- GIVEN the C1 spec and any C1 artifacts exist in the repository
- WHEN the ElevenLabs browser demo or scheduler is exercised
- THEN all current Qora functionality operates identically to pre-C1 state
- AND no test in `cd backend && python3 -m pytest tests/ -q` regresses

#### Scenario: Webhook contract unchanged

- GIVEN a Custom LLM webhook request arrives from ElevenLabs
- WHEN C1 artifacts are present
- THEN the request/response contract is identical to the pre-C1 contract

---

### Requirement: Provider Decision Matrix

C1 MUST produce a documented decision matrix comparing at minimum Telnyx (primary) and
Twilio (comparator) as ElevenLabs SIP trunk carriers. Vapi, Retell, and custom pipeline
paths MAY be noted as deferred alternatives. The decision MUST be driven by measured
latency data, not assumptions.

| Criterion | Weight | Mandatory to measure |
|-----------|--------|----------------------|
| First-word latency (Argentina, p50/p95) | 35% | Yes |
| Voice quality preservation | 25% | Subjective pass/fail |
| Cost per minute (Argentina outbound) | 20% | Yes (public pricing) |
| Integration complexity | 10% | Document |
| Operational risk | 10% | Document |

#### Scenario: Matrix populated before decision

- GIVEN the measurement protocol has been executed
- WHEN the decision record is written
- THEN the matrix contains measured values (not "TBD") for every mandatory criterion
- AND a single provider+path is selected with written rationale

#### Scenario: Telnyx is the primary path evaluated first

- GIVEN the user has an existing Telnyx account
- WHEN C1 validation begins
- THEN Telnyx is configured and tested before Twilio is evaluated
- AND Twilio is used as a latency comparator, not a default

---

### Requirement: Telnyx Validation Prerequisites

Before any Telnyx test call is made, all of the following prerequisites MUST be documented
as satisfied (by the user, not stored as secrets in the repository):

1. Telnyx account active with available credit
2. Telnyx API key obtained
3. SIP trunk connection created (digest auth or IP ACL)
4. Outbound voice profile configured
5. Caller ID / phone number verified or purchased
6. Destination Argentina test phone number available

The spec MUST record which prerequisites are met and which remain pending as a checklist.
No Telnyx credentials or phone numbers MAY be committed to the repository.

#### Scenario: Prerequisites checklist complete

- GIVEN the user confirms all six prerequisites are satisfied
- WHEN the first Telnyx test call is initiated
- THEN the call can be placed without credential or config errors
- AND no secret values appear in any committed file

#### Scenario: Prerequisites incomplete — blocked

- GIVEN one or more prerequisites are not yet satisfied
- WHEN C1 attempts to proceed to measurement
- THEN the phase is marked BLOCKED with the missing items listed
- AND no test call is attempted until prerequisites are resolved

---

### Requirement: Objective Measurement Protocol

C1 MUST define and execute an objective measurement protocol. Latency numbers MUST NOT be
invented or assumed; all values in the decision record MUST come from live test calls.

Metrics to record per provider per destination:

| Metric | Definition |
|--------|-----------|
| Dial-to-ring | INVITE sent to first ring tone audible at destination |
| Answer-to-first-agent-audio | Call answered to first TTS syllable at destination |
| Turn-taking delay | End of user speech to start of agent audio (p50, p95) |
| Jitter | RTP packet delivery variance (ms) |
| Packet loss | % RTP packets lost |
| Call success rate | Successful connects / total attempts |
| Cost per minute | Billed rate for Argentina outbound (provider rate card) |

Minimum sample size: 20 test calls per provider, targeting an Argentina mobile number.
A US number SHOULD be included as a geographic control.

#### Scenario: Measurements recorded and comparable

- GIVEN 20+ test calls complete for at least Telnyx and Twilio
- WHEN results are compiled
- THEN p50 and p95 are reported for turn-taking delay and jitter
- AND cost/min is recorded from the provider rate card
- AND results are presented in a side-by-side table

#### Scenario: Latency fabrication rejected

- GIVEN only hypothesis-level latency data is available
- WHEN the decision record is being written
- THEN all unverified estimates are labelled "hypothesis — requires-live-test"
- AND no estimate is stated as a confirmed fact

---

### Requirement: Region and Edge Placement Consideration

C1 MUST record the geographic region of the Qora webhook/call-logic runtime and document
its expected round-trip latency to each tested provider's nearest SIP edge. A runtime
deployed in a region distant from the SIP edge (e.g. AWS us-east-1 for LatAm calls) MUST
be flagged as a latency risk.

#### Scenario: Region recorded in decision document

- GIVEN the decision record is finalized
- WHEN it is reviewed
- THEN the Qora server region is stated explicitly (e.g. "ngrok tunnel, us-east-1")
- AND the estimated network RTT to the provider SIP edge is noted
- AND any region mismatch adding ≥ 100 ms is flagged as a risk item

#### Scenario: Region mismatch detected during measurement

- GIVEN measured answer-to-first-agent-audio exceeds 1500ms p50
- WHEN latency sources are investigated
- THEN server geography is checked as a contributing factor before blaming the provider
- AND a co-located or edge deployment SHOULD be tested before discarding the provider

---

### Requirement: CallSession Telephony Metadata

`CallSession` MUST store provider-level telephony metadata introduced in C2 as five new
columns: `provider_call_id` (string), `telephony_provider` (string), `telephony_status`
(enum string), `telephony_error` (string), and `provider_metadata` (JSON).
All columns MUST be nullable to preserve compatibility with existing inbound sessions.

#### Scenario: New columns present after migration

- GIVEN the C2 Alembic migration has been applied
- WHEN a `CallSession` row is read from the database
- THEN all five telephony columns are accessible
- AND existing rows that predate the migration have `NULL` values for all five columns

#### Scenario: Inbound sessions unaffected

- GIVEN an inbound call session created before C2 migration
- WHEN the session is read or updated by existing code paths
- THEN no error is raised due to the new columns
- AND existing `elevenlabs_conversation_id` and `outcome` columns are unchanged

---

### Requirement: Agent Phone Number ID

The `Agent` model MUST expose an `elevenlabs_phone_number_id` column (nullable string)
that stores the ElevenLabs phone number resource ID required by the SIP trunk
outbound-call API. The value MUST be configurable via the Agent PATCH API endpoint
and SHOULD be seeded from the `ELEVENLABS_PHONE_NUMBER_ID` environment variable during
initial setup.

#### Scenario: Column present after migration

- GIVEN the C2 Alembic migration has been applied
- WHEN the `agents` table is inspected
- THEN `elevenlabs_phone_number_id` column exists as a nullable string
- AND existing agent rows have `NULL` for this column

#### Scenario: Exposed in Agent API schema

- GIVEN an agent has `elevenlabs_phone_number_id` set in the database
- WHEN `GET /clients/{client_id}/agents/{agent_id}` is called
- THEN the response includes `elevenlabs_phone_number_id`

---

### Requirement: Rollback Guarantee

C1's rollback guarantee is extended to include C2 artifacts. The system MUST remain
fully reversible by toggling a single environment variable and optionally running
`alembic downgrade -1`. All new telephony code MUST be absent from the active code
path when `ENABLE_OUTBOUND_CALLS=false`.
(Previously: rollback was defined as "no production code or DB migration in C1"; C2
extends this to include the new columns and service methods behind the feature flag.)

#### Scenario: Flag removal stops all dialing immediately

- GIVEN `ENABLE_OUTBOUND_CALLS` is removed or set to `false`
- WHEN any trigger path is exercised (manual or future scheduler)
- THEN no ElevenLabs outbound API call is made
- AND no new `CallSession` with telephony metadata is created

#### Scenario: Migration rollback removes new columns cleanly

- GIVEN `alembic downgrade -1` is executed against the C2 migration
- WHEN the database schema is inspected
- THEN `CallSession` no longer has the five telephony columns
- AND `Agent` no longer has `elevenlabs_phone_number_id`
- AND all pre-C2 data remains intact

#### Scenario: Existing demo and webhook unaffected when flag is off

- GIVEN `ENABLE_OUTBOUND_CALLS=false`
- WHEN the ElevenLabs browser demo or Custom LLM webhook is exercised
- THEN all existing Qora functionality operates identically to pre-C2 state
- AND no test in `cd backend && python3 -m pytest tests/ -q` regresses

#### Scenario: C1 artifacts removed — system intact

- GIVEN all C1 spec/decision files are deleted from the repository
- WHEN the application is started
- THEN it behaves identically to pre-C1 state
- AND no error, missing migration, or missing config is introduced

#### Scenario: Future C2 telephony path isolated

- GIVEN C2 is ready to implement the chosen path
- WHEN implementation begins
- THEN the telephony dialer code is gated behind a feature flag or
  an environment variable absent from the production `.env`
- AND the absence of the flag/variable keeps the system in no-real-dialing state
