# Exploration: Post-Call Analysis BI-Friendly Redesign

## Current State

### Analysis Pipeline Architecture

Qora runs **6 parallel GPT dimension modules** plus **4 sequential stateful pipelines** after each call:

**Parallel dimensions (DIMENSION_MODULES — stateless):**
1. `summary` → `PostCallAnalysis.summary` (str)
2. `objections` → `ObjectionsAxis` (list of `Objection` with category, strength, resolution_status, evidence, description, confidence, agent_response_summary, is_primary)
3. `outcome` → `CallOutcome` (classification, reason, confidence, was_abrupt, abandonment_trigger)
4. `problem` → `ProblemAxis` (list of `PainPoint` with category, description, evidence, urgency, confidence, is_primary)
5. `service_issues` → `ServiceIssuesAxis` (list of `ServiceIssue` with category, description, source, severity, evidence, confidence)
6. `commitments` → `CommitmentsAxis` (list of `Commitment` with type, owner, description, due, strength, evidence, confidence)

**Sequential/stateful pipelines:**
7. `interest` pipeline → `InterestsAxis` (catalog-validated items) + `InterestLevelResult` (0-100 with 70/30 formula)
8. `profile_facts` pipeline → `ProfileFactsAxis` (add/update/remove operations against current lead profile)
9. `misc_notes` pipeline → `MiscNotesAxis` (sliding-window operational notes, max 5)
10. `data_corrections` pipeline → `DataCorrectionsAxis` (structured corrections with validation + confidence gate)

**Post-analysis:**
11. `next_action` pipeline → `NextActionResult` (action, reason, confidence, timing, outcome context)

### Storage: Three Levels

| Level | Table | What | BI-Friendly? |
|-------|-------|------|-------------|
| **Per-call** | `call_analyses` | Flattened analysis: classification, interest_level, objections (JSON list), products (JSON list), pain_points (JSON list), service_issues (JSON list), profile_facts (JSON list), commitment_signals (JSON list), summary, etc. | **Partially** — enum columns (classification, urgency) are clean; JSON-as-TEXT arrays require `json_each()` for analytics |
| **Lead accumulation** | `lead_profile_facts` | Namespaced KV rows (profile:, pain:, service_issue:, signal:, objection:, buying_signal:) with supersede semantics for singulars and append-only for lists | **Partially** — fact_key is namespaced which is good, but fact_value is free text (not normalized codes) |
| **Lead legacy** | `leads.extracted_facts` (JSON), `leads.objections_heard` (JSON), `leads.interest_level` (int) | Merged latest-wins blob + union objections | **No** — JSON blob, no queryable structure, latest-wins destroys history |

### What the Analytics Service Already Queries

`backend/app/analytics/service.py` currently produces:
- **Overview**: counts by `CallAnalysis.classification` (BI-friendly — enum column)
- **Service issues**: `json_each(ca.service_issues)` + `json_extract(je.value, '$.category')` — already extracting normalized codes from JSON
- **Interests**: `LeadProfileFact` with `signal:` prefix — counting by fact_key
- **Agent stats**: counts by `CallAnalysis.classification` grouped by `CallSession.agent_id`

### Per-Call Dimension Outputs — BI-Friendliness Audit

| Dimension | Normalized Codes (BI-friendly) | Free Text (needs drill-down only) | Verdict |
|-----------|-------------------------------|----------------------------------|---------|
| **outcome** | `classification` (11 enum values), `confidence`, `was_abrupt`, `abandonment_trigger` (8 enum values) | `reason` | **Good** |
| **objections** | `category` (14 enum values), `strength` (3), `resolution_status` (5), `confidence` (3), `is_primary` | `description`, `evidence`, `agent_response_summary` | **Good** — but duplicates across calls need aggregation |
| **problem** | `category` (11 enum values), `urgency` (4), `confidence` (3), `is_primary` | `description`, `evidence` | **Mixed** — `comparison` category is ambiguous (see issues below) |
| **service_issues** | `category` (10 enum values), `source` (4 enum values), `severity` (3), `confidence` (3) | `description`, `evidence` | **Good** |
| **commitments** | `type` (8 enum values), `owner` (3), `strength` (3), `due` (5), `confidence` (3) | `description`, `evidence` | **Good** |
| **interests** | `product` (catalog-validated), `needs` (list) | — | **Good** |
| **interest_level** | `general_score` (0-100) | — | **Good** |
| **profile_facts** | `category` (11 enum values), `operation` (3), `confidence` (3) | `fact`, `evidence` | **Mixed** — category is normalized but fact text is free-form |
| **misc_notes** | `type` | `note` | **Operational only** — not BI data |
| **data_corrections** | `field` (8 allowed values), `applied` (bool), `confidence` (float) | `evidence`, `corrected_value` | **Good for audit** |

