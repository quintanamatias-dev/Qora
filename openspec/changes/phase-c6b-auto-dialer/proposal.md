# Proposal: Automatic Outbound Dialer Runner (Phase C6b)

## Intent

Phase C6 built the **policy** for retrying calls (when a lead should be called
back) but never built the **execution** (who actually places the call). The
60-second `scheduler_tick` promotes due `ScheduledCall` rows from `pending` to
`in_progress` and stops. Nothing dials. Nothing ever moves the row out of
`in_progress`.

Why this matters beyond a missing feature:

| Cost | Detail |
|---|---|
| Real money | Every scheduled recontact is a lead that was analysed, qualified, and queued — then dropped. |
| Real people | A lead told the agent "call me back at 4pm". Nobody calls. |
| Silent failure | Logs show `scheduler_tick_promoted` and the row shows `in_progress`. Both look healthy. Nothing alerts. This is the worst failure class we have: the system reports success while doing nothing. |

This change closes the gap **and** makes the failure modes loud.

## Scope

### In Scope

- A dialer runner inside the existing `scheduler_tick` that dials claimed rows via `dial_outbound_call(..., scheduled_call=sc)` — a parameter already built for this reuse and never wired.
- Both retry lanes: Qora-owned `tech_retry` **and** agent-scheduled recontacts (`auto_retry`, `followup_tool`, `manual`).
- Outcome-driven completion: `ScheduledCall` reaches `completed` only when the real call finishes.
- A stranded-row reaper covering **both** stranding classes (see below).
- A database-level claim guard so two processes cannot dial the same row or lead.
- New `enable_auto_dialer` flag (default `False`) + startup validator.
- Operator-configurable concurrency limit, default 1.

### Out of Scope (explicit non-goals)

| Non-goal | Why |
|---|---|
| Postgres `SELECT … FOR UPDATE SKIP LOCKED` | Blocked on B3. The claim design below is already correct on SQLite and needs no rewrite on Postgres. |
| Redis / distributed lock | Not needed once the claim is a DB compare-and-swap. |
| Reusing the B10 job executor | `dial_outbound_call` already owns its retry + `schedule_tech_retry` lane; stacking B10 double-retries the same failure and adds a second hidden flag dependency. |
| Calling-hours / quiet-hours work | Already solved at scheduling time by `calculate_scheduled_at()` (per-client timezone + hour window). Confirmed — no work needed. |
| ~~Fixing `schedule_tech_retry`'s deliberate hour-window bypass~~ | **Superseded by decision 7 — now IN scope.** Dormant only while nothing dials; the runner makes it a real midnight call. |
| Enforcing `ScheduledCall.VALID_TRANSITIONS` | See scope decision below. |
| Frontend / operator UI | None required. |

