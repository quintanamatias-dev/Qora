# Spec: Airtable CRM Integration

> New capabilities — no prior spec to delta against.

---

## crm-field-mapping Specification

### Purpose

Per-client declarative mapping from Qora lead fields to external CRM field names, loaded from a versioned config file. Enables any client to define their own CRM schema without touching Qora core.

### Requirements

| # | Requirement | Strength |
|---|-------------|----------|
| FM-1 | System MUST load `crm.yaml` from `backend/clients/{client_id}/crm.yaml` at startup or first sync | MUST |
| FM-2 | System MUST validate all required fields (`adapter`, `base_id`, `table_id`, `match_field`, `credentials_key`) at load time | MUST |
| FM-3 | System MUST resolve credentials from env vars via `credentials_key`; the resolved secret MUST NOT be stored in any config object or log | MUST |
| FM-4 | System MUST silently skip CRM sync for clients that have no `crm.yaml` | MUST |
| FM-5 | System MUST coerce or reject field values that do not match declared CRM field types at mapping time | MUST |
| FM-6 | System SHOULD support arbitrary key-value `field_map` entries so new CRM fields require only config changes | SHOULD |

#### Scenario: Valid config loaded

- GIVEN a client has a well-formed `crm.yaml` with all required fields
- WHEN the sync service initialises for that client
- THEN the field mapping is validated without error
- AND credentials are resolved from the env var named by `credentials_key`

#### Scenario: Missing crm.yaml

- GIVEN a client directory has no `crm.yaml`
- WHEN a post-call sync is triggered for that client
- THEN sync is silently skipped with no error or warning logged

#### Scenario: Invalid config detected at load

- GIVEN `crm.yaml` is present but missing `match_field`
- WHEN the sync service attempts to load the config
- THEN a `ConfigValidationError` is raised and logged
- AND no sync is attempted

#### Scenario: Credential key missing from env

- GIVEN `crm.yaml` references `credentials_key: QUINTANA_AIRTABLE_API_KEY`
- WHEN that env var is not set
- THEN sync fails with a `CredentialResolutionError` logged at ERROR level
- AND the call analysis result is unaffected

---

## crm-sync Specification

### Purpose

Post-call async push of lead data to an external CRM via the `CRMPort` interface, triggered after the summarizer savepoint commits. Failure is fully isolated from call analysis.

### Requirements

| # | Requirement | Strength |
|---|-------------|----------|
| CS-1 | System MUST trigger CRM sync only after the summarizer savepoint commits successfully | MUST |
| CS-2 | CRM sync MUST run asynchronously (fire-and-forget); it MUST NOT block or delay the summarizer response | MUST |
| CS-3 | System MUST upsert the CRM record — match by `match_field` (default: phone normalised to E.164); create if not found | MUST |
| CS-4 | System MUST retry on transient failure with exponential backoff + jitter, up to 3 attempts | MUST |
| CS-5 | After 3 failed attempts, system MUST log a structured error and stop; it MUST NOT raise the exception to the caller | MUST |
| CS-6 | Upsert operation MUST be idempotent: calling it twice with the same lead data MUST NOT create duplicate records | MUST |
| CS-7 | System MUST NOT perform any live Airtable reads during an active call | MUST NOT |
| CS-8 | System MUST NOT sync in the reverse direction (Airtable → Qora) | MUST NOT |
| CS-9 | Adding a new CRM adapter MUST require zero changes outside `app/integrations/adapters/` | MUST |

#### Scenario: Successful post-call sync

- GIVEN a call ends and the summarizer savepoint commits
- WHEN `_schedule_crm_sync(client_id, lead_id)` is invoked
- THEN the lead fields are mapped via `crm.yaml`
- AND an upsert is performed against the configured Airtable table
- AND the record appears in Airtable within 30 seconds

#### Scenario: Record already exists (idempotent upsert)

- GIVEN the lead's phone already matches an existing Airtable record
- WHEN the upsert is executed
- THEN the existing record is updated, not duplicated

#### Scenario: Record not found — create path

- GIVEN no Airtable record matches the lead's normalised phone
- WHEN the upsert is executed
- THEN a new Airtable record is created with all mapped fields

#### Scenario: Transient 429 — retry with backoff

- GIVEN Airtable returns HTTP 429 on the first attempt
- WHEN the adapter retries with exponential backoff + jitter
- THEN the second or third attempt succeeds
- AND the call analysis result is fully unaffected

#### Scenario: All retries exhausted

- GIVEN Airtable returns errors on all 3 attempts
- WHEN the retry budget is exhausted
- THEN a structured error is logged at ERROR level with `client_id`, `lead_id`, and failure reason
- AND no exception propagates to the summarizer
- AND the summarizer result remains persisted in SQLite

#### Scenario: Summarizer savepoint fails

- GIVEN the summarizer savepoint raises an exception before committing
- WHEN the error is caught
- THEN `_schedule_crm_sync` is NOT called
- AND no CRM sync is attempted

#### Scenario: Client without crm.yaml (no side effects)

- GIVEN a client has no `crm.yaml`
- WHEN a call completes for that client
- THEN no CRM sync is attempted
- AND no error, warning, or performance degradation occurs

#### Scenario: Quintana sandbox deployment

- GIVEN `backend/clients/quintana-seguros/crm.yaml` exists with valid config
- WHEN a Quintana call completes
- THEN the sync uses only the field mapping and credentials defined in that config
- AND no Quintana-specific logic is hardcoded in `app/integrations/`

---

## Non-Goals (explicit)

| Non-Goal | Reason |
|----------|--------|
| Live Airtable reads during calls | Latency risk; call path must stay synchronous |
| Bidirectional sync (Airtable → Qora) | SQLite is authoritative; reverse flow deferred |
| Admin UI for CRM config | Config-file-driven; UI deferred |
| HubSpot / Salesforce adapters | Port accommodates them; implementation deferred |
| Multi-CRM per client | Single adapter per client for now |
