# Tasks: Automatic Outbound Dialer Runner (Phase C6b)

Strict TDD. Focused suite gate per task group; full gate per slice:
`cd backend && python3 -m pytest tests/ -q` (baseline 3251 passing, ~101s).
No test may place a real call — use `respx` strict mode, `patch("app.outbound.service.ElevenLabsService")`,
`patch("app.outbound.service.dial_outbound_call")` (unit), and the `tick_db` fixture (`tests/integration/scheduler/test_tick.py`).

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | Slice 1 ~615, Slice 2 ~280, Slice 3 ~330 (total ~1225) |
| 400-line budget risk | Slice 1: Medium (615/800, largest); Slice 2: Low; Slice 3: Low |
| Chained PRs recommended | Yes — already forecast and accepted (3 slices) |
| Suggested split | PR 1 (Claim & dial) → PR 2 (Completion + tech_retry cancel) → PR 3 (Reaper) |
| Delivery strategy | auto-forecast, chained PRs pre-accepted |
| Chain strategy | **pending — orchestrator must ask the user: stacked-to-main vs feature-branch-chain.** Design recommends stacked-to-main (each slice safe alone behind default-off flag) but this has not been confirmed by the user. |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Medium

Slice 1 cannot split further at the migration seam (D3 — shipping the unique
index ahead of the CAS claim is a live regression: bulk `mark_due_calls_in_progress`
would `IntegrityError` on the first lead with two pending rows and wedge the
tick permanently). If a reviewer wants Slice 1 under 600, promote Decision 7
(the allowed-hours clamp, ~55 lines) to its own Slice 0 — nothing else in
Slice 1 depends on it.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Claim & dial: flags, CAS, index+migration, dial loop, D7 clamp, D7-fix | PR 1 | `pytest tests/unit/outbound/test_scheduled_call_guard.py tests/unit/scheduler/ tests/integration/scheduler/test_tick.py tests/integration/scheduler/test_migration.py -q` | `tick_db` integration harness: seed due row, run one `run_scheduler_cycle`, assert claim+dial with mocked ElevenLabs | `enable_auto_dialer` default `False`; revert `service.py` claim/dial code + migration `downgrade()` (step 2 only; step 1 data-fix is irreversible, documented) |
| 2 | Outcome-driven completion + decision 8 tech_retry cancellation | PR 2 | `pytest tests/unit/scheduler/ tests/unit/calls/ tests/integration/scheduler/test_tick.py -q` | `tick_db` end-to-end: due row → claimed → dialed → `close_session` → `completed`, assert parked `tech_retry` cancelled | Revert `resolve_scheduled_call_for_session` + `close_session` hook insertion; Slice 1 behavior unaffected (hook is additive) |
| 3 | Stranded-row reaper (classes a + b, release clamp, age-out) | PR 3 | `pytest tests/unit/scheduler/ tests/integration/scheduler/test_tick.py -q` | `tick_db` with injected `now=`: advance clock past both timeouts, assert no row remains `in_progress`; this is also the gate to flip `enable_auto_dialer=true` | Revert `reap_stranded_scheduled_calls` + its tick wiring; Slices 1–2 remain safe alone under the still-`False` flag |

## Phase 1 (Slice 1 / PR 1): Claim & Dial — ~615 lines

**Dependency**: none (first slice).

### 1.1 Config flags + validator

- [x] 1.1.1 RED: `tests/core/test_config.py` — `enable_auto_dialer=True` + `enable_outbound_calls=False` raises `ValueError` at Settings init; `auto_dialer_max_concurrent_dials < 1` rejected by field validator. (~15 lines)
- [x] 1.1.2 GREEN: `backend/app/core/config.py` — add `enable_auto_dialer: bool = False`, `auto_dialer_max_concurrent_dials: int = 1` (field_validator `>= 1`), `validate_auto_dialer_requires_outbound` `model_validator(mode="after")` declared after `validate_outbound_requires_webhook_auth` (`:311`), mirroring its raise-not-warn shape. (~30 lines)

### 1.2 Migration: duplicate resolution + partial unique index

- [x] 1.2.1 RED: `tests/integration/scheduler/test_migration.py` — seed two `in_progress` rows for one lead, run migration `20260727_0011_auto_dialer_active_lead_index`, assert exactly one survives (`in_progress`), the other is `failed` with the auto-resolve note, and `uq_scheduled_calls_active_lead` exists. Assert the operator-visible log includes the retired-row count. (~25 lines)
- [x] 1.2.2 GREEN: new `backend/alembic/versions/20260727_0011_auto_dialer_active_lead_index.py` (`down_revision="20260716_0010"`) — step 1: window-function `UPDATE` retiring all but the newest `in_progress` row per lead, log `rowcount`; step 2: `CREATE UNIQUE INDEX uq_scheduled_calls_active_lead ON scheduled_calls (lead_id) WHERE status = 'in_progress'` via raw `op.execute`; `downgrade()` drops the index only (step 1 is documented as irreversible in the migration docstring). (~70 lines)
- [x] 1.2.3 GREEN: `backend/app/scheduler/models.py.__table_args__` — add matching `Index("uq_scheduled_calls_active_lead", "lead_id", unique=True, sqlite_where=..., postgresql_where=...)` for ORM/test-DB parity. (~5 lines)

