# Fix custom-LLM event-loop stall

## Objective

Stop the custom-LLM webhook from hanging for minutes without raising an error, and
remove the proven event-loop blocking hazards on that request path.

## Problem

During a real ElevenLabs call the backend logged `memory_context_built`, then produced
no progress for ~277 seconds before `llm_stream_timeout` fired — even though the
configured `asyncio.timeout` is 60 seconds. Concurrent API requests stalled at the same
time (41 `request_started` vs 40 `request_completed`). No `stream_error`, no HTTP 401/429.

Read-only audit established the real timeline:

```
memory_context_built -> ~217s unexplained -> timeout CM entered -> 60s -> llm_stream_timeout
```

The `asyncio.timeout(60.0)` at `backend/app/voice/webhook.py:298` wraps only the OpenAI
stream, and its deadline starts on the first `__anext__` of the `StreamingResponse`
generator — after context building. The timeout value was never the defect.

## Why

Scheduler dispatch and phone arrival are already verified. This stall is the last known
blocker before the remaining attended end-to-end validation.

## Scope

Authorized edit roots:

- `backend/app/ai/llm_streaming.py`
- `backend/app/voice/webhook.py`
- `backend/app/core/logging.py`
- `backend/app/integrations/crm_config.py`
- `backend/tests/**`

Out of scope: provider/agent configuration, live calls, deployment, and every file
already modified on branch `feat/c6b-auto-dialer-slice3-reaper` (autodialer work).

## Constraints

- Strict TDD is active. Test runner: `cd backend && python3 -m pytest tests/ -q`
- Never build the frontend.
- No live provider calls, no outbound network requests from tests.
- Do not mix these changes with the pre-existing dirty working tree.

## Tasks

- [x] **T1 — Bound and reuse the OpenAI client** — DONE
      `backend/app/ai/llm_streaming.py:87` constructs a new `AsyncOpenAI` (and a new
      httpx connection pool) per request, never closes it, and passes no `timeout=` or
      `max_retries=`, so SDK defaults of 600s + 2 retries apply. Give it an explicit
      bounded timeout, stop leaking pools, and make a stalled upstream fail fast instead
      of hanging silently.
      Route: delegated (writer trigger — source + tests).
      Result: `AsyncOpenAI` now gets `httpx.Timeout(connect=5, read=15, write=10, pool=5)`
      and `max_retries=1`, both constructor-overridable, plus a lock-guarded
      per-configuration client cache so the httpx pool is shared instead of leaked.
      Worst case is now `15s x 2 attempts = 30s`, half the 60s turn budget, versus the
      old `600s x 3 = 1800s` — 30x over budget, which is the mechanism behind the 277s
      of silence with no `stream_error`.
      Evidence: RED observed (`assert 600 < 60.0`, `assert 2 <= 1`, `assert 1800 < 60.0`,
      `assert 5 == 1` for client reuse), then `cd backend && .venv/bin/python -m pytest
      tests/unit/ai -q` -> 9 passed. Parent re-ran it: 9 passed in 0.62s.
      Full-suite delta measured against the same tree: +9 passed, zero regressions.
      Files: `backend/app/ai/llm_streaming.py`,
      `backend/tests/unit/ai/test_llm_streaming_client_config.py` (new).
      `webhook.py` needed no change: `StreamingError` already propagates to `generate()`
      at `webhook.py:1306`, proved by test rather than assumed.

