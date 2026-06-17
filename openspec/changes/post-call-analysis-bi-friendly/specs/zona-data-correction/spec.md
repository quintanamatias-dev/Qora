# zona-data-correction Specification

## Purpose

Define how `zona` (lead geographic zone) is captured from call transcripts and routed to structured lead storage via the data corrections pipeline, making it queryable without JSON extraction.

## Requirements

### Requirement: Zona Registered in CORRECTABLE_FIELDS

`zona` MUST be registered as an entry in `CORRECTABLE_FIELDS` in the data corrections pipeline.

The registration MUST specify `storage_type: custom_field` so the corrections pipeline writes to `lead_custom_fields`, not to `profile_facts`.

The initial registration MUST use a permissive validator (accepts any non-empty string). No format constraint or allowlist is applied in this phase.

#### Scenario: Zona extracted from transcript

- GIVEN a call transcript contains a clear location statement ("vivo en Palermo", "soy de zona norte")
- WHEN the data corrections pipeline processes the transcript
- THEN a correction entry for `field: "zona"` MUST be produced with the extracted string as `corrected_value`
- AND `applied_to_qora` MUST be set to `true` after application
- AND the value MUST be written to `lead_custom_fields` for that lead

#### Scenario: No zona mention

- GIVEN a call transcript contains no location reference
- WHEN the data corrections pipeline processes the transcript
- THEN no correction entry for `zona` is produced
- AND no `lead_custom_fields` row for `zona` is created or modified

#### Scenario: Empty or whitespace value rejected

- GIVEN the AI extracts an empty string or whitespace-only value for `zona`
- WHEN the validator runs
- THEN the correction entry MUST be suppressed (not written)

---

### Requirement: CORRECTABLE_FIELDS Registry Design Contract

The `CORRECTABLE_FIELDS` registry MUST be documented as the authoritative control point for which lead fields the AI may update from transcript evidence.

The current implementation MAY be hardcoded. The design MUST acknowledge a future config-driven registry with three input sources:

| Source | Examples |
|--------|---------|
| Basic lead fields | `zona`, `age`, `current_insurance` |
| Client CRM/CSV custom fields | any updatable field from client integration |
| Quote/readiness required fields | fields expected before a quote is ready |

The immediate `zona` entry MUST be added as a hardcoded entry. A design note or ADR entry MUST record the config-driven path so this entry does not calcify as the permanent pattern.

#### Scenario: Zona correction applied with honest labels

- GIVEN a correction for `zona` has been applied to Qora's storage
- WHEN the correction is displayed in any UI surface
- THEN `applied_to_qora: true` MUST be shown
- AND `crm_sync_status` MUST be `null` (not yet tracked)
- AND no CRM sync indicator or "synced" label MUST be displayed

#### Scenario: Config-driven registry future path documented

- GIVEN the spec and design artifacts for this change
- WHEN a developer reads the CORRECTABLE_FIELDS implementation
- THEN a code comment or ADR MUST describe the three-source config-driven registry path
- AND the hardcoded `zona` entry MUST be flagged as the interim implementation

---

### Requirement: Zona Not Duplicated in Profile Facts

If `zona` is captured by the data corrections pipeline and written to `lead_custom_fields`, the same value MUST NOT also be written to `profile_facts` as a lifestyle or location tag.

#### Scenario: Zona routed to corrections, not profile facts

- GIVEN a call transcript contains a clear zona mention
- WHEN both the data corrections and profile facts pipelines process the transcript
- THEN `lead_custom_fields.zona` is populated
- AND no `profile_facts` entry for zona/location is created for the same evidence

#### Scenario: Pre-existing profile fact for location does not block correction

- GIVEN a previous call created a profile fact with location evidence
- AND the current call's corrections pipeline detects zona
- WHEN the correction is applied
- THEN the correction writes to `lead_custom_fields`
- AND does not fail or skip due to the pre-existing profile fact