### 1.3 CAS claim

- [x] 1.3.1 RED: `tests/unit/scheduler/test_service.py` (or new `test_auto_dialer_claim.py`) — `_claim_one` returns `True` once and `False` for the loser on the same row (simulate race via pre-set status); a second lead-row claim raises `IntegrityError` inside `_claim_one`, is caught, logged as `auto_dialer_claim_conflict`, and returns `False`. (~25 lines)
- [x] 1.3.2 GREEN: `backend/app/scheduler/service.py` — add `_CLAIM_TIMEOUT_MINUTES=10`, `_MAX_STRANDED_HOURS=6`, `_claim_one(db, sc_id, now)` per the design's verbatim CAS `UPDATE ... WHERE status='pending'` + `IntegrityError` catch; bounded candidate `SELECT` (`status='pending' AND scheduled_at<=now ORDER BY scheduled_at LIMIT settings.auto_dialer_max_concurrent_dials`); `claim_due_scheduled_calls(db, limit)` wrapping both. (~50 lines)

### 1.4 `_set_scheduled_call_status` transition helper (D8)

- [ ] 1.4.1 RED: `tests/unit/scheduler/test_service.py` — helper sets `status` + `updated_at`, flushes, and is used by every new write site in this slice (assert via call-site test, not a standalone transition-table test — enforcement stays deferred per proposal scope decision). (~10 lines)
- [ ] 1.4.2 GREEN: `backend/app/scheduler/service.py` — add private `_set_scheduled_call_status(db, sc, new_status)`. (~10 lines)

### 1.5 Dial loop + cycle restructure

