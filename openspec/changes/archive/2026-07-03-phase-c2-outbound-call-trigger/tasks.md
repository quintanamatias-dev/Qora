# Tasks: Phase C2 — Outbound Call Trigger

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 650-780 |
| 400-line budget risk | High |
| 800-line session budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | WU1 backend foundation → WU2 status/reconciliation → WU3 frontend/docs |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High
800-line session budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR/commit | Notes |
|------|------|------------------|-------|
| WU1 | Backend trigger foundation | PR 1 / commit 1 | Migration, models, config, validator, ElevenLabs client, endpoint tests. |
| WU2 | Evidence and status safety | PR 2 / commit 2 | Correlation, FAS-safe status, retry classification, timeout sweep tests. |
| WU3 | Operator UX and docs | PR 3 / commit 3 | Leads button, API client, UI tests, docs/test protocol. |

## Phase 1: RED Tests and Foundation

- [x] 1.1 RED: add backend tests for flag-off, auth, invalid phone, concurrency, pre-dial `CallSession`, retry/no-retry, and "no live calls" mocks.
- [x] 1.2 Create Alembic migration for `agents.elevenlabs_phone_number_id` and nullable `call_sessions` telephony metadata/status columns.
- [x] 1.3 Update `backend/app/tenants/models.py`, `backend/app/calls/models.py`, `backend/app/agents/schemas.py`, `backend/app/core/config.py`, and `.env.example`.
- [x] 1.4 Add phone validation helper using `phonenumbers` or a strict E.164 fallback; document tradeoff in code/tests, not as a blocker.

## Phase 2: Backend Dialing Core

- [x] 2.1 Add `OutboundCallRequest`/`OutboundCallResult` in `backend/app/elevenlabs/models.py` with validation tests.
- [x] 2.2 Add `ElevenLabsService.initiate_outbound_call()` in `backend/app/elevenlabs/service.py`; mock HTTP only in automated tests.
- [x] 2.3 Extract reusable `build_dynamic_variables()` from `backend/app/voice/initiation.py` and preserve existing initiation output.
- [x] 2.4 Create `backend/app/outbound/service.py` with `dial_outbound_call()` as the only dialing entry point, including failure classification and one transient retry.
- [x] 2.5 Create/wire `backend/app/outbound/router.py` for `POST /api/v1/clients/{client_id}/leads/{lead_id}/call` with admin auth, flag, validator, and concurrency guard.

## WU1 Fix Batch (Review Remediation — 2026-07-02)

- [x] FIX-CRITICAL-1: Remove `server_default="elevenlabs"` from migration telephony_provider; add migration contract tests.
- [x] FIX-CRITICAL-2: Strengthen dial_outbound_call behavioral tests (flush-before-dispatch, all outcome paths, provider call counts, retry boundaries). Added test_dial_service_behavior.py.
- [x] FIX-CRITICAL-3: Add per-lead asyncio.Lock for TOCTOU-safe concurrency guard. Added test_concurrency_guard.py.
- [x] FIX-WARNING-4: Add ScheduledCall in_progress overlap guard + test_scheduled_call_guard.py.
- [x] FIX-WARNING-5: Replace raw provider_metadata with safe allowlist (_extract_safe_provider_metadata). Added test_provider_metadata_safety.py.
- [x] FIX-WARNING-6: Add 10s cooldown guard in router (_should_cooldown_reject / _record_call_attempt). Added test_cooldown_guard.py.
- [x] FIX-WARNING-7: Replace weak no-live-call test with respx + network-blocking assertions. Added test_no_live_calls.py.
- [x] FIX-WARNING-8: Add auth regression tests (real require_api_key, no bypass). Added test_auth_regression.py.

## WU1 Fix Batch — Re-review Round 2 (2026-07-02)

- [x] REREVIEW-CRITICAL-B1: Manual trigger must check in_progress ScheduledCall (spec says ALL triggers, not just scheduled). Updated `_find_in_progress_scheduled_call` call to run unconditionally; replaced wrong test in test_scheduled_call_guard.py that asserted manual triggers bypass the guard.
- [x] REREVIEW-CRITICAL-B2: Lock held through full critical section (CallSession creation + provider API call + commit), not released after flush. Restructured `async with lead_lock` block to cover Steps 4-9. Updated test_concurrency_guard.py mock to match new 2-SELECT-per-path pattern.
- [x] REREVIEW-CRITICAL-B3: Added `billed_duration_seconds` to `_SAFE_PROVIDER_METADATA_FIELDS` allowlist; spec says "cost and billed_duration_seconds stored without transformation". Added tests in test_rereview_blockers.py.
- [x] REREVIEW-WARNING-B4: Added explicit guard for missing `agent.elevenlabs_phone_number_id` before OutboundCallRequest construction. Returns controlled DialResult(status='failed') instead of propagating Pydantic ValidationError. Added tests in test_rereview_blockers.py.

