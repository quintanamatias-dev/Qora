# Verification Report

**Change**: qora-phase2  
**Version**: N/A  
**Mode**: Standard  
**Artifact Mode**: Hybrid (`.sdd` file + Engram)

---

### Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 12 |
| Tasks complete | 11 |
| Tasks incomplete | 1 |

Incomplete task(s):
- `T05 [CAP-3]` is still unchecked in `.sdd/qora-phase2/tasks.md`, even though the frontend logic is now implemented in `backend/app/static/index.html`.

---

### Build & Tests Execution

**Build**: ➖ Skipped
```text
No build/type-check command was run.
Repo instruction says: "Never build after changes."
```

**Tests**: ✅ 256 passed / ❌ 0 failed / ⚠️ 1 warning
```text
python3 -m pytest tests/ -x -q

256 passed, 1 warning in 2.59s

Warning:
- tests/unit/calls/test_phase2_behaviors.py::test_postcall_closes_orphan_session
- RuntimeWarning: coroutine '_persist_user_turn' was never awaited
```

**Coverage**: ➖ Not available

---

### CAP-3 Final Fix Verification

Verified in `backend/app/static/index.html`:

- `stopConversation()` captures `const sessionIdToClose = currentSessionId;` before `cleanup()` (lines 514-518).
- After `cleanup()`, it calls `fetch(/api/v1/calls/${sessionIdToClose}/end, { body: { reason: 'user_hangup' }})` using the captured ID (lines 519-525).
- `ws.onclose` still keeps `if (currentSessionId)` before calling `/end` (lines 492-499), so the user-stop path will not double-close after `cleanup()` nulls the session, while EL-initiated/non-user closes can still close through `onclose`.
- Reconnect flow still closes the dropped session with `reason: 'reconnect_attempt'` before `startConversation()` (lines 546-560).

---

### Spec Compliance Matrix

| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| CAP-1 User Turn Persistence | User sends a message during active call | `backend/tests/unit/calls/test_phase2_behaviors.py > test_schedule_user_turn_persist_fires_with_last_user_message` + `test_schedule_user_turn_persist_finds_last_user_message` | ⚠️ PARTIAL |
| CAP-1 User Turn Persistence | Webhook payload has no user message | `backend/tests/unit/calls/test_phase2_behaviors.py > test_schedule_user_turn_persist_skips_empty_messages` | ✅ COMPLIANT |
| CAP-1 User Turn Persistence | Both turns persisted per conversation round | (none found) | ❌ UNTESTED |
| CAP-2a End Endpoint | Frontend closes session normally | `backend/tests/unit/calls/test_end_endpoint.py > test_end_by_elevenlabs_id_sets_completed` + `test_end_by_elevenlabs_id_sets_ended_at` + `test_end_increments_call_count` | ✅ COMPLIANT |
| CAP-2a End Endpoint | End called twice (idempotent) | `backend/tests/unit/calls/test_end_endpoint.py > test_end_idempotent_twice_returns_200` + `test_end_idempotent_call_count_not_double_incremented` | ✅ COMPLIANT |
| CAP-2b ElevenLabs Post-Call Webhook | Post-call webhook closes an orphan session | `backend/tests/unit/calls/test_phase2_behaviors.py > test_postcall_closes_orphan_session` + `test_postcall_increments_call_count_for_orphan` | ✅ COMPLIANT |
| CAP-2b ElevenLabs Post-Call Webhook | Post-call webhook arrives after frontend already closed | `backend/tests/unit/calls/test_phase2_behaviors.py > test_postcall_already_completed_stays_completed` | ⚠️ PARTIAL |
| CAP-2c Background Sweeper | Stale session swept | `backend/tests/unit/calls/test_sweeper.py > test_sweeper_abandons_stale_session` + `test_sweeper_does_not_increment_call_count` | ✅ COMPLIANT |
| CAP-2c Background Sweeper | Recent session not swept | `backend/tests/unit/calls/test_sweeper.py > test_sweeper_leaves_recent_session_untouched` | ✅ COMPLIANT |
| CAP-3 Frontend Reconnect | Clean WebSocket close | (no frontend/browser test found) | ❌ UNTESTED |
| CAP-3 Frontend Reconnect | Network drop | (no frontend/browser test found) | ❌ UNTESTED |
| CAP-3 Frontend Reconnect | User clicks Reconectar | (no frontend/browser test found) | ❌ UNTESTED |
| CAP-4 Summary + Fact Extraction | Summary generated after clean call end | `backend/tests/unit/test_summarizer.py > test_summarizer_persists_summary_and_facts` | ⚠️ PARTIAL |
| CAP-4 Summary + Fact Extraction | Summary skipped for abandoned session with no turns | `backend/tests/unit/test_summarizer.py > test_summarizer_skips_when_no_turns` | ⚠️ PARTIAL |
| CAP-4 Summary + Fact Extraction | Summarizer fails | `backend/tests/unit/test_summarizer.py > test_summarizer_gpt_failure_no_exception` + `test_summarizer_gpt_failure_session_stays_completed` | ⚠️ PARTIAL |
| CAP-4 Summary + Fact Extraction | Lead flags do_not_call | `backend/tests/unit/test_summarizer.py > test_summarizer_sets_do_not_call_flag` | ✅ COMPLIANT |
| CAP-5 New Model Fields | Session closed with new fields populated | `backend/tests/unit/calls/test_end_endpoint.py > test_end_by_elevenlabs_id_sets_completed` | ⚠️ PARTIAL |
| CAP-5 New Model Fields | Lead model persists do_not_call default | (none found) | ❌ UNTESTED |
| CAP-6 Conversation History Injection | First call to a lead | `backend/tests/unit/voice/test_memory_injection.py > test_first_call_is_not_returning_caller` + `test_first_call_has_call_number_1` + `test_first_call_has_empty_call_history` | ⚠️ PARTIAL |
| CAP-6 Conversation History Injection | Second call — history exists | `backend/tests/unit/voice/test_memory_injection.py > test_returning_caller_is_returning` + `test_returning_caller_has_call_history` + `test_returning_caller_call_number_incremented` | ✅ COMPLIANT |
| CAP-6 Conversation History Injection | Lead with known insurance from prior call | (none found) | ❌ UNTESTED |
| CAP-6 Conversation History Injection | Lead marked do_not_call | `backend/tests/unit/voice/test_memory_injection.py > test_initiation_blocked_for_do_not_call_lead` | ✅ COMPLIANT |
| CAP-6 Conversation History Injection | ElevenLabs post-call webhook merge | (none found) | ❌ UNTESTED |