- [ ] 1.5.1 RED: `tests/integration/scheduler/test_tick.py` — `DialResult.failed`/`recurrent_error` → claimed row's `sc.status == "failed"`; `DialResult.dialing` → stays `in_progress` with `outcome_session_id` set; flag-off cycle (`enable_auto_dialer=False`) executes only `mark_due_calls_in_progress` (no `auto_dialer_*` events, byte-for-byte unchanged). (~35 lines)
- [ ] 1.5.2 GREEN: `backend/app/scheduler/service.py` — extract `run_scheduler_cycle(db, settings)` from `scheduler_tick`'s loop body; branch per design's data-flow diagram (reaper stub deferred to Slice 3 — call site added now, no-op until 1.6 lands its real body is NOT needed here, reaper is Slice 3 only); dial branch calls `claim_due_scheduled_calls` then `asyncio.gather` over `dial_outbound_call(..., scheduled_call=sc)` (local import, matching existing style), sets terminal/`outcome_session_id` per `DialResult`; emits `auto_dialer_cycle_started`, `auto_dialer_claimed`, `auto_dialer_dial_attempted`, `auto_dialer_dial_accepted`, `auto_dialer_dial_failed`, `auto_dialer_dial_exception` (forced `failed` on unexpected raise, since `dial_outbound_call`'s never-raises contract is a contract, not a guarantee). (~30 lines)

### 1.6 Decision 7 — allowed-hours clamp for `tech_retry` (independently revertable commit)

- [ ] 1.6.1 RED: `tests/unit/outbound/test_c6_tech_retry_persistence.py` — tech retry scheduled at 23:58 local → `scheduled_at` is next day's `scheduler_allowed_hours_start` in the client's `scheduler_timezone`; tech retry scheduled at 14:00 local (inside window) → exactly `now + 5min`, byte-for-byte unchanged. (~20 lines)
- [ ] 1.6.2 GREEN: `backend/app/scheduler/service.py::schedule_tech_retry` (`:634-635`) — replace fixed `now + 5min` with `calculate_scheduled_at(now_utc=now_utc, cooldown_minutes=_TECH_RETRY_DELAY_MINUTES, start_hour=..., end_hour=..., tz_str=...)`; `client is None` guard returns `None` + `tech_retry_client_not_found` warning; `tech_retry_deferred_to_allowed_hours` WARNING log when clamped; correct the now-false docstring at `:564` ("independent of client cooldown/hours") in the same commit. (~35 lines)

### 1.7 `get_active_scheduled_call_for_lead` multi-row fix (D7)

- [ ] 1.7.1 RED: `tests/unit/scheduler/test_service.py` — two active (`pending`/`in_progress`) rows for one lead (the D1-confirmed reachable state) → `get_active_scheduled_call_for_lead` returns one row instead of raising `MultipleResultsFound`. (~10 lines)
- [ ] 1.7.2 GREEN: `backend/app/scheduler/service.py:223-237` — replace `scalar_one_or_none()` with `.order_by(ScheduledCall.scheduled_at).limit(1)` + `result.scalars().first()`. (~5 lines)

### 1.8 REFACTOR + slice-1 close-out

- [ ] 1.8.1 Full-suite gate: `cd backend && python3 -m pytest tests/ -q` — must stay at 3251+N passing, 0 regressions.
- [ ] 1.8.2 Verify flag-off parity manually: run one `run_scheduler_cycle` with `enable_auto_dialer=False` against `tick_db`, assert `scheduler_tick_promoted` fires and zero `auto_dialer_*` events — the proposal's byte-for-byte guarantee.

## Phase 2 (Slice 2 / PR 2): Outcome-Driven Completion + Decision 8 — ~280 lines

**Dependency**: Slice 1 merged (`outcome_session_id`, `_set_scheduled_call_status`, claim/dial loop must exist).

### 2.1 Mapping table + resolution function

- [ ] 2.1.1 RED: new `tests/unit/scheduler/test_completion_hook.py` — `telephony_status='completed'` → `new_status='completed'`; `'voicemail'` → `'completed'`; `'no_answer'`/`'failed'`/`'recurrent_error'`/`'stale_in_call'` → `'failed'`; no linked `ScheduledCall` → returns `None` (no-op); row not `in_progress` → no-op (idempotent); non-terminal `telephony_status` → no-op. (~35 lines)
- [ ] 2.1.2 GREEN: `backend/app/scheduler/service.py` — `_TELEPHONY_TO_SCHEDULED_STATUS` dict per design; `resolve_scheduled_call_for_session(db, *, call_session_id, telephony_status, source="close_session")` — mutates in-memory only, caller owns flush/commit. (~40 lines)

### 2.2 `close_session` call site + ordering guard

- [ ] 2.2.1 RED: `tests/unit/calls/test_close_session_scheduled_call_hook.py` (new) — hook runs **after** `_apply_voicemail_heuristic` (`:704`) and **before** `_merge_sibling_sessions`/`flush()` (`:707-709`): assert a short-duration zero-turn outbound call resolves the linked `ScheduledCall` to `completed` reading the post-heuristic `voicemail` value, not the pre-heuristic `completed` (regression guard for the ordering bug). Second `close_session` call on the same session → idempotent, no duplicate resolution. Not added to the early `cs.status=="completed"` return (`:658`) — assert a second close via that path is still a no-op for the hook. (~30 lines)
- [ ] 2.2.2 GREEN: `backend/app/calls/service.py::close_session` — insert `resolve_scheduled_call_for_session(...)` call after `:704`, before `:707`, joining the existing flush. (~15 lines)

### 2.3 Decision 8 — cancel parked `tech_retry` on successful conversation

- [ ] 2.3.1 RED: `tests/unit/scheduler/test_completion_hook.py` — pending `tech_retry` for the lead is `cancelled` (via `_set_scheduled_call_status`) when this session resolves `new_status=='completed'`; pending `tech_retry` is **untouched** when this session resolves `'failed'`; an `in_progress` (already claimed) `tech_retry` is **not** cancelled; no pending `tech_retry` for the lead → no-op with no extra write. (~30 lines)
- [ ] 2.3.2 GREEN: `backend/app/scheduler/service.py` — add `get_pending_tech_retry_for_lead(db, *, client_id, lead_id)` (filters `trigger_reason=='tech_retry'`, `status=='pending'`); inside `resolve_scheduled_call_for_session`, when `new_status=='completed'`, look it up and cancel via `_set_scheduled_call_status(db, stale_retry, "cancelled")`; emit `tech_retry_cancelled_by_successful_call` WARNING with `scheduled_call_id`, `lead_id`, `resolved_from_session_id`. (~40 lines)

### 2.4 Integration + REFACTOR

- [ ] 2.4.1 RED→GREEN: `tests/integration/scheduler/test_tick.py` — end-to-end: due row → claimed → dialed (mocked ElevenLabs) → `close_session` → `ScheduledCall.status == 'completed'`; extend with a second seeded pending `tech_retry` for the same lead → asserted `cancelled` after the same `close_session` call. (~60 lines, spans 2.1–2.3 wiring)
- [ ] 2.4.2 Full-suite gate: `cd backend && python3 -m pytest tests/ -q` — 0 regressions vs. Slice 1 baseline.
- [ ] 2.4.3 Update `proposal.md`/`design.md` decision 8 status from "drafted" to "implemented" (doc-only, no code).

## Phase 3 (Slice 3 / PR 3): Stranded-Row Reaper — ~330 lines

**Dependency**: Slices 1–2 merged (`outcome_session_id`, completion mapping, `_set_scheduled_call_status` must exist). This slice is the gate for flipping `enable_auto_dialer=true` anywhere.

### 3.1 Class (a) — never dialed

- [ ] 3.1.1 RED: `tests/integration/scheduler/test_tick.py` — `in_progress` + `outcome_session_id IS NULL` + `updated_at < now-10min` + attempts remaining → released to `pending`, `scheduled_call_reaped_stale` (`requeued=True`); attempts exhausted → `failed`, `scheduled_call_reap_exhausted`. (~30 lines)
- [ ] 3.1.2 GREEN: `backend/app/scheduler/service.py` — class (a) branch of `reap_stranded_scheduled_calls(db, now=...)`: predicate + `attempt_number < max_attempts` → `pending` via `_set_scheduled_call_status`; else `failed`. (~35 lines)

### 3.2 Release clamp (must rewrite `scheduled_at` only when clamp moves it forward)

- [ ] 3.2.1 RED: `tests/integration/scheduler/test_tick.py` — row released at 02:00 local → `scheduled_at` clamped to next `scheduler_allowed_hours_start` (09:00); row released at 14:00 local (inside window) → `scheduled_at` **unchanged** (regression guard: this is what makes the 6h age-out bound a crash loop instead of resetting every pass). (~20 lines)
- [ ] 3.2.2 GREEN: reaper class (a) release path — `new_at = calculate_scheduled_at(now, 0, start, end, tz)`; assign `sc.scheduled_at = new_at` **only when `new_at > now`**. (~15 lines)

### 3.3 Age-out cap

- [ ] 3.3.1 RED: `tests/integration/scheduler/test_tick.py` — class (a) row with `now - scheduled_at > 6h` → `failed` regardless of remaining attempts, `scheduled_call_reap_exhausted`. (~15 lines)
- [ ] 3.3.2 GREEN: add `_MAX_STRANDED_HOURS=6` age-out check to the class (a) branch, evaluated before the attempts-remaining check. (~15 lines)

### 3.4 Class (b) — dialed, completion signal never arrived

- [ ] 3.4.1 RED: `tests/integration/scheduler/test_tick.py` — `in_progress` + `outcome_session_id NOT NULL` + linked `CallSession` at terminal `telephony_status` → resolved via the Slice-2 shared mapping table; non-terminal `telephony_status` → untouched (left for the 30-min sweeper); `outcome_session_id` pointing at a missing `CallSession` → `failed` + `scheduled_call_reap_session_missing` ERROR. (~35 lines)
- [ ] 3.4.2 GREEN: class (b) branch of `reap_stranded_scheduled_calls` — loads `CallSession`, reuses `_TELEPHONY_TO_SCHEDULED_STATUS` (Slice 2) for terminal statuses; missing session → treat as class (a) / `failed` + the ERROR event. (~40 lines)

### 3.5 Tick wiring + full-cycle no-stranding proof

- [ ] 3.5.1 RED: `tests/integration/scheduler/test_tick.py` — clock advanced past both the 10-min claim timeout and the 30-min telephony sweep timeout → **no** `ScheduledCall` remains `in_progress` after two cycles. (~25 lines)
- [ ] 3.5.2 GREEN: `run_scheduler_cycle` — call `reap_stranded_scheduled_calls(db)` whenever `enable_outbound_calls` is true (independent of `enable_auto_dialer`), **before** the claim step per the design's ordering (released/resolved rows must be re-claimable / index-free in the same cycle). (~20 lines)

### 3.6 Rollout gate + follow-up close-out (cross-slice, lands with this PR)

- [ ] 3.6.1 Flip `enable_auto_dialer` default check: confirm it is still `False` in every env config (`.env.example`, deploy configs) — this slice unblocks the flip, it does not perform it. Explicit gate, not a footnote.
- [ ] 3.6.2 File the follow-up issue: enforce `ScheduledCall.VALID_TRANSITIONS` through `_set_scheduled_call_status()` (single seam created across Slices 1–3) — reference `proposal.md`'s deferred-enforcement scope decision.
- [ ] 3.6.3 Full-suite gate: `cd backend && python3 -m pytest tests/ -q` — 0 regressions vs. Slice 2 baseline.
- [ ] 3.6.4 Rollout dry run per `design.md` Migration/Rollout: deploy with flag `False`, verify `scheduler_tick_promoted` fires and no `auto_dialer_*`/`scheduled_call_reap*` events except from the reaper on genuinely stale pre-existing rows; only then consider flipping the flag on one client with `auto_dialer_max_concurrent_dials=1`.
