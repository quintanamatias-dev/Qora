# Apply Progress: qora-phase2

## Batch 1 — Foundation + Phase 2a (T01–T07 in prompt / T01–T04, T06–T07 in tasks.md)

### Task Status

| Task (prompt) | Task (tasks.md) | Description | Status |
|---------------|-----------------|-------------|--------|
| T01 | T01 | CallSession model fields | ✅ |
| T02 | T02 | Lead model fields | ✅ |
| T03 | T02 (part) | Migration script | ✅ |
| T04 | T03 | User turn persistence (fire-and-forget) | ✅ |
| T05 | T04 | End session endpoint + schemas | ✅ |
| T06 | T06 | ElevenLabs post-call webhook | ✅ |
| T07 | T07 | Background sweeper | ✅ |

---

## Batch 2 — Phase 2b: Memory Generation (T08–T10)

### Task Status

| Task | tasks.md | Description | Status |
|------|----------|-------------|--------|
| T08 | T08 | summarizer.py — GPT-4o-mini summary + fact extraction | ✅ |
| T09 | T09 | Trigger summarization from /end, postcall, sweeper | ✅ |
| T10 | T10 | Persist summary/facts, merge into Lead | ✅ |

## Batch 3 — Phase 2c: Memory Injection (T11–T12)

### Task Status

| Task | tasks.md | Description | Status |
|------|----------|-------------|--------|
| T11 | T11 | Memory injection at initiation (call_history, confirmed_facts, is_returning_caller, call_number) | ✅ |
| T12 | T12 | do_not_call block in initiation + prompt.md memory variables section | ✅ |

---

## Files Created/Modified

### Batch 1

| File | Action | Description |
|------|--------|-------------|
| `backend/app/calls/models.py` | Modified | Added `summary`, `closed_reason`, `total_user_turns`, `total_agent_turns`, `extracted_facts` to CallSession |
| `backend/app/leads/models.py` | Modified | Added `summary_last_call`, `objections_heard`, `interest_level`, `extracted_facts`, `do_not_call`, `next_action`, `next_action_at` to Lead |
| `backend/app/calls/schemas.py` | Created | Pydantic models: `EndSessionRequest`, `EndSessionResponse`, `ElevenLabsPostCallPayload` |
| `backend/app/calls/service.py` | Modified | Added `count_turns()`, `get_sessions_for_lead()`, `get_session_by_elevenlabs_id()`, `close_session()`, `schedule_user_turn_persist()`, `_persist_user_turn()` |
| `backend/app/calls/router.py` | Modified | Added `POST /{session_id}/end` (idempotent close) and `POST /elevenlabs-postcall` (webhook merge). Updated GET endpoints to expose new fields |
| `backend/app/voice/webhook.py` | Modified | Added `schedule_user_turn_persist()` call in `generate()` — fire-and-forget user turn persistence |
| `backend/app/sweeper.py` | Created | `sweep_stale_sessions()` + `stale_session_sweeper()` async loop (60s, 10min threshold, no call_count increment) |
| `backend/app/main.py` | Modified | Registered `stale_session_sweeper` as asyncio background task in lifespan; cancels on shutdown |
| `backend/scripts/migrate_phase2.py` | Created | Idempotent ALTER TABLE migration for both tables; checks PRAGMA table_info before adding |

### Batch 2

| File | Action | Description |
|------|--------|-------------|
| `backend/app/summarizer.py` | Created | `generate_summary_and_facts()` — single GPT-4o-mini call (JSON mode), 0-turn skip, full error swallowing. `_merge_facts_into_lead()` — objection union, interest_level update, do_not_call flag, extracted_facts merge |
| `backend/app/calls/service.py` | Modified | Added `_schedule_summarize()` + `_summarize_in_background()` helpers. `close_session()` now calls `_schedule_summarize(session_id)` after flush — non-blocking via `asyncio.create_task` |
| `backend/app/calls/router.py` | Modified | Imported `_schedule_summarize`. In `elevenlabs_postcall_webhook`: trigger re-summary when transcript is merged into a completed session |
| `backend/app/sweeper.py` | Modified | `sweep_stale_sessions()` calls `_schedule_summarize(session_id)` for each abandoned session after flush. Summarizer handles 0-turn skip internally |

### Batch 3

| File | Action | Description |
|------|--------|-------------|
| `backend/app/voice/initiation.py` | Modified | Added `_format_call_history()` + `_format_confirmed_facts()` helpers. Endpoint now: (1) checks `lead.do_not_call` → 403, (2) loads last 3 completed sessions, (3) injects `call_history`, `confirmed_facts`, `is_returning_caller`, `call_number` into `dynamic_variables` (plain + underscore-wrapped for EL templates) |
| `backend/app/prompts/loader.py` | Modified | `_build_variables()` now includes CAP-6 memory variables with safe empty defaults (`call_history=""`, `confirmed_facts=""`, `is_returning_caller="false"`, `call_number=str(call_count)`). Prevents `{{call_history}}` etc. from being left unresolved in the custom-LLM webhook render path |
| `backend/clients/quintana-seguros/prompt.md` | Modified | Replaced `{{returning_caller_context}}` with `{{call_number}}`, `{{confirmed_facts}}`, `{{call_history}}`. PASO 1 updated with conditional first-call vs returning-call greeting using `{{call_number}}` |

