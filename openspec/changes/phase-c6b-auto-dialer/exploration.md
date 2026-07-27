# Exploration: Automatic Outbound Dialer Runner (Phase C6b)

## Current State

Phase C6 (`c8bfbda`) built the retry/recontact **policy** (when a call should
happen) but never the **execution** (who actually dials it). Today:

- `scheduler_tick()` (`backend/app/scheduler/service.py:701`), a 60s loop
  started in `lifespan()` (`backend/app/main.py:179`), calls only
  `mark_due_calls_in_progress()` (`:666`) — flips due `pending` rows to
  `in_progress` and stops. No dial is ever fired from this path.
- `dial_outbound_call()` (`backend/app/outbound/service.py:135`) is called
  from exactly one place: the manual "Call Now" HTTP handler in
  `backend/app/outbound/router.py`. It already accepts a `scheduled_call`
  kwarg (`:142`, comment: *"None for manual trigger; future scheduler passes
  a ScheduledCall"*) — the function was **designed** for this use case and
  never wired up.
- Nothing in the codebase ever transitions a `ScheduledCall` row out of
  `in_progress`. `complete_scheduled_call()` (`:322`) and
  `cancel_scheduled_call()` (`:240`) exist but are only reachable from
  operator-facing HTTP endpoints in `backend/app/scheduler/router.py`
  (`:288`, `:377`) — never called automatically.

Net effect confirmed by evidence, not assumption: a scheduled retry is
created, promoted to `in_progress` by the tick, logged as
`scheduler_tick_promoted`, and then sits forever. `in_progress` **is** a
practical dead end today — no code path exits it without a human clicking a
button.

## Research Answers

### Q1 — Full lifecycle & legal transitions

`VALID_TRANSITIONS` (`backend/app/scheduler/models.py:30`):

```python
"pending":     ["in_progress", "cancelled", "expired"],
"in_progress": ["completed", "failed", "cancelled"],
"completed": [], "failed": [], "cancelled": [], "expired": [],
```

⚠️ CodeGraph flags this dict has **no covering tests** — nothing asserts the
transition table is actually enforced anywhere (see Landmine #1 below).

Creation paths, all → `status="pending"`:
- `auto_schedule()` (`:350`) — client-owned recontact, rules-gated (scheduler
  enabled, outcome matches `scheduler_retry_on_outcomes`, not `do_not_call`,
  dedup guard, `attempt_count < scheduler_max_attempts`).
- `schedule_tech_retry()` (`:553`) — Qora-owned transient-failure retry, max 2,
  fixed 5-minute delay, isolated by `trigger_reason="tech_retry"` so it never
  touches the client's recontact counter.
- Manual creation via `ScheduledCallCreate` (`backend/app/scheduler/router.py`,
  schema at `backend/app/scheduler/schemas.py:20`).

`pending → in_progress`: only `mark_due_calls_in_progress()` (`:666`), called
by `scheduler_tick`.

`in_progress → completed | failed`: **only** via
`complete_scheduled_call()`/manual reschedule-to-cancelled endpoints — no
automatic caller exists. `dial_outbound_call()` never touches
`ScheduledCall.status` at all; it only mutates `CallSession.telephony_status`.
This means even wiring the runner to *call* `dial_outbound_call` is
insufficient by itself — the runner must **also** explicitly transition the
`ScheduledCall` row, or `in_progress` remains a dead end with a different
symptom (a call fires, but the queue row still looks stuck).

**Yes — `in_progress` is a dead end in practice**, confirmed by grep across
the whole `backend/app` tree: no non-test, non-HTTP-handler code calls
`complete_scheduled_call`, `cancel_scheduled_call`, or writes
`ScheduledCall.status` outside the tick's promotion and the two operator
endpoints.

### Q2 — Where the runner should live

| Option | Fit | Verdict |
|---|---|---|
| **(a) Extend `scheduler_tick` inline** | Reuses the existing 60s poll, existing `get_session()` pattern, existing `structlog` conventions. `dial_outbound_call` already accepts `scheduled_call=` for exactly this. | **Recommended** |
| (b) New dedicated async loop in `main.py` lifespan | Doubles DB polling of the same table on an independent cadence — two loops racing/duplicating `mark_due_calls_in_progress`-style queries against `scheduled_calls`. No architectural benefit over (a); adds a second `asyncio.create_task` + shutdown-cancel block to maintain (`main.py:169-237` already has 4 of these). | Rejected — redundant |
| (c) Reuse B10 durable job executor (`backend/app/jobs/`, `enable_job_executor`) | B10's `_run_job()` (`backend/app/jobs/executor.py:223`) gives per-job retry/backoff and crash recovery via `executor.recover()` (`main.py:163`). But: (1) it is a *one-shot dispatch* primitive (enqueue → run → terminal), not a *recurring poll* primitive — you'd still need `scheduler_tick` (or something like it) to find due rows and `enqueue()` a job per row, so it doesn't replace the polling loop, only wraps the dial call; (2) `dial_outbound_call` **already implements its own retry** (one immediate retry, then `schedule_tech_retry` on repeated transient failure, `outbound/service.py:605-659`) — bolting B10's retry/backoff on top would double-retry the same failure through two independent mechanisms; (3) it stacks a second off-by-default flag (`enable_job_executor`) as a hidden prerequisite for the new flag, complicating the "one kill switch" requirement. | Rejected for v1 — real overlap with existing dial-level retry, not free durability |

**Recommendation: (a).** Concretely: after `mark_due_calls_in_progress()`
promotes rows, iterate the newly-`in_progress` rows (or re-query
`status=in_progress` due-or-recent rows) inside the same tick, load
`lead`/`agent`/`client`, call `dial_outbound_call(..., scheduled_call=sc)`,
then transition `sc.status` based on `DialResult.status`
(`dialing`→ leave `in_progress`+set `outcome_session_id`; the CallSession's
own webhook/sweep lifecycle later resolves the real outcome — `completed`
should be set by the **existing** webhook/reconciliation path once a
terminal telephony_status is observed, not by the runner blindly marking
`completed` the moment the API call is accepted. `failed`/`recurrent_error`
→ `sc.status = "failed"` immediately, since `dial_outbound_call` never raises
and already handles its own reschedule via `schedule_tech_retry`).

This is a **new coupling to design carefully in the spec phase**: does
"in_progress → completed" mean "API accepted" or "call actually finished"?
Evidence says CallSession's terminal state is resolved later (webhook or
`stale_outbound_telephony_sweeper`, `outbound/sweep.py:440`) — so the
ScheduledCall's own `completed` transition should probably be driven by that
same downstream resolution, not synchronously by the runner. Flag this as an
open design question for the spec phase, not resolved by this exploration.

### Q3 — Concurrency & duplicate-call safety across processes

`_get_lead_lock()` (`backend/app/outbound/service.py:97`) is an in-process
`asyncio.Lock` keyed by `lead_id` in a module-level dict
(`_LEAD_LOCKS: dict[str, asyncio.Lock]`, `:94`). The code's own comment block
(`:276-297`) already documents this is an MVP trade-off: *"Future: move to a
distributed (Redis) lock with a commit-then-unlock protocol for multi-process
deployments."*

**Confirmed: this does NOT survive multi-process.** Two separate uvicorn
worker processes (Phase B2 public deploy) each get their own
`_LEAD_LOCKS` dict — the lock provides zero cross-process exclusion. The
in-DB guards (`_find_active_call_session`, `_find_in_progress_scheduled_call`
at `:341`) are real SELECT-then-check queries, but between the SELECT and the
`db.commit()` of the new `CallSession`, a second process's SELECT can still
observe the pre-commit state (classic TOCTOU) — the current code only
prevents this *within one process* because the lock serializes access before
the SELECT even runs.

**What's needed for multi-process safety (deferred to B3/Postgres per user's
own phasing, but must be flagged now):**
- SQLite has no `SELECT ... FOR UPDATE`; the only real CAS primitive
  available is an atomic `UPDATE ... WHERE status='pending' AND id=?`
  (checking `rowcount==1`) to claim a row before promotion — the same
  pattern already used implicitly by the single bulk `UPDATE` in
  `mark_due_calls_in_progress`, but currently done as SELECT-then-mutate-then-
  flush, not an atomic conditional UPDATE.
