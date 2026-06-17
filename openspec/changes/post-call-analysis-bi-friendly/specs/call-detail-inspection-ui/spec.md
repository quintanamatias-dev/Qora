# call-detail-inspection-ui Specification

## Purpose

Define how per-call analysis dimensions are displayed in the call detail view. The view is an inspection tool for QA, support, and analytics — not a decorative summary. It MUST expose normalized values, evidence, and honest correction status.

## Requirements

### Requirement: Dimensions Displayed as Structured Variable/Value

Each dimension (objection, pain point, service issue, interest) in the call detail view MUST be displayed as a structured entry showing:
- Normalized category code (e.g. `current_provider`, `price`)
- Relevant scalar attributes (e.g. `strength`, `resolution_status`, `urgency`)
- Evidence quote, displayed inline (collapsible)

Decorative summary cards that hide normalized values MUST NOT be the primary display format for inspection.

#### Scenario: Objection displayed with normalized values

- GIVEN a call analysis with `objection: {category: "current_provider", strength: "medium", resolution_status: "unresolved", evidence: "recién cambié hace 6 meses"}`
- WHEN the call detail view renders
- THEN `category: current_provider` is visible as a label/value
- AND `strength: medium` and `resolution_status: unresolved` are displayed as structured fields
- AND the evidence quote is visible inline (or behind a collapse toggle)

#### Scenario: Multiple objections listed separately

- GIVEN a call has 2 objections with different categories
- WHEN the call detail view renders
- THEN both objections are listed as separate structured entries
- AND each entry shows its own category, strength, and evidence independently

---

### Requirement: Data Corrections Show Applied vs CRM Status

The call detail view MUST display each data correction with two distinct states:
- `Applied to Qora ✓` — shown when `applied_to_qora: true`
- CRM sync status — shown ONLY when a real field-level CRM parity system is implemented and `crm_sync_status` has a non-null value

When `crm_sync_status` is `null`, NO sync indicator, sync icon, or "synced" label of any kind MUST appear.

#### Scenario: Correction applied to Qora, CRM status unknown

- GIVEN a data correction with `applied_to_qora: true` and `crm_sync_status: null`
- WHEN the call detail view renders
- THEN "Applied to Qora ✓" (or equivalent) is shown
- AND no CRM sync label or icon is displayed

#### Scenario: Correction applied and CRM verified

- GIVEN a data correction with `applied_to_qora: true` and `crm_sync_status: "in_sync"`
- WHEN the call detail view renders
- THEN both "Applied to Qora ✓" and "Verified in CRM ✓" (or equivalent) are shown as distinct states

#### Scenario: Correction not yet applied

- GIVEN a data correction with `applied_to_qora: false`
- WHEN the call detail view renders
- THEN no "Applied" label is shown
- AND a pending or unapplied indicator is displayed

---

### Requirement: Older Call Corrections Do Not Show Current Sync State

If a newer call has since changed the same field value, the correction shown in an older call's detail view MUST NOT claim the field is currently in sync with CRM.

An older call's correction shows only what happened in that call — not current lead state.

#### Scenario: Older call correction stale after newer call

- GIVEN call #1 corrected `zona` to "Palermo" with `applied_to_qora: true`
- AND call #2 (newer) corrected `zona` to "Belgrano"
- WHEN call #1 detail view renders
- THEN the correction shows "Applied to Qora ✓" (historical fact for that call)
- AND no "currently in sync" or current-state indicator is shown
- AND a note or design treatment MAY indicate this correction is superseded by a later call

---

### Requirement: Call Detail Shows Raw Per-Call Output (No Aggregation)

The call detail view MUST display the raw, unaggregated output of the analysis for that specific call. It MUST NOT roll up or deduplicate across multiple calls for the same lead.

Lead-level rollups (counts per category across all calls) belong in the lead view, not the call detail view.

#### Scenario: Call detail shows only its own dimensions

- GIVEN lead A has 3 calls, each with different objections
- WHEN call #2 detail view is opened
- THEN only call #2's objections are shown
- AND objections from calls #1 and #3 are NOT included or summarized

#### Scenario: Lead view shows rollup; call detail does not

- GIVEN the lead view shows "price objection: 3 occurrences"
- WHEN a user drills into call #1's detail view
- THEN only call #1's objections are shown
- AND there is no aggregate count in the call detail view

---

### Requirement: Lead View Rollups Are Separate from Call Detail

The lead view MUST display per-category rollup counts across all calls for the lead (e.g. `COUNT(*)` of `price` objections). This is separate from and independent of the call detail view.

The lead view SHOULD provide a link/drilldown to each individual call's detail view for evidence inspection.

#### Scenario: Lead view shows objection frequency rollup

- GIVEN lead A has 3 calls with `price` as primary objection in 2 of them
- WHEN the lead view renders the objection summary
- THEN a count of 2 for `price` is shown
- AND a link to each contributing call's detail view is accessible