## Affected Areas

- `backend/app/analysis/universal/objections.py` — category enum governs BI dimension; prompt boundary rules affect `current_provider` false positives
- `backend/app/analysis/universal/problem.py` — `comparison` category ambiguity; boundary rules between pain/objection/signal
- `backend/app/analysis/universal/profile_facts.py` — `lifestyle` category catches location facts that should populate `zona`
- `backend/app/analysis/universal/data_corrections.py` — `CORRECTABLE_FIELDS` registry missing `zona`, so location facts from conversations never populate the structured field
- `backend/app/summarizer.py` — merge logic (`_merge_facts_into_lead`, `_write_lead_profile_facts`); dual-write to call_analyses + lead_profile_facts
- `backend/app/analytics/service.py` — current BI queries use `json_each()` on JSON-as-TEXT columns; could use dedicated columns instead
- `backend/app/calls/models.py` — `CallAnalysis` model stores arrays as JSON-in-TEXT; per-call analysis fact tables would be an alternative
- `backend/app/leads/models.py` — `LeadProfileFact` namespace system already supports BI queries via fact_key prefixes

## Investigation Results

### Issue 1: Profile fact "Mora vive en Vicente López" stored but `zona` remains unset

**Root cause confirmed**: `zona` is NOT in `CORRECTABLE_FIELDS` (data_corrections.py). The pipeline only handles: name, phone, email, age, car_make, car_model, car_year, current_insurance. When a lead says "vivo en Vicente López", the profile_facts pipeline correctly captures it as a `lifestyle` category profile fact (stored in `lead_profile_facts` as `profile:lifestyle:{slug}`). But there is NO bridge between profile facts and structured CRM custom fields.

**The gap**: Profile facts pipeline stores unstructured text ("vive en Vicente López") in `lead_profile_facts`. The `zona` custom field in `crm.yaml` expects a clean zone value ("Vicente López"). These are two different systems with no connection:
1. Profile facts = conversational memory for the AI agent (free text, no schema)
2. Custom fields / CORRECTABLE_FIELDS = structured CRM data (validated, typed)

**Fix options**:
- **Option A**: Add `zona` to `CORRECTABLE_FIELDS` so the data corrections pipeline can extract and validate it from the transcript directly. This is the simplest and most correct path — the corrections pipeline already handles extracting structured values from free conversation.
- **Option B**: Build a "fact → structured field reconciliation" layer that post-processes profile facts and maps them to custom fields. More complex, more general, but overkill for the immediate need.

### Issue 2: Duplicate/near-duplicate signals across calls

**Root cause**: `_write_lead_profile_facts` (summarizer.py L1662-1700) uses append-only deduplication by normalized fact_key. Dedup is case-insensitive `strip().lower()`. However:
- If call 1 produces `objection:current_provider` and call 2 produces `objection:current_provider` — the second is correctly deduplicated.
- If call 1 produces `pain:comparison` and call 2 produces `pain:comparison` — also correctly deduplicated.
- **Near-duplicates** are NOT caught: `pain:cost` from call 1 and `pain:payment_or_budget` from call 2 are stored as separate facts even though they may represent the same underlying concern. This is **by design** — categories are distinct enum values and may represent genuinely different angles of a concern.
- **Cross-dimension overlap** is the real concern: a lead's dissatisfaction with their current provider could appear as `objection:current_provider` AND `pain:dissatisfaction` AND `service_issue:bad_experience` — three separate namespace entries for one underlying signal. The prompts have boundary rules but GPT doesn't always follow them perfectly.

