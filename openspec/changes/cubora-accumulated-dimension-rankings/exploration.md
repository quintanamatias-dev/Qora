# Exploration: Cubora Accumulated Dimension Rankings

## Current State

### Data Model Overview

The system has two analysis storage layers:

1. **Per-call analysis** (`call_analyses` table) — flattened columns for every dimension produced by the GPT post-call pipeline. Contains: `summary`, `interest_level`, `classification`, `objections` (JSON), `pain_points` (JSON), `service_issues` (JSON), `products` (JSON), `specific_needs` (JSON), `profile_facts` (JSON), `commitment_signals` (JSON), `misc_notes` (JSON), `data_corrections` (JSON), plus BI columns: `primary_objection_category`, `primary_pain_category`, `objections_count`, `pain_points_count`, `service_issues_count`.

2. **Lead-level accumulated data** — relational tables:
   - `lead_profile_facts` — namespaced key-value store with supersede semantics (profile:, pain:, service_issue:, signal:, buying_signal: prefixes)
   - `lead_interest_history` — append-only scalar interest_level time series
   - `Lead.extracted_facts` (JSON blob) — legacy merged facts from all calls, includes misc_notes
   - `Lead.objections_heard` — union of objection categories across calls
   - `Lead.interest_level` — latest scalar
   - `Lead.summary_last_call` — latest summary

### Frontend Layout

**Call Detail** (`call-analysis-panel.tsx`) shows 12 dimension cards:
1. Pain Points (structured — category, urgency, description, evidence, is_primary)
2. Summary + Interest Level + Classification + Outcome + Urgency + Primary Need + Next Action + Current Insurance + BI Summary
3. Objections (structured — category, strength, resolution_status, evidence, is_primary)
4. Service Issues (structured — category, source, severity, description, evidence)
5. Detected Interests (flat product IDs + need tags from `products` and `specific_needs`)
6. Commitment Signals (flat strings)
7. Profile Facts (key-value from pipeline updates)
8. Notes (structured MiscNotesAxis — type + note)
9. Data Corrections (structured with Qora/CRM sync badges)
10. Audit section (analysis_status, analyzed_at, error)

**Lead Detail** (`detail-page.tsx`) shows:
- Section A: Lead Record
- Section B: Quote Readiness Fields
- Section C: Qora Memory — "Accumulated Profile Facts" (from `lead_profile_facts` grouped by namespace) + Interest History (scalar time series) + Last call summary
- Section D-bis: Dimension Rollups (broken — reads from `CallSession.extracted_facts` but BI data lives in `call_analyses`)
- Section D: Call History
- Section E: CRM / Airtable
- Section F: Next-Call Context Preview

### Known Bugs and Gaps

#### BUG-1: Dimension Rollups data source mismatch
`DimensionRollupsSection` calls `buildCategoryRollup(sessions, 'primary_objection_category')` which reads `session.extracted_facts.primary_objection_category`. But the summarizer writes `primary_objection_category` **only** to `CallAnalysis` columns (lines 1444-1465 of `summarizer.py`), **not** into `CallSession.extracted_facts` (line 411 writes the raw `facts` dict which never includes `primary_*` keys). Result: "No dimension summary data available yet."

**Fix**: The rollup must read from `call_analyses` instead of `call_sessions.extracted_facts`. Two options:
- Option A: Backend provides a new lead-level rollup API endpoint that queries `call_analyses` with GROUP BY.
- Option B: Frontend fetches call analysis for each session and aggregates client-side (N+1, not recommended).

#### BUG-2: Profile Facts empty on Call Detail while lead-level has facts
Call Detail `ProfileFactsCard` renders `analysis.profile_facts` which is the per-call pipeline *updates* list (add/update/remove operations). This shows operations, not accumulated facts. If a call produced only `update` or `remove` operations with no new `add`, the card would show operations that look odd to operators. Meanwhile, the lead-level "Accumulated Profile Facts" in Section C shows the accumulated `lead_profile_facts` rows correctly.

The user's observation that "Call Detail Profile Facts is empty while Lead Detail has facts" is expected behavior: later calls may produce `update` operations targeting existing facts rather than new `add` operations — so the per-call profile_facts can be empty even when the lead has accumulated facts from earlier calls.

