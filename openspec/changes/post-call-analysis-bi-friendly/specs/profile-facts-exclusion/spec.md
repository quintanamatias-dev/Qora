# profile-facts-exclusion Specification

## Purpose

Define routing rules that prevent structured lead fields from being duplicated as profile facts. When a detected value maps to a known structured field (custom field, lead contact field), it MUST be routed to the appropriate structured storage or suppressed — never stored as a profile fact.

## Requirements

### Requirement: Structured Field Exclusion Routing

Before emitting any profile fact, the profile facts pipeline MUST check whether the detected field maps to a known structured lead field.

The following fields MUST be in the exclusion list:

| Detected Field | Route To |
|---------------|----------|
| `age` / demographic age | `lead_custom_fields` via data corrections |
| `zona` / location | `lead_custom_fields` via data corrections |
| `car_make`, `car_model`, `car_year` | `lead_custom_fields` via data corrections |
| `current_insurance` | `lead_custom_fields` via data corrections |
| `name` | lead contact fields (suppress if already set) |
| `phone` | lead contact fields (suppress if already set) |
| `email` | lead contact fields (suppress if already set) |

If the detected value maps to a field in this list, the profile fact MUST NOT be emitted.

#### Scenario: Age detected — routed to corrections, not profile facts

- GIVEN a call transcript contains a clear age statement ("tengo 23 años")
- WHEN the profile facts pipeline processes the transcript
- THEN no profile fact for `family_context` or any age proxy is emitted
- AND the age value is routed to data corrections for `lead_custom_fields` storage

#### Scenario: Zona detected — suppressed from profile facts

- GIVEN a call transcript contains a zona/location statement
- WHEN the profile facts pipeline processes the transcript
- THEN no profile fact with location/lifestyle/zona evidence is emitted
- AND the zona value is handled by the zona-data-correction pipeline

#### Scenario: Car make/model detected — routed to corrections

- GIVEN a lead mentions their vehicle ("tengo un Toyota Corolla 2020")
- WHEN the profile facts pipeline processes the transcript
- THEN no profile fact for vehicle ownership is emitted
- AND the vehicle fields are routed to data corrections for `car_make`/`car_model`/`car_year`

#### Scenario: Contact field already set — suppress, do not overwrite

- GIVEN a lead's `email` is already set in lead contact fields
- AND the transcript contains an email mention that matches the existing value
- WHEN the profile facts pipeline processes the transcript
- THEN no profile fact for email is emitted
- AND the existing contact field is not modified by this pipeline

---

### Requirement: Suppressed Facts Logged for Audit

Suppressed profile facts MUST be logged at the call level with the reason for suppression.

The log entry MUST include: detected field category, suppression reason (`structured_field_exists` or `routed_to_corrections`), and the call ID.

This log MUST NOT be user-visible in the call detail UI; it is for internal QA/audit only.

#### Scenario: Suppression audit log written

- GIVEN a profile fact is suppressed due to structured field exclusion
- WHEN the pipeline completes
- THEN a suppression log entry is written with the detected field, reason, and call_id
- AND the suppression is NOT surfaced as an error or warning in the call detail view

#### Scenario: Non-excluded field passes through normally

- GIVEN a call transcript contains a personality trait or preference not in the exclusion list ("le gusta el fútbol", "prefiere cuotas mensuales")
- WHEN the profile facts pipeline processes the transcript
- THEN the profile fact is emitted normally
- AND no suppression log entry is created

---

### Requirement: Exclusion List is Exhaustive at Deploy Time

At the time this change ships, the exclusion list MUST include ALL known structured lead fields that the corrections pipeline or lead contact fields already handle.

If a new structured field is added to the corrections pipeline in the future, it MUST also be added to the profile facts exclusion list in the same change.

#### Scenario: New corrections field triggers exclusion list update

- GIVEN a new field is added to `CORRECTABLE_FIELDS` (e.g. `occupation`)
- WHEN that change is implemented
- THEN the profile facts exclusion list MUST be updated in the same PR or change
- AND a test MUST verify the field does not appear as a profile fact