**BI impact**: Counting "how many leads had price-related concerns" requires querying across `objection:price`, `pain:cost`, `pain:payment_or_budget`, and potentially `service_issue:billing_issue`. This is solvable at the query/reporting layer but requires understanding the cross-dimension mapping.

### Issue 3: `current_provider` objection without clear evidence

**Root cause**: The objections prompt (objections.py L128-138) has explicit boundary rules:
> "Dissatisfaction with a PREVIOUS or CURRENT provider's service that motivates the lead to SEEK alternatives — that is a pain point or service issue, not resistance to YOUR offering. Only count current_provider if the lead uses their satisfaction with the current provider as a reason to REJECT your offer."

However, GPT-4o-mini sometimes misclassifies. When a lead mentions their current insurance provider in passing (e.g., "tengo La Meridional"), the model may classify it as `current_provider` objection even when the lead isn't using provider satisfaction as rejection. The evidence field should surface this, but if evidence is weak, it's a false positive.

**BI impact**: `current_provider` objection count may be inflated. The `confidence` field exists but is rarely used for filtering in analytics queries.

### Issue 4: `comparison` appearing as pain when it may be intent/signal

**Root cause**: The problem dimension's category list (problem.py L24-36) includes `comparison` defined as "active comparison with competitors." The prompt says:
> "A pain point exists when the lead reveals a problem, dissatisfaction, fear, unmet need, or urgency that motivates their interest."