- SQLite's single-writer model + WAL (already configured per `main.py:142`
  `db_initialized`) serializes writes at the file level, which *coincidentally*
  narrows (but does not eliminate) the TOCTOU window for a single-file SQLite
  deployment even across processes — worth noting as a partial mitigation,
  not a guarantee.
- True fix (Postgres, B3-deferred): `SELECT ... FOR UPDATE SKIP LOCKED` on
  the claim query, or a unique partial index / advisory lock keyed by
  `lead_id`.

**v1 recommendation given B3 is deferred:** keep the current
single-process assumption **explicit and documented** (not silently
reused), and replace the SELECT-then-mutate promotion with an atomic
conditional `UPDATE` per row (`WHERE status='pending' AND scheduled_at<=now`
returning affected id) so that if B2 multi-process ships before B3, the claim
step degrades to "safe within SQLite's write serialization" rather than
"actively racy." This is a small, cheap hardening even before Postgres.

### Q4 — Collision with manual "Call Now"

Existing guards, verified in `outbound/service.py`:
- Guard 3 (`:301-322`): rejects if an active `CallSession` exists for the
  lead (`concurrent_active_session`).
- Guard 3b (`:324-360`): rejects if an `in_progress` `ScheduledCall` exists
  for the lead **other than the one currently being processed**
  (`concurrent_scheduled_call`) — this guard already explicitly special-cases
  `scheduled_call is not None` to exclude itself (`exclude_sc_id`,
  `:340`), which only makes sense if it was written anticipating exactly this
  runner. Router-side surfacing at `outbound/router.py:299-313` returns a 409
  for both guard codes.