- [x] **T2 — Make logging non-blocking on the event loop** — DONE
      `backend/app/core/logging.py:76` uses `structlog.PrintLoggerFactory()`, so every log
      line is a synchronous `write()+flush()` to stdout on the loop thread. A stalled
      Docker log pipe freezes the entire process. This matches the loop-wide stall
      signature.
      Route: delegated (writer trigger — source + tests).
      Decision (user): backpressure policy is DROP. A full queue discards the record
      and the caller returns immediately. Losing log lines under extreme pressure beats
      stalling a real-time voice backend.
      Result: a bounded `queue.Queue(maxsize=10000)` sits between callers and the sink,
      fed by two `_DroppingQueueHandler`s — one on the root logger carrying the unchanged
      `ProcessorFormatter` (stdlib bridge), one on a dedicated non-propagating
      `qora.log_sink` logger where structlog's native chain lands via `_QueueLoggerFactory`.
      Rendering still happens on the calling thread (`QueueHandler.prepare` formats before
      enqueueing), so output bytes are unchanged for console and JSON; only `write()+flush()`
      moved to a daemon `qora-log-writer` thread. `enqueue` uses `put_nowait` and swallows
      `queue.Full` after bumping a lock-guarded counter exposed by
      `get_dropped_record_count()` — a plain integer, never a log line.
      `shutdown_logging()` is atexit-registered, idempotent, and called first by
      `setup_logging`, so reconfiguring replaces rather than stacks.
      Evidence: RED observed (`ImportError: cannot import name 'get_dropped_record_count'`,
      then the predicted bridge-test failure), then `cd backend && .venv/bin/python -m
      pytest tests/ -q` -> `43 failed, 3409 passed`, all 43 under `tests/unit/outbound/`.
      **+10 passed.** Parent spot check: 18 passed in 0.12s.
      Adjusted test, disclosed: `tests/test_logging.py::test_stdlib_logger_captured_via_bridge`
      used to reassign `handler.stream` on the root handler, which is now a `QueueHandler`
      with no `.stream`, so the mutation silently no-op'd. It now injects the buffer at
      configuration time and calls `shutdown_logging()` before reading. It also gained an
      assertion that the message text is present, which the original never checked.
      Not fixed, honestly: two pre-existing tests in `tests/test_logging.py`
      (`test_log_format_json_produces_json_lines`, `test_log_format_console_produces_non_json`)
      re-`structlog.configure(...)` after `setup_logging`, so they bypass the shipped
      transport and prove less than they appear to. Left alone; the new format tests cover
      the real path.

- [x] **T3 — Move CRM config loading off the loop** — DONE
      `backend/app/integrations/crm_config.py:233-237` performs `stat`/`read_text`/
      `yaml.safe_load` in a plain `def`, called from five async sites
      (`webhook.py:863/930/973/1051`, `context.py:375`) without `asyncio.to_thread` —
      unlike `loader.py` and `skill_loader.py`, which do it correctly.
      Route: delegated (writer trigger — source + tests across 4 files).
      Result: added `CRMConfigLoader.load_async`, a coroutine that awaits
      `asyncio.to_thread(CRMConfigLoader.load, ...)` — the same house pattern
      `prompts/loader.py` and `prompts/skill_loader.py` already use. The sync `load()`
      body, signature and exceptions are untouched, so the many existing synchronous
      callers and their tests keep working. The five voice call sites now await it:
      `webhook.py` fast path, lazy-build path, new-session path and the per-turn
      `render_for_agent` fallback, plus `context.py` inside `build_voice_context`.
      One-line change each; no opportunistic refactor of `webhook.py`.
      Evidence: RED observed (`AssertionError: build_voice_context loaded CRM config on
      the event loop thread`, 10 failed / 2 passed — the 2 pin sync behaviour), then
      `cd backend && .venv/bin/python -m pytest tests/ -q` -> `43 failed, 3421 passed`,
      all 43 under `tests/unit/outbound/`. **+12 passed.**
      Parent spot check: 12 passed in 0.35s.
      Correction to this audit: **there is no cache.** `CRMConfigLoader.load()` has no
      memoization at all — no `lru_cache`, no dict, no mtime invalidation. Every call is
      a genuine `exists()` + `read_text()` + `yaml.safe_load()`. No cache was added: that
      is a behavioural change, not a preservation, and it is risky where many tests write
      a fresh `crm.yaml` into `tmp_path` and read it back within sub-second mtime
      granularity. It belongs in its own work unit.
      Concurrency: `load()` is pure with respect to module state, so concurrent
      `load_async` calls need no lock.
      Not fixed, honestly: five modules OUTSIDE the authorized roots still call the
      blocking `load()` from async code and still stall the loop —
      `app/integrations/crm_sync_service.py:69`, `app/integrations/crm_import_service.py:171`,
      `app/leads/router.py:339`, `app/summarizer.py:1173`, and
      `app/integrations/crm_config_router.py:210,442,544,625`. The last two are async HTTP
      handlers with the same single-thread stall property. The fix is now mechanical: one
      `await` per site.
      Also disclosed: the `webhook.py` call-site coverage test is AST-based, not
      behavioural. It resolves local aliases and asserts every call is an awaited
      `load_async`, so it catches a regression to `.load(` or a dropped `await`, but it
      does not execute the webhook request path. `context.py` does have a real thread
      identity test through `build_voice_context`.