## WU1 Fix Batch — Final Re-review Round 3 (2026-07-02)

- [x] FINAL-CRITICAL-1: Router maps ScheduledCall-overlap DialResult to HTTP 200 → fixed to HTTP 409. Added `failure_code: str | None = None` field to `DialResult` dataclass. Service sets structured codes: `concurrent_active_session`, `concurrent_scheduled_call`, `flag_off`, `invalid_phone`, `agent_not_configured`. Router maps `concurrent_active_session` and `concurrent_scheduled_call` failure codes to HTTP 409 using `_CONCURRENT_GUARD_CODES` set (no string matching). Added 4 router tests + 2 DialResult unit tests + 2 service tests in test_final_rereview_blockers.py.
- [x] FINAL-CRITICAL-2: Pre-dial CallSession flushed but not durably committed before provider API call. Fixed service.py: added `await db.commit()` after `await db.flush()` for the pre-dial record; then `await db.refresh(call_session)` to reload attributes expired by SQLAlchemy after commit. Post-provider result is committed in a second commit (two-commit flow). Added 4 persistence tests in test_final_rereview_blockers.py proving commit before dispatch and all fields persisted.
- [x] FINAL-SUGGESTION-3: Stale comment `# Raw provider response JSON: cost, billed_duration_seconds, etc.` in migration updated to say safe/allowlisted metadata with explicit list of permitted fields and rationale.

## WU1 Fix Batch — Round 4 (2026-07-02)

- [x] ROUND4-CRITICAL-1: Missing `agent.elevenlabs_agent_id` guard before pre-dial commit.
  Problem: `elevenlabs_agent_id` is nullable on `Agent`. With the two-commit flow, a dialing
  `CallSession` was durably committed BEFORE `OutboundCallRequest` construction — which raises
  `Pydantic.ValidationError` when `agent_id=None`, leaving a dangling `telephony_status='dialing'`
  session with no corresponding provider call.
  Fix: Added Guard 2b-i for `agent.elevenlabs_agent_id` BEFORE Guard 3 (before the lock, before
  `db.commit()`). Returns `DialResult(status='failed', failure_code='agent_not_configured', ...)`.
  The existing `elevenlabs_phone_number_id` guard was renamed Guard 2b-ii; both are in the
  pre-lock, pre-commit section. `OutboundCallRequest` now uses pre-validated local vars
  (`agent_elevenlabs_id`, `agent_phone_number_id`) — no None can reach Pydantic.
  Tests: 4 tests in `tests/unit/outbound/test_agent_id_guard.py`:
    - `test_missing_elevenlabs_agent_id_returns_controlled_failure_no_dangling_session`
    - `test_missing_elevenlabs_agent_id_no_dangling_commit_even_with_valid_phone_number_id`
    - `test_configured_agent_id_proceeds_normally`
    - `test_missing_agent_id_does_not_override_phone_number_id_guard`

- [x] ROUND4-WARNING-1: Artifact wording drift — spec/design/tasks/elevenlabs models said
  "raw provider response JSON" instead of "safe/allowlisted provider metadata".
  Fix: Updated wording in:
    - `specs/outbound-call-trigger/spec.md` — "Successful API response persisted" scenario
    - `design.md` — data flow comment
    - `tasks.md` — Phase 3 task 3.2
    - `backend/app/elevenlabs/models.py` — `OutboundCallResult.provider_metadata` docstring
  Implementation is unchanged — `_extract_safe_provider_metadata()` was already correct.

- [x] ROUND4-WARNING-2 (documented, not implemented): In-process `asyncio.Lock` is single-
  process MVP only. Multi-worker / multi-instance deployments require Redis distributed lock
  or DB-level idempotency key before production. Documented in service.py comments (Guard 3
  block) and in this tasks entry. No implementation change needed for WU1.

## Phase 3: Correlation and Reconciliation

- [x] 3.1 Update webhook/session linkage to store `elevenlabs_conversation_id` only from webhook evidence and never mark `completed` from provider SIP state alone.
- [x] 3.2 Persist `provider_call_id`, safe/allowlisted provider metadata (permitted fields: `call_id`, `status`, `duration_seconds`, `billed_duration_seconds`, `cost`, `message`), cost/billed seconds when present, and FAS-safe evidence fields on `CallSession`.
- [x] 3.3 Add timeout sweep for old `in_call` sessions to mark `stale_in_call` or operator-review status with regression tests.

## WU2 Batch (Status/Reconciliation — 2026-07-03)