So: **operator clicks Call Now while runner is dialing the same lead** → the
runner's `dial_outbound_call` call (holding the lead lock, `CallSession`
already committed) blocks the manual call attempt via Guard 3
(`concurrent_active_session`), assuming both run in the same process (see
Q3). **Runner tries to dial while operator's manual call is active** →
symmetric, same guard rejects the runner's attempt safely (`DialResult(status=
"failed", failure_code="concurrent_active_session")` — never raises).

What's missing: nothing structural for same-process collisions — the guards
already anticipate this pair. The gap is purely the Q3 cross-process gap:
these guards are DB-query + in-process-lock based, not a DB-level CAS, so
they inherit the same multi-process weakness.

### Q5 — Orphaned `in_progress` rows

Two distinct orphan risks exist and need separate handling:

1. **`ScheduledCall` stuck `in_progress`** if the process crashes between
   `mark_due_calls_in_progress` committing the promotion and the runner
   calling `dial_outbound_call`. No existing reaper covers `ScheduledCall`
   rows — this is a **net-new gap** introduced by adding the runner (it
   doesn't exist today because nothing ever promotes-then-dials).
2. **`CallSession` stuck `dialing`/`ringing`** if the process crashes
   mid-dial — this **already has a reaper**:
   `stale_outbound_telephony_sweeper()` (`backend/app/outbound/sweep.py:440`),
   started conditionally on `enable_outbound_calls` (`main.py:186-192`),
   which transitions stale sessions >30min old to `stale_in_call` or
   `completed` depending on webhook evidence.

**Recommendation:** add a matching reaper for risk #1 — e.g. a
`stale_scheduled_call_sweeper` (or fold the check into the existing tick)
that requeues (`in_progress → pending`, or `→ failed` if `attempt_number ≥
max_attempts`) any `ScheduledCall` stuck `in_progress` past a timeout (e.g.
5-10 min — far shorter than the CallSession's 30-min window, since between
promotion and dial there should be no meaningful provider-side work in
flight) **with no linked `outcome_session_id`**. This is a small, mandatory
addition, not deferrable — without it, a single crash during rollout
silently strands rows exactly the way the current bug already does, just
one step later in the pipeline.

Observability: B9 (`openspec/changes/b9-observability`) already gives
`structlog` context binding (`bind_job_context`, `calls/service.py` pattern)
and Sentry init (`main.py:124`). The runner and its reaper should emit
structured events following the existing naming convention
(`scheduler_tick_promoted`, `outbound_dial_blocked_*`) — e.g.
`auto_dialer_dial_attempted`, `auto_dialer_dial_failed`,
`scheduled_call_reaped_stale`. No new observability infrastructure is
needed, only conformant event names.

### Q6 — Calling-hours / decency constraints

**Already fully handled at scheduling time — no new work needed.**
`calculate_scheduled_at()` (`backend/app/scheduler/service.py:49-93`) clamps
every computed `scheduled_at` into `[scheduler_allowed_hours_start,
scheduler_allowed_hours_end)` in the client's `scheduler_timezone`
(`ZoneInfo`-based, per-client column on `Client`,
`backend/app/tenants/models.py`). Both `auto_schedule` (`:517-523`) and the
manual reschedule endpoint (`reschedule_call`, `:308-314`, called from
`scheduler/router.py`) route through this or an equivalent hour-window check.

The one caveat: `schedule_tech_retry()` (`:553`) **deliberately bypasses**
allowed-hours clamping — "Uses a hardcoded 5-minute delay (independent of
client cooldown/hours)" (`:564`). This is intentional per its own docstring
(transient provider retries are Qora-owned, not client-facing scheduling),
but worth flagging explicitly: if a lead's `next_action_at` lands at 11:58pm
and a tech_retry fires 5 minutes later, the runner *will* dial at 12:03am.
This is pre-existing C6 behavior, not something this phase introduces or
needs to fix — but it should be named as an accepted risk in the proposal,
not silently inherited.

### Q7 — Counter separation

Confirmed correctly isolated already, purely at scheduling time — the runner
does not need to touch either counter:
- `tech_retry` count: `schedule_tech_retry()` counts existing
  `trigger_reason == "tech_retry"` rows (`:596-603`), capped at
  `_TECH_RETRY_MAX_ATTEMPTS = 2` (`:38`).
- Client recontact count: `auto_schedule()` counts rows where
  `trigger_reason != "tech_retry"` (`:447-454`), capped at
  `client.scheduler_max_attempts`, with `calculate_backoff_delay()`
  (`:96-114`) applying `scheduler_backoff_multiplier` per attempt.

The runner's only interaction with these counters is indirect: firing the
dial is what eventually produces the outcome that a future `auto_schedule` or
`schedule_tech_retry` call will count. No new counter logic belongs in the
runner itself.

### Q8 — Testability without dialing anyone

Existing fakes/fixtures directly reusable:
- `backend/tests/unit/outbound/test_dial_service.py`,
  `test_dial_service_behavior.py` — mock `ElevenLabsService` /
  `initiate_outbound_call`, exercising `dial_outbound_call` end-to-end
  without network calls.
- `test_no_live_calls.py` — an existing guard test whose name implies it
  already asserts no real provider call escapes in the test suite (passed
  when run: `6 passed in 0.20s` alongside `test_scheduled_call_guard.py`).
- `test_scheduled_call_guard.py` — already tests the Guard 3b overlap logic
  the runner will depend on.
- `backend/tests/integration/scheduler/test_tick.py` — a DB-backed
  integration harness (`tick_db` fixture, real aiosqlite DB via
  `init_db_with_migrations`, real `seed_quintana` + `create_lead`) already
  proves the pattern for testing `scheduler_tick`/`mark_due_calls_in_progress`
  against a real (temp-file) DB. This is the natural harness to extend for
  the runner: seed a due `ScheduledCall`, monkeypatch/mock the ElevenLabs
  client the same way `test_dial_service.py` does, run the extended tick,
  assert `ScheduledCall.status` and `CallSession` state.

No new test infrastructure is required — this is testable entirely with
existing fixtures and mocking conventions, keeping Strict TDD viable without
inventing new patterns.

## Kill Switch — Validating the User's Requirement

**The user's position is correct and should NOT be merged into
`enable_outbound_calls`.** Evidence for why a separate flag is required, not
just preferred:

1. `enable_outbound_calls` gates the **capability** to dial at all (manual +
   automatic) and is validated to require `QORA_WEBHOOK_AUTH_ENABLED=true`
   (`config.py:337`). It is already a meaningful, independently-reasoned-about
   flag with its own security invariant. Overloading it to also mean "and
   also auto-dial unattended" conflates two very different risk profiles:
   an operator manually clicking "Call Now" is a deliberate, one-call-at-a-time
   action; an always-on background loop dialing whoever is due is unattended
   and unbounded.
2. The user's stated fear — an untrusted runner firing a real call before
   it's proven — is exactly the scenario the C6 gap already produces today by
   accident (rows silently stuck) once someone flips `enable_outbound_calls`
   for manual testing. If the runner were gated by the *same* flag, enabling
   manual Call Now testing would **also** silently activate the automatic
   loop the moment there's a due row — the opposite of what the user is
   asking for.
3. Precedent already exists in the codebase for exactly this composition
   pattern: `stale_outbound_telephony_sweeper` is gated by
   `enable_outbound_calls` alone (`main.py:186`), while `enable_job_executor`
   is a fully independent flag gating unrelated startup behavior
   (`main.py:160`). A new `enable_auto_dialer: bool = False` flag,
   **AND**-composed with `enable_outbound_calls` (i.e. the runner only dials
   when *both* are true — dialing capability must exist AND auto-mode must be
   explicitly opted into), follows the existing convention directly.

**What else the flag must guard**, beyond "should the runner call
`dial_outbound_call`":
- The tick's post-promotion dial loop must short-circuit entirely (not even
  query for candidate rows) when `enable_auto_dialer` is false — so the
  *existing* behavior (`mark_due_calls_in_progress` only) is byte-for-byte
  unchanged when the new flag is off. This preserves the "flip it off
  instantly" guarantee: no in-flight state depends on the flag being read
  mid-tick.
- The new reaper (Q5) should probably run **regardless** of
  `enable_auto_dialer` — a stuck `in_progress` row is a symptom worth cleaning
  up even if auto-dialing is currently disabled (e.g. it was enabled briefly,
  crashed, then got turned back off). This is a genuine design choice for the
  spec phase, not fully resolved here.
- Given `enable_outbound_calls` requires `QORA_WEBHOOK_AUTH_ENABLED=true`,
  and the runner requires `enable_outbound_calls`, `enable_auto_dialer=true`
  transitively requires webhook auth too — worth a startup-time validator
  mirroring `validate_outbound_requires_webhook_auth` (`config.py:311`) that
  fails loudly if someone sets `enable_auto_dialer=true` while
  `enable_outbound_calls=false`, rather than silently no-op'ing. A silent
  no-op here is a worse trap than a hard failure: the operator would believe
  the dialer is on.

## Mandatory vs. Deferrable Safety Mechanisms

**Mandatory for v1 (do not ship without these):**
1. `enable_auto_dialer` flag, AND-composed with `enable_outbound_calls`,
   defaulting False, with a startup validator preventing the silent-no-op
   trap described above.
2. Explicit `ScheduledCall.status` transition after every
   `dial_outbound_call` call (currently missing entirely) — otherwise the
   bug is only half-fixed (calls fire, but the queue view still lies).
3. Stale `in_progress` `ScheduledCall` reaper (Q5, risk #1) — without it, the
   very first crash during rollout reproduces a variant of the original bug.
4. Structured logging for every new transition, following existing event
   naming conventions (Q5 observability note).

**Deferrable (explicitly, with a documented follow-up):**
1. Cross-process/DB-level CAS locking (Q3) — genuinely blocked on B3
   (Postgres); defer, but land the cheap atomic-`UPDATE` hardening for the
   promotion step now since it's nearly free and reduces (not eliminates)
   risk if B2 (multi-process) ships before B3.
2. Reusing B10's durable job executor (Q2 option c) — revisit only if
   evidence emerges that inline dialing under the tick causes tick-loop
   latency problems (e.g. many due calls in one tick blocking the 60s
   cadence) or if unattended crash-retry semantics beyond what
   `dial_outbound_call`'s built-in retry + tech_retry lane already provide
   become necessary.
3. Any change to `schedule_tech_retry`'s hour-window bypass (Q6 caveat) —
   pre-existing accepted behavior, out of scope for this phase.

## Hidden Landmine

**`VALID_TRANSITIONS` (`backend/app/scheduler/models.py:30`) has zero test
coverage and, per CodeGraph's blast-radius scan, only one caller in the
entire codebase** — and that caller could not be located as an actual
enforcement point during this exploration (no `validate_transition`-style
function was found calling into `ScheduledCall`'s `VALID_TRANSITIONS`; the
similarly-named `validate_transition` at `backend/app/calls/states.py:91` is
for `CallStatus`, a **different** state machine belonging to `CallSession`,
not `ScheduledCall`). In other words: **the `ScheduledCall` transition table
is currently decorative** — nothing in the runtime code path actually
enforces that `sc.status = "completed"` can't be set from `sc.status =
"pending"`, or that an invalid transition raises. Every existing writer
(`mark_due_calls_in_progress`, `complete_scheduled_call`,
`cancel_scheduled_call`) manually checks `sc.status` with hand-written
`if`/`raise ValueError` guards instead of consulting the table.

This matters directly for the new runner: if the runner's transition logic
is added as another set of hand-written `if` checks (following the existing
pattern), that's consistent with today's code but perpetuates an
un-enforced state machine — a future change that touches `ScheduledCall`
status has no structural safety net. **Recommendation for the spec phase:**
either (a) accept the existing pattern for consistency and scope a
`validate_transition`-style helper as a fast-follow, or (b) use this phase
as the trigger to add real enforcement (a `validate_transition(from, to)`
helper mirroring `calls/states.py:91`, called by all four write sites). (b)
is more correct but expands scope beyond "add the runner" — flag this as a
scope decision for the proposal, not something this exploration resolves.

## Size Estimate

Rough estimate based on the surface area actually touched (not
speculative):

| Area | Est. changed lines |
|---|---|
| `config.py`: new flag + validator | ~30 |
| `scheduler/service.py`: dial loop + status transitions + reaper | ~120-160 |
| `main.py`: wiring (mostly none — reuses existing `scheduler_task`) | ~5-10 |
| Unit tests (dial loop, flag composition, validator) | ~150-200 |
| Integration tests (extend `test_tick.py` harness) | ~150-200 |
| Reaper + its tests | ~80-120 |
| **Total** | **~535-720** |

This likely fits **under the 800-line review budget as a single PR**, but is
close enough to the ceiling that the reaper (Q5, mandatory) is the natural
split point if it comes in over budget: PR1 = flag + inline dial loop +
status transitions + tests; PR2 = stale-row reaper + its tests. Recommend
sizing precisely once the design phase fixes the exact transition semantics
(the open question in Q2 about when `completed` is set materially affects
LOC — if the runner must also listen for/poll CallSession terminal state
that's meaningfully more code than a fire-and-forget `in_progress` stays
`in_progress` until the existing sweep/webhook resolves it).

## Ready for Proposal

**Yes**, with one explicit decision to carry into the proposal/design phase
rather than resolve here: **when exactly does `ScheduledCall.status` become
`completed`** — synchronously when `dial_outbound_call` returns `dialing`, or
asynchronously when the linked `CallSession` reaches a terminal
`telephony_status` (webhook or sweep-driven)? This exploration found strong
evidence for the latter (Q2) but it's a real design fork with different LOC
and coupling implications, not a research question with one factual answer.
