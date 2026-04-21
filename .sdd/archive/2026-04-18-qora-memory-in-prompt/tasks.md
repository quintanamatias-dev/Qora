# Tasks: qora-memory-in-prompt

## Group 1 — Shared memory module
- [x] T01 | test | RED | CAP-1 None lead | Files: `backend/tests/unit/test_memory.py` | AC: `build_memory_context(None)` raises `ValueError`.
- [x] T02 | test | RED | CAP-1 no prior sessions | Files: `backend/tests/unit/test_memory.py` | AC: empty `call_history`, empty `confirmed_facts`, `False`, `1` for zero completed sessions.
- [x] T03 | test | RED | CAP-1 one completed session | Files: `backend/tests/unit/test_memory.py` | AC: one history line includes summary substring.
- [x] T04 | test | RED | CAP-1 max 3 sessions | Files: `backend/tests/unit/test_memory.py` | AC: only 3 newest completed summaries ordered by `ended_at DESC`.
- [x] T05 | test | RED | CAP-1 history format | Files: `backend/tests/unit/test_memory.py` | AC: line is `Llamada del DD/MM/YYYY: "..."`, truncated to 150 chars, BA timezone.
- [x] T06 | test | RED | CAP-1 empty facts | Files: `backend/tests/unit/test_memory.py` | AC: `confirmed_facts == ""` for `None`/empty facts.
- [x] T07 | test | RED | CAP-1 facts ordering | Files: `backend/tests/unit/test_memory.py` | AC: only known keys rendered in fixed order: insurance, interest, next action.
- [x] T08 | test | RED | CAP-1 returning caller | Files: `backend/tests/unit/test_memory.py` | AC: any completed session makes `is_returning_caller` true.
- [x] T09 | test | RED | CAP-1 call number | Files: `backend/tests/unit/test_memory.py` | AC: `call_number == lead.call_count + 1`.
- [x] T10 | test | RED | CAP-1 logging | Files: `backend/tests/unit/test_memory.py` | AC: `memory_context_built` logs `lead_id`, `session_count`, `has_facts`, `call_number`.
- [x] T11 | test | RED | CAP-1 status filter | Files: `backend/tests/unit/test_memory.py` | AC: non-`completed` sessions never affect history/returning state.
- [x] T12 | test | RED | CAP-1 summary filter | Files: `backend/tests/unit/test_memory.py` | AC: `NULL`/empty summaries excluded from `call_history`.
- [x] T13 | prod | GREEN | CAP-1 all scenarios | Files: `backend/app/memory.py` | AC: add `MemoryContext`, `build_memory_context()`, `format_call_history()`, `format_confirmed_facts()` passing T01-T12.

## Group 2 — PromptLoader async + memory wiring
- [x] T14 | test | RED | CAP-2 backward compat | Files: `backend/tests/unit/prompts/test_loader.py` | AC: `render()` works without `db` and yields empty memory defaults.
- [x] T15 | test | RED | CAP-2 async variables | Files: `backend/tests/unit/prompts/test_loader.py` | AC: `_build_variables()` is async and preserves current variable set.
- [x] T16 | test | RED | CAP-2 real memory injection | Files: `backend/tests/unit/prompts/test_loader.py` | AC: with `db+lead`, uses `build_memory_context` values for 4 memory keys.
- [x] T17 | test | RED | CAP-2 db none | Files: `backend/tests/unit/prompts/test_loader.py` | AC: `db=None` resolves memory to empty defaults.
- [x] T18 | test | RED | CAP-2 lead none | Files: `backend/tests/unit/prompts/test_loader.py` | AC: `lead=None` resolves empty defaults even with db.
- [x] T19 | test | RED | CAP-2 placeholder removal | Files: `backend/tests/unit/prompts/test_loader.py` | AC: rendered prompt contains no literal memory placeholders.
- [x] T20 | test | RED | CAP-2 boolean stringification | Files: `backend/tests/unit/prompts/test_loader.py` | AC: rendered `is_returning_caller` is `"true"`/`"false"`.
- [x] T21 | test | RED | CAP-2 number stringification | Files: `backend/tests/unit/prompts/test_loader.py` | AC: rendered `call_number` is digit string.
- [x] T22 | prod | GREEN | CAP-2 builder integration | Files: `backend/app/prompts/loader.py` | AC: `_build_variables()` async, accepts `db`, injects memory or defaults.
- [x] T23 | prod | GREEN | CAP-2 render signature | Files: `backend/app/prompts/loader.py` | AC: `render()` accepts optional `db` and threads it through.
- [x] T24 | prod | GREEN | CAP-2 insurance agent | Files: `backend/app/prompts/insurance_agent.py` | AC: `render_system_prompt(..., memory=None)` uses memory call number when present.

## Group 3 — Custom-LLM webhook passes DB
- [x] T25 | test | RED | CAP-3 happy path | Files: `backend/tests/integration/voice/test_custom_llm_memory.py` | AC: webhook prompt includes prior summary when lead has completed session.
- [x] T26 | test | RED | CAP-3 graceful failure | Files: `backend/tests/integration/voice/test_custom_llm_memory.py` | AC: if builder raises, response stays 200/SSE and logs `memory_context_failed`.
- [x] T27 | test | RED | CAP-3 no lead | Files: `backend/tests/integration/voice/test_custom_llm_memory.py` | AC: no lead renders empty memory without crash.
- [x] T28 | prod | GREEN | CAP-3 db lifetime | Files: `backend/app/voice/webhook.py` | AC: keep DB open through `PromptLoader().render(..., db=session)`.
- [x] T29 | prod | GREEN | CAP-3 fallback logging | Files: `backend/app/prompts/loader.py` | AC: catch builder exceptions, log structured failure, use empty defaults.

