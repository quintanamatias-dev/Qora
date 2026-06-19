# Lead Dimension Rollups Specification

## Purpose

Define the backend rollup API and frontend accumulated dimension ranking UI that provides operators a reliable cross-call view of what a lead has repeatedly signaled. Covers: rollup endpoint, Detected Interests ranking, Service Issues ranking, Accumulated Facts container rename, and dimension rollup embedding.

## Requirements

### Requirement: Rollup API Endpoint

The system MUST expose `GET /api/v1/leads/{lead_id}/dimension-rollups` that queries `call_analyses` (not `CallSession.extracted_facts`) and returns count-based rankings for detected interests, service issues, objections, and pain points for the given lead.

The endpoint MUST NOT read from `CallSession.extracted_facts` for any rollup dimension.

#### Scenario: Lead with multiple calls

- GIVEN a lead with 3+ call analysis records in `call_analyses`
- WHEN `GET /api/v1/leads/{lead_id}/dimension-rollups` is called
- THEN the response includes `detected_interests`, `service_issues`, `objections`, and `pain_points` arrays ordered by mention count descending

#### Scenario: Single-call lead

- GIVEN a lead with exactly one call analysis record
- WHEN `GET /api/v1/leads/{lead_id}/dimension-rollups` is called
- THEN each ranking array contains the values from that single call with mention count = 1 and no errors or empty-state errors

#### Scenario: Lead with no call analyses

- GIVEN a lead with zero call analysis records
- WHEN `GET /api/v1/leads/{lead_id}/dimension-rollups` is called
- THEN the response returns empty arrays for all dimensions and HTTP 200

---

### Requirement: Detected Interests Ranking

The system MUST display a Detected Interests ranking table inside the Accumulated Facts section with columns: `interest`, `#`, `category`. The column header for mention count MUST be `#`. No strength column. No evidence column. Rows ordered by `#` descending.

Interest labels MUST be normalized from the `PRODUCT_CATALOG` and `NEED_TAGS` allowlists only. Items outside these allowlists MUST NOT appear in the ranking.

#### Scenario: Multiple interest mentions across calls

- GIVEN a lead whose calls mention `auto_todo_riesgo` in 3 calls and `hogar` in 1 call
- WHEN the Accumulated Facts section renders the Detected Interests ranking
- THEN the table shows `auto_todo_riesgo | 3 | <category>` in row 1 and `hogar | 1 | <category>` in row 2
- AND the column header reads `#`

#### Scenario: Interest outside catalog

- GIVEN a call analysis that somehow contains a product ID not in `PRODUCT_CATALOG` or `NEED_TAGS`
- WHEN the ranking is computed
- THEN that interest MUST NOT appear in the ranking table

---

### Requirement: Service Issues Ranking

The system MUST display a Service Issues ranking table inside the Accumulated Facts section with columns: normalized issue/tag (`IssueCategoryType`), `#`, `strength`. The column header for mention count MUST be `#`. No evidence column in the ranking UI.

Strength MUST be derived from mention count thresholds: 3+ mentions = `high`, 2 mentions = `medium`, 1 mention = `low`.

#### Scenario: Multiple service issue mentions

- GIVEN a lead whose calls record `poor_attention` in 2 calls and `delay` in 1 call
- WHEN the Accumulated Facts section renders the Service Issues ranking
- THEN the table shows `poor_attention | 2 | medium` in row 1 and `delay | 1 | low` in row 2
- AND the column header for the count column reads `#`

#### Scenario: Strength threshold boundaries

- GIVEN a service issue mentioned exactly 3 times
- WHEN the ranking is rendered
- THEN the strength column shows `high`

- GIVEN a service issue mentioned exactly 1 time
- WHEN the ranking is rendered
- THEN the strength column shows `low`

---

### Requirement: Accumulated Facts Container Rename

The system MUST rename the "Accumulated Profile Facts" container label to "Accumulated Facts" in all UI text, test assertions, and string literals. The Profile dimension MUST remain as a sub-section inside Accumulated Facts.

#### Scenario: Rename reflected in UI

- GIVEN a lead detail page is loaded
- WHEN the Accumulated Facts section renders
- THEN the section heading reads "Accumulated Facts" not "Accumulated Profile Facts"
- AND the Profile sub-section is still visible inside it

#### Scenario: Tests use updated label

- GIVEN the test suite runs against the lead detail page
- WHEN tests query for the section heading
- THEN assertions reference "Accumulated Facts" and do not reference "Accumulated Profile Facts"

---

### Requirement: Remove Standalone Dimension Rollups Section

The system MUST remove the standalone `DimensionRollupsSection` component from the lead detail page. Rollup data MUST be embedded directly inside the relevant dimensions within Accumulated Facts.

#### Scenario: DimensionRollupsSection absent

- GIVEN a lead detail page is rendered
- WHEN the page DOM is inspected
- THEN no element with the `DimensionRollupsSection` identity exists
- AND objection/pain rollup data appears inside the Accumulated Facts section

---

### Requirement: Next Call Context Preview Preserved

The system MUST NOT modify `build_voice_context()`, `build_memory_context()`, `_format_accumulated_profile()`, or the context preview endpoint. The Next Call Context Preview output MUST be byte-for-byte identical before and after the change for any given lead state.

#### Scenario: Context preview snapshot comparison

- GIVEN a lead with existing call analyses and profile facts
- WHEN `GET /api/v1/leads/{lead_id}/context-preview` is called before and after the change
- THEN the two responses are identical

---

### Requirement: No DB Migrations

The system MUST NOT introduce new database tables, schema migrations, or `ALTER TABLE` statements as part of this change. All rollup data MUST be derived from existing `call_analyses` columns.

#### Scenario: Migration file check

- GIVEN the changeset is applied
- WHEN the migrations folder is inspected
- THEN no new migration files exist for this change
