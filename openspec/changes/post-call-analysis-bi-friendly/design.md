# Design: Post-Call Analysis BI-Friendly Redesign

## Technical Approach

Six areas tightened across backend (Python/SQLite) and frontend (React/TS) without changing lead state mutation semantics. Backend dimension codes stabilized to English; 5 denormalized columns added to `call_analyses`; profile facts exclusion routing added; shared CRM parity module created; frontend call detail view refactored from decorative cards to structured inspection tables; label registry provides client-language display labels at render time.

## Architecture Decisions

| # | Decision | Choice | Alternatives Considered | Rationale |
|---|----------|--------|------------------------|-----------|
| AD-1 | Migration approach for 5 columns | Idempotent migration script (`migrate_bi_columns.py`) using existing `add_column_if_missing` + SQLite PRAGMA pattern | Alembic (not in use in Qora) | Qora uses idempotent scripts (13 existing in `backend/scripts/`), not Alembic. Follow existing pattern. |
| AD-2 | Index type on category columns | Standard B-tree indexes on `primary_objection_category` and `primary_pain_category` via `CREATE INDEX IF NOT EXISTS` | GIN/partial indexes | SQLite only supports B-tree. Category cardinality is low (~10-20 values) — B-tree is optimal for GROUP BY/filter. |
| AD-3 | Backfill strategy for existing rows | Backfill in migration script: scan existing `call_analyses` rows, parse JSON `objections`/`pain_points`/`service_issues`, populate columns | No backfill (null for old rows) | BI queries need historical data. One-time scan is safe — `call_analyses` table is bounded by call volume. |
| AD-4 | Suppression log for profile facts exclusion | Application-level `logger.info()` with structured fields (`field`, `reason`, `call_id`) | Dedicated DB table | Suppression is QA/audit only, not user-facing. Structured logging is sufficient; a DB table adds schema for data nobody queries. Revisit if audit volume warrants it. |
| AD-5 | Label registry format | TypeScript `Record<string, Record<string, string>>` map in `frontend/src/config/dimension-labels.ts` | Backend config file, DB table | Labels are a UI-only concern (spec: "MUST NOT leak into analytics"). TS const map is tree-shakeable, type-safe, requires no backend deploy. Client language resolved from existing `analysis_language` on Client model. |
| AD-6 | CRM parity module placement | New `backend/app/analytics/crm_parity.py` returning `SyncState` enum | Inline in each surface | Spec mandates shared module. `analytics/` package already exists. Module returns `unknown` for all fields until real sync engine ships. |
| AD-7 | `CORRECTABLE_FIELDS` registry documentation | Inline code comment + ADR block in `data_corrections.py` above the registry dict | Separate ADR file | Keeps the context co-located with the code. The three-source config path is documented without creating a file nobody will find. |
| AD-8 | Denormalized column population point | Inside existing `_upsert_call_analysis()` in `summarizer.py`, deriving from already-computed `facts` dict | Separate post-processing step | Spec requires atomic population in same transaction. `_upsert_call_analysis` already sets all `ca.*` fields from `facts` — adding 5 more lines follows the established pattern exactly. |
| AD-9 | Frontend call detail refactor scope | Modify existing `ObjectionsCard`, `PainPointsCard`, `ServiceIssuesCard`, `DataCorrectionsCard` in `call-analysis-panel.tsx` to show structured fields + evidence | New component file | Components already exist and are the right abstraction boundary. Refactoring in-place keeps the component count stable and the container-presentational pattern intact. |

## Data Flow

```
Transcript
    │
    ▼
GPT Pipelines (objections, pain_points, service_issues, ...)
    │
    ▼
_upsert_call_analysis()  ──→  call_analyses table
    │                          (JSON arrays + 5 new denormalized columns)
    │                          (same transaction, atomic)
    ▼
Analytics service  ──→  Uses indexed columns for GROUP BY / COUNT
    │
    ▼
Frontend API  ──→  call-analysis-panel.tsx  ──→  dimension-labels.ts
                   (structured fields + evidence)   (code → display label)
```

Profile facts exclusion:
```
GPT profile_facts output
    │
    ▼
Exclusion check (EXCLUDED_STRUCTURED_FIELDS set)
    ├── Match → logger.info(suppressed) → discard
    └── No match → emit as ProfileFactUpdate
```

CRM parity:
```
Lead view / Call detail view
    │
    ▼
crm_parity.resolve_sync_state(field, qora_value)
    │
    └── Returns SyncState.UNKNOWN (no sync engine yet)
        → UI shows nothing (no fake "synced" label)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/scripts/migrate_bi_columns.py` | Create | Idempotent migration: add 5 columns + 2 indexes to `call_analyses`; backfill from JSON |
