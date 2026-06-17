# Proposal: Post-Call Analysis BI-Friendly Redesign

> **Status**: Ready for approval
> **Phase**: Proposal
> **Change key**: `post-call-analysis-bi-friendly`

Qora's per-call analysis pipeline produces rich structured output, but several dimensions have BI-unfriendly shapes, a known data gap (`zona`), category boundary ambiguities that produce misleading cross-dimension counts, a call detail view that is visually pleasant but not inspection/BI-ready, and no parity tracking between Qora-applied corrections and CRM sync. This change tightens six areas without changing lead state mutation semantics.

---

## Intent

**Primary purpose**: Analytics. Post-call analysis exists so clients can answer reporting questions across calls, leads, agents, and time: which pain points repeat most, which objections block conversion, which agents over-detect price friction, which zones produce the most unresolved blockers. UI readability and localization are secondary concerns — they serve analytics presentation but do not drive the architecture.

**Problem**: BI/Tableau queries require `json_each()` gymnastics. `zona` is never written to structured storage. The `comparison` pain category mixes buying-intent signals with competitive-pain. `current_provider` objections are over-detected (mention ≠ rejection). The call detail view shows pretty cards but hides normalized values and evidence. Data corrections report `applied: true` (Qora-only) but display no CRM sync status — showing a fake "synced" label risks misleading users. Profile facts can duplicate structured lead fields (age as `family_context`, zona as `lifestyle`). Backend dimension codes change locale depending on client, making analytics codes unstable.

**Why now**: BI export is being requested by clients; `zona` gap causes CRM mapping failures; call detail view is the primary inspection tool for QA/support.

---

## Scope

### In Scope

- Add `zona` to `CORRECTABLE_FIELDS` in `data_corrections.py` with `custom_field` storage mapping
- Register `zona` with no validator initially (permissive: accepts any non-empty string)
- Tighten `current_provider` objection boundary: require **contextual rejection evidence** (sales blocker/traba), not mere mention and not only strong explicit rejection — see Phase 2
- Reclassify `comparison`: may be action/intent (buying signal), not objection/pain — move to `interests` or a dedicated `signals` dimension, not pain_points
- Add 5 denormalized columns to `CallAnalysis`: `primary_objection_category`, `primary_pain_category`, `objections_count`, `pain_points_count`, `service_issues_count`
- Populate those columns in `summarizer.py` `_upsert_call_analysis()`
- Analytics service: add indexed column queries (no more `json_each()` for primary/count breakdowns)
- **Call detail UX**: display per-call dimensions as structured variable/normalized values + evidence/quotes, not decorative cards
- **Data corrections labels**: show `applied_to_qora: true/false` immediately; show CRM sync status only when real field-level parity is implemented
- **Profile facts exclusion rules**: age, zona, car, current_insurance, name, phone, email must NOT become profile facts if those fields exist as structured lead/custom fields — route to data_corrections/structured storage or suppress as duplicates
- **Localization**: backend dimension/category codes remain stable English; display labels for dashboards/UI are resolved via a client-language label registry (Spanish for Spanish clients)
- **Category code quality**: if a code is too vague to support reporting (e.g. `lack_of_clarity` covers too many distinct root causes), refine the code taxonomy before shipping — do not merely translate vague codes

### Out of Scope

- Full relational fact tables (per-call normalized rows per objection/pain/signal) — deferred to Phase 3+
- PostgreSQL migration
- Confidence approval flow for data corrections (threshold stays `0.0`)
- Aggregation across agents/clients (separate analytics roadmap)
- Building the actual CRM field-level sync engine — only the label/UX parity plan is in scope now

---

## Capabilities

### New Capabilities
- `zona-data-correction`: Add `zona` to the corrections pipeline with `custom_field` storage and no validator initially
- `profile-facts-exclusion`: Routing rules to suppress structured-field duplicates from profile_facts and send them to data_corrections or discard

