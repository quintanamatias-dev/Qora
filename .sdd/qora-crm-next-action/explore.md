# Exploration: CRM Next Action Column (Issue #27)

## Executive Summary

Issue #27 replaces the Interest% column in the **existing** React CRM lead table (`frontend/src/features/leads/lead-table.tsx`) with a Next Action column. The lead table already exists as a fully functional presentational component with integration tests. The backend already returns `next_action`, `next_action_at`, `do_not_call`, and `status` on every Lead response. However, the **scheduled call time** (`scheduled_at`) lives in the `scheduled_calls` table, NOT on the Lead model — so the backend list endpoint needs enrichment to include the next pending call's `scheduled_at`.

## Current State

### Frontend Lead Table (`lead-table.tsx`, 98 lines)
- Presentational component, container-presentational pattern
- Columns: Name | Phone | Status (Badge) | Calls | Last Called | **Interest** (percentage)
- Uses `formatInterestLevel(lead.interest_level)` → "X%" or "—"
- Container: `page.tsx` → `useLeads(clientId)` → `fetchLeads()` → `GET /api/v1/leads?client_id=X`

### Frontend Types (`api/types.ts`)
- `Lead` interface already has: `status`, `do_not_call`, `next_action`, `next_action_at`, `interest_level`, `call_count`
- `LeadStatus = 'new' | 'called' | 'interested' | 'not_interested' | 'follow_up'`

### Badge Component (`design/components/badge.tsx`)
- Variants: `success` (green), `active` (secondary), `neutral` (gray), `error` (red), `warning` (yellow)
- Lead-specific: `new`, `called`, `interested`, `not_interested`, `follow_up`

### Backend Lead Model (`leads/models.py`)
- `next_action: str | None` — AI-suggested text ("call_again", "send_quote", "wait", "do_not_call")
- `next_action_at: datetime | None` — **NEVER populated** by the summarizer (always null)
- `do_not_call: bool` — set True when AI suggests "do_not_call"
- `status: str` — LeadStatus enum

### Backend ScheduledCall Model (`scheduler/models.py`)
- `scheduled_at: datetime` — actual next call time
- `status: str` — pending/in_progress/completed/failed/cancelled/expired
- `lead_id: str` — FK to leads
- Index: `ix_scheduled_calls_lead_status` on (lead_id, status)

### Backend Leads Router (`leads/router.py`)
- `_lead_to_dict()` already serializes `next_action`, `next_action_at`, `do_not_call`
- `list_leads()` returns `[_lead_to_dict(lead) for lead in leads]` — NO join with scheduled_calls

### Key Gap
`Lead.next_action_at` is NEVER set. The summarizer only sets `Lead.next_action` (a string). The actual scheduled time is `ScheduledCall.scheduled_at`. To show "En 2h" or "Mañana 10:00", we need `scheduled_at` from the pending ScheduledCall for each lead.

### Existing Helper
`scheduler/service.py` → `get_active_scheduled_call_for_lead(db, client_id, lead_id)` returns the pending/in_progress ScheduledCall for a lead. But calling this N times = N+1 problem. Need batch query.

## Affected Areas

### Must Change
| File | Why |
|------|-----|
| `backend/app/leads/router.py` | `_lead_to_dict()` + `list_leads()` — add `next_scheduled_call_at` from scheduled_calls batch query |
| `frontend/src/api/types.ts` | Add `next_scheduled_call_at: string \| null` to Lead interface |
| `frontend/src/features/leads/lead-table.tsx` | Replace Interest column with Next Action column |
| `frontend/src/design/components/badge.tsx` | May need `info` badge variant (blue) for scheduled calls |
| `frontend/tests/mocks/handlers.ts` | Update fixtures with `next_scheduled_call_at` |
| `frontend/src/features/leads/page.test.tsx` | Update tests (currently test "75%" interest display) |
| `frontend/src/api/leads.test.ts` | Update fixture with new field |
| `backend/tests/unit/leads/test_router.py` | Add tests for `next_scheduled_call_at` enrichment |

### May Change
| File | Why |
|------|-----|
| `frontend/src/features/leads/detail-page.tsx` | Already shows Interest Level — confirm it stays there |

