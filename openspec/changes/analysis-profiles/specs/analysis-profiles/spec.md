# analysis-profiles Specification

## Purpose

Define the behavioral contract for per-client, versioned analysis profiles: the `client_analysis_profile_revisions` schema and its immutable-revision lifecycle, the `insurance`/`generic` code templates and the one-time migration seed, the per-call/per-client catalog resolution that replaces `interests.py`'s module-load prompt construction, the empty-catalog pipeline skip, the `analysis_profile_revision_id` stamped onto `CallAnalysis`, and the profile CRUD/rollback/apply-template API. This spec does not define next-action rule thresholds (unchanged, still on `Client` columns) or any post-call analysis dimension other than interest detection.

---

## Requirements

### Requirement: Every Client Has Exactly One Active Analysis Profile Revision

Every client MUST have an active `client_analysis_profile_revisions` row at all times after the one-time migration seed. Revisions MUST be immutable once created — no `UPDATE` or `DELETE` path exists on this table.

#### Scenario: A newly migrated client has revision 1

- GIVEN a client existed before this change's migration ran
- WHEN the migration completes
- THEN exactly one `client_analysis_profile_revisions` row exists for that client, with `revision_number = 1`
- AND `clients.active_analysis_profile_revision_id` points at that row

#### Scenario: Editing a profile creates a new revision, never mutates an existing one

- GIVEN a client has an active revision with `revision_number = 1`
- WHEN the client's profile is updated via the write API
- THEN a new row is created with `revision_number = 2`
- AND the row for `revision_number = 1` is unchanged
- AND `clients.active_analysis_profile_revision_id` now points at `revision_number = 2`

#### Scenario: Rollback creates a new revision, it does not resurrect the old one

- GIVEN a client has revisions 1 and 2, with revision 2 currently active
- WHEN a rollback to revision 1 is requested
- THEN a new revision 3 is created, with `config` copied from revision 1
- AND `clients.active_analysis_profile_revision_id` points at revision 3, not revision 1
- AND revision 1's own row is unchanged

---

### Requirement: Quintana's Catalog Is Byte-Identical Before and After Migration

The one-time migration MUST seed Quintana Seguros's first revision with product and need-tag IDs that exactly match the existing `catalog.py` module's `PRODUCT_CATALOG` and `NEED_TAGS` constants. Every other existing client MUST be seeded with an empty catalog.

#### Scenario: Quintana's seeded revision matches catalog.py exactly

- GIVEN the migration runs against a database containing Quintana Seguros's client row
- WHEN the migration completes
- THEN Quintana's seeded revision's product ids, as a set, equal `catalog.py`'s `PRODUCT_CATALOG` ids exactly
- AND Quintana's seeded revision's need-tag ids, as a set, equal `catalog.py`'s `NEED_TAGS` ids exactly

#### Scenario: Every other existing client is seeded with an empty catalog

- GIVEN the migration runs against a database containing clients other than Quintana Seguros
- WHEN the migration completes
- THEN each of those clients' seeded revision has an empty `products` list and an empty `need_tags` list

---

### Requirement: The Interest Pipeline's Prompt Is Built Per Call, Not Per Process

The product/need-tag catalog injected into Agent 1's prompt MUST be resolved from the calling client's active analysis profile at call time. No part of the prompt construction MUST be fixed at module import time.

#### Scenario: Two different clients produce two different prompts in the same process

- GIVEN two clients with different active analysis profiles (different product catalogs)
- WHEN the interest-detection prompt is built for a call belonging to each client, in the same running process
- THEN the two resulting prompt strings differ in their listed product IDs, reflecting each client's own catalog

#### Scenario: Editing a client's profile changes the next call's prompt without a restart

- GIVEN a client's active analysis profile is edited via the write API while the application process is already running
- WHEN a new call for that client is analyzed afterward, in the same process
- THEN the prompt built for that call reflects the newly edited catalog, not the catalog that was active before the edit

---

### Requirement: An Empty Product Catalog Skips the Interest Pipeline Entirely

When a client's active analysis profile has an empty product catalog, the interest-detection pipeline MUST NOT invoke either Agent 1 or Agent 2 for that call. The result MUST be a normal empty result, not an error marker.

#### Scenario: No agents are called when products are empty

- GIVEN a client's active analysis profile has an empty `products` list
- WHEN a call for that client is analyzed
- THEN neither the interest-detection agent nor the interest-level agent is invoked
- AND the resulting `detected_interests` is an empty, non-error result