#### GAP-1: No lead-level Detected Interests accumulation
Per-call analysis stores `InterestsAxis.items[]` (product + needs + evidence + confidence) in `call_analyses.products` and `call_analyses.specific_needs`. But there is NO lead-level table to accumulate interests across calls. `lead_interest_history` only stores the scalar `interest_level` (0-100), not the detected interest items.

#### GAP-2: No lead-level Service Issues accumulation
Per-call analysis stores `ServiceIssuesAxis.issues[]` (category, source, severity, description, evidence) in `call_analyses.service_issues`. But there is NO lead-level table or roll-up for service issues. The `lead_profile_facts` table has `service_issue:` namespace prefix but only stores plain string values from the legacy `_write_lead_profile_facts` dual-write, not the structured BI-friendly categories.

#### GAP-3: Naming confusion — "Accumulated Profile Facts" vs "Profile Facts"
The lead detail page Section C header says "Accumulated Profile Facts" for what is conceptually ALL accumulated facts by namespace (profile:, pain:, service_issue:, signal:). The user wants this renamed to "Accumulated Facts" with "Profile" being one dimension inside it.

#### GAP-4: Dimension Rollups as a separate confusing section
The current `DimensionRollupsSection` attempts to show objection/pain rollups as a standalone section. The user wants roll-up behavior embedded directly into the relevant lead-level dimensions (e.g., interests ranking inside the Interests dimension, service issues ranking inside the Service Issues dimension), not as a separate confusing "Dimension Rollups" div.

## Affected Areas

### Backend
- `backend/app/calls/models.py` — CallAnalysis model (may need new denormalized columns if we add interests/service-issues BI counts)
- `backend/app/leads/models.py` — may need new lead_detected_interests or similar table
- `backend/app/summarizer.py` — `_upsert_call_analysis()` and `_merge_facts_into_lead()` write paths
- `backend/app/leads/router.py` — `_lead_to_dict()` for new lead-level fields; new rollup API endpoint
- `backend/app/memory.py` — `_format_accumulated_profile()` renders lead memory context (must NOT break)
- `backend/app/voice/context.py` — `build_voice_context()` assembles misc_notes (must NOT break)
- `backend/app/analysis/universal/interest/interests.py` — InterestsAxis schema (read-only, no changes needed)
- `backend/app/analysis/universal/service_issues.py` — ServiceIssuesAxis schema with IssueCategoryType (existing categories are the normalization tags)
- `backend/app/analysis/universal/interest/catalog.py` — PRODUCT_CATALOG and NEED_TAGS (the canonical allowlist)

### Frontend
- `frontend/src/features/leads/detail-page.tsx` — MemorySection (rename, restructure), DimensionRollupsSection (replace), new accumulated dimension components
- `frontend/src/features/calls/call-analysis-panel.tsx` — per-call Detected Interests card (currently shows flat product IDs + need tags, could be enriched later)
- `frontend/src/api/types.ts` — new Lead fields for accumulated interests/service-issues rankings
- `frontend/src/api/hooks.ts` — potential new API hook for lead-level rollups
- `frontend/src/config/dimension-labels.ts` — new labels for service issue categories
- `frontend/src/features/leads/dimension-rollups.test.tsx` — tests need updating/replacement

## Analysis Dimensions Audit

### Universal dimensions in PostCallAnalysis schema:
| Dimension | Call Detail | Lead Accumulation | Status |
|-----------|-------------|-------------------|--------|
| summary | ✅ Summary card | ✅ Lead.summary_last_call (latest) | OK — per-call context |
| interest_level | ✅ Interest bar | ✅ lead_interest_history + Lead.interest_level | OK |
| classification | ✅ Badge | ❌ Not accumulated | OK — per-call only |
| objections | ✅ Structured cards | ⚠️ Lead.objections_heard (categories only) + broken rollup | Needs fix: rollup data source |
| pain_points | ✅ Structured cards | ⚠️ Broken rollup only | Needs fix: rollup data source |
| service_issues | ✅ Structured cards | ❌ No lead-level ranking | **NEW**: count-based ranking needed |
| detected_interests | ✅ Product + need tags | ❌ No lead-level ranking | **NEW**: count-based ranking needed |
| profile_facts | ✅ Pipeline updates | ✅ lead_profile_facts by namespace | OK — rename container |
| commitments | ✅ Signal list | ❌ (call-level only, per user decision) | OK — keep per-call |
| misc_notes | ✅ Typed notes | ❌ (call-level context, per user decision) | OK — keep per-call context |
| data_corrections | ✅ Inline rows + sync | ❌ (call-level audit, applied to lead) | OK — per-call audit |
| next_action | ✅ Badge | ✅ Lead.next_action | OK |
| outcome | ✅ Classification | ❌ Not accumulated | OK — per-call |
| urgency | ✅ In summary card | ❌ Not accumulated | OK — per-call |

