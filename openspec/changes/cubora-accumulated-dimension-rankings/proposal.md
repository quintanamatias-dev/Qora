# Proposal: Cubora Accumulated Dimension Rankings

## Intent

Lead detail (Section C / D-bis) shows stale, broken, or missing accumulated data:
- `DimensionRollupsSection` is always empty (reads `extracted_facts` but BI lives in `call_analyses`).
- No lead-level ranking exists for Detected Interests or Service Issues.
- "Accumulated Profile Facts" naming conflates the container with one dimension inside it.
- Rollup UI is a confusing standalone section instead of inline per-dimension context.

Operators need a single reliable view of what a lead has repeatedly signaled across all calls.

## Scope

### In Scope
- Fix BUG: rollup data source reads `call_analyses` instead of `CallSession.extracted_facts`.
- New backend endpoint: `GET /api/v1/leads/{lead_id}/dimension-rollups` querying `call_analyses` with GROUP BY.
- Detected Interests ranking: columns `interest`, `mention_count`, `category`. Ordered by mention count desc. No strength column. Labels normalized from `PRODUCT_CATALOG` / `NEED_TAGS` allowlists.
- Service Issues ranking: columns `issue` (normalized `IssueCategoryType` tag), `mention_count`, `strength`. Strength only here, not on interests. No evidence column in ranking.
- Rename container "Accumulated Profile Facts" → "Accumulated Facts"; "Profile" becomes one sub-dimension inside it.
- Embed rankings directly inside relevant lead dimensions; remove standalone `DimensionRollupsSection`.
- Single-call leads (e.g., Mora Santucho): rankings display current values once — no multi-call accumulation label needed.
- Preserve `Next Call Context Preview` exactly — no changes to `build_voice_context`, `build_memory_context`, or `_format_accumulated_profile`.
- Audit universal dimensions: commitment, data correction, misc notes, next action, objections, outcome, problem, profile, services, summary.

### Out of Scope
- Commitment Signals and Misc Notes accumulation (remain call-level / next-context).
- `extra_axes_data` column rendering.
- Client-wide cross-lead aggregation (future).
- New DB tables or schema migrations.

## Capabilities

### New Capabilities
- `lead-dimension-rollups`: Backend rollup API + frontend accumulated dimension ranking UI (interests + service issues embedded in Accumulated Facts).

### Modified Capabilities
- None (no existing `openspec/specs/` entries).

## Approach

Backend: new `GET /api/v1/leads/{lead_id}/dimension-rollups` endpoint. Queries `call_analyses` with `GROUP BY` per dimension. Returns normalized lists: detected interests (count ordered), service issues (count + strength from thresholds: 3+ = high, 2 = medium, 1 = low), objection/pain rollups (category + count).

Frontend: restructure Section C → "Accumulated Facts" container with sub-sections: Profile (existing), Detected Interests ranking table (NEW), Service Issues ranking table (NEW). Remove `DimensionRollupsSection`. Add `dimension-labels.ts` entries for `IssueCategoryType` tags. Update tests.

No new tables. Zero migration risk. Context preview untouched.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/leads/router.py` | New | Add `dimension-rollups` endpoint; aggregate from `call_analyses` |
| `backend/app/calls/models.py` | Read-only audit | Verify `call_analyses` indexes cover `lead_id` GROUP BY queries |
| `frontend/src/features/leads/detail-page.tsx` | Modified | Rename section, embed ranking cards, remove `DimensionRollupsSection` |
| `frontend/src/api/types.ts` | Modified | Add `DimensionRollups` response type |
| `frontend/src/api/hooks.ts` | New | `useLeadDimensionRollups` hook |
| `frontend/src/config/dimension-labels.ts` | Modified | Labels for `IssueCategoryType` normalized tags |
| `frontend/src/features/leads/dimension-rollups.test.tsx` | Modified | Update/replace for new components |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Rollup query slow on large `call_analyses` tables | Low | `lead_id` is indexed; typical lead has 1–10 calls |
| Context preview accidentally altered | Low | Explicit no-touch constraint on `build_voice_context` / `memory.py` |
| Interest label too long for UI column | Med | Labels from `PRODUCT_CATALOG` are already short IDs; map in `dimension-labels.ts` |
| Service issues freeform fallback slips through | Low | `IssueCategoryType` enum is strict; GPT is already constrained to it |

## Rollback Plan

All changes are additive or UI-only. To revert:
1. Remove/disable new `dimension-rollups` endpoint (feature-flaggable at route level).
2. Re-add `DimensionRollupsSection` from git history.
3. Revert `detail-page.tsx` section rename via `git revert` on the component commit.
No DB migrations to undo.

## Dependencies

- `IssueCategoryType` enum in `analysis/universal/service_issues.py` (read-only, already normalized).
- `PRODUCT_CATALOG` + `NEED_TAGS` in `analysis/universal/interest/catalog.py` (read-only allowlists).

## Success Criteria

- [ ] `DimensionRollupsSection` removed; objection/pain rollups display correctly inside Accumulated Facts.
- [ ] Detected Interests ranking shows `interest`, `mention_count`, `category` ordered by count desc. No strength column.
- [ ] Service Issues ranking shows normalized `IssueCategoryType` tag, `mention_count`, `strength`. No evidence column.
- [ ] Single-call lead (e.g., Mora Santucho) renders current values without errors or empty states.
- [ ] "Accumulated Profile Facts" label replaced by "Accumulated Facts" across UI and tests.
- [ ] Next Call Context Preview renders identical output before and after change (verified by snapshot/diff test).
- [ ] No new DB migrations in the changeset.