## Group 4 — Initiation refactor
- [x] T30 | test | RED | CAP-4 regression | Files: `backend/tests/integration/voice/test_initiation.py` | AC: initiation response keys/types/values remain identical.
- [x] T31 | test | RED | CAP-4 no duplication | Files: `backend/tests/integration/voice/test_initiation.py` | AC: `initiation.py` imports `build_memory_context` and contains no inline date-format memory helpers.
- [x] T32 | prod | GREEN | CAP-4 shared builder | Files: `backend/app/voice/initiation.py` | AC: delegate memory creation to `build_memory_context`; remove duplicated helpers.

## Group 5 — End-to-end memory cycle
- [x] T33 | test | RED | CAP-5 second call summary | Files: `backend/tests/integration/voice/test_session_continuity_e2e.py` | AC: second rendered prompt contains first-call summary substring after simulated summarizer update.
- [x] T34 | test | RED | CAP-5 call number in prompt | Files: `backend/tests/integration/voice/test_session_continuity_e2e.py` | AC: rendered prompt contains `"2"` for second call.
- [x] T35 | test | RED | CAP-5 returning caller flag | Files: `backend/tests/integration/voice/test_session_continuity_e2e.py` | AC: rendered prompt contains `"Llamada del"` (call_history non-empty) when prior completed session exists.
- [x] T36 | prod | GREEN | CAP-5 verification fixups | Files: `backend/app/memory.py`, `backend/app/prompts/loader.py`, `backend/app/voice/webhook.py`, `backend/tests/integration/voice/test_session_continuity_e2e.py` | AC: no code expected; only minimal fixes if T33-T35 expose gaps.

## Group 6 — Documentation
- [x] T37 | docs | N/A | CAP-3/CAP-4 delivery docs | Files: `docs/elevenlabs-setup.md` | AC: explain memory is built at custom-LLM render time, revise initiation wording, note Twilio/SIP parity.

## Group 7 — Final verification
- [x] T38 | verify | N/A | All CAPS | Files: `backend/**` | AC: run `cd backend && python3 -m pytest tests/ -q`; all existing + new tests pass.
- [x] T39 | verify | N/A | All CAPS | Files: `backend/**` | AC: run `cd backend && ruff check . && ruff format --check .` clean.
- [x] T40 | verify | N/A | CAP-3/CAP-5 smoke | Files: runtime/logs | AC: manual two-call curl path shows `memory_context_built` and prompt memory content.

## Verify Remediation — Round 1 (post-verify criticals + warning)

- [x] T41 | test+prod | RED→GREEN | C1 fix: is_returning_caller summary-independent | Files: `backend/app/memory.py`, `backend/tests/unit/test_memory.py` | AC: completed session with summary=None or "" → is_returning_caller=True; call_history="" (REQ-1.5). Split query into 2: EXISTS for flag, filtered for history.
- [x] T42 | template+test | GREEN | C2 fix: add {{is_returning_caller}} to prompt template | Files: `backend/clients/quintana-seguros/prompt.md`, `backend/tests/integration/voice/test_session_continuity_e2e.py`, `backend/tests/unit/prompts/test_loader.py` | AC: rendered prompt contains "true"/"false" from {{is_returning_caller}} substitution. Updated T35 assertion to strict "true" check. Added T42c (false for first call) + 2 unit tests.
- [x] T43 | test+prod | RED→GREEN | W1 fix: wire memory into JAUMPABLO fallback branch | Files: `backend/app/prompts/loader.py`, `backend/tests/unit/prompts/test_loader.py` | AC: fallback branch builds memory context and passes memory kwarg to render_system_prompt. Spy test verifies kwarg is non-None with correct call_number.

## Red → Green pairs
- T01-T12 → T13
- T14-T21 → T22-T24
- T25-T27 → T28-T29
- T30-T31 → T32
- T33-T35 → T36
- T41 (RED), T42b/T42c/T42u (RED+GREEN), T43 (RED) → all GREEN after fixes

- [x] T44 | test+prod | RED→GREEN | REQ-2.4 fix: call_number "1" fallback | Files: `backend/tests/unit/prompts/test_loader.py`, `backend/app/prompts/loader.py` | AC: When db=None OR lead=None, call_number MUST resolve to "1". Updated T17 assertion from "5"→"1". Added 3 new tests (db=None, lead=None, memory wins over legacy kwarg).

## Recommended batches
- Batch 1: T01-T24 — memory builder + async prompt plumbing.
- Batch 2: T25-T36 — webhook DB wiring, initiation refactor, E2E continuity.
- Batch 3: T37-T40 — docs and full verification.
- Remediation: T41-T43 — verify round 1 critical/warning fixes.
- Remediation 2: T44 — REQ-2.4 call_number fallback fix.