### Legacy/noise check:
All 12 dimension cards in Call Detail map to real PostCallAnalysis schema fields. There are no legacy ElevenLabs auto-dimensions shown — the pipeline is fully custom GPT-based. The `extra_axes_data` column exists but is not rendered in the UI (reserved for future use).

## Next Call Context Preview Audit

The Context Preview endpoint (`GET /api/v1/leads/{lead_id}/context-preview`) builds from:
1. **System prompt** — present/absent indicator (content redacted)
2. **Lead profile** — `_build_lead_profile_block(lead, custom_fields)` → structured lead fields
3. **Call history** — `build_memory_context()` → last 3 completed sessions with summaries
4. **Misc notes** — from `lead.extracted_facts["misc_notes"]` → the LATEST call's sliding-window notes (max 5)
5. **Skills index** — from `load_agent_skills(client_id, agent_slug)` → registry.yaml entries
6. **Tools** — from `build_tool_definitions(enabled_names)` → tool names list

**IMPORTANT discovery**: Misc notes in the context preview come from `Lead.extracted_facts["misc_notes"]`, which is the **merged** version (latest call's notes overwrite previous). The sliding-window pipeline (`run_misc_notes_pipeline`) receives the current notes from the lead's extracted_facts and produces a full replacement set. So the agent context always gets the LATEST pipeline output (max 5 notes), not a merge of "last two calls." The "last two calls" concept applies to **call_history** (last 3 sessions with summaries), not to misc_notes directly.

The accumulated profile facts are injected into context via `_format_accumulated_profile()` in `memory.py`, which is called during `build_voice_context()` through the PromptLoader render path. This renders profile: facts by category and interest evolution.

**No changes needed to context preview** — the user's requirement to preserve it is safe because we're only adding/fixing lead-level UI dimensions, not modifying the context assembly pipeline.

## Approaches

### Approach 1: Backend-driven lead-level rollup API (Recommended)

Create a new API endpoint `GET /api/v1/leads/{lead_id}/dimension-rollups` that queries `call_analyses` for this lead and returns:
- **Detected Interests ranking**: GROUP BY product, COUNT(*) mentions, derive strength from count thresholds. Filter out non-interest items (actions like "comprar" are already excluded by the InterestsAxis schema — it only allows catalog products).
- **Service Issues ranking**: GROUP BY category, COUNT(*) mentions, derive strength. The `IssueCategoryType` already provides 10 normalized categories (poor_attention, delay, lack_of_response, etc.) — these are the tags/normalization the user wants.
- **Objection rollup**: GROUP BY primary_objection_category, COUNT(*).
- **Pain rollup**: GROUP BY primary_pain_category, COUNT(*).

Frontend replaces `DimensionRollupsSection` with individual accumulated dimension cards inside the "Qora Memory" section (renamed to "Accumulated Facts").

- **Pros**: Single query, BI-ready, no new tables, uses existing normalized data, no N+1, clean separation of concerns, later extensible to client-wide aggregation.
- **Cons**: New API endpoint to maintain, slightly more backend work.
- **Effort**: Medium

### Approach 2: Frontend aggregation from per-call analysis data

Fetch all call analyses for the lead client-side and aggregate in the browser.

- **Pros**: No backend changes.
- **Cons**: N+1 API calls (one per session), poor performance, duplicates BI logic in frontend, not reusable for client-wide aggregation, violates the BI-friendly design philosophy.
- **Effort**: Medium but wrong direction

### Approach 3: New relational accumulation tables

Create `lead_detected_interests` and `lead_service_issues` tables with per-lead rows accumulated by the summarizer during `_merge_facts_into_lead`.

- **Pros**: True relational normalization, fastest queries, supports complex aggregation.
- **Cons**: New tables, new migration, more summarizer complexity, increases write-path risk, overkill for count-based ranking which can be derived from existing call_analyses data.
- **Effort**: High

## Recommendation

**Approach 1: Backend-driven lead-level rollup API** is the clear winner.

Rationale:
1. `call_analyses` already stores all the normalized data needed (products, service_issues with categories, primary_objection_category, primary_pain_category, counts).
2. A single GROUP BY query per dimension gives count-based rankings directly — no new tables.
3. The IssueCategoryType enum (10 categories) already provides the normalization tags the user wants for service issues deduplication.
4. Product catalog IDs are already normalized — `auto_todo_riesgo`, `moto`, etc.
5. Later client-wide aggregation is trivial: just remove the `WHERE lead_id = ?` filter.
6. No risk to context preview or existing behavior.

### Implementation Sketch

**Backend**: New endpoint `GET /api/v1/leads/{lead_id}/dimension-rollups`:
```python
# Returns:
{
  "detected_interests": [
    {"rank": 1, "interest": "auto_todo_riesgo", "mention_count": 3, "strength": "high"},
    {"rank": 2, "interest": "hogar", "mention_count": 1, "strength": "low"},
  ],
  "service_issues": [
    {"rank": 1, "issue": "poor_attention", "mention_count": 2, "strength": "medium"},
  ],
  "objections": [
    {"category": "price", "count": 2},
  ],
  "pain_points": [
    {"category": "cost", "count": 3},
  ],
}
```

Strength derivation: `high` = 3+ mentions, `medium` = 2 mentions, `low` = 1 mention (configurable thresholds).

**Frontend**:
- Rename "Accumulated Profile Facts" → "Accumulated Facts"
- Within "Accumulated Facts" section, show sub-sections: Profile (existing), Detected Interests (NEW ranking table), Service Issues (NEW ranking table)
- Remove standalone `DimensionRollupsSection`
- Add objection/pain rollup rows into "Accumulated Facts" or a separate "Analysis Rollups" sub-section
- Interests table columns: rank, interest (with dimension-label localization), mention count, strength badge
- Service issues table columns: rank, issue/tag (localized), mentions, strength badge
- No evidence column in ranking tables (evidence is per-call, viewable in Call Detail)

## Risks

1. **Migration safety**: No new DB tables in the recommended approach. The rollup endpoint queries existing `call_analyses` rows — zero migration risk.
2. **Performance**: GROUP BY on `call_analyses WHERE lead_id = ?` is indexed (`ix_call_analyses_classification` exists, lead_id is indexed). For a typical lead with 1-10 calls, this is trivially fast.
3. **Naming change**: Renaming "Accumulated Profile Facts" to "Accumulated Facts" requires test updates in `detail-page.test.tsx` and `dimension-rollups.test.tsx`.
4. **Context preview preservation**: No changes to `build_voice_context()`, `build_memory_context()`, or `_format_accumulated_profile()`. Verified safe.
5. **Service issues normalization**: The backend `IssueCategoryType` already provides 10 canonical categories. GPT is prompted with these exact categories. No additional normalization needed — the LLM is already constrained.
6. **Interests actions filter**: The `InterestsAxis` schema already constrains products to `PRODUCT_CATALOG` IDs (9 insurance products). Actions like "comprar" cannot appear as products — the catalog is a strict allowlist. Need tags are similarly constrained to `NEED_TAGS`. So the user's concern about actions appearing as interests is already handled by the existing pipeline.

## Ready for Proposal

**Yes** — The exploration is complete. All affected files identified, data model understood, approach validated against existing BI infrastructure. The recommended approach uses existing normalized data with zero new tables, fixes the Dimension Rollups data-source bug, and adds lead-level Detected Interests and Service Issues rankings.

The orchestrator should proceed to `sdd-propose` with:
- Change name: `cubora-accumulated-dimension-rankings`
- Approach: Backend rollup API endpoint + frontend restructured "Accumulated Facts" section
- Scope: 1 new backend endpoint, ~3 frontend components changed, ~1 test file replaced/updated
- Risk: Low (no new tables, no context assembly changes)
