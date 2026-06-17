# Apply Progress: post-call-analysis-bi-friendly

## Status

25/25 tasks complete.

## Work Units

| PR | Scope | Commit | Status |
|----|-------|--------|--------|
| PR 1 | Zona correction + dimension prompt/category refinements | `36197e0` | Complete |
| PR 2 | BI columns + profile facts exclusion | `97c297e` | Complete |
| PR 3 | Labels + call detail inspection UI + CRM parity | `35add23` | Complete |

## TDD Cycle Evidence

| Task group | Test files | RED | GREEN | Triangulation |
|------------|------------|-----|-------|---------------|
| PR 1 — zona correction | `test_zona_data_correction.py`, `test_data_corrections_custom_fields.py` | New failing registry/persistence tests written before implementation | Backend suite passed | Covered no-zona, whitespace rejection, `zona sur`, and summarizer → `lead_custom_fields` persistence |
| PR 1 — objection/category refinements | `test_objections_contextual_blocker.py`, `test_comparison_and_need_tags.py`, `test_interest_need_tags_validation.py` | Prompt/category contract and need-tag validation failures confirmed | Backend suite passed | Covered neutral provider mention, contextual blocker, comparison removal, `COMPARANDO_OPCIONES`, and invalid tag → `other` |
| PR 2 — BI columns/storage | `test_bi_columns_migration.py`, `test_summarizer_bi_columns.py`, `test_analytics_indexed_columns.py` | Migration/model/analytics tests written before implementation | Backend suite passed | Covered true old-schema migration, idempotency, backfill, primary objection/pain breakdowns, service issue totals |
| PR 2 — profile facts exclusion | `test_profile_facts_exclusion.py` | Structured-field suppression tests written before implementation | Backend suite passed | Covered age, zona, vehicle, current insurance, contact fields, non-excluded passthrough, and audit call_id logging |
| PR 3 — CRM parity | `test_crm_parity.py` | New parity contract tests written before implementation | Backend suite passed | Covered unknown/in_sync/out_of_sync, latest correction selection, stale/older-call behavior |
| PR 3 — label registry | `dimension-labels.test.ts` | Label lookup tests written before implementation | Frontend suite passed | Covered `es`/`en`, stable English keys, fallback-to-code, locale completeness |
| PR 3 — call detail inspection UI | `call-analysis-panel.test.tsx`, `dimension-rollups.test.tsx` | Component behavior tests written before/refactoring UI | Frontend suite/build passed | Covered structured objections, service issues, interests, data corrections states, stale correction wording, rollup counts/fallback/drilldowns |

## Verification Evidence

| Command | Result |
|---------|--------|
| `cd backend && python3 -m pytest tests/ -q` | 2264 passed |
| `cd frontend && npm test` | 644 passed |
| `cd frontend && npm run build` | Passed |
| `cd frontend && npm run lint` | Passed |

## Notes

- Migration approach intentionally follows Qora's existing idempotent SQLite script pattern, not Alembic.
- `lack_of_clarity` category audit outcome: keep for now because it remains a useful GROUP BY for broad clarity gaps; future analytics can split it if real call volume shows ambiguous clustering.
- CRM parity intentionally defaults to `unknown` unless the current CRM value is available; no fake sync labels are emitted.