"Active comparison" is ambiguous — it could be:
- A **pain point** if the lead is frustrated by having to compare ("estoy harto de comparar precios")
- A **buying signal** if the lead is actively shopping ("estoy comparando opciones" = they're in buying mode)
- A **commitment signal** if the lead commits to compare ("voy a comparar tu propuesta con la de X")

**BI impact**: `comparison` as a pain category inflates the pain count with what may actually be positive buying intent. The category should be split or reclassified.

## Approaches

### 1. **Prompt Engineering + Category Refinement** (Recommended first step)
Tighten dimension prompts and category definitions to reduce cross-dimension overlap and false positives. No schema changes needed.

- **Objections**: Strengthen `current_provider` boundary — require explicit rejection evidence, not just mention of current provider. Add `confidence` threshold guidance in prompt.
- **Problem**: Remove or redefine `comparison` — split into `active_shopping` (buying signal, move to interests/commitments) vs `overwhelmed_by_options` (genuine pain). Or simply remove `comparison` and let the interests pipeline handle comparison intent.
- **Profile facts**: Add a boundary rule that location/zone facts should be flagged for structured capture (new category `location` or instruction to surface `zona` explicitly).
- Pros: Lowest risk, no code changes, immediately improves output quality
- Cons: GPT compliance is probabilistic; doesn't solve the structural data gap (zona)
- Effort: **Low**

### 2. **Structured Per-Call Analysis Fact Tables** (BI-optimal but large)
Replace JSON-as-TEXT array columns in `call_analyses` with dedicated relational tables:
- `call_analysis_objections` (call_analysis_id, category, strength, resolution_status, evidence, is_primary, confidence)
- `call_analysis_pain_points` (call_analysis_id, category, urgency, description, evidence, is_primary, confidence)
- `call_analysis_service_issues` (call_analysis_id, category, source, severity, evidence, confidence)
- `call_analysis_commitments` (call_analysis_id, type, owner, strength, due, evidence, confidence)

Each row is one detected item per call. Standard SQL analytics (no json_each needed).

- Pros: Fully relational, standard SQL GROUP BY/COUNT, proper indexes, clean foreign keys, trivially exportable to any BI tool
- Cons: Schema expansion (4 new tables), dual-write during transition, migration complexity, all analytics queries need rewriting
- Effort: **High**

### 3. **Hybrid: Dedicated Columns + JSON Evidence** (Recommended)
Keep the current `call_analyses` table but add dedicated normalized columns for the most queried dimensions, while preserving JSON arrays for evidence/drill-down:

**Per call_analyses row, add:**
- `primary_objection_category` (enum text, indexed) — the `is_primary` objection's category
- `primary_pain_category` (enum text, indexed) — the `is_primary` pain point's category
- `objection_count` (int) — number of objections detected
- `pain_count` (int) — number of pain points detected
- `service_issue_count` (int) — number of service issues detected
- `commitment_count` (int) — number of commitments detected
- `has_price_objection` (bool) — common BI filter
- `has_current_provider_objection` (bool) — common BI filter
- `primary_commitment_type` (enum text) — strongest commitment type

Keep existing JSON arrays for drill-down (evidence, descriptions).

**Lead-level aggregation views/materialized queries:**
- Count of calls with objection category X across the lead's history (query `call_analyses` directly)
- Strongest pain category (most frequent across calls)
- Objection persistence score (same objection repeated across N calls = stronger signal)

- Pros: Standard SQL for top BI queries, no new tables, backward compatible, JSON preserved for drill-down
- Cons: Denormalized columns need to be kept in sync during summarizer writes; limited to "most common" BI queries
- Effort: **Medium**

### 4. **Add `zona` to CORRECTABLE_FIELDS + CRM Bridge** (Tactical fix for Issue 1)
Add `zona` to the data corrections pipeline's `CORRECTABLE_FIELDS` registry so when a lead mentions their zone/neighborhood, the pipeline can:
1. Extract the zone value from the transcript
2. Validate it (non-empty string)
3. Write it to `lead_custom_fields` via the existing correction flow

This is orthogonal to the main BI redesign but solves a concrete data gap.

- Pros: Fixes the zona gap immediately, minimal code change (add 1 entry to CORRECTABLE_FIELDS dict)
- Cons: Only solves zona; other potential fact→field bridges still need manual addition
- Effort: **Low**

## Recommendation

**Phase 1: Prompt Engineering + zona fix (Approach 1 + 4)**
- Tighten dimension prompts to reduce cross-dimension false positives
- Add `zona` to CORRECTABLE_FIELDS
- Reclassify or remove `comparison` from PainPointCategory
- Add `confidence >= medium` guidance to objections prompt for `current_provider`
- This is low-risk, high-value, and validates the BI-friendliness gaps empirically

**Phase 2: Hybrid denormalized columns (Approach 3)**
- Add primary_objection_category, primary_pain_category, and count columns to call_analyses
- Update _upsert_call_analysis to populate them from the structured axis outputs
- Update analytics service to use dedicated columns instead of json_each() for top-level queries
- This gives the biggest BI improvement with moderate effort

**Phase 3 (future): Full relational fact tables (Approach 2)**
- Only if Phase 2 proves insufficient for analytics needs
- Consider when PostgreSQL migration happens (json_each → jsonb_array_elements is already a concern)

## Risks

- **GPT compliance variance**: Prompt changes improve average quality but won't eliminate all misclassification. Each GPT call is probabilistic — tighter prompts reduce but don't eliminate false positives. Must accept some noise and handle it at the BI aggregation layer.
- **Category changes break analytics history**: If `comparison` is removed from PainPointCategory, existing call_analyses rows with `comparison` pain points in their JSON will still have them. Old data needs to be interpretable under the new schema. Mitigation: never delete categories from the Literal type; add new ones and deprecate old ones.
- **Denormalized column staleness**: If Phase 2 columns are added but the summarizer has a bug that skips populating them, BI queries silently under-count. Mitigation: test coverage on _upsert_call_analysis column population.
- **zona CORRECTABLE_FIELDS expansion**: Adding zona means GPT may generate false zona corrections. The validation is currently just "non-empty string" — no zone allowlist exists. Mitigation: start with no validator (same as current_insurance), add zone validation later if false positives appear.
- **Cross-dimension counting complexity**: Even with prompt improvements, the same underlying concern can appear across dimensions. BI consumers need documentation on which dimensions to query for which business question (e.g., "price concern" = objection:price OR pain:cost).

## Ready for Proposal

**Yes** — the exploration covers all 6 investigation tasks. The codebase is well-structured for this change: the dimension module pattern makes prompt/category changes surgical, the call_analyses table is designed for column additions, and the CORRECTABLE_FIELDS registry is trivially extensible.

Recommended next step: create a proposal with the three-phase approach above, starting with prompt engineering + zona fix as the immediate deliverable, followed by hybrid denormalized columns for BI queries.