---

## Deviations from Design

### Batch 1
1. **Task numbering mismatch**: The prompt uses T01–T07 numbering but `tasks.md` has different numbering (tasks.md has T01–T07 but T05 is frontend work skipped for this batch, and T03 = user turn / T04 = end endpoint / T06 = postcall). Implementation followed `tasks.md` task descriptions, not prompt numbering.
2. **Migration script location**: Prompt said `backend/scripts/migrate_phase2.py`. Created that directory since it didn't exist.
3. **`call_count` removal note**: No increment logic existed before — `close_session()` added it for the first time.
4. **Session lookup in `/end`**: Parameter is `session_id` (internal UUID), consistent with existing router patterns.
5. **T05 (frontend reconnect)**: Skipped — out of scope for Batch 1.

### Batch 2
1. **Sweeper trigger decision**: The task description said "do NOT trigger summary" for sweeper abandoned sessions, but the spec explicitly states "via any path: /end, ElevenLabs webhook, or sweeper". Implemented per spec — trigger from sweeper, let summarizer's own 0-turn guard handle skipping. This matches the spec requirement and is more correct.
2. **`_schedule_summarize` exported**: The function uses a `_` prefix (conventionally private) but is imported from `router.py` and `sweeper.py`. This is acceptable for intra-package use and avoids code duplication.
3. **`close_session()` triggers summary even for idempotent calls**: The idempotent path (already completed) returns early before the `_schedule_summarize()` call, so no double-summarization occurs.

### Batch 3
1. **`InitiationResponse` type extended**: Changed `dict[str, str | int]` to `dict[str, str | int | bool]` to accommodate `is_returning_caller: bool` value. Existing tests pass without change since they check specific keys, not the type annotation.
2. **`returning_caller_context` preserved in `_build_variables`**: Did not remove the old field — left it for backward compatibility with any prompts that might still reference it. The quintana-seguros prompt no longer uses it, but it won't cause issues if present.
3. **`call_number` in loader is `str`**: `_build_variables` returns `dict[str, str]` and the regex replacer substitutes strings. `call_number` is serialized as `str(call_count)` in the loader path (e.g. `"1"`), but as `int` in the initiation path's `dynamic_variables`. This is correct — ElevenLabs receives the proper typed value, and the template renderer gets a clean string substitution.

---

## Test Results

### Batch 1
- **220 tests passed** — all pre-existing tests pass after changes.
- Syntax check: all 9 modified/created files pass AST parsing.

### Batch 2
- **220 tests passed** — all pre-existing tests continue to pass.
- Syntax check: all 4 modified/created files (summarizer.py, service.py, router.py, sweeper.py) pass AST parsing.

### Batch 3
- **220 tests passed** — all pre-existing tests continue to pass after T11 + T12.
- Syntax check: all 2 modified files (initiation.py, loader.py) pass AST parsing.

---

## Verify Fixes — CRITICAL 1 + CRITICAL 2

### CRITICAL 1 — End endpoint resolves by elevenlabs_conversation_id

**Status**: ✅ Fixed

**Change**: Modified `POST /{conversation_id}/end` in `backend/app/calls/router.py` to resolve by `elevenlabs_conversation_id` first (via `get_session_by_elevenlabs_id()`), then fall back to internal UUID lookup.

**Also fixed**: `close_session()` in `backend/app/calls/service.py` — timezone-naive/aware datetime bug triggered when computing `duration_seconds`. SQLite returns naive datetimes even for `timezone=True` columns; added `replace(tzinfo=timezone.utc)` normalization.

### CRITICAL 2 — Phase 2 behavioral tests

**Status**: ✅ Added 36 new tests

| Test File | Count | Coverage |
|-----------|-------|----------|
| `tests/unit/calls/test_end_endpoint.py` | 7 | CAP-2a: EL ID resolution, clean close, ended_at, call_count, fallback UUID, idempotency x2, 404 |
| `tests/unit/calls/test_sweeper.py` | 5 | CAP-2c: stale → abandoned, no call_count increment, recent → untouched, returns 0, multiple stale |
| `tests/unit/test_summarizer.py` | 7 | CAP-4: 0 turns skip, no exception, GPT failure no raise, session stays completed, do_not_call set, no set for other, persists summary |
| `tests/unit/voice/test_memory_injection.py` | 9 | CAP-6: do_not_call → 403, normal → 200, first call flags, empty history, returning caller, history content, call_number, underscore vars |
| `tests/unit/calls/test_phase2_behaviors.py` | 8 | CAP-1: fires task, skips empty, skips no-user-role, last msg; CAP-2b: orphan close, count increment, already-completed idempotent, 404 |

### Files Changed in Verify Phase