## Settled Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Runner executes **both** lanes (`tech_retry` and recontacts) | The queue is one table with one due-time semantics. Splitting lanes at execution time would duplicate the runner for no safety gain — the counters are already isolated at *scheduling* time (`auto_schedule` excludes `tech_retry`; `schedule_tech_retry` counts only its own). |
| 2 | `completed` means **the call actually finished**, not "dial accepted" | Mechanism, chosen from what already exists: `close_session()` (`backend/app/calls/service.py:609`) is the single convergence point for the ElevenLabs post-call webhook and `/end`, and already calls `update_telephony_status_on_session_end()`. The runner sets `outcome_session_id` at dial time; the `ScheduledCall` is resolved from the linked `CallSession`'s terminal `telephony_status` at that same point. The existing `stale_outbound_telephony_sweeper` is the backstop when the webhook never arrives. |
| 3 | Stranded rows are **auto-released and re-queued**, respecting existing attempt limits | A row needing a human to unstick it is the same silent failure with extra steps. Release to `pending` when attempts remain, `failed` when exhausted. |
| 4 | Multi-process double-dial is **solved here**, not deferred | Two guards: (a) an atomic conditional claim — `UPDATE … SET status='in_progress' WHERE id=? AND status='pending'`, dial only when `rowcount == 1`; (b) a partial unique index on `lead_id` where `status IN ('pending','in_progress')`, formalising an invariant the code *already assumes* (`get_active_scheduled_call_for_lead` calls `scalar_one_or_none()`, which raises on duplicates today). Both are correct under SQLite's WAL single-writer model and identically correct on Postgres — `SKIP LOCKED` later is an optimisation, not a rewrite. The in-process `asyncio.Lock` (`outbound/service.py:97`) stays as a fast path, no longer as the only guard. |
| 5 | Concurrency limit is a setting, default 1 | `auto_dialer_max_concurrent_dials: int = 1`. Default 1 makes the first production behaviour identical to a human clicking "Call Now" one at a time. |
| 6 | New `enable_auto_dialer: bool = False`, **AND**-composed with `enable_outbound_calls` | Manual dialing and unattended auto-dialing are different risk profiles: one is a deliberate single action, the other is an always-on loop. Overloading one flag means enabling manual testing silently enables the loop. Follows the existing `enable_job_executor` / `enable_outbound_calls` convention. A startup validator **fails loudly** if `enable_auto_dialer=true` while `enable_outbound_calls=false` — a silent no-op would make the operator believe the dialer is running. When the flag is off, the tick must not even query for candidates: existing behaviour stays byte-for-byte unchanged. |
| 7 | **Technical retries respect the client's allowed-hours window** | `schedule_tech_retry` (`backend/app/scheduler/service.py:553`) computes `scheduled_at = now + 5min` with **no** allowed-hours clamp, while `auto_schedule` clamps via `calculate_scheduled_at()` (`:517-523`). A call failing at 23:58 schedules a retry at 00:03 — dormant today only because nothing dials. The runner makes it a real midnight call, so this stops being inherited risk and becomes a defect this change introduces into production. Fix reuses the existing `calculate_scheduled_at()` clamp (no duplicated logic): pass `cooldown_minutes=_TECH_RETRY_DELAY_MINUTES` plus the client's window/timezone, so the result is identical (`now + 5min`) inside the window and rolls forward to the next allowed slot outside it. `_TECH_RETRY_MAX_ATTEMPTS=2` and the 5-minute delay stay unchanged — see design for the semantics analysis. Cost ~55 lines including tests; folded into slice 1, boundaries unchanged. |
| 8 | **A pending `tech_retry` is cancelled automatically when a real conversation for that lead completes.** Status: **implemented** (Slice 2 / PR 2 — `resolve_scheduled_call_for_session` + `get_pending_tech_retry_for_lead`, `backend/app/scheduler/service.py`). | Decision 7 widens the tech_retry parking window from 5 minutes to up to ~13 hours. `auto_schedule` rule 4 (`:434-442`) blocks scheduling a client-owned recontact while ANY pending/in_progress `ScheduledCall` exists for the lead — tech_retry included. Concrete failure: an 08:00 manual call succeeds and produces a "call me Tuesday" follow-up → `auto_schedule` is blocked by the stale parked tech_retry → the Tuesday recontact is never created → at 09:00 the now-meaningless tech_retry dials someone who spoke to us an hour ago. Fix: hang the cancellation off the same `close_session()` completion hook Slice 2 already introduces (`backend/app/calls/service.py:609`) — no new seam. A "successful conversation" is any call whose resolved `telephony_status` maps to `completed` under the Slice 2 mapping table (`completed`, `voicemail`) — reuses the concept the completion hook already computes, no new terminal-status vocabulary. Rejected: (a) expire the retry if it cannot run within ~2h — loses the contact entirely when no other recontact exists for that lead, reproducing the original bug; (b) accept as debt — decision 7 turned this from a 5-minute theoretical collision into a ~13-hour plausible one. Cost ~40 lines including tests; folded into slice 2 (same hook, same commit boundary as the completion mapping). |

## The Two Stranded States (critical)

Because completion is outcome-driven (decision 2), there are now **two**
distinct ways a row can strand. A reaper that only handles the first
reproduces the original bug one step downstream.

