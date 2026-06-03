# Delta Specs: session-id-and-crm-match

---

## Domain 1: Call Session Lifecycle

### Delta for call-session-lifecycle

---

## ADDED Requirements

### Requirement: Backend-Only Conversation ID Resolution

The system MUST resolve `elevenlabs_conversation_id` on a `CallSession` entirely server-side, with no dependency on frontend code or frontend-provided conversation IDs.

The system MUST backfill `elevenlabs_conversation_id` from the `session_store` at custom-LLM webhook time when the ElevenLabs request body does not include `conversation_id`.

The system SHALL NOT require frontend cooperation to close a session or trigger post-call analysis.

#### Scenario: Webhook receives conversation_id in body

- GIVEN the custom-LLM webhook receives a request with a valid `conversation_id` in `elevenlabs_extra_body`
- WHEN the webhook creates or updates the `CallSession`
- THEN `elevenlabs_conversation_id` is stored non-NULL on the DB record immediately

#### Scenario: Webhook receives no conversation_id — backfill from session_store

- GIVEN the initiation webhook previously created a `session_store` entry at `(client_id, real_el_conv_id)`
- AND the custom-LLM webhook receives a request with no `conversation_id` in the body
- WHEN the webhook resolves session context via `find_by_client_lead`
- THEN the real EL conversation_id from the initiation entry is copied to the new `CallSession.elevenlabs_conversation_id`
- AND the DB record is NOT stored with NULL in that column

#### Scenario: Webhook creates session with no prior initiation entry

- GIVEN no initiation webhook ran (signed-URL flow) and EL sends no `conversation_id`
- WHEN the custom-LLM webhook creates a `CallSession`
- THEN the session is created with `elevenlabs_conversation_id = NULL` (unavoidable)
- AND the 600-second reconciliation window MUST remain active as the fallback path

#### Scenario: /end endpoint updates conversation_id on existing session

- GIVEN a `CallSession` exists with `elevenlabs_conversation_id = NULL`
- AND `/end` is called with the real EL `conversation_id` in the path param
- WHEN `_reconcile_session` matches the session by `(client_id, lead_id, status=initiated, el_conv_id IS NULL)`
- THEN `CallSession.elevenlabs_conversation_id` is set to the real EL value
- AND the session is closed, analysis is triggered, and CRM sync fires

#### Scenario: Reconciliation matches orphaned session within window

- GIVEN a `CallSession` with `status=initiated` and NULL `elevenlabs_conversation_id`
- AND the session was created within the last 600 seconds
- WHEN `/end` is called with `client_id` and `lead_id` hints
- THEN reconciliation assigns the conversation_id, closes the session, and no orphan remains

#### Scenario: Multiple sessions for same lead — most recent matched

- GIVEN two `CallSession` rows with `status=initiated` for the same `(client_id, lead_id)`
- WHEN `/end` triggers reconciliation
- THEN the session with the highest `turn_count` (most recent active session) is matched
- AND the other session is left unchanged

#### Scenario: Race condition on concurrent webhooks

- GIVEN a rapid reconnect creates two custom-LLM webhook requests for the same lead within seconds
- WHEN both webhooks attempt to create or update `CallSession` entries
- THEN each creates a separate DB record (no upsert merge at webhook time)
- AND `cleanup_expired(ttl_seconds=300)` in the session_store prevents stale entries from matching reconciliation

---

## Domain 2: CRM External Lead ID

### Delta for crm-sync

---

## ADDED Requirements

### Requirement: Lead Model Stores Numeric External Lead ID

The `Lead` model MUST include an `external_lead_id` column of type `Integer`, nullable.

The column MUST store the Meta/Facebook numeric lead ID — distinct from `external_crm_id` (Airtable record ID string).

An auto-migration MUST add the column via `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER` at application startup when absent.

#### Scenario: Column present after migration

- GIVEN the application starts against a DB without the `external_lead_id` column
- WHEN the startup auto-migration runs
- THEN `external_lead_id INTEGER` is added to the `leads` table
- AND existing rows have `external_lead_id = NULL`

---

### Requirement: Airtable Import Populates external_lead_id

The CRM import service MUST populate `external_lead_id` from the Airtable `lead_id` field during both create and update operations.

The `crm.yaml` field_mappings MUST include a mapping of `source: external_lead_id` → `target: "lead_id"` with `type: integer`.

#### Scenario: Import creates lead with external_lead_id

- GIVEN an Airtable record with a numeric `lead_id` field (e.g. `123456`)
- WHEN the CRM import runs
- THEN a `Lead` is created with `external_lead_id = 123456`
- AND the Airtable `recXXX` record ID is stored in `external_crm_id` (unchanged)

#### Scenario: Import updates existing lead with external_lead_id

- GIVEN a `Lead` already exists matched by phone
- AND the Airtable record has a numeric `lead_id`
- WHEN the CRM import runs
- THEN `external_lead_id` is updated on the existing `Lead` record

#### Scenario: Import skips external_lead_id when Airtable field is absent

- GIVEN an Airtable record with no `lead_id` field (manually added lead)
- WHEN the CRM import runs
- THEN the `Lead` is created or updated with `external_lead_id = NULL`
- AND no error is raised

---

### Requirement: CRM Sync Uses external_lead_id as Primary Match Field

The CRM sync service MUST include `external_lead_id` in the `_lead_to_dict()` output mapped to the `lead_id` Airtable column.

The `crm.yaml` `match_field` for `quintana-seguros` MUST be `"lead_id"` when `external_lead_id` is available.

#### Scenario: Sync pushes lead with external_lead_id

- GIVEN a `Lead` with `external_lead_id = 123456`
- WHEN the CRM sync runs post-call analysis
- THEN the Airtable upsert uses `lead_id = 123456` as the match key
- AND no duplicate Airtable record is created on repeated syncs

#### Scenario: Lead without external_lead_id falls back to email match

- GIVEN a `Lead` with `external_lead_id = NULL`
- WHEN the CRM sync runs
- THEN the Airtable upsert uses `external_crm_id` (Airtable `recXXX`) for lookup
- AND the sync completes without error

#### Scenario: Duplicate external_lead_ids detected

- GIVEN two `Lead` rows share the same `external_lead_id`
- WHEN the CRM sync pushes either lead
- THEN a warning is logged identifying the conflict
- AND the sync proceeds with the first matched record (no silent data loss)

#### Scenario: Null external_lead_id excluded from push dict

- GIVEN `_lead_to_dict()` is called for a `Lead` with `external_lead_id = NULL`
- WHEN the field is mapped
- THEN `external_lead_id` key is omitted from the output dict (or sent as `None`)
- AND the FieldMapper does not pass a null value as the Airtable match key

---

## Constraints

- **Problem 1**: All conversation_id resolution MUST be backend-only. No frontend changes may be required for correct session lifecycle behavior.
- **Problem 2**: `external_lead_id` MUST be Integer type. Meta lead IDs are numeric. String or UUID types are not acceptable.