**Compliance summary**: 9/23 scenarios compliant, 7 partial, 7 untested

---

### Correctness (Static — Structural Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| CAP-1 | ✅ Implemented | `schedule_user_turn_persist()` scans `body.messages` from the end and schedules background persistence; agent turns are persisted in `voice/webhook.py`. |
| CAP-2 | ✅ Implemented | `/calls/{conversation_id}/end`, `/calls/elevenlabs-postcall`, and sweeper logic exist and match spec shape. |
| CAP-3 | ✅ Implemented | Frontend now closes sessions on `onclose`, shows reconnect UI only for non-1000 closes, and `stopConversation()` uses captured session ID to avoid the race. |
| CAP-4 | ✅ Implemented | Async summarizer exists, uses a single GPT call, persists summary/facts, and merges into `Lead`. |
| CAP-5 | ✅ Implemented | New fields exist on `CallSession` and `Lead`; migration script exists at `backend/scripts/migrate_phase2.py`. |
| CAP-6 | ✅ Implemented | Initiation loads recent completed sessions, injects memory variables, and blocks `do_not_call` leads. |

---

### Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| AD-1 Async post-processing via `asyncio.create_task` | ✅ Yes | Used for summarization and user-turn persistence. |
| AD-2 Sweeper runtime in lifespan async loop | ✅ Yes | `stale_session_sweeper()` is started from `app/main.py`. |
| AD-3 Close endpoint in calls router | ✅ Yes | Implemented in `backend/app/calls/router.py`. |
| AD-4 Summarizer model `gpt-4o-mini` | ✅ Yes | Uses `settings.openai_model_fast`. |
| AD-5 JSON fact storage on `CallSession` + `Lead` | ✅ Yes | Implemented with SQLAlchemy JSON columns. |
| AD-6 User turn source = last user message | ✅ Yes | Implemented by reverse scan in `schedule_user_turn_persist()`. |
| AD-7 Memory variable injection in prompt loader + initiation | ✅ Yes | Both locations updated. |
| AD-8 Migration strategy | ⚠️ Minor deviation | Migration script exists, but path is `backend/scripts/migrate_phase2.py` rather than `scripts/migrate_phase2.py` in the design table. |

---

### Issues Found

**CRITICAL** (must fix before archive):
- CAP-3 frontend behavior is still unproven by runtime/browser tests (`clean close`, `network drop`, `reconnect`).
- Several Phase 2 spec scenarios remain untested (`CAP-1 both-turn persistence`, `CAP-5 do_not_call default`, `CAP-6 confirmed_facts content`, `CAP-6 transcript merge/regeneration`).

**WARNING** (should fix):
- `.sdd/qora-phase2/tasks.md` still marks `T05` incomplete, creating audit-trail drift.
- Test suite is green but emits one `RuntimeWarning` about `_persist_user_turn` never awaited during tests.
- Some scenarios are only partially covered (e.g. post-call merge, summary-to-lead merge assertions, zero-turn abandoned path specificity).

**SUGGESTION** (nice to have):
- Add a browser-level or JS-unit test around `stopConversation()` / `ws.onclose` to lock the CAP-3 race-condition fix.
- Add explicit assertions for `confirmed_facts` content and transcript merge-triggered re-summary.

---

### Verdict

PARTIAL

Implementation-wise, the CAP-3 race condition fix is correct and the backend suite is fully green (256/256), but archive should wait until the remaining Phase 2 spec gaps — especially untested CAP-3 frontend behavior — are covered or explicitly accepted.