| File | Action | Description |
|------|--------|-------------|
| `backend/app/calls/router.py` | Modified | `/{conversation_id}/end` — resolve by elevenlabs_conversation_id first, fall back to internal UUID |
| `backend/app/calls/service.py` | Modified | `close_session()` — normalize naive datetime from SQLite before computing duration_seconds |
| `backend/tests/unit/calls/test_end_endpoint.py` | Created | 7 tests for CAP-2a end endpoint (EL ID, idempotency, 404) |
| `backend/tests/unit/calls/test_sweeper.py` | Created | 5 tests for CAP-2c sweeper (stale/recent/multiple) |
| `backend/tests/unit/test_summarizer.py` | Created | 7 tests for CAP-4 summarizer (0-turn skip, GPT fail, do_not_call) |
| `backend/tests/unit/voice/test_memory_injection.py` | Created | 9 tests for CAP-6 memory injection (do_not_call, first/returning caller) |
| `backend/tests/unit/calls/test_phase2_behaviors.py` | Created | 8 tests for CAP-1 + CAP-2b (user turn, postcall webhook) |

### Test Results

- **256 tests passed** (220 pre-existing + 36 new) — no regressions.

## Batch 4 — CAP-3 Frontend Reconnect (T05)

### Task Status

| Task | tasks.md | Description | Status |
|------|----------|-------------|--------|
| T05 | T05 | Frontend: call `/end` on WS close + reconnect button | ✅ |

### Files Changed

| File | Action | Description |
|------|--------|-------------|
| `backend/app/static/index.html` | Modified | Added `currentSessionId` state variable; captures EL `conversation_id` from initiation metadata event; `ws.onclose` calls `POST /api/v1/calls/{id}/end` with `reason="user_hangup"` (code 1000) or `reason="network_drop"` (non-1000); `showReconnectButton` captures dropped session ID in closure and calls `/end` with `reason="reconnect_attempt"` before starting new session; `cleanup()` clears `currentSessionId` |

### Test Results
- **256 tests passed** — no regressions (frontend-only change, no new backend tests needed).

---

## Summary — All Tasks Complete (T01–T12 + T05 + Verify CRITICALs) ✅

All tasks for qora-phase2 have been implemented across 4 batches:
- **Batch 1 (T01–T07)**: Foundation models, migrations, user turn persistence, session lifecycle endpoints, postcall webhook, sweeper
- **Batch 2 (T08–T10)**: GPT-4o-mini summarizer, fact extraction, lead memory persistence
- **Batch 3 (T11–T12)**: Memory injection at initiation, do_not_call enforcement, prompt.md memory variables
- **Batch 4 (T05)**: CAP-3 frontend reconnect — WS close → POST /end, reconnect button → POST /end before new session
- **Verify Fixes**: CRITICAL 1 (EL ID resolution in /end endpoint) + CRITICAL 2 (36 Phase 2 behavioral tests)

---

## Testing Notes

### CAP-3 Frontend Behaviors

CAP-3 frontend behaviors (WebSocket close handlers, reconnect button, `"Se perdió la conexión"` message display) are tested via **manual E2E only** — this MVP has no headless browser test framework set up.

The backend `/end` endpoint behavior for all three close reasons (`user_hangup`, `network_drop`, `reconnect_attempt`) **IS** covered in automated tests:
- `backend/tests/unit/calls/test_end_endpoint.py` — tests clean close, idempotency, 404, ElevenLabs ID resolution, call_count increment

**Future work**: Add Playwright (or similar) for frontend integration tests to cover the JS WebSocket `onclose` handler and reconnect button flow in a real browser context.

### Verify Gap Closure (Final Pass)

Additional tests added in final verify pass to close spec gaps:

| Test | Spec Scenario | File |
|------|---------------|------|
| `test_both_turns_persisted_per_round` | CAP-1: Both turns per conversation round | `test_phase2_behaviors.py` |
| `test_new_lead_has_do_not_call_false` | CAP-5: Lead persists do_not_call default | `test_phase2_behaviors.py` |
| `test_format_confirmed_facts_with_insurance` | CAP-6: Lead with known insurance from prior call | `test_phase2_behaviors.py` |
| `test_format_confirmed_facts_empty_when_no_facts` | CAP-6: confirmed_facts fallback | `test_phase2_behaviors.py` |
| `test_format_confirmed_facts_includes_all_known_fields` | CAP-6: confirmed_facts multi-field formatting | `test_phase2_behaviors.py` |
| `test_postcall_merges_extra_turns_when_el_has_more` | CAP-2b: Transcript merge + re-summary trigger | `test_phase2_behaviors.py` |

**RuntimeWarning fixed**: The `coroutine '_persist_user_turn' was never awaited` warning in `test_schedule_user_turn_persist_finds_last_user_message` was resolved by calling `.close()` on the coroutine after inspecting it. The coroutine was being passed to a patched `asyncio.create_task` (mock, not real event loop) and was never scheduled or closed, causing the garbage collector to emit the warning.