| Class | Symptom | Detection | Resolution |
|---|---|---|---|
| **(a) Never dialed** | Crash between claim and dial | `status='in_progress'` AND `outcome_session_id IS NULL` past a short claim timeout (~5–10 min — no provider work should be in flight in that window) | Release to `pending` if attempts remain, else `failed` |
| **(b) Dialed, completion signal never arrived** | Lost or failed post-call webhook | `status='in_progress'` AND `outcome_session_id IS NOT NULL` AND the linked `CallSession` has reached a terminal `telephony_status` | Resolve the `ScheduledCall` from the `CallSession`'s terminal state |

Class (b) needs no new timeout logic: `stale_outbound_telephony_sweeper`
already forces every stranded `CallSession` to a terminal status within 30
minutes. The reaper reads that result rather than re-inventing it.

The reaper runs whenever `enable_outbound_calls` is on, **independently of
`enable_auto_dialer`** — a row stranded during a brief pilot must still get
cleaned up after the flag is switched back off.

## Scope Decision: `VALID_TRANSITIONS`

`VALID_TRANSITIONS` (`backend/app/scheduler/models.py:30`) is currently
**decorative** — zero enforcement, zero test coverage, no function consults
it. Every writer hand-rolls `if`/`raise` checks.

**Recommendation: accept and defer enforcement — but do not inherit it
silently.** Reasoning: real enforcement means touching all four existing
write sites, including two operator endpoints already in production, plus
their tests (~120–180 lines) — scope creep into a change that is already over
budget, and unrelated to the bug being fixed. Instead, this change routes
**all** its new status writes through one private helper in the scheduler
service, so the follow-up enforcement change has exactly one seam to swap
instead of a scattered set of new `if` statements. Cost: ~10 lines. A
dedicated follow-up change should be filed at merge time.

## Capabilities

### New Capabilities

- `auto-dialer-runner`: claiming, dialing, concurrency limiting, outcome-driven completion, and stranded-row recovery for scheduled outbound calls.

### Modified Capabilities

- `outbound-call-trigger`: dialing gains a second, unattended trigger path; `ScheduledCall` linkage and completion semantics become part of the contract.

## Approach

Extend `scheduler_tick` inline (exploration option **a**) — it already owns
the 60s cadence, the `get_session()` pattern, and the `structlog` conventions.
A second loop would double-poll the same table; the B10 executor would
double-retry the same failure.

Per tick, with the flag on:

1. Claim due rows atomically (compare-and-swap, `rowcount == 1`).
2. Dial up to `auto_dialer_max_concurrent_dials` in parallel; record `outcome_session_id`.
3. On dial failure (`dial_outbound_call` never raises), mark the row `failed` — its own `schedule_tech_retry` lane handles rescheduling.
4. Leave successful dials `in_progress`; the post-call path resolves them.
5. Run the reaper for both stranded classes.

**Tests come first.** Strict TDD is active (`cd backend && python3 -m pytest
tests/ -q`, 3251 passing, ~101s). No new test infrastructure is needed: the
`test_tick.py` integration harness, the `test_dial_service.py` ElevenLabs
mocks, `test_no_live_calls.py`, and `test_scheduled_call_guard.py` already
cover every seam this change touches.

## Delivery: Chained PRs

Revised estimate **exceeds the 800-line review budget** — decisions 1, 2, 4
and 5 expanded scope past the exploration's original ~535–720.

| Slice | Contents | Est. lines | Ships first? |
|---|---|---|---|
| **1 — Claim & dial** | Flag + concurrency setting + startup validator; atomic CAS claim; partial unique index migration (with a pre-migration duplicate check); dial loop; `outcome_session_id` linkage; failure transitions; structured events; unit + integration tests | **~470** | **Yes** |
| **2 — Outcome-driven completion** | Resolve `ScheduledCall` from the linked `CallSession`'s terminal status at the `close_session()` convergence point; tests | ~245 | Second |
| **3 — Stranded-row reaper** | Both stranding classes (a) and (b), auto-release respecting attempt limits, tests | ~300 | Third |
| | **Total** | **~1015** | |

**Slice 1 ships first** because it is independently reviewable (claiming and
dialing is one coherent idea), independently safe (`enable_auto_dialer`
defaults to `False`, so merging changes nothing at runtime), and it is the
only slice the others depend on.

