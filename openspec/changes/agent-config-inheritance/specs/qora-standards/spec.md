# qora-standards Specification

## Purpose

Define the behavioral contract for the Qora standard itself: a versioned, code-defined floor of configuration values that no panel, API, or database row can set or override at any level. This spec covers the concrete enumerated list of locked standards, the `STANDARD_VERSION` mechanism, and the guarantee that locked fields are locked by construction, not by a permission check that could be bypassed.

---

## Requirements

### Requirement: The Qora Standard Is Code, Not Data

The Qora standard MUST be defined in a versioned Python module, carrying a `STANDARD_VERSION` string literal. No database table, API endpoint, or admin UI control MAY create, update, or delete a standard value. Changing a standard value MUST require a code change reviewed through the normal PR process.

#### Scenario: No write endpoint exists for standard values

- WHEN the API surface is inspected for any endpoint capable of modifying a Qora standard value
- THEN no such endpoint exists

#### Scenario: A standard value changes only through a code deploy

- GIVEN a Qora standard value needs to change (e.g. the default LLM model)
- WHEN that change is made
- THEN it is made by editing the `AgentConfigStandard` module and deploying new code
- AND `STANDARD_VERSION` is incremented as part of that same change

---

### Requirement: Locked Fields Cannot Be Set at Client or Agent Level

Every field whose policy is `locked` in the field-policy registry MUST resolve to the Qora standard's value regardless of what any client or agent revision contains for that field. Attempting to set a `locked` field at the client or agent level MUST be rejected at write time (see `config-inheritance` spec's write-validation requirement) — this spec defines the READ-side guarantee that a locked field cannot be made to resolve to anything but the standard, even if an override value were somehow present in stored data.

#### Scenario: A locked field resolves to the standard even if a stale override exists in stored data

- GIVEN a field whose policy is `locked`
- AND a client or agent revision's stored config happens to contain a value for that field (e.g. from data created before the field was reclassified as `locked`)
- WHEN the config is resolved
- THEN the resolved value is the Qora standard's current value
- AND the resolved provenance is `standard`, not `client` or `agent`

---

### Requirement: The Concrete List of Locked Standards Is Enumerated

The set of locked Qora-standard fields and their values MUST be an explicit, enumerable list — not an implicit default inferred from the absence of client/agent overrides. Each locked standard MUST have a documented rationale tying it to a platform-wide concern (cost, compliance, consistency, or caching behavior), not an arbitrary choice.

#### Scenario: Every locked field has a non-empty standard value

- GIVEN the field-policy registry
- WHEN every field whose policy is `locked` is inspected in `AgentConfigStandard`
- THEN each one has a defined, non-null value

#### Scenario: The locked-standards list covers fields fixed today in code, not only AgentConfigV1 fields

- GIVEN the locked standards enumerated for this capability
- WHEN compared against configuration that was previously fixed only by hardcoded values, code constants, or environment variables (e.g. the post-call analysis model, the memory window size, the technical retry limit)
- THEN each of those previously-implicit platform behaviors has a corresponding explicit entry in the locked-standards list

---

### Requirement: Standard Version Is Recorded Per Call

Every call session MUST record the `STANDARD_VERSION` that was active when the session was created, so that any later dispute about "what configuration did this call actually use" can be answered precisely, including for `locked` fields that have no client/agent revision history of their own.

#### Scenario: A call session's standard_version identifies the exact locked-field values used

- GIVEN a call session recorded `standard_version="2026.10.1"`
- WHEN someone needs to know what value a `locked` field (e.g. `analysis_model`) had during that call
- THEN looking up `AgentConfigStandard` as it existed at `STANDARD_VERSION="2026.10.1"` (via git history / code review of that version) answers the question exactly, without needing any database row for that field