### Should NOT Change
| File | Why |
|------|-----|
| `backend/app/leads/models.py` | No schema changes needed |
| `backend/app/leads/service.py` | Business logic unchanged |
| `backend/app/scheduler/models.py` | Model already has what we need |

## Approaches

### Approach A: Backend Enrichment (Recommended)

Modify `list_leads()` and `get_lead_by_id()` to batch-query pending ScheduledCalls and add `next_scheduled_call_at` to the response.

**Backend:**
1. In `leads/router.py` `list_leads()`: after fetching leads, batch-query `scheduled_calls` for all lead_ids with status IN ('pending', 'in_progress')
2. Build `{lead_id: scheduled_at}` lookup
3. Pass to `_lead_to_dict()` (or new helper) to add `next_scheduled_call_at`

```sql
SELECT lead_id, MIN(scheduled_at) 
FROM scheduled_calls 
WHERE lead_id IN (:lead_ids) AND status IN ('pending', 'in_progress')
GROUP BY lead_id
```

**Frontend:**
1. Add `next_scheduled_call_at: string | null` to `Lead` type
2. Replace Interest column with Next Action in `lead-table.tsx`
3. Add `deriveNextAction()` + `formatRelativeTime()` helpers
4. Badge color mapping: blue→scheduled, red→closed, yellow→sin agenda, gray→pendiente

**Pros:** Clean, single source of truth, batch query (no N+1), all display logic in frontend  
**Cons:** Backend change required, need backend test updates  
**Effort:** Medium

### Approach B: Frontend Separate Query

Keep leads endpoint as-is, add separate `/api/v1/scheduler/queue?client_id=X&status=pending` call from frontend and join client-side.

**Pros:** No backend changes  
**Cons:** Two queries, client-side join, can't sort by next action, more complex  
**Effort:** Medium (worse architecture)

### Approach C: Use Lead.next_action_at (WRONG)

Populate `Lead.next_action_at` in the summarizer.

**Pros:** No new fields  
**Cons:** This field is never set, would duplicate ScheduledCall.scheduled_at, creates data inconsistency  
**Effort:** High

## Recommendation

**Approach A: Backend Enrichment.**

### Next Action Display Logic
```typescript
function deriveNextAction(lead: Lead): { label: string; badge: BadgeStatus } {
  // Priority 1: Closed (not_interested or do_not_call)
  if (lead.status === 'not_interested' || lead.do_not_call)
    return { label: "Cerrado", badge: "error" }

  // Priority 2: Has scheduled call
  if (lead.next_scheduled_call_at)
    return { label: formatRelativeTime(lead.next_scheduled_call_at), badge: "active" }

  // Priority 3: Contacted but no schedule
  if (lead.call_count > 0)
    return { label: "Sin agenda", badge: "warning" }

  // Priority 4: New, never contacted
  return { label: "Pendiente", badge: "neutral" }
}
```

### Badge Variant Check
- `error` (red) → "Cerrado" ✅ exists
- `warning` (yellow) → "Sin agenda" ✅ exists
- `neutral` (gray) → "Pendiente" ✅ exists
- `active` (secondary/20) → scheduled call — need to verify it looks "blue". If not, add `info` variant.

## Risks

1. **N+1 query risk**: Must batch-query scheduled_calls, NOT call per-lead. Use `WHERE lead_id IN (...)`.
2. **Badge "blue" color**: `active` uses `bg-secondary/20 text-secondary`. Need to verify it reads as "blue" in the Sovereign Interface palette. May need `info` variant.
3. **Relative time formatting**: "En 2h", "Mañana 10:00" requires timezone-aware formatting. Frontend receives UTC ISO strings. Need `Intl.RelativeTimeFormat` or custom utility. Edge cases: past dates (overdue), same day vs. next day.
4. **Test updates**: 6+ test files reference `interest_level` in fixtures/assertions. All need updating.
5. **Interest% in detail page**: Already shown in `detail-page.tsx`. Confirm it stays there — only removed from the list table column.

## Ready for Proposal

Yes — exploration complete. Approach A (backend enrichment) is clear, all affected files identified, risks documented. Ready to proceed: proposal → spec → design → tasks → apply.
