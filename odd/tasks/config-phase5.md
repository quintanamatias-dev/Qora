# Configuration Phase 5 — Analysis Profiles

Goal: implement `openspec/changes/analysis-profiles`. Each client gets its own versioned analysis profile (product catalog + need tags + labels), so the universal analysis stops using Quintana's hardcoded products for every client (survey critical defect #5).

Branch `feat/config-phase5` from `main` `93dea4b`. Overnight autonomous run; the user reviews in the morning. Not deployed.

## Tasks

- [x] 1. Templates (insurance, generic), profile schema, revisions model, migration 0023 (Quintana gets insurance, every other client gets generic).
- [x] 2. Profile service and API (get, put with validation, revisions, rollback, apply-template).
- [x] 3. Per-call catalog injection in the interest pipeline, skip when the catalog is empty, `call_analyses.analysis_profile_revision_id`, golden regression for Quintana.
- [ ] 4. leads and calls consumers use the client's catalog; static-import guard.
- [ ] 5. Frontend labels come from the API with a fallback to the static map (no editor UI; the admin redesign belongs to the user).
- [ ] 6. Full suites, golden regression and rollout notes.

## Evidence

- Design commit `54ee2ec` (P5-D1..D7).
- Tasks 1-2: `app/analysis/profiles/schema.py` and `templates.py` (insurance = catalog.py IDs plus labels from dimension-labels.ts; generic is empty). `ClientAnalysisProfileRevision` + `clients.active_analysis_profile_revision_id`; migration 0023 (Quintana gets insurance, the others generic); `create_client` seeds generic. The service lives in `tenants/revisions_service.py` and the API in `clients/router.py`, because the existing guard forbids fastapi and sqlalchemy imports under `app/analysis/**` (deviation from the design's paths, which is correct). Endpoints: GET/PUT `/clients/{id}/analysis-profile`, GET `/revisions`, POST `/rollback`, POST `/apply-template`. RED observed. Real-data copy: Quintana has insurance with 9 products and 10 tags. Worker full suite: 3899 passed. `call_analyses.analysis_profile_revision_id` moves to task 3.
- Task 3: the Agent-1 prompt is built per call from the catalog. An empty catalog skips Agents 1/2 (0 LLM calls); empty need tags are discarded. The summarizer resolves the catalog once and stamps `CallAnalysis.analysis_profile_revision_id` (migration 0024). Golden: Quintana's prompt is byte-identical to the capture taken BEFORE the change. Worker full suite: 3913 passed. Gaps for task 4: `seed_quintana` creates Quintana with the generic profile on a fresh DB (prod gets insurance from migration 0023); the needs validator in interests.py still uses the global NEED_TAGS.
