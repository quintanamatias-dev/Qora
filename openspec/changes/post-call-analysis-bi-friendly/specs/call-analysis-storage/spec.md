# call-analysis-storage Specification

## Purpose

Define the denormalized column additions to the `call_analyses` table that enable BI queries on primary objection/pain categories and dimension counts without JSON extraction gymnastics.

## Requirements

### Requirement: Denormalized Columns in call_analyses

The `call_analyses` table MUST include the following five denormalized columns:

| Column | Type | Source | Purpose |
|--------|------|--------|---------|
| `primary_objection_category` | VARCHAR | `objections[is_primary=true].category` | filter/group without JSON |
| `primary_pain_category` | VARCHAR | `pain_points[is_primary=true].category` | filter/group without JSON |
| `objections_count` | INTEGER | `len(objections)` | count without JSON |
| `pain_points_count` | INTEGER | `len(pain_points)` | count without JSON |
| `service_issues_count` | INTEGER | `len(service_issues)` | count without JSON |

All five columns MUST be nullable. A `null` value means no data in that dimension for this call — not zero.

An Alembic migration MUST create these columns. Indexes MUST be added on `primary_objection_category` and `primary_pain_category`.

#### Scenario: Call with objections and pain points

- GIVEN a call analysis produces 2 objections (one `is_primary: true` with `category: "price"`) and 1 pain point (`is_primary: true`, `category: "service_quality"`)
- WHEN `_upsert_call_analysis()` runs
- THEN `primary_objection_category = "price"`, `primary_pain_category = "service_quality"`, `objections_count = 2`, `pain_points_count = 1`

#### Scenario: Call with no objections

- GIVEN a call analysis produces zero objections
- WHEN `_upsert_call_analysis()` runs
- THEN `primary_objection_category = null` and `objections_count = 0`

#### Scenario: Denormalized columns match JSON source

- GIVEN a stored call analysis row
- WHEN the denormalized columns are compared with the JSON `objections`/`pain_points`/`service_issues` arrays
- THEN `primary_objection_category` equals the `category` of the item with `is_primary: true` in `objections`
- AND `objections_count` equals `len(objections)`
- AND the same consistency holds for pain and service issues

---

### Requirement: Atomic Population in Summarizer

The five denormalized columns MUST be populated in `_upsert_call_analysis()` in the same database transaction as the JSON dimension arrays.

The population logic MUST derive values from the already-computed analysis output — no second AI call, no separate pass.

#### Scenario: Columns populated atomically

- GIVEN `_upsert_call_analysis()` receives a completed call analysis object
- WHEN it writes the call analysis to the database
- THEN all five denormalized columns are written in the same transaction as the JSON arrays
- AND if the transaction rolls back, neither the JSON arrays nor the denormalized columns are persisted

#### Scenario: Column population from JSON is consistent

- GIVEN the analysis JSON contains `objections: [{"category": "current_provider", "is_primary": true}, {"category": "price", "is_primary": false}]`
- WHEN the summarizer populates denormalized columns
- THEN `primary_objection_category = "current_provider"` and `objections_count = 2`

---

### Requirement: No Blind Deduplication of Occurrences

The same objection or pain category MAY appear in multiple calls for the same lead. The storage layer MUST NOT deduplicate or merge these occurrences.

Each call analysis row is an independent, immutable record of what happened in that call.

#### Scenario: Same objection in two calls for one lead

- GIVEN lead A has two calls, both with `primary_objection_category = "price"`
- WHEN stored
- THEN two separate `call_analyses` rows exist, each with `primary_objection_category = "price"`
- AND no merge or deduplication occurs at storage time

#### Scenario: BI count query uses per-call rows

- GIVEN a BI query runs `SELECT primary_objection_category, COUNT(*) FROM call_analyses GROUP BY primary_objection_category`
- WHEN the query runs
- THEN each call contributes independently to the count
- AND the result reflects occurrence frequency across calls, not across leads

---

### Requirement: Analytics Service Uses Indexed Columns

The analytics service MUST use the denormalized columns (`primary_objection_category`, `primary_pain_category`, `objections_count`, etc.) for primary/count queries.

`json_each()` or equivalent JSON extraction MUST NOT be required for these queries after this change ships.

#### Scenario: Primary objection breakdown query

- GIVEN multiple call analyses with varied `primary_objection_category` values
- WHEN a client requests "most common primary objections"
- THEN the analytics service queries `primary_objection_category` directly
- AND the query does not use `json_each()` or JSON path extraction
