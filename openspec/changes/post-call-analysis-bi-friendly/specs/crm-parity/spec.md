# crm-parity Specification

## Purpose

Define shared CRM parity logic used by two surfaces: lead-level Quote Readiness fields and call-level Data Corrections. Enforce honest sync states, distinguish `applied_to_qora` from `crm_verified`, and prevent stale sync indicators on older calls.

## Requirements

### Requirement: Shared CRM Parity Resolution Module

CRM parity/sync resolution logic MUST be implemented in a single shared module (e.g. `crm_parity.py`). This logic MUST NOT be duplicated across the Quote Readiness surface and the Data Corrections surface.

The shared module MUST resolve parity for a field by comparing the current Qora value with the client CRM/Airtable value and returning one of three states:

| State | Meaning |
|-------|---------|
| `in_sync` | Qora value matches client CRM value |
| `out_of_sync` | Qora value differs from client CRM value |
| `unknown` | CRM value not available or parity not yet tracked |

#### Scenario: Lead-level Quote Readiness parity resolved

- GIVEN a lead has `zona = "Palermo"` in Qora custom fields
- AND the client CRM has `zona = "Palermo"` for the same lead
- WHEN the shared parity module resolves `zona`
- THEN the result is `in_sync`

#### Scenario: Out-of-sync detected

- GIVEN a lead has `zona = "Belgrano"` in Qora custom fields
- AND the client CRM has `zona = "Palermo"` for the same lead
- WHEN the shared parity module resolves `zona`
- THEN the result is `out_of_sync`

#### Scenario: CRM value not available

- GIVEN the CRM integration has not yet synced or CRM data is unavailable for this lead/field
- WHEN the shared parity module resolves the field
- THEN the result is `unknown`

---

### Requirement: applied_to_qora and crm_verified Are Distinct States

`applied_to_qora` and `crm_verified` MUST be treated and displayed as separate, independent states. A correction being applied to Qora MUST NOT imply CRM verification.

| Field | Meaning |
|-------|---------|
| `applied_to_qora: true` | The correction has been written to Qora's storage |
| `crm_sync_status: "in_sync"` | The Qora value now matches the client CRM value |

The UI MUST display both states explicitly when available, and MUST NOT infer one from the other.

#### Scenario: Applied to Qora but CRM not yet checked

- GIVEN `applied_to_qora: true` and `crm_sync_status: null`
- WHEN any UI surface renders the correction status
- THEN only "Applied to Qora ✓" is shown
- AND no CRM sync state is shown or implied

#### Scenario: Applied and CRM verified

- GIVEN `applied_to_qora: true` and `crm_sync_status: "in_sync"`
- WHEN any UI surface renders the correction status
- THEN both states are shown as distinct labels: "Applied to Qora ✓" and "Verified in CRM ✓"

#### Scenario: Unknown sync state — no indicator shown

- GIVEN `crm_sync_status: "unknown"` or `null`
- WHEN any UI surface renders
- THEN no sync indicator, sync icon, or sync-related label is shown
- AND the UI does not default to showing "synced"

---

### Requirement: Older Calls Do Not Imply Current Sync State

A call-level data correction represents what happened in that specific call. If a newer call has since changed the same field, the older call's correction MUST NOT be used to imply the field's current sync state.

Sync status resolution MUST always be based on the latest-call correction for each field, not on arbitrary historical corrections.

#### Scenario: Older call correction superseded by newer call

- GIVEN call #1 corrected `zona` to "Palermo" (`applied_to_qora: true`)
- AND call #2 (newer) corrected `zona` to "Belgrano" (`applied_to_qora: true`)
- WHEN sync status is resolved for this lead's `zona` field
- THEN only call #2's correction is used as the basis for parity resolution
- AND call #1's correction is NOT used to determine current sync state

#### Scenario: Call detail for older call does not show current sync state

- GIVEN call #1 is no longer the latest call for a corrected field
- WHEN call #1's detail view renders
- THEN the correction for that field shows historical `applied_to_qora: true` only
- AND no current sync state from CRM is shown for call #1's correction

---

### Requirement: Parity Applied Consistently to Both Surfaces

The same shared parity module MUST be used by both:
1. Lead-level Quote Readiness: compare Qora custom field values with client CRM values for required quote fields
2. Call-level Data Corrections: for the latest call's corrections, resolve whether the resulting Qora value matches CRM

Neither surface MUST implement its own sync resolution logic.

#### Scenario: Quote Readiness parity uses shared module

- GIVEN a lead view needs to show Quote Readiness field sync states
- WHEN the UI or API resolves parity for `zona`, `age`, etc.
- THEN the shared `crm_parity` module is called
- AND the result (in_sync / out_of_sync / unknown) is used for display

#### Scenario: Data Corrections parity uses same shared module

- GIVEN a call detail view needs to show sync state for a correction
- WHEN sync state is resolved for that correction
- THEN the same shared `crm_parity` module is called
- AND the result is identical to what the lead view would show for the same field

---

### Requirement: CRM Sync Engine Not Implemented in This Change

This change MUST NOT implement a CRM field-level sync engine. Only the parity resolution label/UX contract and the shared module interface are in scope.

The shared module MAY return `unknown` for all fields until a real CRM sync engine is implemented.

#### Scenario: Parity module returns unknown before sync engine exists

- GIVEN no CRM sync engine has been implemented
- WHEN the shared parity module is called for any field
- THEN the result is `unknown`
- AND the UI shows no sync indicator
