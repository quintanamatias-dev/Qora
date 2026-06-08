# Spec: dynamic-lead-fields

Change: `dynamic-lead-fields`
Phase: spec
Date: 2026-06-08

> New capabilities: `lead-custom-fields`, `quote-ready-config`
> Modified capabilities: `crm-sync`, `prompt-rendering`, `capture-data-tool`

---

## 1. New Capability: `lead-custom-fields`

CRUD service for the `lead_custom_fields` table — type-enforced key-value storage for client-specific business data attached to leads.

### Data Model

#### Table: `lead_custom_fields`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PRIMARY KEY, autoincrement |
| `lead_id` | Integer | FK → `leads.id`, NOT NULL |
| `client_id` | String | NOT NULL |
| `field_key` | String | NOT NULL |
| `field_value` | Text | nullable |
| `field_type` | String | NOT NULL — enum: `string`, `integer`, `boolean`, `date`, `phone` |
| `created_at` | DateTime | NOT NULL, default UTC now |
| `updated_at` | DateTime | NOT NULL, auto-updated on write |

Index: UNIQUE on `(lead_id, client_id, field_key)` — one row per field per lead per client.

### Requirements

| # | Requirement | Strength |
|---|-------------|----------|
| CF-1 | System MUST enforce the unique constraint `(lead_id, client_id, field_key)` | MUST |
| CF-2 | `field_type` MUST be one of: `string`, `integer`, `boolean`, `date`, `phone` | MUST |
| CF-3 | System MUST coerce input to the declared `field_type` at write time | MUST |
| CF-4 | If coercion fails, system MUST reject the write and return a typed error | MUST |
| CF-5 | Write operation MUST be upsert: insert on new key, update on existing key | MUST |
| CF-6 | `field_value` MUST be stored as TEXT regardless of `field_type`; coercion is the caller's responsibility at read time | MUST |
| CF-7 | System MUST support batch-read: fetch ALL custom fields for a lead in a single query | MUST |
| CF-8 | System MUST support batch-read for multiple leads: `lead_id IN (...)` pattern | MUST |
| CF-9 | System MUST NOT allow a `client_id` to read or write another client's custom fields | MUST |
| CF-10 | Startup migration MUST create the table idempotently (`CREATE TABLE IF NOT EXISTS`) | MUST |
| CF-11 | Startup migration MUST copy existing lead column data (`car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona`) to `lead_custom_fields` rows exactly once, guarded by a migration marker | MUST |

#### Scenario: Write new custom field

- GIVEN lead `L1` belongs to client `quintana-seguros`
- WHEN `upsert_custom_field(lead_id=L1, client_id="quintana-seguros", field_key="car_year", field_value="2021", field_type="integer")` is called
- THEN a row is inserted with `field_value="2021"`, `field_type="integer"`
- AND `updated_at` is set to now

#### Scenario: Upsert overwrites existing field

- GIVEN a row exists for `(L1, "quintana-seguros", "car_year")` with `field_value="2021"`
- WHEN the same key is written with `field_value="2023"`
- THEN the existing row is updated; no duplicate row is created
- AND `updated_at` is refreshed

#### Scenario: Type coercion failure at write

- GIVEN `field_type="integer"` and `field_value="not-a-number"`
- WHEN the write is attempted
- THEN the write is rejected with a `FieldTypeError`
- AND no row is inserted or updated

#### Scenario: Cross-client isolation

- GIVEN lead `L1` belongs to `client_a`
- WHEN `client_b` attempts to read custom fields for `L1`
- THEN no rows are returned (empty result, not an error)

#### Scenario: Startup migration — data copied once

- GIVEN an existing lead with `car_make="Toyota"` set as a column value
- WHEN the application starts and the migration has not previously run
- THEN a `lead_custom_fields` row is created for `field_key="car_make"`, `field_value="Toyota"`
- AND a migration marker is set to prevent re-running

#### Scenario: Startup migration — idempotent on re-start

- GIVEN the migration marker is already set
- WHEN the application starts again
- THEN no rows are re-inserted or duplicated

---

## 2. New Capability: `quote-ready-config`

Client-configurable "quote-ready" check driven by `crm.yaml`; replaces the hardcoded 5-field `is_quote_ready()` function.

### CRM Config Extension (`crm.yaml`)