| `backend/app/calls/models.py` | Modify | Add 5 mapped columns + update `__table_args__` with 2 new indexes |
| `backend/app/summarizer.py` | Modify | Add 5 column assignments in `_upsert_call_analysis()` from existing `facts` dict |
| `backend/app/analytics/service.py` | Modify | Replace `json_each()` in `get_service_issues()` with `service_issues_count`; add primary category query helpers |
| `backend/app/analytics/crm_parity.py` | Create | `SyncState` enum + `resolve_sync_state()` returning `UNKNOWN`; `resolve_latest_correction()` for recency lookup |
| `backend/app/analysis/universal/profile_facts.py` | Modify | Add `EXCLUDED_STRUCTURED_FIELDS` set + exclusion check before GPT call in prompt boundary rules |
| `backend/app/analysis/universal/data_corrections.py` | Modify | Add `zona` to `CORRECTABLE_FIELDS`; add ADR comment block for config-driven registry path |
| `frontend/src/api/types.ts` | Modify | Add 5 new fields to `CallAnalysis` interface |
| `frontend/src/config/dimension-labels.ts` | Create | `Record<string, Record<string, string>>` label map (es/en); `resolveLabel()` helper |
| `frontend/src/features/calls/call-analysis-panel.tsx` | Modify | Refactor dimension cards to show `category`/`strength`/`resolution_status` + collapsible evidence; update `DataCorrectionsCard` for `applied_to_qora` vs `crm_sync_status` display |
| `frontend/src/features/leads/detail-page.tsx` | Modify | Add rollup counts with drilldown links to call detail; integrate `resolveLabel()` for display |

## Interfaces / Contracts

```python
# backend/app/analytics/crm_parity.py
from enum import Enum

class SyncState(str, Enum):
    IN_SYNC = "in_sync"
    OUT_OF_SYNC = "out_of_sync"
    UNKNOWN = "unknown"

def resolve_sync_state(
    field: str,
    qora_value: str | None,
    crm_value: str | None = None,  # None until sync engine exists
) -> SyncState:
    """Shared parity resolution for lead-level and call-level surfaces."""
    if crm_value is None:
        return SyncState.UNKNOWN
    return SyncState.IN_SYNC if str(qora_value).strip().lower() == str(crm_value).strip().lower() else SyncState.OUT_OF_SYNC

def resolve_latest_correction(
    corrections_by_call: list[dict],  # [{call_timestamp, field, corrected_value, ...}]
    field: str,
) -> dict | None:
    """Return the most recent correction for a field, or None."""
    ...
```

```typescript
// frontend/src/config/dimension-labels.ts
export type LabelLocale = 'es' | 'en'

export const DIMENSION_LABELS: Record<string, Record<LabelLocale, string>> = {
  current_provider: { es: 'Proveedor actual como traba', en: 'Resistance from current provider' },
  price: { es: 'Precio', en: 'Price' },
  service_quality: { es: 'Calidad de servicio', en: 'Service quality' },
  // ... all category codes
}

export function resolveLabel(code: string, locale: LabelLocale): string {
  return DIMENSION_LABELS[code]?.[locale] ?? code  // fallback to code
}
```

```python
# Profile facts exclusion — addition to profile_facts.py
EXCLUDED_STRUCTURED_FIELDS: set[str] = {
    "age", "zona", "car_make", "car_model", "car_year",
    "current_insurance", "name", "phone", "email",
}
# Exclusion enforced in prompt boundary rules + post-processing validation
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Denormalized column population from facts dict | Extend `test_upsert_call_analysis_*` in `test_summarizer.py` — assert 5 new columns match JSON source |
| Unit | Profile facts exclusion routing | New tests in `test_profile_facts.py` — assert excluded fields produce no updates, non-excluded pass through |
| Unit | CRM parity resolution | New `test_crm_parity.py` — assert `UNKNOWN` when no CRM value, `IN_SYNC`/`OUT_OF_SYNC` for matching/differing values |
| Unit | Label registry fallback | Jest test for `resolveLabel()` — known code returns label, unknown code returns code as-is |
| Integration | Migration script idempotency | Run `migrate_bi_columns.py` twice on test DB — assert no errors, columns exist, indexes present |
| Integration | Backfill correctness | Seed `call_analyses` rows with known JSON → run migration → assert denormalized columns match |
| Component | Call detail dimension cards | RTL tests — assert structured fields rendered (category, strength, evidence toggle), not just text blobs |

## Migration / Rollout

**Migration script** (`migrate_bi_columns.py`):
1. Add 5 nullable columns via `ALTER TABLE call_analyses ADD COLUMN ... DEFAULT NULL`
2. Create 2 indexes via `CREATE INDEX IF NOT EXISTS`
3. Backfill: `SELECT id, objections, pain_points, service_issues FROM call_analyses` → parse JSON → `UPDATE` each row

**Backfill safety**: Runs inside a single connection. Each row UPDATE is independent. If interrupted, re-run is safe (idempotent — checks existing column values).

**Rollout order**: Migration script → backend deploy (new columns populated on new calls) → frontend deploy (new UI reads new fields, falls back gracefully for missing).

**Rollback**: `ALTER TABLE call_analyses DROP COLUMN` for each of the 5 columns (SQLite 3.35+). Analytics service falls back to `json_each()`.

## Open Questions

- [ ] Exact NEED_TAGS allowlist values for interests — requires review of observed interest tags in production data before Phase 2 ships
- [ ] Category code audit results — which codes fail the "useful GROUP BY" test — requires production data analysis
