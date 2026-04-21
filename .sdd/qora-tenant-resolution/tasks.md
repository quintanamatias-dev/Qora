# Tasks: Path-Based Tenant Resolution

## Group 1 — Refactor (3)
- [x] **T01 — test — RED — CAP-3** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`, `backend/app/voice/webhook.py`.
  - Fail unless `_process_custom_llm_request(body, client_id, request)` exists as a private helper.
- [x] **T02 — prod — GREEN — CAP-3** Files: `backend/app/voice/webhook.py`.
  - Extract current webhook body-processing into `_process_custom_llm_request`; no behavior change or duplicate logic.
- [x] **T03 — test — GREEN — CAP-3** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Update existing webhook tests so refactor preserves passing legacy behavior.

## Group 2 — Path-based route (9)
- [x] **T04 — test — RED — CAP-1 happy path** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Add valid path-tenant SSE test; mock OpenAI with `respx`; expect 200 + `text/event-stream`.
- [x] **T05 — prod — GREEN — CAP-1 happy path** Files: `backend/app/voice/webhook.py`.
  - Register `POST /{client_id}/custom-llm/chat/completions`; resolve path tenant and call shared helper.
- [x] **T06 — test — RED — CAP-1 unknown tenant** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Expect 404 and `{"error":"client not found"}`; no stream starts.
- [x] **T07 — test — RED — CAP-1 inactive tenant** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Expect 403 and `{"error":"Tenant disabled"}` for inactive tenant.
- [x] **T08 — prod — GREEN — CAP-1 unknown/inactive** Files: `backend/app/voice/webhook.py`.
  - Add shared tenant validation: 404 for missing, warning + 403 for inactive.
- [x] **T09 — test — RED — CAP-1 precedence/mismatch** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Assert path `client_id` wins over body value and mismatch warning is logged.
- [x] **T10 — prod — GREEN — CAP-1 precedence/mismatch** Files: `backend/app/voice/webhook.py`.
  - Implement path-over-body resolution and `client_id_mismatch` structured logging.
- [x] **T11 — test — RED — CAP-1 logging** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Assert `custom_llm_path_request` emits `client_id`, `conversation_id`, and request-size fields.
- [x] **T12 — prod — GREEN — CAP-1 logging** Files: `backend/app/voice/webhook.py`.
  - Emit `custom_llm_path_request` with required structured fields before helper call.

## Group 3 — Legacy route deprecation (3)
- [x] **T13 — test — RED — CAP-2 deprecation log** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Assert successful legacy requests log `custom_llm_legacy_route_used` with migration hint.
- [x] **T14 — prod — GREEN — CAP-2 deprecation log** Files: `backend/app/voice/webhook.py`.
  - Rename legacy handler if needed, keep route order literal-first, add warning log only on success.
- [x] **T15 — test — GREEN — CAP-2 legacy 422 unchanged** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Preserve 422 when body has no `client_id`; confirm no deprecation event is emitted.

## Group 4 — Structural consistency (3)
- [x] **T16 — test — RED — CAP-3 CallSession parity** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Parametrize legacy/path routes; same input must create identical `CallSession` fields except resolution source.
- [x] **T17 — test — RED — CAP-3 SSE parity** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Parametrize both routes; streamed `data:` chunks must keep identical JSON shape.
- [x] **T18 — test — RED — CAP-3 tool parity** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Parametrize both routes; tool-call execution/result injection/continuation must match.

## Group 5 — Documentation (2)
- [x] **T19 — docs — GREEN — CAP-2 rollout** Files: `docs/elevenlabs-setup.md`.
  - Document EL dashboard setup, URL template, `/chat/completions` suffix behavior, and common gotchas.
- [x] **T20 — docs — GREEN — CAP-2 rollout** Files: `backend/README.md` or `.sdd/qora-tenant-resolution/README.md`.
  - Add a short pointer to the new setup guide and path-based endpoint.

## Group 6 — Final verification (3)
- [x] **T21 — prod — GREEN — CAP-1/CAP-2/CAP-3** Files: none (verification against `backend/tests/`).
  - Run `cd backend && python3 -m pytest tests/ -q`; suite must pass at 262+ tests.
- [x] **T22 — prod — GREEN — CAP-1/CAP-2/CAP-3** Files: none (verification against backend Python files).
  - Run Ruff check and format; leave workspace clean.
- [x] **T23 — prod — GREEN — CAP-1/CAP-2** Files: none (manual API verification).
  - Curl both routes for happy path, 404 unknown tenant, and 403 inactive tenant.

## Red/Green Pairing Summary
- Pairs: `T01→T02`, `T04→T05`, `T06/T07→T08`, `T09→T10`, `T11→T12`, `T13→T14`.
- Follow-up verification tests: `T03`, `T15`, `T16`, `T17`, `T18`.

## Recommended sdd-apply batching
- **Batch 1:** Groups 1 + 2 — helper extraction, tenant validation, path route, logging.
- **Batch 2:** Groups 3 + 4 — legacy deprecation logging and downstream parity coverage.
- **Batch 3:** Groups 5 + 6 — docs, full verification, manual curl checks.

## Verify Remediation (post-verify Round 1)

- [x] **T24 — test — RED/GREEN — CAP-1 S5** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - `test_path_route_missing_chat_completions_suffix_returns_404` — no route match → 404 by FastAPI routing. No prod change needed.
- [x] **T25 — test — RED/GREEN — CAP-1 S6** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - 3 sub-tests: special chars, path traversal (`..%2Fetc%2Fpasswd`), very long string (300 chars). All → 404. No prod change needed.
- [x] **T26 — test — RED — CAP-1 S7** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - `test_concurrent_tenants_same_conversation_id_no_cross_contamination` — RED confirmed: `session_store.get(tuple)` returned None (old string key).
- [x] **T27 — prod — GREEN — CAP-1 S7** Files: `backend/app/voice/filler.py`, `backend/app/voice/webhook.py`, `backend/tests/unit/voice/test_filler.py`, `backend/tests/unit/prompts/test_filler_policy.py`, `backend/tests/test_spec_coverage.py`.
  - `SessionStore._sessions` key changed from `str` → `tuple[str, str]`. All call sites updated. 7 old-API test references fixed.
- [x] **T28 — docs — README URL** Files: `backend/README.md`.
  - Updated lines 101-106: now shows path-based (recommended) + legacy (deprecated) ngrok URL examples.
- [x] **T29 — spec — log field contract** Files: `.sdd/qora-tenant-resolution/spec.md`.
  - CAP-1 Requirement #3: removed "request size in bytes", added `message_count` + `model` with rationale comment.
- [x] **T30 — test — GREEN — CAP-1 S6 tighten** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - Tightened 3 S6 sub-tests from `assert response.status_code in (404, 422)` → `assert response.status_code == 404`. All 3 pass with exact 404 (no handler change needed — actual behavior already always returns 404). Updated docstrings to document why 422 never occurs (FastAPI accepts any str path param; handler's tenant lookup returns 404 for unknowns).

## Verify Remediation Round 3

- [x] **T31 — spec — CAP-2 `hint` field naming** Files: `.sdd/qora-tenant-resolution/spec.md`.
  - Updated CAP-2 "deprecation warning includes migration hint" scenario: `hint` → `migration_hint`. Added rationale note. Implementation uses `migration_hint` for clarity; spec aligned.
- [x] **T32 — test — GREEN — CAP-2 legacy 404 body** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Tightened `test_custom_llm_unknown_client_returns_404`: added `assert data == {"detail": {"error": "client not found"}}`. Actual response shape confirmed before adding assertion.
- [x] **T33 — test — RED/GREEN — CAP-3 tool parity** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - Added `test_path_route_tool_call_triggers_execution` + `_build_tool_call_only_stream()` helper. Proves path route: detects tool call (finish_reason=tool_calls), dispatches tool (call_count==2), resumes stream (final content + [DONE] present).

## Verify Remediation Round 4

- [x] **T34 — test — GREEN — CAP-1 same-value precedence** Files: `backend/tests/unit/voice/test_custom_llm_path_route.py`.
  - `test_path_route_same_client_id_in_both_path_and_body` — triangulation for T09: when path and body carry IDENTICAL client_id, asserts 200 + [DONE] and NO `client_id_mismatch` log. Proves mismatch detection only fires on actual disagreement. No prod change needed.
- [x] **T35 — test — GREEN — CAP-3 legacy tool-call parity** Files: `backend/tests/integration/voice/test_custom_llm.py`.
  - `test_legacy_route_tool_call_triggers_execution` — mirror of T33 targeting the legacy route (`/api/v1/voice/custom-llm/chat/completions`). Uses `_build_tool_call_only_stream()` helper. Same assertions as T33: call_count==2, [DONE] present, final content present. No prod change needed.