### Modified Capabilities
- `call-analysis-dimensions`: Tighten `current_provider` objection boundary (contextual blocker, not mention); reclassify `comparison` from pain to action/intent category; tighten interests to normalized tags, not arbitrary near-duplicates; audit and refine category codes for analytical precision
- `call-analysis-storage`: Add 5 denormalized columns to `CallAnalysis`; populate in summarizer
- `call-detail-ux`: Show per-call dimensions as normalized values + evidence, not decorative summary cards; distinguish `applied_to_qora` vs CRM-verified status
- `data-corrections-sync`: Shared logic for CRM parity across both lead-level Quote Readiness fields and call-level Data Corrections; replace ambiguous sync label with honest `applied_to_qora` label; define roadmap for real CRM parity
- `dimension-label-registry`: Stable English backend codes + client-language display label registry for UI/dashboards; analytics codes are never localized

---

## Approach

### Phase 1 — Data Corrections + zona fix (Low effort, Low risk)

Add `zona` to `CORRECTABLE_FIELDS`. Storage: `custom_field`. No validator initially (permissive). The corrections pipeline already has the plumbing; this is a registry entry only.

**`CORRECTABLE_FIELDS` — what it is and where it's going**: This registry controls which lead fields the AI is allowed to update from transcript evidence. Today it is a hardcoded list in `data_corrections.py`. The immediate change adds `zona` as a hardcoded entry. **Longer term**, `CORRECTABLE_FIELDS` should become a configurable registry driven by three sources:

| Source | Examples |
|--------|---------|
| Basic lead fields Qora can update | `zona`, `age`, `current_insurance` |
| Client CRM/CSV custom fields | any field the client's integration exposes as updatable |
| Quote/readiness required fields | fields the client expects Qora to collect or correct before a quote is ready |

The config-driven registry is Out of Scope for this change but must be called out in the design phase so the hardcoded `zona` entry does not calcify into the wrong pattern.

**Data corrections labels**: Show `Applied to Qora ✓` immediately after a correction is applied. Do NOT show a CRM sync label until real field-level CRM parity is implemented. This prevents the current misleading "synced to CRM" display when Qora has only written locally.

### Phase 2 — Prompt Engineering + Category Refinement (Low effort, Medium risk)

**`current_provider` objection (contextual sales blocker)**: The correct boundary is **contextual sales blocker (traba)**: the lead uses their current provider as a reason to **resist or slow down the sale** ("no me apuro, estoy bien con X", "recién cambié hace 6 meses", "no vale la pena, X me cubre bien"). This catches real friction without over-firing on neutral mentions.