```yaml
quote_ready_fields:           # required fields for "quoted" status
  - car_make
  - car_model
  - car_year
  - age
  - zona

field_definitions:            # describes each capturable custom field
  - field_key: car_make
    field_type: string
    label: "Car Make"
  - field_key: car_model
    field_type: string
    label: "Car Model"
  - field_key: car_year
    field_type: integer
    label: "Car Year"
  - field_key: current_insurance
    field_type: string
    label: "Current Insurance"
  - field_key: age
    field_type: integer
    label: "Age"
  - field_key: zona
    field_type: string
    label: "Zone"

api_key: "..."                # renamed from api_key_env; stores key directly for dev/test
```

### Requirements

| # | Requirement | Strength |
|---|-------------|----------|
| QR-1 | `is_quote_ready(lead, custom_fields, config)` MUST check that all keys in `config.quote_ready_fields` are present (non-null, non-empty) in `custom_fields` | MUST |
| QR-2 | If `quote_ready_fields` is absent from config or empty, `is_quote_ready` MUST return `False` (never quote) | MUST |
| QR-3 | `crm.yaml` MUST support `field_definitions` list with `field_key`, `field_type`, `label` | MUST |
| QR-4 | `crm.yaml` field `api_key_env` MUST be renamed to `api_key`; the resolver MUST read it as a literal value (not an env var lookup) for dev/test | MUST |
| QR-5 | A client with no `crm.yaml` MUST never reach "quoted" status | MUST |

#### Scenario: All quote-ready fields present

- GIVEN `quote_ready_fields: [car_make, car_model, car_year, age, zona]`
- AND all 5 keys exist as non-empty custom fields for lead `L1`
- WHEN `is_quote_ready` is evaluated
- THEN it returns `True`

#### Scenario: One required field missing

- GIVEN `zona` custom field is absent for lead `L1`
- WHEN `is_quote_ready` is evaluated
- THEN it returns `False`

#### Scenario: `quote_ready_fields` absent from config

- GIVEN a client config has no `quote_ready_fields` key
- WHEN `is_quote_ready` is evaluated
- THEN it returns `False` (safe degradation)

#### Scenario: New non-insurance client

- GIVEN client `acme` has no `crm.yaml`
- WHEN a call completes for an `acme` lead
- THEN `is_quote_ready` returns `False`; lead status never transitions to `quoted`

---

## 3. Modified Capability: `crm-sync`

### Current Behavior

`_lead_to_dict(lead)` reads `car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona` directly from Lead ORM attributes. `_update_lead_from_qora_data()` and `_create_lead_from_qora_data()` write those fields directly to Lead columns.

### MODIFIED Requirements

#### Requirement: CRM Export Reads Custom Fields

(Previously: `_lead_to_dict` read 6 fields from Lead ORM columns)

`_lead_to_dict(lead, custom_fields)` MUST accept a pre-loaded `custom_fields` dict and merge it into the export payload. The `FieldMapper` MAY map any `field_key` from `custom_fields` to a CRM column via `crm.yaml` `field_mappings`. Base Lead fields (`name`, `phone`, `email`, `status`) MUST continue to be read from the Lead ORM.

##### Scenario: Export includes custom fields

- GIVEN lead `L1` with custom fields `{car_make: "Toyota", car_year: "2021"}`
- WHEN `_lead_to_dict` is called
- THEN the returned dict includes `car_make` and `car_year`
- AND `FieldMapper` maps them to the configured CRM columns

##### Scenario: Export with no custom fields

- GIVEN lead `L1` has no rows in `lead_custom_fields`
- WHEN `_lead_to_dict` is called
- THEN the dict contains only base Lead fields
- AND no error is raised

#### Requirement: CRM Import Writes Custom Fields

(Previously: import wrote directly to Lead ORM columns for `car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona`)

`_update_lead_from_qora_data()` and `_create_lead_from_qora_data()` MUST classify each reverse-mapped field: if it is a base Lead field (`name`, `phone`, `email`, `status`) → write to Lead column; otherwise → upsert to `lead_custom_fields`.

##### Scenario: Import routes base vs custom fields

- GIVEN Airtable record with `name="Ana"`, `car_make="Ford"`, `age="35"` (reverse-mapped)
- WHEN `_update_lead_from_qora_data` processes the record
- THEN `lead.name` is set to `"Ana"`
- AND `lead_custom_fields` rows for `car_make` and `age` are upserted

