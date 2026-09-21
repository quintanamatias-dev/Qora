# Tasks: Normalize phone numbers safely

**Delivery plan updated by explicit user choice:** implementation is approved for automatic chaining as **stacked-to-main**. This document authorizes neither commits, branches, pull requests, nor other Git mutations; those require a later explicit delivery request. Preserve the 400-line review budget without code-golf or `size:exception`.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 470–760 implementation lines (additions + deletions; excludes planning artifacts) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | Slice 1 engine/lock → Slice 2 API/CRM → Slice 3 corrections/outbound |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

**Planning accounting:** the implementation slice forecasts exclude `openspec/changes/phone-number-normalization/` planning artifacts, including this updated `tasks.md`. Measure planning/documentation changes separately at delivery; do not claim the whole aggregate diff is within 400 lines.

**Implementation tasks:** 23, all persisted complete. Each delivery slice is one cohesive, independently verifiable work unit intended to stay within 400 changed lines. No task authorizes migration, backfill, live call, deployment, commit, branch, or pull-request creation.

## Delivery slice 1 — engine and dependency lock (estimated 130–210 lines)

**Start:** no mandatory `phonenumbers` dependency and no shared normalizer.  
**End:** a locked, qualified 9.x dependency and pure explicit-region AR normalizer with focused real-library coverage.  
**Dependencies:** none.  
**Test paths:** `backend/tests/unit/phones/test_normalization.py`.  
**Rollback paths:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/phones/__init__.py`, `backend/app/phones/normalization.py`, and `backend/tests/unit/phones/test_normalization.py` together.  
**Delivery boundary:** this is the first stacked-to-main slice; it contains its dependency lock and tests, but no ingress, CRM, correction, or outbound integration.

- [x] RED: Qualify a published, non-yanked Python `phonenumbers` 9.x release supporting Python >=3.11 and prove its public NATIONAL formatter supports literal 2-, 3-, and 4-digit AR domestic-mobile fixtures; add the selected bounded dependency/lock entries and failing real-library cases in `backend/tests/unit/phones/test_normalization.py`. <!-- sdd-owner: implementation -->
- [x] GREEN: Create `backend/app/phones/__init__.py` and `backend/app/phones/normalization.py` with `normalize_phone(raw, *, region)` and safe `PhoneNormalizationError`; implement full-input ASCII grammar, explicit AR/country/type policy, E.164 equality, and formatter-based domestic `0?AC15SN` proof without a regex fallback or inferred region. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: Expand `backend/tests/unit/phones/test_normalization.py` with literal expected outputs for international mobile/fixed, 2/3/4-digit domestic areas, idempotency, non-AR/type rejection, and malformed/ambiguous/local/bare-geographic inputs; assert stable reasons and no input-bearing messages. <!-- sdd-owner: implementation -->
- [x] REFACTOR: Make policy constants and lexical/metadata helpers private and deterministic in `backend/app/phones/normalization.py`; retain no ORM, logging, network, provider, area-code table, or substring-`15` heuristic. <!-- sdd-owner: implementation -->

**Verification:** run the focused normalization tests against the locked real library; record exact results. If the public metadata round-trip cannot be proven, stop at this slice with the bounded dependency/metadata blocker.  
**Rollback outcome:** remove the lock, package, engine, and its tests as one unit; no data rewrite is involved.

## Delivery slice 2 — API ingress and CRM canonical comparison (estimated 145–240 lines)

**Start:** slice 1 engine is available, but lead creation and CRM comparison may accept formatting variants or invalid input.  
**End:** API creation stores only canonical AR values, and CRM normalizes each valid row before tenant-scoped comparison while safely skipping invalid rows.  
**Dependencies:** slice 1 must be present and its focused engine tests passing.  
**Test paths:** `backend/tests/unit/leads/test_phone_normalization.py`, `backend/tests/unit/integrations/test_crm_import.py`, `backend/tests/unit/integrations/test_field_mapping.py`, and `backend/tests/integration/integrations/test_crm_sync_service.py`.  
**Rollback paths:** `backend/app/leads/service.py`, `backend/app/leads/router.py`, `backend/app/integrations/crm_import_service.py`, `backend/app/integrations/field_mapping.py`, and the listed slice-specific tests.  
**Delivery boundary:** this stacked-to-main slice owns all intake and CRM semantics plus their tests; it excludes correction and dial-time behavior.

- [x] RED: Add failing service/router coverage in `backend/tests/unit/leads/test_phone_normalization.py` for canonical persistence, invalid/ambiguous rejection before Lead/custom-field/flush/commit, safe `{error: invalid_phone, reason}` detail, and existing client resolution before phone validity. <!-- sdd-owner: implementation -->
- [x] GREEN: Normalize with `region="AR"` in `backend/app/leads/service.py:create_lead` before model construction, and in `backend/app/leads/router.py:create_new_lead` catch only `PhoneNormalizationError` around that call and preserve all unrelated auth/client behavior. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: Extend the same lead tests with equivalent accepted spellings and non-PII error assertions using an isolated database assertion for the no-write boundary. <!-- sdd-owner: implementation -->
- [x] REFACTOR: Keep normalization ownership at the service ingress seam and narrow router exception handling so request schemas, seed data, and unrelated CRUD paths remain unchanged. <!-- sdd-owner: implementation -->
- [x] RED: Add failing cases in `backend/tests/unit/integrations/test_crm_import.py` and `backend/tests/unit/integrations/test_field_mapping.py` for pre-lookup canonical arguments, mixed-batch exact skipped counts/reasons, equivalent same-batch forms, tenant isolation, legacy-row preservation, and safe mapping failures. <!-- sdd-owner: implementation -->
- [x] GREEN: In `backend/app/integrations/crm_import_service.py:import_leads_from_crm`, normalize after reverse mapping and before `_find_lead_by_phone`; skip invalid/missing rows before lookup/savepoint/mutation, retain canonical lookup with `client_id`, and remove phone/input-bearing lookup diagnostics. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: Delegate `backend/app/integrations/field_mapping.py:normalize_phone_e164` and `_coerce_phone` to the engine with explicit AR, translate only safe `MappingError` details, and cover valid canonical push behavior without rewriting stored leads. <!-- sdd-owner: implementation -->
- [x] REFACTOR: Verify `backend/tests/integration/integrations/test_crm_sync_service.py` preserves ordinary sync lifecycle, savepoint isolation, external-ID/status/custom-field behavior, and no cross-tenant match, merge, or backfill. <!-- sdd-owner: implementation -->

**Verification:** run the listed lead and CRM tests, recording exact results; demonstrate canonical tenant-scoped matching, valid-row continuation, and no-write rejection.  
**Rollback outcome:** revert only this slice’s lead/CRM paths and tests; slice 1 remains a reusable dependency and no stored legacy values are rewritten.

## Delivery slice 3 — corrections and outbound guard (estimated 195–310 lines)

**Start:** slices 1–2 are present; correction and pre-dial paths still need the shared policy.  
**End:** every phone correction is canonical before write, and manual/scheduled dialing rejects noncanonical or invalid stored phones before session/provider side effects.  
**Dependencies:** slices 1 and 2 must be present and their focused tests passing.  
**Test paths:** `backend/tests/test_data_corrections.py`, `backend/tests/test_summarizer_corrections.py`, `backend/tests/unit/outbound/test_phone_validator.py`, existing outbound router/service guard suites, and `backend/tests/unit/scheduler/test_auto_dialer_claim.py`.  
**Rollback paths:** `backend/app/analysis/universal/data_corrections.py`, `backend/app/summarizer.py`, `backend/app/outbound/phone.py`, and the listed correction/outbound/scheduler tests.  
**Delivery boundary:** this final stacked-to-main slice includes corrections, shared pre-dial enforcement, regressions, and final implementation verification; it must remain 195–310 changed lines rather than absorbing planning artifacts.

- [x] RED: Add failing phone-specific cases in `backend/tests/test_data_corrections.py` and `backend/tests/test_summarizer_corrections.py` for canonical accepted values, ambiguous rejection, direct `applied=True` bypass, unchanged prior value, fact exclusion, and digit-free touched logs. <!-- sdd-owner: implementation -->
- [x] GREEN: Delegate `backend/app/analysis/universal/data_corrections.py:_validate_phone` and `_process_corrections` to the engine, preserving `(ok, reason)` and producing canonical `corrected_value` only for accepted phone changes. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: Revalidate phone corrections in `backend/app/summarizer.py:_apply_structured_corrections` after existing gates and before `setattr`; mark failures unapplied with a safe reason so `_merge_facts_into_lead` receives no applied invalid phone correction. <!-- sdd-owner: implementation -->
- [x] REFACTOR: Limit changed correction diagnostics to phone-specific paths, omit current/corrected digits and parser text, and preserve non-phone registry, confidence, audit, and coercion behavior. <!-- sdd-owner: implementation -->
- [x] RED: Add failing strict-validator cases in `backend/tests/unit/outbound/test_phone_validator.py` plus existing outbound router/service suites for domestic/ambiguous/foreign stored values, original-value preservation, manual 422, zero `CallSession`, and zero provider calls. <!-- sdd-owner: implementation -->
- [x] GREEN: Rewrite `backend/app/outbound/phone.py:validate_e164` to require exact ASCII canonical E.164 first, validate with explicit AR through the engine, require equality, return the original unchanged, and raise safe `ValueError` containing only E.164/reason context. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: Add a real shared-guard scheduled regression in `backend/tests/unit/scheduler/test_auto_dialer_claim.py` for invalid/ambiguous stored data: failed scheduled status, null outcome session, no provider/session, and unchanged retry behavior; keep provider/probe/network mocked. <!-- sdd-owner: implementation -->
- [x] REFACTOR: Confirm existing `backend/app/outbound/router.py`, `backend/app/outbound/service.py`, and `backend/app/scheduler/service.py` guard ordering remains unchanged: invalid phone is before lock/session/provider, while auth/ownership/cooldown/flags/consent/concurrency/retry precedence is preserved. <!-- sdd-owner: implementation -->
- [x] Run `cd backend && python3 -m pytest -q` with the focused normalization, lead, CRM, correction, outbound, and scheduler test targets; record exact results and any intentionally unrun integration requirement without claiming a run that did not occur. <!-- sdd-owner: implementation -->
- [x] Re-read `openspec/changes/phone-number-normalization/specs/phone-number-normalization/spec.md` and `openspec/changes/phone-number-normalization/specs/outbound-call-trigger/spec.md` against the completed behaviors; confirm no schema/UI/flag/backfill/provider/retry scope was added and no source/spec artifact was broadened. <!-- sdd-owner: implementation -->
- [x] Measure additions plus deletions for each implementation slice, including lock and test changes, before any later delivery request; retain the 195–310 slice-3 estimate and report planning artifacts separately rather than claiming the aggregate diff is within 400 lines. <!-- sdd-owner: implementation -->

**Verification:** run the listed correction, outbound, scheduler, and full backend test targets with mocked providers; record exact results and explicitly identify any unrun requirement. Confirm rejected candidates do not change a lead, facts, `CallSession`, provider-call count, or retry behavior.  
**Rollback outcome:** revert only correction and outbound guard paths plus their tests; retain fail-closed dialing and do not reintroduce an optional import or permissive regex fallback. If a safe rollback cannot preserve that property, stop for operator direction.