**Why this matters for BI**: The old soft rule over-detected (any mention counted). A "strong rejection only" rule would under-detect (omits friction that doesn't reach explicit refusal). Contextual sales blockers are the useful BI signal: they predict conversion difficulty and churn risk.

**`comparison` — moved out of pain_points**: Comparison behavior (shopping around, requesting multiple quotes) is **buying intent / action**, not pain. Placing it in `pain_points` produces misleading "pain count" inflations. Correct placement: either `interests` (as a normalized tag like `COMPARANDO_OPCIONES`) or a dedicated `signals` category.

**Interests — normalized tags**: Interests currently produce arbitrary near-duplicate strings. Add a `NEED_TAGS` allowlist. Interests must emit tags from the allowlist; free-form string generation without anchoring to allowed values is suppressed.

**Category code quality audit**: Before shipping, every category code (`lack_of_clarity`, `service_quality`, `competitive_pain`, etc.) must answer the question: "Can a BI analyst write a useful GROUP BY on this code?" If the answer is "it covers too many distinct issues to be actionable," the code must be split or renamed. Vague codes are as harmful as missing codes — they silently corrupt aggregate reporting.

### Phase 3 — Denormalized Columns (Medium effort, Low risk)

Add to `call_analyses` table:

| Column | Type | Source | BI purpose |
|--------|------|--------|------------|
| `primary_objection_category` | VARCHAR | `objections[is_primary=true].category` | filter/group without JSON |
| `primary_pain_category` | VARCHAR | `pain_points[is_primary=true].category` | filter/group without JSON |
| `objections_count` | INTEGER | `len(objections)` | simple count in BI |
| `pain_points_count` | INTEGER | `len(pain_points)` | simple count in BI |
| `service_issues_count` | INTEGER | `len(service_issues)` | simple count in BI |

Populate in `_upsert_call_analysis()`. Add migration. Add indexes on `primary_objection_category`, `primary_pain_category`.

### Phase 4 — Profile Facts Exclusion Rules (Low effort, Low risk)

Add exclusion routing in `profile_facts.py`: before emitting a profile fact, check if the detected field maps to a known structured lead/custom field. If it does:
- Route to `data_corrections` (if the corrections pipeline can receive it) or structured storage
- Suppress from `profile_facts` to avoid the duplicate
- Age → `age` custom field; zona → `zona` custom field; car/vehicle → `car_make`/`car_model`; current_insurance → `current_insurance` custom field; name/phone/email → lead contact fields

Age as `family_context` fact (age=23) is a misclassification: age is a structured demographic field, not a family relationship fact. The exclusion rule prevents this category of error without requiring prompt-by-prompt fixes.

### Phase 5 — Localization / Label Registry (Medium effort, Medium risk)

Backend codes remain stable English (`active_comparison`, `competitive_pain`, `price`, `current_provider`, etc.). **Analytics codes are NEVER localized** — localized codes would break GROUP BY queries and make cross-client aggregation impossible.

A client-language label registry maps each code to a display label per client language:
```
active_comparison → ES: "Comparando opciones" | EN: "Actively comparing"
competitive_pain  → ES: "Dolor con proveedor actual" | EN: "Pain with current provider"
```

Dashboard/UI renders display labels; analytics/BI queries use backend codes. Client language is resolved at render time from the client config. Label changes never require a backend deploy.

---

## CRM Parity — Shared Logic Contract

CRM parity/sync is a **cross-cutting concern** that applies to two distinct surfaces. The logic for resolving sync status must be shared, not duplicated:

| Surface | What it tracks | Sync states |
|---------|---------------|-------------|
| **Lead-level Quote Readiness fields** | Compare current Qora custom field values with client CRM/Airtable values | `in_sync` / `out_of_sync` / `unknown` |
| **Call-level Data Corrections** | For the latest-call correction: is the resulting Qora field value now synchronized with CRM? | `in_sync` / `out_of_sync` / `unknown` |

**Rules that must be enforced**:
- Older calls (not the latest) must NOT imply current sync status — if a newer call changed the value, the older call's correction is no longer the source of truth
- The UI must never show a sync indicator when sync status is unknown or not yet tracked (`crm_sync_status: null` = show nothing, not "synced")
- `applied_to_qora` and `crm_verified` are separate states — the UI must distinguish them explicitly

---

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/analysis/universal/data_corrections.py` | Modified | Add `zona` to `CORRECTABLE_FIELDS`; honest sync label contract; note for config-driven registry |
| `backend/app/analysis/universal/objections.py` | Modified | Tighten `current_provider` to contextual sales blocker |
| `backend/app/analysis/universal/problem.py` | Modified | Remove `comparison`; reclassify to signals/interests; audit category code quality |
| `backend/app/analysis/universal/interests.py` | Modified | Normalize interests to NEED_TAGS allowlist |
| `backend/app/analysis/universal/profile_facts.py` | Modified | Add structured-field exclusion/routing rules |
| `backend/app/calls/models.py` | Modified | Add 5 denormalized columns to `CallAnalysis` |
| `backend/app/summarizer.py` | Modified | Populate denormalized columns in `_upsert_call_analysis()` |
| `backend/app/analytics/service.py` | Modified | Use indexed columns for primary/count queries |
| `backend/migrations/` | New | Alembic migration for 5 new columns |
| `frontend/` (call detail view) | Modified | Display normalized values + evidence; distinguish applied_to_qora vs crm_verified |
| `backend/app/labels/` (new or config) | New | Client-language label registry for dimension/category codes |
| `backend/app/analytics/crm_parity.py` (new or module) | New | Shared CRM parity resolution logic for lead-level and call-level surfaces |

---

## Lead-Level vs Call-Level Split

| Level | What belongs here | Storage |
|-------|-------------------|---------|
| **Call-level** | Per-call dimensions (objections, pain, signals, service issues, corrections, outcome, profile fact operations) | `call_analyses` |
| **Lead-level** | Accumulated facts, CRM mappings, custom fields (zona, car_make…), rollup counts, next-call context | `lead_profile_facts`, `lead_custom_fields`, `leads` |
| **Aggregation** | Per-lead rollups from calls; per-client/agent analytics | `analytics/service.py` queries |

Dimensions that mutate lead state (data corrections, profile facts) write to lead-level tables AND record the operation at call level. Reporting always reads from call level; state from lead level.

---

## Output Shape Examples

### `data_corrections` (after `zona` fix + honest labels)
```json
{
  "corrections": [
    {
      "field": "zona",
      "current_value": null,
      "corrected_value": "Palermo",
      "confidence": 0.92,
      "evidence": "sí, vivo en Palermo, zona norte",
      "applied_to_qora": true,
      "crm_sync_status": null
    }
  ]
}
```
`crm_sync_status: null` = not yet tracked. UI shows "Applied to Qora ✓". No fake "synced" label.

### `objections` (contextual sales blocker)
```json
{
  "objections": [
    {
      "category": "current_provider",
      "strength": "medium",
      "resolution_status": "unresolved",
      "evidence": "recién cambié hace 6 meses, no vale la pena moverme ahora",
      "is_primary": true
    }
  ]
}
```

### `signals` / `interests` (comparison reclassified)
```json
{
  "interests": [
    { "tag": "COMPARANDO_OPCIONES", "evidence": "estoy comparando precios con varias aseguradoras" }
  ]
}
```

### Denormalized call-level summary (new columns)
```json
{
  "primary_objection_category": "price",
  "primary_pain_category": "service_quality",
  "objections_count": 2,
  "pain_points_count": 2,
  "service_issues_count": 1
}
```

---

## UI / Data Inspection Requirements

**Call detail view** (per-call analysis) — in scope:
- Each dimension shows normalized category codes, strength/urgency/severity values, and resolution_status as structured fields (not decorative summary cards)
- Evidence quotes displayed inline (collapsible)
- `data_corrections` shows field → corrected_value + confidence + `Applied to Qora ✓` label
- CRM sync field displayed only if real parity is implemented; otherwise omitted — **never fake it**
- Older call corrections must not show current sync state if a newer call has since changed the field value
- Do NOT aggregate or deduplicate in this view — show raw call-level output

**Lead view** (lead-level rollups):
- Shows `COUNT(*)` of objections per category across all calls for this lead
- `zona` as a regular lead field (populated from corrections pipeline)
- Quote Readiness fields with CRM parity status (in_sync / out_of_sync / unknown) from shared parity logic
- Link/drilldown to individual call detail view for evidence

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `comparison` removal breaks existing analytics history | Medium | Never delete old category value; add migration comment; nullify for pre-change calls is optional |
| Interests NEED_TAGS allowlist too restrictive | Medium | Start with known tags + a fallback `other` tag; iterate allowlist from observed values |
| `zona` false positives | Low | Permissive (no-validator) intentional; no CRM auto-push yet; human review step |
| `current_provider` tightening drops genuine blockers | Low | Prompt tightening only; test on sample transcripts before deploy |
| Denormalized columns diverge from JSON source | Low | Populate atomically in same `_upsert_call_analysis()` transaction; add test coverage |
| Profile facts exclusion over-suppresses edge cases | Low | Suppression is category-specific; log suppressed facts for audit in Phase 4 |
| Label registry adds deployment coupling (frontend/backend) | Medium | Registry is read-only config; client language resolved at render time, no backend change per label update |
| Vague category codes silently corrupt aggregate reports | Medium | Mandatory audit before Phase 2 ship: every code must pass "useful GROUP BY" test or be split/renamed |
| Hardcoded `CORRECTABLE_FIELDS` calcifies without config roadmap | Low | Design phase must include config-driven registry stub even if not implemented yet |
| CRM parity logic duplicated across surfaces | Medium | Shared module (`crm_parity.py`) required before either surface implements sync indicators |

---

## Rollback Plan

- **Phase 1 (zona + labels)**: Remove `zona` from `CORRECTABLE_FIELDS`. No migration rollback needed. Revert label field to previous display.
- **Phase 2 (prompts)**: Revert prompt strings. Old categories remain valid in DB. No migration.
- **Phase 3 (columns)**: Drop 5 new columns via down migration. Analytics service falls back to `json_each()`. Zero data loss.
- **Phase 4 (exclusion rules)**: Revert `profile_facts.py` routing logic. No DB impact.
- **Phase 5 (label registry)**: Revert to hardcoded labels. No analytics impact.

---

## Dependencies

- No external dependencies
- Alembic migration tooling (already in use)
- Existing `lead_custom_fields` table (already used by data corrections for `age`, `car_make`, etc.)
- Frontend call detail view refactor requires design alignment before implementation
- CRM parity shared module must exist before either Quote Readiness or Data Corrections surfaces implement sync indicators

---

## Success Criteria

- [ ] `zona` populated correctly in `lead_custom_fields` for calls where lead states their location
- [ ] `current_provider` objection fires on contextual sales blockers, not bare provider mentions
- [ ] `comparison` does NOT appear in `pain_points`; appears in `interests`/`signals` instead
- [ ] Interests emit normalized tags from allowlist, not arbitrary near-duplicate strings
- [ ] Every category code passes the "useful GROUP BY" test before Phase 2 ships
- [ ] `primary_objection_category` and `primary_pain_category` queryable without `json_each()`
- [ ] BI query for "most repeated pain points across calls/leads/clients/agents" runs without JSON gymnastics
- [ ] Call detail view shows per-call dimensions with normalized values + evidence quotes (not card summaries)
- [ ] Data corrections UI shows "Applied to Qora ✓" vs "Verified in CRM" as distinct states; no CRM label when `crm_sync_status` is null
- [ ] Older call corrections do NOT show current sync state when a newer call has changed the field
- [ ] Age, zona, car, current_insurance, name, phone, email do NOT appear as profile facts when structured fields exist
- [ ] Dashboard labels are in client language; backend codes are English regardless of client
- [ ] `CORRECTABLE_FIELDS` design doc or ADR documents the config-driven registry path for future implementation

---

## Review Workload Forecast

| Phase | Files Changed | Est. Lines | PR Recommendation |
|-------|--------------|------------|-------------------|
| Phase 1 (zona + label fix) | 1–2 | ~40–60 | PR 1 with Phase 2 |
| Phase 2 (prompts + category audit + interests allowlist) | 3–4 | ~80–110 | PR 1 (combined with Phase 1) |
| Phase 3 (columns + migration + summarizer + analytics) | 4–5 | ~200–280 | PR 2 — schema change |
| Phase 4 (profile facts exclusion rules) | 1 | ~40–60 | PR 2 or PR 3 |
| Phase 5 (label registry + call detail UX + crm_parity module) | 4–6 | ~180–240 | PR 3 — UX + config + shared logic |
| **Total** | **13–18** | **~540–750** | **3 sequential PRs** |

> Total estimate ~540–750 lines. Under the 800-line budget. Auto-forecast: **3 reviewable PRs** — PR 1 (Phase 1 + Phase 2, prompt/registry/category audit, ~120–170 lines), PR 2 (Phase 3 + Phase 4, schema/storage/exclusion, ~240–340 lines), PR 3 (Phase 5, label registry + call detail UX + CRM parity module, ~180–240 lines). Monitor PR 3 — if call detail UX or CRM parity module grows past 300 lines, slice into PR 3a (backend: labels + parity module) and PR 3b (frontend: call detail view).

---

## Next Recommended Phase

→ **sdd-spec**: Write delta specs for `zona-data-correction` (new), `profile-facts-exclusion` (new), and `call-analysis-dimensions`, `call-analysis-storage`, `call-detail-ux`, `data-corrections-sync`, `dimension-label-registry` (modified). Add spec stub for `correctable-fields-registry` (future config pattern, not implemented yet).

Then → **sdd-design** for Phase 3 column migrations, Phase 4 exclusion rules, Phase 5 label registry architecture, and shared CRM parity module design.