---

## 4. Modified Capability: `prompt-rendering`

### Current Behavior

`_build_variables()` reads `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance` directly from Lead ORM attributes.

### MODIFIED Requirements

#### Requirement: `_build_variables` Merges Custom Fields

(Previously: `_build_variables` read 4 fields directly from Lead ORM attributes)

`_build_variables(lead, db, custom_fields)` MUST accept a pre-loaded `custom_fields` dict and merge its key-value pairs into the template variable context. Base Lead fields (name, phone, email, status) take precedence on key collision. Template files (`system-prompt.md`) MUST NOT change; `{{car_make}}` resolves from `custom_fields`.

##### Scenario: Template resolves custom field variable

- GIVEN `custom_fields = {car_make: "Toyota", car_year: "2021"}`
- AND system-prompt.md contains `{{car_make}} {{car_year}}`
- WHEN `_build_variables` builds the context
- THEN `{{car_make}}` resolves to `"Toyota"` and `{{car_year}}` resolves to `"2021"`

##### Scenario: Missing custom field — empty string

- GIVEN `car_model` is absent from `custom_fields`
- AND system-prompt.md contains `{{car_model}}`
- WHEN the template is rendered
- THEN `{{car_model}}` resolves to `""` (not an error)

---

## 5. Modified Capability: `capture-data-tool`

### Current Behavior

`_QUINTANA_TOOL_CONFIG` in `tenants/service.py` is a hardcoded JSON schema for `capture_data` with `car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona`. `register_interest` tool writes directly to Lead ORM columns.

### MODIFIED Requirements

#### Requirement: `capture_data` Schema Generated from `field_definitions`

(Previously: `_QUINTANA_TOOL_CONFIG` was a hardcoded constant in `tenants/service.py`)

The `capture_data` tool schema MUST be generated dynamically from the client's `field_definitions` list in `crm.yaml`. Each entry in `field_definitions` MUST produce one property in the OpenAI function-calling schema. The `_QUINTANA_TOOL_CONFIG` constant MUST be removed.

##### Scenario: Schema generated from config

- GIVEN `field_definitions` lists `car_make (string)`, `car_year (integer)`, `age (integer)`
- WHEN `build_tool_definitions` generates the `capture_data` schema for this client
- THEN the schema `properties` contains exactly `car_make`, `car_year`, `age` with correct JSON types
- AND `lead_id` is always included as a required property regardless of config

##### Scenario: Client with no `field_definitions`

- GIVEN a client config has no `field_definitions`
- WHEN `build_tool_definitions` is called for this client
- THEN `capture_data` is excluded from the tool list (same behavior as missing `tool_config`)

#### Requirement: `capture_data` Writes to `lead_custom_fields`

(Previously: `capture_data` wrote to `LeadProfileFact` under `captured:` namespace)

`capture_data` MUST upsert each captured field to `lead_custom_fields` using the client's `field_definitions` to resolve `field_type`. It MUST also continue writing a `LeadProfileFact` row under `captured:{field_name}` for backward compatibility with the intelligence pipeline (dual-write during WU-5).

##### Scenario: Captured field stored in custom_fields

- GIVEN a live call for lead `L1`, client `quintana-seguros`
- WHEN `capture_data(lead_id="L1", car_make="Toyota", car_year=2022)` is called
- THEN `lead_custom_fields` rows are upserted for `car_make="Toyota"` and `car_year="2022"`
- AND `LeadProfileFact` rows for `captured:car_make` and `captured:car_year` are also written

#### Requirement: `register_interest` Removed

(Previously: `register_interest` was a tool that wrote to Lead ORM columns)
(Reason: Superseded by `capture_data`; writing to removed Lead columns is a hard error post-WU-1)
(Migration: All agents MUST use `capture_data`. Any `register_interest` entry in `tools_enabled` is stripped at load time with a deprecation warning, per `configurable-agent-tools` spec.)

---

## 6. Post-Call Pipeline Changes

### MODIFIED Requirements

#### Requirement: `current_lead_data` Snapshot Includes Custom Fields

(Previously: snapshot included `age`, `car_make`, `car_model`, `car_year`, `current_insurance` from Lead ORM)