- [x] WU2-3.1: `backend/app/outbound/linkage.py` — `link_outbound_session_by_webhook()` with two-path lookup (conversation_id primary, provider_call_id fallback). `update_telephony_status_on_session_end()` helper integrated into `calls/service.py` `close_session()` and `_reconcile_session()`. 7 unit tests (test_wu2_fas_safe_linkage.py).
- [x] WU2-3.2: WU1 already persists `provider_call_id` + safe metadata from API response. WU2 adds `update_telephony_status_on_session_end()` to sync telephony_status on session-end webhook — 5 unit tests (test_wu2_close_session_linkage.py). FAS contract: `completed` only via webhook evidence.
- [x] WU2-3.3: `backend/app/outbound/sweep.py` — `sweep_stale_outbound_sessions()` + `stale_outbound_telephony_sweeper()` background loop. 30-min ceiling; no-webhook-evidence → `stale_in_call`; with-evidence → `completed`. Registered in `main.py` lifespan (flag-guarded). 9 unit tests (test_wu2_stale_sweep.py).

## WU2 Fix Batch (Review Blocker Remediation — 2026-07-03)

- [x] WU2-FIX-B1: `provider_call_id` fallback wired to real webhook routes. Added `provider_call_id: str | None` to both `ElevenLabsPostCallPayload` and `EndSessionRequest` schemas. The `elevenlabs-postcall` route now passes `provider_call_id` to `link_outbound_session_by_webhook()` when the session is not found by `conversation_id` (first-time linkage path). 5 tests in `test_wu2_review_blockers.py::TestB1*`.
- [x] WU2-FIX-B2: Linkage lookups scoped by `client_id` and `telephony_status IS NOT NULL`. `_find_by_conversation_id()` and `_find_by_provider_call_id()` now accept an optional `client_id` param and add `WHERE client_id = :cid` and `WHERE telephony_status IS NOT NULL` predicates. `link_outbound_session_by_webhook()` accepts and propagates `client_id`. Cross-tenant collision test added. 4 tests in `TestB2*`.
- [x] WU2-FIX-B3: `POST /calls/elevenlabs-postcall` now enforces `require_webhook_secret` via `dependencies=[Depends(require_webhook_secret)]`. When `QORA_WEBHOOK_AUTH_ENABLED=true`, missing or invalid `X-Webhook-Secret` returns 401 before any session mutation. `link_outbound_session_by_webhook` also imported at module level for testability. 5 tests in `TestB3*`.
- [x] WU2-FIX-B4: Sweep completion evidence fixed. Added `call_sessions.session_end_received` Boolean column (migration `20260703_0005`). `link_outbound_session_by_webhook()` and `update_telephony_status_on_session_end()` now set `session_end_received=True`. `sweep_stale_outbound_sessions()` now checks `session_end_received` instead of `elevenlabs_conversation_id IS NOT NULL`. Model updated; old sweep test helper updated to explicitly set `session_end_received=False`. 5 tests in `TestB4*` (plus updated `test_wu2_stale_sweep.py`).
- [x] WU2-FIX-B5: Route-level and sweep integration behavior tests. JSON roundtrip tests for `provider_call_id` in both schema classes. Comprehensive 3-session sweep evidence contract test (`stale_with_end → completed`, `conv_only → stale_in_call`, `no_evidence → stale_in_call`). 3 tests in `TestB5*`. Migration contract tests updated to include `20260703_0005` in `_KNOWN_REVISIONS`.

## WU2 Re-Review Fix Batch (Second R1/R4 Pass — 2026-07-03)

- [x] WU2-RE1: CRITICAL reliability — `/calls/{conversation_id}/end` route now uses
  `body.provider_call_id` for outbound linkage fallback when `close_session()` raises
  ValueError (conversation_id not found). If `link_outbound_session_by_webhook()` finds
  a session by provider_call_id, returns 200 with the linked session instead of 404.
  Without provider_call_id or when linkage also fails → still 404 (correct).
  4 tests in `test_wu2_rereview_blockers.py::TestRE1*`.

- [x] WU2-RE2: CRITICAL risk — `POST /calls/elevenlabs-postcall` now requires `client_id`
  in the payload before attempting `provider_call_id` fallback linkage. Without client_id,
  the fallback is skipped entirely (safe no-match over cross-tenant linkage risk).
  Added `client_id: str | None = None` to `ElevenLabsPostCallPayload` schema.
  Route passes `client_id` to `link_outbound_session_by_webhook()`.
  Updated `TestB1*` in `test_wu2_review_blockers.py` to include client_id.
  4 tests in `test_wu2_rereview_blockers.py::TestRE2*`.