#### Scenario: Agent 1 still runs when products are non-empty, even if need tags are empty

- GIVEN a client's active analysis profile has a non-empty `products` list and an empty `need_tags` list
- WHEN a call for that client is analyzed
- THEN the interest-detection agent is invoked
- AND any detected interest's needs are empty, reflecting the empty need-tag catalog, without skipping product detection itself

---

### Requirement: Every Analyzed Call Is Stamped With Its Resolved Profile Revision

`CallAnalysis` rows written after this change MUST record the `analysis_profile_revision_id` that was active for the owning client at the time of analysis. A later edit to that client's profile MUST NOT change the stamped value on an already-written row.

#### Scenario: A newly analyzed call is stamped with the client's active revision

- GIVEN a client's active analysis profile revision is a specific, known revision
- WHEN a call for that client is analyzed
- THEN the resulting `CallAnalysis` row's `analysis_profile_revision_id` equals that known revision's id

#### Scenario: A later profile edit does not retroactively change an earlier call's stamp

- GIVEN a call was analyzed and its `CallAnalysis` row was stamped with revision 1's id
- WHEN the client's profile is subsequently edited, creating revision 2 as active
- THEN the earlier call's `CallAnalysis.analysis_profile_revision_id` still equals revision 1's id, unchanged

---

### Requirement: Consumers Resolve the Client's Catalog, Never a Global Constant

Any code that filters or labels data by product or need-tag identity (the lead-interest rollup, the call-analysis response) MUST resolve the calling client's own active catalog rather than reading a module-level, globally shared constant.

#### Scenario: Two clients' interest rollups reflect their own distinct catalogs

- GIVEN two clients with different active analysis profiles
- WHEN each client's lead-interest rollup is computed
- THEN each rollup is filtered against that client's own resolved catalog, not a catalog shared across every client

#### Scenario: No remaining direct import of the legacy module-level catalog in consumer code

- GIVEN the consumer cutover is complete
- WHEN the consumer source files are inspected
- THEN neither the lead-interest rollup module nor the call-analysis response module imports the legacy module-level product or need-tag constants directly

---

### Requirement: Profile Write API Validates Uniqueness and Non-Empty Labels

A write to a client's analysis profile MUST be rejected when it contains a duplicate product id, a duplicate need-tag id, or any entry with an empty label in either language.

#### Scenario: A duplicate product id is rejected

- GIVEN a profile write request contains two product entries with the same id
- WHEN the write is submitted
- THEN the request is rejected with a client error naming the duplicate id

#### Scenario: An empty label is rejected

- GIVEN a profile write request contains an entry whose Spanish or English label is an empty string
- WHEN the write is submitted
- THEN the request is rejected with a client error naming the offending field

#### Scenario: A valid write creates exactly one new revision

- GIVEN a profile write request contains unique ids and non-empty labels throughout
- WHEN the write is submitted
- THEN exactly one new revision is created
- AND it becomes the client's active revision

---

### Requirement: Applying a Template Creates a New Revision From Code-Defined Data

Requesting a vertical template application MUST create a new revision whose configuration exactly matches that template's current code-defined data. An unknown vertical name MUST be rejected.

#### Scenario: Applying the insurance template matches the code template exactly

- GIVEN a client requests the `insurance` template be applied
- WHEN the request is processed
- THEN a new revision is created whose product and need-tag entries exactly match the `insurance` template's current code-defined data

#### Scenario: An unknown vertical name is rejected

- GIVEN a client requests a template application naming a vertical that has no corresponding code template
- WHEN the request is processed
- THEN the request is rejected with a client error, and no new revision is created

---

### Requirement: Frontend Labels Prefer the Fetched Profile, Fall Back Visibly

The frontend's product/need-tag label lookup MUST prefer labels fetched from the client's analysis profile API. When the fetch fails, or a specific id is absent from the fetched profile, the lookup MUST fall back to the existing static label map, and the fallback MUST be visible in the console.

#### Scenario: A fetched label is used in preference to the static map

- GIVEN the analysis profile API returns a label for a given product id
- WHEN that product id's label is looked up
- THEN the fetched label is used, not the static map's label for the same id

#### Scenario: A failed fetch falls back without breaking the render

- GIVEN the analysis profile API call fails
- WHEN a product or need-tag label is looked up
- THEN the static map's label is used instead
- AND a console warning is logged noting the fallback occurred
