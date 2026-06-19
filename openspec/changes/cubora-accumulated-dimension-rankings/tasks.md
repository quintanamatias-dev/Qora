# Tasks: Cubora Accumulated Dimension Rankings

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 500-700 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single implementation; backend/API + frontend UI/tests together |
| Delivery strategy | single implementation OK under requested 800-line budget |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Endpoint contract, UI embedding, and regression tests | PR 1 | Single review unit; no migrations; verify backend pytest plus frontend tests |

## Phase 1: RED Tests / Contracts

- [x] 1.1 Add backend tests in `backend/tests/` for `GET /api/v1/leads/{lead_id}/dimension-rollups`: multi-call counts, single-call count=1, no analyses returns empty arrays.
- [x] 1.2 Add backend regression test proving rollups use `call_analyses` normalized fields, not `CallSession.extracted_facts`.
- [x] 1.3 Replace `frontend/src/features/leads/dimension-rollups.test.tsx` expectations with failing tests for Accumulated Facts, no `DimensionRollupsSection`, `#` headers, and no forbidden columns.
- [x] 1.4 Add/extend frontend label tests for issue, product, and need-tag labels in `frontend/src/config/dimension-labels.ts`.

## Phase 2: Backend GREEN

- [x] 2.1 Add response models/helper in `backend/app/leads/router.py` for detected interests, service issues, objections, and pain points.
- [x] 2.2 Implement `_build_dimension_rollups()` in `backend/app/leads/router.py` using existing `call_analyses` columns only; filter interests to `PRODUCT_CATALOG` / `NEED_TAGS`.
- [x] 2.3 Add `GET /{lead_id}/dimension-rollups` in `backend/app/leads/router.py`; derive service issue strength as high/medium/low from counts.
- [x] 2.4 Verify no migration files, new tables, or `ALTER TABLE` scripts are added for this change.

## Phase 3: Frontend GREEN

- [x] 3.1 Add `DimensionRollups` types in `frontend/src/api/types.ts` and `fetchLeadDimensionRollups()` in `frontend/src/api/leads.ts`.
- [x] 3.2 Add `useLeadDimensionRollups(clientId, leadId)` in `frontend/src/api/hooks.ts` with stable query key and enabled guard.
- [x] 3.3 Update `frontend/src/config/dimension-labels.ts` with normalized issue, product, and need-tag labels.
- [x] 3.4 Modify `frontend/src/features/leads/detail-page.tsx`: rename to "Accumulated Facts", keep Profile inside, embed rankings and objection/pain rollups.
- [x] 3.5 Remove `DimensionRollupsSection` render path and `buildCategoryRollup` export from `frontend/src/features/leads/detail-page.tsx`.

## Phase 4: Regression / Verification

- [x] 4.1 Add/keep context-preview regression proving `build_voice_context()`, `build_memory_context()`, `_format_accumulated_profile()`, and preview output remain unchanged.
- [x] 4.2 Run `cd backend && python3 -m pytest tests/ -q` and targeted frontend tests for lead detail and dimension labels.
- [x] 4.3 Update completed checklist only after tests pass and inspect the diff for no DB migrations.