The post-call data corrections snapshot MUST be built by merging base Lead fields + all custom fields for the lead. The `CORRECTABLE_FIELDS` registry MUST write corrections to `lead_custom_fields` (not Lead ORM columns).

##### Scenario: Correction applies to custom field

- GIVEN `CORRECTABLE_FIELDS` contains `car_year` pointing to custom_fields write
- WHEN the analysis pipeline applies a correction for `car_year`
- THEN `lead_custom_fields` row for `car_year` is updated
- AND no write to `lead.car_year` (column removed) is attempted

---

## 7. API & Frontend

### MODIFIED Requirements

#### Requirement: Lead API Response Excludes Removed Columns

(Previously: `CreateLeadRequest`, `_lead_to_dict`, and frontend `Lead` type included `car_make`, `car_model`, `car_year`, `current_insurance`)

The Lead API response MUST NOT include the 6 removed columns as top-level fields. It MUST include `custom_fields: Record<string, string>` populated from `lead_custom_fields` rows for the requesting client. The `CreateLeadRequest` schema MUST accept `custom_fields?: Record<string, string>` and write them to `lead_custom_fields`.

##### Scenario: Lead response includes custom_fields

- GIVEN lead `L1` has custom fields `{car_make: "Toyota", zona: "Norte"}`
- WHEN `GET /leads/{id}` is called
- THEN the response body includes `"custom_fields": {"car_make": "Toyota", "zona": "Norte"}`
- AND top-level `car_make` / `zona` fields are absent

##### Scenario: Lead creation with custom_fields

- GIVEN `POST /leads` body `{"name": "Ana", "phone": "+5491...", "custom_fields": {"car_make": "Ford"}}`
- WHEN the request is processed
- THEN lead is created with `name` and `phone` on the `leads` row
- AND a `lead_custom_fields` row for `car_make="Ford"` is created

---

## Acceptance Criteria (cross-cutting)

| # | Criterion |
|---|-----------|
| AC-1 | All 6 hardcoded columns absent from active read/write paths after WU-7 |
| AC-2 | Existing Quintana leads preserve all field values after startup migration |
| AC-3 | Migration runs exactly once per DB; migration marker prevents re-run |
| AC-4 | `is_quote_ready` driven solely by `crm.yaml`; no hardcoded field names in code |
| AC-5 | `capture_data` schema contains exactly the fields from `field_definitions` |
| AC-6 | `register_interest` absent from codebase and tool registry |
| AC-7 | CRM export (`_lead_to_dict`) includes all custom fields for the lead |
| AC-8 | CRM import writes non-base fields to `lead_custom_fields`, not Lead ORM |
| AC-9 | Template `{{car_make}}` resolves correctly from custom_fields in rendered prompts |
| AC-10 | A client with no `crm.yaml` / empty `quote_ready_fields` never reaches "quoted" |
| AC-11 | Frontend `Lead` type has no `car_make`/`car_model`/`car_year`/`current_insurance` top-level fields |
| AC-12 | All backend tests pass: `cd backend && python3 -m pytest tests/ -q` |

---

## Security Considerations

| Area | Requirement |
|------|-------------|
| Client isolation | `lead_custom_fields` reads MUST always be scoped by `client_id` |
| `api_key` in config | `crm.yaml` `api_key` MUST NOT be logged or included in API responses; dev/test only pattern |
| Type enforcement | Coercion at write time prevents injection of unexpected types into downstream pipelines |
| Cross-tenant | Custom field reads/writes MUST validate that the lead belongs to the requesting client |

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Lead with no custom fields exported to CRM | Export includes only base fields; no error |
| `field_type` coercion for `boolean`: `"true"` / `"1"` / `"yes"` | All coerced to `True`; `"false"` / `"0"` / `"no"` coerced to `False` |
| Duplicate field_key in `field_definitions` | Config validation MUST reject with error at load time |
| Startup migration races (two workers restart simultaneously) | UNIQUE constraint on `lead_custom_fields` ensures idempotency; second insert fails gracefully |
| `car_year` stored as `"2021"` (TEXT) read as integer | Caller coerces at read time using `field_type`; raw storage is always TEXT |
| `register_interest` in DB `tools_enabled` post-cleanup | Stripped at agent load with deprecation warning; agent continues |
