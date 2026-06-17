# Tasks: Post-Call Analysis BI-Friendly Redesign

## Review Workload Forecast

**Answer:** implement as 3 chained PRs. Planned total is ~540-750 changed lines, under the user 800-line review threshold. Each PR remains below ~400 lines, so auto-forecast can proceed without a size exception.

| Field | Value |
|-------|-------|
| Estimated changed lines | ~540-750 total |
| User budget risk (800 lines) | Low |
| 400-line budget risk | Low per PR; High as one PR |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 |
| Delivery strategy | auto-chain / auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

## PR 1 — Phase 1+2: Zona + Dimension Prompt Refinements (~120-170 lines)

Review first: backend extraction rules and tests. No schema/UI work in this PR.

- [x] 1.1 **Test first:** Add/extend `backend/tests/test_summarizer_corrections.py` or existing corrections tests for `zona` extraction, no-zona suppression, whitespace rejection, and `applied_to_qora` label behavior. Acceptance: `zona-data-correction` scenarios.
- [x] 1.2 Add `zona` to `CORRECTABLE_FIELDS` in `backend/app/analysis/universal/data_corrections.py` with `storage_type: custom_field`, permissive non-empty validator, and inline ADR note for future config-driven registry. Depends on 1.1.
- [x] 1.3 **Test first:** Add/extend objection tests for `current_provider` contextual blocker, neutral mention rejection, and explicit rejection strength. Acceptance: `call-analysis-dimensions` objection scenarios.
- [x] 1.4 Tighten `backend/app/analysis/universal/objections.py` prompt/rules so `current_provider` fires only for contextual sales blockers. Depends on 1.3.
- [x] 1.5 **Test first:** Add/extend pain/interests tests proving comparison emits `COMPARANDO_OPCIONES`, not `pain_points.comparison`, and unknown interests emit `other`. Acceptance: comparison and NEED_TAGS scenarios.
- [x] 1.6 Update `backend/app/analysis/universal/problem.py` and `backend/app/analysis/universal/interests.py`: remove `comparison` from pain taxonomy, add NEED_TAGS allowlist/fallback, and audit vague category codes before ship. Depends on 1.5.

## PR 2 — Phase 3+4: BI Columns + Profile Facts Exclusion (~240-340 lines)

Review first: migration/backfill safety, then summarizer writes, then exclusion routing.

- [x] 2.1 **Test first:** Add migration tests for `backend/scripts/migrate_bi_columns.py`: idempotent double-run, 5 nullable columns, 2 indexes, JSON backfill correctness. Acceptance: `call-analysis-storage` denormalized column scenarios.
- [x] 2.2 Create `backend/scripts/migrate_bi_columns.py` using existing idempotent SQLite script pattern; add columns/indexes and backfill from `objections`, `pain_points`, `service_issues`. Depends on 2.1.
- [x] 2.3 **Test first:** Extend `backend/tests/unit/test_summarizer.py` for `_upsert_call_analysis()` atomic population of primary categories/counts, including empty objections. Acceptance: atomic population scenarios.
- [x] 2.4 Modify `backend/app/calls/models.py` and `backend/app/summarizer.py` to map and populate the five denormalized columns in the same transaction as JSON fields. Depends on 2.2, 2.3.
- [x] 2.5 **Test first:** Add/extend analytics service tests proving primary/count queries use indexed columns and do not require `json_each()` for new breakdowns. Acceptance: analytics service indexed-column scenario.
- [x] 2.6 Update `backend/app/analytics/service.py` to use `primary_objection_category`, `primary_pain_category`, and count columns for BI-friendly queries. Depends on 2.4, 2.5.
- [x] 2.7 **Test first:** Extend `backend/tests/unit/test_profile_facts_pipeline.py` and `backend/tests/integration/test_profile_facts_integration.py` for age, zona, vehicle, insurance, contact suppression, audit logging, and non-excluded passthrough. Acceptance: `profile-facts-exclusion` scenarios.
- [x] 2.8 Update `backend/app/analysis/universal/profile_facts.py` with `EXCLUDED_STRUCTURED_FIELDS`, prompt boundary rules, post-processing suppression, and structured `logger.info()` audit fields. Depends on 2.7.

## PR 3 — Phase 5: Labels + Call Detail Inspection UI + CRM Parity (~180-240 lines)

Review first: shared contracts (`crm_parity`, labels), then UI rendering. Do not implement CRM sync engine.

- [x] 3.1 **Test first:** Add `backend/tests/unit/test_crm_parity.py` for `unknown`, `in_sync`, `out_of_sync`, latest correction selection, and older-call non-current-state behavior. Acceptance: `crm-parity` scenarios.
- [x] 3.2 Create `backend/app/analytics/crm_parity.py` with `SyncState`, `resolve_sync_state()`, and `resolve_latest_correction()`; default unknown when CRM value is unavailable. Depends on 3.1.
- [x] 3.3 **Test first:** Add frontend tests for `resolveLabel()` known labels, fallback-to-code, and stable-code display behavior. Acceptance: `dimension-label-registry` scenarios.
- [x] 3.4 Create `frontend/src/config/dimension-labels.ts` and update `frontend/src/api/types.ts` with new call analysis fields; labels support `es`/`en` and never replace analytics codes. Depends on 3.3.
- [x] 3.5 **Test first:** Extend `frontend/src/features/leads/analysis-panel.test.tsx` or create call-analysis-panel tests for structured category/scalar/evidence rendering, separate entries, and raw per-call output. Acceptance: `call-detail-inspection-ui` dimension scenarios.
- [x] 3.6 Refactor `frontend/src/features/calls/call-analysis-panel.tsx` to show normalized variable/value rows, collapsible evidence, and raw per-call dimensions; use labels only for display. Depends on 3.4, 3.5.
- [x] 3.7 **Test first:** Extend UI tests for data corrections states: applied-only, applied+verified, unknown/null hides sync labels, unapplied pending state, and older-call no-current-sync indicator. Acceptance: CRM parity + call detail correction scenarios.
- [x] 3.8 Update `DataCorrectionsCard` in `frontend/src/features/calls/call-analysis-panel.tsx` and lead rollups in `frontend/src/features/leads/detail-page.tsx`; show `Applied to Qora` separately from CRM status and add drilldown counts. Depends on 3.2, 3.6, 3.7.

## Verification

- [ ] V.1 Run backend verification after each backend PR: `cd backend && python3 -m pytest tests/ -q`.
- [ ] V.2 Run relevant frontend test command for PR 3 using the project package script discovered during implementation.
- [ ] V.3 Confirm no `.atl` files, application implementation outside the active PR scope, or unrelated artifacts changed.