- [x] WU2-RE3: WARNING deployment auth — Added `Settings.outbound_without_webhook_auth_warning`
  property (True when `enable_outbound_calls=True AND NOT qora_webhook_auth_enabled`).
  Added inline config comment documenting the production requirement to set both
  `QORA_WEBHOOK_AUTH_ENABLED=true` and `QORA_WEBHOOK_SECRET` before enabling outbound.
  Does NOT fail startup (backward compat) — surfaces as structured WARNING at lifespan.
  3 tests in `test_wu2_rereview_blockers.py::TestRE3*`.

- [x] WU2-RE4: WARNING metadata — Removed `message` from `_SAFE_PROVIDER_METADATA_FIELDS`.
  Free-form provider messages may contain PII (phone numbers, caller names, SIP addresses).
  Prefer not persisting free-form provider text. Updated spec.md permitted-fields list.
  Updated `test_provider_metadata_safety.py` tests (2 assertions updated to reflect removal).
  4 tests in `test_wu2_rereview_blockers.py::TestRE4*`.

## Phase 4: Frontend Operator UX

- [x] 4.1 Add `triggerCall(clientId, leadId)` and `CallTriggerResponse` in `frontend/src/api/leads.ts` and `frontend/src/api/types.ts`.
- [x] 4.2 Add green "Call Now" button after `next_action` in `frontend/src/features/leads/lead-table.tsx` with confirmation, loading, "Calling…" badge, and error states.
- [x] 4.3 RED/GREEN Vitest tests for button placement, confirmation, success badge, and 403/409/422/429 error feedback.

## Phase 5: Verification and Docs

- [x] 5.1 Run backend pytest with ElevenLabs mocked; prove no automated test can place a real call.
  - Result: 2900 passed, 1 known pre-existing failure (`test_demo_session_end_is_scoped_to_demo_client` — RuntimeError: Database not initialized). All ElevenLabs calls mocked via respx + network-blocking assertions. Zero live calls in any test.
- [x] 5.2 Run frontend tests and one manual flag-off API smoke test proving no `CallSession` or provider call occurs.
  - Frontend: 728 tests passed (50 files). TypeScript build clean. ESLint clean. MSW intercepts all POST /api/v1/clients/:clientId/leads/:leadId/call calls in tests — no live fetch.
  - Backend flag-off smoke: `ENABLE_OUTBOUND_CALLS=false` returns 403; no `CallSession` created; ElevenLabs API not called. Covered by existing backend tests.
- [x] 5.3 Update relevant roadmap/pricing/operator test protocol docs with flag defaults, real-call warning, phone-number ID setup, and C2 limits.
  - Root `.env.example` already documents `ENABLE_OUTBOUND_CALLS=false` (default), `ELEVENLABS_PHONE_NUMBER_ID`, rollback instructions, and Phase C2 context (added in WU1).
  - `design.md` documents production config requirements (QORA_WEBHOOK_AUTH_ENABLED=true, QORA_WEBHOOK_SECRET, ELEVENLABS_PHONE_NUMBER_ID) — added in WU2.
  - Frontend `lead-table.tsx` confirmation dialog copy: "real call", "~$0.21/min", ElevenLabs + Telnyx.
  - `triggerCall()` in `leads.ts` has a JSDoc warning: "must NEVER be called without explicit operator confirmation".

## WU3 Batch (Frontend Operator UX — 2026-07-03) — COMPLETE

- [x] WU3-4.1: `triggerCall(clientId, leadId)` in `frontend/src/api/leads.ts` + `CallTriggerResponse` / `OutboundTriggerStatus` types in `frontend/src/api/types.ts`. 7 unit tests in `trigger-call.test.ts` (RED→GREEN: URL, method, success shape, 403/409/422/429 error propagation, URI encoding).
- [x] WU3-4.2: Green "Call Now" button added as 8th column after "Next Action" in `frontend/src/features/leads/lead-table.tsx`. Radix Dialog confirmation warns "real call / ~$0.21/min". Per-row `CallRowState` state machine: idle → confirming → loading → calling | error. "Calling…" Badge on success. Error span + "Call Now" retry link on failure. Row click isolation via `e.stopPropagation()`. `LeadTable` now requires `clientId` prop. `LeadsPage`/`LeadsArea` updated to thread `clientId`.
- [x] WU3-4.3: 15 Vitest tests in `call-now-button.test.tsx` covering button placement, column ordering, confirmation dialog, call dispatch guard, cancel path, Calling… badge, button absence in calling state, dialog closure on success, and 403/409/422/429/500 error feedback + re-enable on error. MSW default handler added to `handlers.ts` for `POST /api/v1/clients/:clientId/leads/:leadId/call`.
- [x] WU3-5.1: Backend pytest run: 2900 passed, 1 pre-existing failure (tracked).
- [x] WU3-5.2: Frontend vitest run: 728 passed (50 files). Build: clean. Lint: clean.
- [x] WU3-5.3: Docs verified complete. No new doc files needed.
