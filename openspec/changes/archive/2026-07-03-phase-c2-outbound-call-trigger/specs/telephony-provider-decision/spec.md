# Delta for Telephony Provider Decision

## ADDED Requirements

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

## MODIFIED Requirements

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