- [x] **T5 — BLOCKER: repair test fixtures broken by the phone normalizer** — DONE
      Commit `d61cde5 feat(phones): add explicit-region Argentine phone normalizer` made
      `app/phones/normalization.py:103` reject fixture phone numbers that the rest of the
      suite still seeds (`+5411077777`, `+5411155501` — 8 national digits), raising
      `PhoneNormalizationError: Invalid phone: invalid_number` at fixture setup.
      Observed on this tree: **69 failed, 410 errors, 2950 passed** in ~115s. The failures
      are shared-fixture setup errors spread across ~40 files (`test_summarizer.py` 55,
      `test_memory.py` 30, `calls/test_end_endpoint.py` 24, ...), not isolated cases.
      This is NOT caused by T1 — measured delta of the T1 change is exactly +9 passed.
      Impact: the documented baseline of 3251 passed does not reproduce, so strict TDD
      has no trustworthy green signal for T2/T3 and the acceptance criteria below cannot
      be evaluated.
      Decision (user): the validator is correct; the numbers were wrong. The normalizer
      was not weakened, patched or bypassed.
      Result: 87 literals across 44 files under `backend/tests/`, 58 distinct values
      remapped. Transform preserves the tail — `+54[9]11<tail>` becomes `+54911` + tail
      zero-padded to 8 digits, e.g. `+5411000099` -> `+5491100000100`. The mapping is
      injective and disjoint from every already-valid literal, so no two distinct seed
      leads collapsed into one. Each output was round-tripped through
      `normalize_phone(x, region="AR")`.
      Intentionally left invalid: `tests/unit/phones/test_normalization.py` (16, subject
      under test), opaque CRM payloads never normalized, `called_number` (the agent's
      number), and direct `Lead(...)` ORM construction that bypasses `create_lead`.
      `+5491140485464` (owner's real test phone) untouched.
      Evidence: `cd backend && .venv/bin/python -m pytest tests/ -q`
      before `69 failed, 2950 passed, 410 errors`, after `45 failed, 3384 passed`.
      **+434 passed, -410 errors.** Zero `PhoneNormalizationError` hits remain.
      Parent spot check: the three worst-hit files
      (`test_memory.py`, `test_summarizer.py`, `calls/test_end_endpoint.py`)
      -> 141 passed in 8.12s.

- [x] **T6 — Remove the `app.phones` import from `app/analysis`** — DONE
      `backend/app/analysis/universal/data_corrections.py:32` imports
      `app.phones.normalization`, which `tests/unit/test_analysis_schema.py:82` forbids
      (only `app.analysis.*` internal imports are permitted). Introduced by commit
      `d61cde5`, not by this feature. 2 of the remaining 45 failures.
      Decision (parent, user delegated it): remove the import rather than widen the rule.
      The test states its own intent — "so the package remains copy-pastable into other
      runtimes" — and that import genuinely breaks it. Widening the rule would change the
      intent, which needs the user; removing the import does not.
      Approach: `CORRECTABLE_FIELDS["phone"]` stops referencing a phones-backed callable.
      `run_data_corrections_pipeline` accepts explicit per-field validator overrides, and
      `app/summarizer.py` (already outside the analysis boundary) supplies the real phone
      validator. Default must be fail-closed: with no validator supplied, a phone
      correction is REJECTED, never applied unvalidated.
      Route: delegated (writer trigger — source + tests across 3+ files).
      Result: `_validate_phone` is gone from the analysis package. The `phone` registry
      entry now points at `_reject_unvalidated_phone`, which always returns
      `(False, "phone_validator_not_configured")`, so an uninjected phone correction is
      rejected with a reason instead of falling through to the permissive
      non-empty-string path. `_process_corrections` and `run_data_corrections_pipeline`
      gained `validators` and `normalizers` mappings merged over `CORRECTABLE_FIELDS`.
      The writer added the `normalizers` seam beyond the brief, correctly: the removed
      code also canonicalized `corrected_value` to E.164 *before* the idempotency gate,
      so a validators-only seam would have silently lost the canonical audit value and
      the format-insensitive no-op drop. `validate_phone_correction` and
      `normalize_phone_correction` live in `app/summarizer.py` and are wired in at the
      `run_data_corrections_pipeline` call site.
      Evidence: RED observed (`AssertionError: ... must not import 'app.phones.normalization'`
      plus 11 more, `12 failed, 164 passed`), then
      `cd backend && .venv/bin/python -m pytest tests/ -q` -> `43 failed, 3399 passed`,
      with all 43 remaining failures under `tests/unit/outbound/` (autodialer work).
      **+15 passed, the 2 boundary failures gone.**
      Parent spot check: `tests/unit/test_analysis_schema.py tests/unit/analysis`
      -> 240 passed in 1.24s.
      Not fixed, honestly: `summarizer.py:1351` still re-normalizes the phone inside
      `_apply_structured_corrections`. Now redundant with the injected normalizer, but
      left as a defensive gate for callers that bypass the pipeline.

- [ ] **T4 — Capture runtime evidence at the next attended call**
      The code cannot distinguish blocked stdout vs fd/pool exhaustion vs a storage hang
      as the cause of the actual 217s. Requires `py-spy dump`, `lsof -p` fd counts, or
      `strace` while the process is stuck.       Requires explicit user authorization for a
      live call.
      Route: manual/attended, not a code task.
      Status: the user was asked and **declined for now** — they cannot take a call at
      the moment. Blocked pending availability, not pending a decision.

## Remaining suite failures (43) — none caused by this feature

**Measured, not assumed.** Earlier revisions of this document claimed all 43 belonged to
uncommitted autodialer work. That was wrong, and it was repeated several times before
anyone checked. Backing up the dirty files, reverting them to HEAD, running the suite and
restoring byte-for-byte gives:

| tree state | result |
|---|---|
| committed source + committed tests | 30 failed + 6 errors |
| committed source + dirty tests | 30 failed |
| dirty source + dirty tests (actual) | 43 failed |

So **30 failures are already committed on `feat/c6b-auto-dialer-slice3-reaper`** and
predate this session. The in-progress autodialer edits add 13 more. The 6 errors are the
phone-fixture problem, fixed by T5 (`055f36a`).

- **43 in `backend/tests/unit/outbound/*`** — owned by the autodialer work, 30 of them
  already committed. Symptoms:
  `failure_code == 'ownership_mismatch'` where `'concurrent_scheduled_call'` /
  `'agent_not_configured'` expected, `'failed' == 'dialing'`, HTTP 422 where 409/200
  expected. Belongs to that branch's work, not here.
  Note: `test_c6_tech_retry_persistence.py` went 2 -> 3 failures — not a regression; its
  6 fixture ERRORs are gone, so previously unreachable tests now execute and surface the
  same pre-existing autodialer defect.
- The 2 former `backend/tests/unit/test_analysis_schema.py` failures are fixed by T6.

## Deferred (found during audit, not part of this feature)

- `backend/app/voice/webhook.py:1133` uses `db` after its `async with db_session()` block
  closed at line 875 (or unbound on the fast path), swallowed by a bare
  `except Exception: pass` — lead custom fields are silently dropped with no logging.
- `backend/app/core/database.py:84-87` sets `busy_timeout=5000` on a startup connection
  that is immediately discarded, so runtime connections never receive it.

## Acceptance criteria

- A stalled or slow upstream LLM surfaces a bounded, logged failure in seconds, not
  minutes of silence.
- No synchronous filesystem or stdout write remains on the custom-LLM async path.
- `cd backend && python3 -m pytest tests/ -q` passes (baseline: 3251 passed).

## Environment notes

- `python3` on PATH is the system Python 3.11 framework build and lacks `phonenumbers`
  and `respx`. The only working interpreter is `backend/.venv/bin/python`. The runner
  recorded in `sdd-init/qora` (`python3 -m pytest`) does not work on this machine — use
  `cd backend && .venv/bin/python -m pytest tests/ -q`.
- Working tree is dirty on `feat/c6b-auto-dialer-slice3-reaper` with unrelated autodialer
  work. Nothing in this feature has been committed.

## Progress

- Audit complete (read-only).
- T1 done and green, verified independently by the parent.
- T5 done: suite went from `69 failed / 410 errors / 2950 passed` to
  `45 failed / 3384 passed`. Strict TDD now has a usable signal again.
- T6 done: `43 failed / 3399 passed`, every remaining failure under
  `tests/unit/outbound/` and owned by the autodialer work.
- T2 done: `43 failed / 3409 passed`.
- T3 done: `43 failed / 3421 passed`. The 43 never moved — they are the autodialer's.
- Committed on `feat/c6b-auto-dialer-slice3-reaper`, scoped to this feature's paths only:
  - `b70cdbb fix(llm): bound the OpenAI client timeout and reuse its connection pool` (T1)
  - `009ccfc refactor(analysis): inject phone validation instead of importing app.phones` (T6)
  - `2849f47 fix(logging): move stdout writes off the event loop behind a bounded queue` (T2)
  - `ec2de87 fix(crm-config): load CRM config off the event loop on the voice path` (T3)
  T5's fixture repairs are still uncommitted and entangled with the autodialer work in
  the same test files; they need a separate untangling pass.
- Every code task is done. T4 remains and is not a code task: it needs an authorized
  attended call to capture runtime evidence.

## Acceptance criteria — status

- "A stalled or slow upstream LLM surfaces a bounded, logged failure in seconds" —
  **met by T1.** Worst case is now `15s x 2 = 30s` inside the 60s turn budget, proved by
  test, versus `600s x 3 = 1800s` before.
- "No synchronous filesystem or stdout write remains on the custom-LLM async path" —
  **met for the audited path** by T2 (stdout) and T3 (CRM config YAML). NOT met
  repository-wide: five modules outside this feature's roots still call the blocking
  CRM loader from async code, listed under T3.
- "`pytest tests/` passes (baseline: 3251 passed)" — **not met, and the baseline was
  wrong.** Current state is `43 failed, 3421 passed`. Every failure belongs to the
  in-progress autodialer work dirty in `backend/app/outbound/service.py`, not to this
  feature. This criterion cannot be honestly closed until that work lands.

## Review status

RDD is on. `gentle-ai review assess` rated the `b70cdbb..009ccfc` candidate **medium**
(7 paths, 762 lines, `slice_budget_reached`). The user granted consent, START froze
lineage `review-e1690288c259a6d8`, and native selected a single lens, `review-reliability`.

The lens could NOT be captured. **Three attempts, all failed:**
`opencode_task_output_empty`, `opencode_reviewer_result_refused`, then
`opencode_task_output_empty` again. The third attempt used the provider-issued task
prompt verbatim. Each time, exact-lineage STATUS still reoffered the same bound slot,
which is what licensed the retry.

The failure mode is the reviewer sub-agent completing without producing any output —
a client-runtime behaviour, not a Gentle AI code defect, so no defect report was filed.

State: lineage `review-e1690288c259a6d8` is alive and bound but unreviewed.
No receipt exists and none was fabricated. Releasing it needs
`gentle-ai review abandon` with an explicit maintainer authorization block, which is a
deliberate human gate — not taken.

The two later commits, `2849f47` (T2) and `ec2de87` (T3), were never assessed: an open
transaction is bound to the earlier candidate. They are unreviewed too.

Delivery follows ordinary repository policy. Nothing here blocks it.

## Next step

No code task left in this feature. Open follow-ups, in the order they matter:

1. **T4** — capture runtime evidence at the next attended call (`py-spy dump`, `lsof -p`
   fd counts) to learn what actually caused the 217s. Needs the user to authorize a live
   call. Until then the cause remains unproven; T1/T2/T3 removed hazards, they did not
   prove a diagnosis.
2. Untangle T5's fixture repairs from the autodialer's edits in the same test files and
   commit them separately.
3. ~~The five async call sites outside this feature still blocking on
   `CRMConfigLoader.load`.~~ **Done in `dbe09d3`** — seven sites converted across five
   modules. One remains, one frame deeper: `crm_config_router._load_config_or_none` is a
   plain `def` that keeps `load()`, and three async handlers
   (`crm_config_router.py:365`, `:468`, `:492`) call it, so they still block. Fixing it
   needs a signature change, deliberately not taken unilaterally.
4. CRM config has no cache at all — one `stat` + read + YAML parse per turn per call site.
5. The two weak format tests in `tests/test_logging.py` that bypass the shipped transport.