**Enablement gate:** the flag must stay `False` in every environment until
slice 3 merges. Slices 1 and 2 alone would dial without full stranded-row
recovery. The default-off flag makes this gate enforceable rather than a
convention.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `backend/app/core/config.py` | Modified | `enable_auto_dialer`, `auto_dialer_max_concurrent_dials`, startup validator |
| `backend/app/scheduler/service.py` | Modified | CAS claim, dial loop, transition helper, reaper |
| `backend/app/scheduler/models.py` | Modified | Partial unique index on active rows per lead |
| `backend/app/calls/service.py` | Modified | Completion hook at the `close_session()` convergence point |
| `backend/app/outbound/service.py` | Unchanged | `scheduled_call=` kwarg already exists; consumed, not modified |
| `backend/app/main.py` | Minimal | Reuses the existing `scheduler_task`; no new background task |
| Alembic migration | New | Partial unique index |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Auto-dialer enabled while outbound disabled → silent no-op | Medium | Startup validator fails loudly. This is the exact failure class being eliminated. |
| Partial unique index migration fails on existing duplicate active rows | Medium | Pre-migration duplicate detection + resolution step in slice 1; the code already assumes this invariant. |
| Many due rows in one tick block the 60s cadence | Low | Concurrency cap (default 1) bounds in-flight dials; per-tick claim batch is bounded. |
| Runner dials while an operator clicks "Call Now" | Low | Existing Guard 3 / 3b already handle this pair and return a clean `DialResult`, never raising. |
| ~~`tech_retry` dials outside decent hours (inherited)~~ | ~~Low~~ | **Resolved by decision 7** — the clamp now applies. Residual risk moved to design: a tech retry rolled forward to the next allowed slot holds the lead's active-row slot for up to ~13h, deferring `auto_schedule`'s recontact for that lead. Accepted. |
| `ScheduledCall` state machine stays unenforced | Medium | Accepted and deferred; new writes funnel through one helper so the follow-up has a single seam. |
| Slices 1–2 merged, flag enabled before slice 3 | Low | Enablement gate documented; flag defaults `False`. |

## Rollback Plan

Set `ENABLE_AUTO_DIALER=false`. The tick reverts to promote-only behaviour on
the next 60s cycle with no in-flight state depending on the flag. Rows already
`in_progress` are resolved by the reaper (which runs regardless of the flag).
Full code rollback is a revert of the slice PRs in reverse order; the only
non-reversible artefact is the unique index migration, which is safe to leave
in place since it encodes an invariant the existing code already assumes.

## Success Criteria

**Proves it works:**

- [ ] A due `ScheduledCall` is claimed, dialed, and reaches `completed` only after the real call ends — verified against a real DB in the `test_tick.py` harness with mocked ElevenLabs.
- [ ] Both `tech_retry` and recontact rows are dialed by the same path.
- [ ] Two concurrent claim attempts on one row produce exactly one dial (`rowcount == 1` on the winner, 0 on the loser).
- [ ] Concurrent in-flight dials never exceed `auto_dialer_max_concurrent_dials`.
- [ ] With `enable_auto_dialer=false`, the tick issues no candidate query and behaviour is unchanged.

**Proves it fails loudly, not silently:**

- [ ] `enable_auto_dialer=true` + `enable_outbound_calls=false` fails at startup with an explicit message — the app does not boot into a false-healthy state.
- [ ] A row stranded with no dial (class a) is released and re-queued within the claim timeout, emitting `scheduled_call_reaped_stale`.
- [ ] A row stranded after dialing with no completion signal (class b) is resolved from the linked `CallSession`'s terminal status, emitting a distinct event.
- [ ] Every claim, dial attempt, dial failure, completion, and reap emits a structured event following existing naming conventions (`auto_dialer_dial_attempted`, `auto_dialer_dial_failed`, `scheduled_call_reaped_stale`).
- [ ] No `ScheduledCall` can sit `in_progress` indefinitely — asserted by a test that advances the clock past both timeouts.
