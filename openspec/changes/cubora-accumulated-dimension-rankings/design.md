# Design: Cubora Accumulated Dimension Rankings

## Technical Approach

New `GET /api/v1/leads/{lead_id}/dimension-rollups` endpoint queries `call_analyses` with GROUP BY per dimension, returning normalized ranking lists. Frontend replaces broken `DimensionRollupsSection` with embedded ranking tables inside a renamed "Accumulated Facts" container. No new DB tables or migrations. Context preview pipeline untouched.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Rollup data source | Backend GROUP BY on `call_analyses` | Frontend aggregation (N+1), new relational tables | Single indexed query, zero migration, reuses existing normalized columns (`products`, `service_issues` JSON, `primary_objection_category`, `primary_pain_category`) |
| Endpoint granularity | Single `/dimension-rollups` endpoint returning all dimensions | Separate endpoint per dimension | One RTT, one hook, simpler cache invalidation; payload is small (lead has 1-10 calls) |
| Strength derivation | Count-based thresholds (3+=high, 2=medium, 1=low) | Per-call severity aggregation | Count thresholds are deterministic and frontend-renderable; per-call severity requires weighted logic not justified for MVP |
| Interests ranking columns | `interest`, `#`, `category` | Adding strength column | User explicitly excluded strength from interests; category (product vs need) provides useful grouping |
| Service issues ranking columns | `issue`, `#`, `strength` | Adding evidence column | User explicitly excluded evidence from ranking UI; evidence is per-call, viewable in Call Detail |
| Rollup placement | Embedded inside "Accumulated Facts" (Section C) | Separate section (current D-bis) | User requirement: rollups belong with their dimension, not as confusing standalone block |

## Data Flow

```
call_analyses (existing rows)
    │
    │ SELECT lead_id, GROUP BY dimension
    ▼
leads/router.py → /dimension-rollups endpoint
    │
    │ JSON response
    ▼
useLeadDimensionRollups hook (TanStack Query)
    │
    ▼
MemorySection (renamed "Accumulated Facts")
    ├── Profile Facts (existing, unchanged)
    ├── DetectedInterestsRanking (NEW — table: interest, #, category)
    ├── ServiceIssuesRanking (NEW — table: issue, #, strength)
    ├── Objections Rollup (moved from D-bis, fixed data source)
    ├── Pain Points Rollup (moved from D-bis, fixed data source)
    └── Interest History (existing, unchanged)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/leads/router.py` | Modify | Add `GET /{lead_id}/dimension-rollups` endpoint; new async helper `_build_dimension_rollups()` queries `call_analyses` with GROUP BY for products, service_issues, primary_objection_category, primary_pain_category |
| `frontend/src/api/types.ts` | Modify | Add `DimensionRollups` response interface with `detected_interests`, `service_issues`, `objections`, `pain_points` arrays |
| `frontend/src/api/leads.ts` | Modify | Add `fetchLeadDimensionRollups(clientId, leadId)` function |
| `frontend/src/api/hooks.ts` | Modify | Add `useLeadDimensionRollups(clientId, leadId)` TanStack Query hook |
| `frontend/src/features/leads/detail-page.tsx` | Modify | (1) Rename `MemorySection` title "Accumulated Profile Facts" → "Accumulated Facts". (2) Add `DetectedInterestsRanking` + `ServiceIssuesRanking` sub-components inside `MemorySection`. (3) Move objection/pain rollups from `DimensionRollupsSection` into `MemorySection`, sourced from new hook instead of broken `extracted_facts`. (4) Remove `DimensionRollupsSection` component + its render call in layout. (5) Remove `buildCategoryRollup` export (dead code after migration). |
| `frontend/src/config/dimension-labels.ts` | Modify | Add `IssueCategoryType` labels: `poor_attention`, `delay`, `lack_of_response`, `claim_problem`, `billing_issue`, `administrative_problem`, `communication_problem`. Add product catalog labels: `auto_todo_riesgo`, `auto_terceros_completo`, `auto_terceros`, `moto`, `hogar`, `vida`, `comercio`, `art`, `caucion`. Add need tag labels: `precio_competitivo`, `mayor_cobertura`, etc. |
| `frontend/src/features/leads/dimension-rollups.test.tsx` | Modify | Replace `buildCategoryRollup`/`DimensionRollupsSection` tests with tests for `DetectedInterestsRanking`, `ServiceIssuesRanking`, and the new hook-driven rollup rendering |

## Interfaces / Contracts

```python
# Backend response — GET /api/v1/leads/{lead_id}/dimension-rollups
{
  "detected_interests": [
    {"interest": "auto_todo_riesgo", "count": 3, "category": "product"},
    {"interest": "precio_competitivo", "count": 2, "category": "need"}
  ],
  "service_issues": [
    {"issue": "poor_attention", "count": 2, "strength": "medium"},
    {"issue": "delay", "count": 1, "strength": "low"}
  ],
  "objections": [
    {"category": "price", "count": 2},
    {"category": "current_provider", "count": 1}
  ],
  "pain_points": [
    {"category": "cost", "count": 3},
    {"category": "coverage", "count": 1}
  ]
}
# strength: "high" (count >= 3), "medium" (count == 2), "low" (count == 1)
# category for interests: "product" if in PRODUCT_CATALOG, "need" if in NEED_TAGS
# All arrays sorted by count desc
```

```typescript
// Frontend — frontend/src/api/types.ts
interface DetectedInterestRollup {
  interest: string
  count: number
  category: 'product' | 'need'
}

interface ServiceIssueRollup {
  issue: string
  count: number
  strength: 'high' | 'medium' | 'low'
}

interface CategoryRollup {
  category: string
  count: number
}

interface DimensionRollups {
  detected_interests: DetectedInterestRollup[]
  service_issues: ServiceIssueRollup[]
  objections: CategoryRollup[]
  pain_points: CategoryRollup[]
}
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `DetectedInterestsRanking` renders columns: interest, `#`, category; `ServiceIssuesRanking` renders columns: issue, `#`, strength; empty state handling | Vitest + RTL, replace existing `dimension-rollups.test.tsx` |
| Unit | Dimension label resolution for new product/issue codes | Extend `dimension-labels.test.ts` |
| Integration | `/dimension-rollups` endpoint returns correct GROUP BY counts from seeded `call_analyses` rows | pytest with async DB session, seed 3-5 `CallAnalysis` rows for one lead |
| Snapshot | "Accumulated Facts" section heading text, ranking table column headers (`#` not "mention count") | RTL snapshot or inline assertion |

## Migration / Rollout

No migration required. The endpoint queries existing `call_analyses` rows using existing indexed columns (`lead_id`, `primary_objection_category`, `primary_pain_category`). Products and service_issues are JSON TEXT columns parsed at app level — no schema change needed. Frontend changes are purely additive/replacement with no feature flag needed (rollback via `git revert`).

## Open Questions

- [x] Column headers — resolved: `#` for count columns in both rankings (user correction applied)
- [x] Strength on interests — resolved: no strength column on interests (user correction applied)
- [ ] Need tag display: should `COMPARANDO_OPCIONES` (uppercase) be normalized to lowercase in display label? Current catalog has mixed case.
