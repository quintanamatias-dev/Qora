# Design: Automatic Outbound Dialer Runner (Phase C6b)

## Technical Approach

Confirm the proposal's option (a): extend `scheduler_tick`. One addition — the
tick body is extracted into `run_scheduler_cycle(db, settings)` so tests drive
one cycle instead of an infinite `while True` loop. Per cycle:

```
run_scheduler_cycle(db, settings)
  ├─ if enable_outbound_calls        → reap_stranded_scheduled_calls(db)      # slice 3
  ├─ if enable_auto_dialer AND enable_outbound_calls
  │      → claim_due_scheduled_calls(db, limit)   # CAS, replaces bulk promote
  │      → asyncio.gather(dial…)                  # slice 1
  └─ else                            → mark_due_calls_in_progress(db)         # unchanged
```

Claim replaces bulk promotion when the dialer is on — promoting rows we will
not dial is the original bug. With `enable_auto_dialer=False` the executed path
is byte-for-byte today's behaviour.

## Architecture Decisions

| # | Decision | Alternatives rejected | Rationale |
|---|---|---|---|
| D1 | Partial unique index scoped to **`status='in_progress'` only**, not `('pending','in_progress')` | Proposal's `IN ('pending','in_progress')` | **Challenge to decision 4, with evidence.** `schedule_tech_retry`'s dedup guard (`service.py:577-584`) filters `trigger_reason == "tech_retry"` only. So a lead with an active `auto_retry` row *and* a new `tech_retry` row is a normal, reachable state — and it is guaranteed on every `recurrent_error` from a scheduled dial (the `in_progress` row is still `in_progress` when `dial_outbound_call` calls `schedule_tech_retry` at `outbound/service.py:676`). The proposal's index would raise `IntegrityError` on that path every time. `in_progress`-only enforces exactly the double-dial invariant and collides with nothing. |
| D2 | Claim is a per-row conditional `UPDATE`, `rowcount == 1`, `IntegrityError` caught as "claim lost" | Bulk `UPDATE`; `SELECT … FOR UPDATE` | Bulk update cannot attribute a unique-index violation to one row. Catching `IntegrityError` turns D1 into a working cross-process guard instead of a crash. Identical on Postgres; `SKIP LOCKED` later is an optimisation. |
| D3 | Index + CAS claim **must ship in the same slice** | Migration-only slice 1a | The existing bulk `mark_due_calls_in_progress` promotes *all* due rows in one flush. Two pending rows for one lead (auto_retry + tech_retry) both promote → `IntegrityError` → `scheduler_tick_failed`, and the tick never promotes again. Shipping the index before the CAS is a live regression. This is why slice 1 cannot be split further. |
| D4 | Concurrency bound = **claim batch size**, no semaphore | `asyncio.Semaphore` over an unbounded batch | The cycle awaits `gather` before the next sleep, so claiming ≤ N rows *is* the in-flight bound. Fewer moving parts and trivially assertable. |
| D5 | Claim timestamp = existing `updated_at`, no new column | New `claimed_at` column | For rows matching class (a) (`in_progress` + `outcome_session_id IS NULL`) the CAS is provably the last writer. A column would duplicate a fact the row already carries; saves ~25 lines of model/migration/test. |
| D6 | Decision 7 clamp = one call to the existing `calculate_scheduled_at()` | New tech-retry-specific window helper | Zero duplicated clamp logic; the function is pure and already test-covered. Inside the window it returns `now + 5min` exactly — the current behaviour is preserved bit-for-bit. |
| D7 | Fix `get_active_scheduled_call_for_lead` to `.order_by(scheduled_at).limit(1)` + `.first()` | Leave as `scalar_one_or_none()` | Per D1 the multi-active-row state is reachable *today*, so `scalar_one_or_none()` can raise `MultipleResultsFound` inside `auto_schedule` rule 4, breaking the summarizer path. ~5 lines + one test. In scope because this design changes the surrounding invariant. |
| D8 | All new ORM status writes go through `_set_scheduled_call_status()` | Hand-rolled `if`/`raise` per site | Honours the proposal's deferred-`VALID_TRANSITIONS` bargain: one seam for the follow-up. The CAS claim is the single documented exception (Core UPDATE, no ORM instance). |
| D9 | Cancel a lead's pending `tech_retry` inside the same `close_session()` hook Slice 2 already adds, triggered whenever the resolved `telephony_status` maps to `completed` | New standalone sweep/cron; expiry-based release | Proposal decision 8. No new seam — the hook already resolves the terminal status for every closed session, so checking for a parked `tech_retry` row is one extra query at an existing convergence point. Expiry loses the contact entirely when no other recontact exists (worse than the bug being fixed). |

## Data Flow

```
scheduler_tick (60s)
   │
   ├─[reaper]─ in_progress + outcome_session_id IS NULL + updated_at < now-10m
   │             └─→ pending (clamped) | failed
   ├─[reaper]─ in_progress + outcome_session_id NOT NULL
   │             └─→ CallSession.telephony_status ──map──→ completed | failed
   │
   └─[dialer]─ CAS claim (≤ N rows) ─→ dial_outbound_call(scheduled_call=sc)
                                          │
                        DialResult.failed/recurrent_error ─→ sc.status = failed
                        DialResult.dialing ─→ sc.outcome_session_id = cs.id (stays in_progress)
                                                     │
                                        close_session() ──→ resolve_scheduled_call_for_session()
                                                                └─→ completed | failed
```

## The Claim Statement (verbatim contract)

```python
# app/scheduler/service.py
_CLAIM_TIMEOUT_MINUTES: int = 10
_MAX_STRANDED_HOURS: int = 6

async def _claim_one(db: AsyncSession, sc_id: str, now: datetime) -> bool:
    """Atomically claim a pending ScheduledCall. True iff this process won."""
    stmt = (
        sa.update(ScheduledCall)
        .where(ScheduledCall.id == sc_id, ScheduledCall.status == "pending")
        .values(status="in_progress", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    try:
        result = await db.execute(stmt)
        await db.commit()
    except IntegrityError:                      # uq_scheduled_calls_active_lead
        await db.rollback()
        logger.warning("auto_dialer_claim_conflict", scheduled_call_id=sc_id,
                       reason="lead_already_in_progress")
        return False
    if result.rowcount != 1:
        logger.warning("auto_dialer_claim_conflict", scheduled_call_id=sc_id,
                       reason="lost_race", rowcount=result.rowcount)
        return False
    return True
```

Candidate selection is a separate bounded `SELECT … WHERE status='pending' AND
scheduled_at <= now ORDER BY scheduled_at LIMIT settings.auto_dialer_max_concurrent_dials`.
The `SELECT` is advisory; the `UPDATE` is authoritative.

## Migration Plan

`backend/alembic/versions/20260727_0011_auto_dialer_active_lead_index.py`
(`down_revision = "20260716_0010"`).

**Step 1 — pre-migration duplicate resolution (runs before the index).**
Keep the newest `in_progress` row per lead; retire the rest.

```sql
UPDATE scheduled_calls
   SET status = 'failed',
       notes  = COALESCE(notes || ' | ', '') ||
                'auto-resolved by migration 0011: duplicate in_progress row'
 WHERE id IN (
   SELECT id FROM (
     SELECT id, ROW_NUMBER() OVER (
       PARTITION BY lead_id
       ORDER BY scheduled_at DESC, created_at DESC, id DESC) AS rn
       FROM scheduled_calls WHERE status = 'in_progress'
   ) ranked WHERE ranked.rn > 1
 );
```

The migration logs the affected row count (`op.get_bind()` → `rowcount`) so the
operator sees what was retired. Window functions are available on SQLite ≥ 3.25
(bundled with CPython 3.11+) and on all Postgres versions.

**Step 2 — index.** Raw `op.execute` so one statement is valid on both dialects:

```sql
CREATE UNIQUE INDEX uq_scheduled_calls_active_lead
    ON scheduled_calls (lead_id) WHERE status = 'in_progress';
```

Model parity in `scheduler/models.py.__table_args__`:
`Index("uq_scheduled_calls_active_lead", "lead_id", unique=True, sqlite_where=text("status = 'in_progress'"), postgresql_where=text("status = 'in_progress'"))`.

**Rollback.** `downgrade()` = `DROP INDEX IF EXISTS uq_scheduled_calls_active_lead`.
Step 1 is **not** reversible — retired rows stay `failed`. Documented in the
migration docstring; those rows were unresolvable dead ends before the change.

## Concurrency vs. the Per-Lead Lock

| Layer | Scope | Role |
|---|---|---|
| `auto_dialer_max_concurrent_dials` (claim batch) | Per cycle, process-wide | Bounds simultaneous in-flight dials. Default 1. |
| `uq_scheduled_calls_active_lead` | Cross-process, DB | At most one in-flight scheduled call per lead. Authoritative. |
| `_get_lead_lock()` (`outbound/service.py:97`) | Per lead, in-process | Unchanged fast path; still serialises runner-vs-manual in one process. |
| Guards 3 / 3b | Per dial | Unchanged; return a clean `DialResult`, never raise. |

The runner adds **no** lock of its own. Two rows for one lead can never both be
claimed: the second CAS hits the index and is logged as `auto_dialer_claim_conflict`.

## The Completion Hook

```python
# app/scheduler/service.py
_TELEPHONY_TO_SCHEDULED_STATUS: dict[str, str] = {
    "completed": "completed",   # real conversation
    "voicemail": "completed",   # attempt consumed; recontact is auto_schedule's job
    "no_answer": "failed",
    "failed": "failed",
    "recurrent_error": "failed",
    "stale_in_call": "failed",  # no completion evidence — operator-visible
}

async def resolve_scheduled_call_for_session(
    db: AsyncSession, *, call_session_id: str, telephony_status: str,
    source: str = "close_session",
) -> ScheduledCall | None:
    """Resolve the in_progress ScheduledCall linked to a finished CallSession.

    No-op (returns None) when no linked row exists, when the row is not
    in_progress (idempotent), or when telephony_status is non-terminal.
    Mutates in-memory only — the caller owns flush/commit.
    """
```

**Call site.** `app/calls/service.py::close_session`, inserted **after**
`_apply_voicemail_heuristic(cs)` (`:704`) and **before**
`_merge_sibling_sessions` / `session.flush()` (`:707-709`). Ordering is load-
bearing: the voicemail heuristic can rewrite `telephony_status` from
`completed` → `voicemail`, and the hook must read the final value. Joining the
existing flush keeps hook + close in one transaction.

Not added to the `cs.status == "completed"` early return (`:658`) — that path
means a prior close already resolved the row.

**Statuses that never reach the hook** are covered elsewhere: `failed` /
`no_answer` / `recurrent_error` set by `dial_outbound_call` resolve
synchronously from `DialResult`; `stale_in_call` and sweep-set `completed`
resolve via reaper class (b). Same mapping table for all three paths.

### Decision 8 — Cancelling a Parked `tech_retry` on a Successful Conversation

**Status: implemented** (Slice 2 / PR 2). Shipped as `get_pending_tech_retry_for_lead`
+ the cancellation branch inside `resolve_scheduled_call_for_session`,
`backend/app/scheduler/service.py` — exactly the seam described below.

Same hook, same commit as the mapping above — no new seam. After
`resolve_scheduled_call_for_session` resolves the just-finished session's own
`ScheduledCall` (if any) to `new_status == "completed"`, look up whether the
**lead** has a separate pending `tech_retry` row via
`get_active_scheduled_call_for_lead(db, client_id=..., lead_id=...)` filtered
to `trigger_reason == "tech_retry"` and `status == "pending"`, and cancel it
through `_set_scheduled_call_status()` (D8) with a distinct log event.

"Successful conversation" reuses the mapping table's existing vocabulary — no
new terminal-status concept: any path whose resolved `new_status ==
"completed"` (i.e. `telephony_status` in `{"completed", "voicemail"}`)
qualifies. `failed`-mapped outcomes (`no_answer`, `failed`,
`recurrent_error`, `stale_in_call`) do **not** trigger cancellation — those
are exactly the failures a parked tech_retry exists to cover.

Scope: only the **pending** tech_retry is cancelled here. An `in_progress`
tech_retry (already claimed/dialing) is left alone — it resolves through its
own dial-outcome or the reaper, same as any other in-flight row.

```python
_TECH_RETRY_CANCEL_LOG = "tech_retry_cancelled_by_successful_call"

# inside resolve_scheduled_call_for_session, after this call's own sc resolves:
if new_status == "completed":
    stale_retry = await get_pending_tech_retry_for_lead(db, client_id=..., lead_id=...)
    if stale_retry is not None:
        await _set_scheduled_call_status(db, stale_retry, "cancelled")
        logger.warning(_TECH_RETRY_CANCEL_LOG,
                       scheduled_call_id=stale_retry.id, lead_id=lead_id,
                       resolved_from_session_id=call_session_id)
```

## Reaper

Runs only when **both** `enable_auto_dialer` and `enable_outbound_calls` are
true — the same gate as the claim step, and **before** it so released rows
are re-claimable in the same cycle and resolved rows free the lead's index
slot. (R3-1: gating on `enable_outbound_calls` alone let the reaper
misclassify legacy rows bulk-promoted by `mark_due_calls_in_progress`, since
that path and the CAS-claim path were not otherwise distinguishable. With
the flags AND'd, the two paths are mutually exclusive by construction — no
row the reaper inspects can ever have come from the legacy promoter.)

| Class | Predicate | Resolution |
|---|---|---|
| (a) never dialed | `status='in_progress'` AND `outcome_session_id IS NULL` AND `updated_at < now − 10 min` | `attempt_number < max_attempts` → `pending`; else `failed` |
| (a) aged out | as above AND `now − scheduled_at > 6 h` | `failed` — bounds a crash-loop |
| (b) dialed, no signal | `status='in_progress'` AND `outcome_session_id IS NOT NULL` | Load `CallSession`; terminal `telephony_status` → shared map. Non-terminal → skip (the 30-min `stale_outbound_telephony_sweeper` terminalises it). Session row missing → treat as class (a). |

**Attempt accounting.** `attempt_number` is set at creation and is **never**
incremented by the reaper — a release re-queues the *same* attempt, so no
double-counting. Neither counter query (`auto_schedule` rule 5,
`schedule_tech_retry` rule) changes.

**Release clamp.** `new_at = calculate_scheduled_at(now, 0, start, end, tz)`;
assign `sc.scheduled_at = new_at` **only when `new_at > now`** (i.e. only when
clamping actually moved it). A row released at 02:00 rolls to 09:00; a row
released inside the window keeps its original `scheduled_at`, which is what
makes the 6-hour age-out bound a crash-loop instead of resetting it every pass.

## Decision 7 — Mechanism and Semantics

Replace `schedule_tech_retry` `:634-635`:

```python
client = await db.get(Client, client_id)
if client is None:
    logger.warning("tech_retry_client_not_found", client_id=client_id, lead_id=lead_id)
    return None                       # FK would reject the insert anyway

raw_at = now_utc + timedelta(minutes=_TECH_RETRY_DELAY_MINUTES)
scheduled_at = calculate_scheduled_at(
    now_utc=now_utc,
    cooldown_minutes=_TECH_RETRY_DELAY_MINUTES,
    start_hour=client.scheduler_allowed_hours_start,
    end_hour=client.scheduler_allowed_hours_end,
    tz_str=client.scheduler_timezone,
)
if scheduled_at != raw_at:
    logger.warning("tech_retry_deferred_to_allowed_hours",
                   lead_id=lead_id, raw_scheduled_at=raw_at.isoformat(),
                   scheduled_at=scheduled_at.isoformat(),
                   deferred_minutes=int((scheduled_at - raw_at).total_seconds() // 60))
```

The docstring at `:564` ("independent of client cooldown/hours") must be
corrected in the same commit — a docstring that contradicts the code is the
same silent-failure class this change exists to remove.

**Semantics — recommendation: change nothing else.**

| Question | Recommendation | Reasoning |
|---|---|---|
| Is a retry rolled 00:03 → 09:00 still a "transient failure retry"? | No, but keep it | It is the only queued attempt for that lead. Dropping it re-creates the exact bug being fixed: a lead analysed, queued, then silently abandoned. The alternative (dial at midnight) is worse. |
| Adjust `_TECH_RETRY_MAX_ATTEMPTS = 2`? | **No** | The cap still binds correctly. Retry #1 lands at 09:00; if it fails, retry #2 lands 09:05 — inside the window, genuinely transient-shaped. The pathological path (2 retries both rolled overnight) requires two failures spread across two nights and is still bounded at 2. |
| Adjust the 5-minute delay? | **No** | Inside the window it is unchanged. Outside it, the delay is irrelevant — the window dominates. |
| Interaction to accept | A parked tech retry holds the lead's only active row for up to ~13 h, so `auto_schedule` rule 4 (dedup guard, `:434-442`) defers the client-owned recontact for that lead until it resolves. Accepted: the lead *is* called at 09:00, and the recontact lane re-evaluates from that call's facts. Fixing rule 4 is out of scope. |

## Observability

Uses `app.core.logging.get_logger` (B9 convention already used by
`outbound/sweep.py` and `outbound/linkage.py`); the new scheduler code adopts it
instead of bare `structlog.get_logger`. Sentry is already wired at
`main.py:124`, so ERROR-level events reach it with no new infrastructure.

**Proves the system is working** (absence of these = the dialer is not running):

| Event | Level | Key fields |
|---|---|---|
| `auto_dialer_cycle_started` | INFO | `candidates`, `limit` — emitted only when candidates > 0 |
| `auto_dialer_claimed` | INFO | `scheduled_call_id`, `lead_id`, `trigger_reason`, `attempt_number` |
| `auto_dialer_dial_attempted` | INFO | `scheduled_call_id`, `lead_id` |
| `auto_dialer_dial_accepted` | INFO | `scheduled_call_id`, `call_session_id` |
| `scheduled_call_resolved_from_session` | INFO | `call_session_id`, `telephony_status`, `new_status`, `source` |

**Proves it is failing LOUDLY:**

| Event | Level | Meaning |
|---|---|---|
| `auto_dialer_claim_conflict` | WARNING | Lost CAS race or index conflict — expected under contention, alarming if constant |
| `auto_dialer_dial_failed` | ERROR | `failure_code`, `error` from `DialResult` |
| `auto_dialer_dial_exception` | ERROR | `dial_outbound_call` raised despite its never-raises contract; row forced to `failed` |
| `scheduled_call_reaped_stale` | WARNING | Class (a); `requeued` bool |
| `scheduled_call_reap_exhausted` | ERROR | Attempts exhausted or aged out → `failed` |
| `scheduled_call_reap_session_missing` | ERROR | `outcome_session_id` points at a missing `CallSession` |
| `tech_retry_deferred_to_allowed_hours` | WARNING | Decision 7 fired; includes `deferred_minutes` |
| (startup) `ValueError` from `validate_auto_dialer_requires_outbound` | fatal | App refuses to boot rather than pretending to dial |

## Config

```python
enable_auto_dialer: bool = False
auto_dialer_max_concurrent_dials: int = 1     # field_validator: >= 1
```

`validate_auto_dialer_requires_outbound` is a `model_validator(mode="after")`
declared **after** `validate_outbound_requires_webhook_auth` (`config.py:311`),
mirroring its shape: raise, do not warn. Precedent and rationale are identical —
success criteria require "the app does not boot into a false-healthy state".

## Testing Strategy

No test may reach a provider. Three layers, all existing:

| Guard | Mechanism | Source pattern |
|---|---|---|
| No live HTTP | `respx` strict mode asserts zero unregistered requests | `tests/unit/outbound/test_no_live_calls.py` |
| Provider seam | `patch("app.outbound.service.ElevenLabsService")` with `AsyncMock.initiate_outbound_call` | `test_dial_service.py` |
| Runner seam (unit only) | `patch("app.outbound.service.dial_outbound_call")` — the runner imports it locally at call time, matching `scheduler_tick`'s existing local-import style | new |
| Real DB | `tick_db` fixture: temp aiosqlite + `init_db_with_migrations` + `seed_quintana` + `create_lead` | `tests/integration/scheduler/test_tick.py` |
| Clock | `reap_stranded_scheduled_calls(db, now=…)` injectable parameter — no `freezegun` dependency | new |

Integration tests mock **ElevenLabs**, not `dial_outbound_call`, so the real
guards and `CallSession` writes execute.

| Slice | RED tests (written first) |
|---|---|
| 1 | Validator raises on `auto_dialer=true` + `outbound=false`; `max_concurrent < 1` rejected; CAS returns `True` once and `False` for the loser on the same row; second lead-row claim raises `IntegrityError` → `auto_dialer_claim_conflict`; `DialResult.failed` → `sc.status == "failed"`; `DialResult.dialing` → stays `in_progress` with `outcome_session_id` set; flag-off cycle executes only `mark_due_calls_in_progress`; tech retry at 23:58 local → `scheduled_at` is next 09:00 in client TZ; tech retry at 14:00 → exactly `now + 5min`; `get_active_scheduled_call_for_lead` with two active rows returns one instead of raising; migration test: two duplicate `in_progress` rows → one survives, index exists |
| 2 | `telephony_status='completed'` → `completed`; `voicemail` → `completed`; `no_answer`/`stale_in_call` → `failed`; hook runs after the voicemail heuristic (assert `completed` not `voicemail`-ordering bug); no linked row → no-op; second `close_session` → idempotent; end-to-end: due row → claimed → dialed → `close_session` → `completed`; **D9**: pending `tech_retry` for the lead is `cancelled` when this session resolves to `completed`; pending `tech_retry` is **untouched** when this session resolves to `failed`; `in_progress` `tech_retry` is **not** cancelled (only `pending`); no pending `tech_retry` for the lead → no-op, no extra query side effects |
| 3 | Class (a) with attempts remaining → `pending` + `scheduled_call_reaped_stale`; attempts exhausted → `failed` + `scheduled_call_reap_exhausted`; released at 02:00 local → `scheduled_at` clamped to 09:00; released at 14:00 → `scheduled_at` unchanged; aged > 6 h → `failed`; class (b) terminal → mapped; class (b) non-terminal → untouched; missing `CallSession` → `scheduled_call_reap_session_missing`; clock advanced past both timeouts → **no** row remains `in_progress` |

Full suite gate per slice: `cd backend && python3 -m pytest tests/ -q`
(baseline 3251 passing, ~101 s).

## Delivery: Re-validated Slices

Boundaries are **unchanged** from the proposal. Decision 7 folds into slice 1 as
its own commit. Sizes are revised upward — the proposal's numbers predated D1,
D3, D7 and the reaper's clamp/age-out.

| Slice | Contents | Proposal | Revised | Why |
|---|---|---|---|---|
| 1 — Claim & dial | Flags + validators; CAS claim; `in_progress` unique index + duplicate-resolution migration; dial loop; `outcome_session_id`; transition helper; decision 7; `get_active_scheduled_call_for_lead` fix; tests | ~470 | **~615** | Migration data step (~70), decision 7 (~55), D7 fix (~15), cycle restructure (~30) |
| 2 — Outcome-driven completion | Mapping table + `resolve_scheduled_call_for_session`; `close_session` hook; decision 8 stale-tech_retry cancellation; tests | ~245 | **~280** | Confirmed (~240) + decision 8 (~40) |
| 3 — Stranded-row reaper | Classes (a) + (b); release clamp; age-out; tick wiring; tests | ~300 | **~330** | Release clamp + age-out cap |
| | **Total** | ~1015 | **~1225** | |

Strategy: **stacked PRs to main** (each slice lands independently; the default-
off flag is what makes that safe). Chain: `slice-1 → slice-2 → slice-3`, each
child targeting its parent branch, rebased until the diff shows only its own work.

Slice 1 is ~615 against the session budget of 800 — inside budget but the
largest of the three. It **cannot** be split at the migration seam (see D3). If
a reviewer wants it under 600, promote decision 7 to its own slice 0 (~55
lines); nothing else in slice 1 depends on it.

**Enablement gate unchanged:** `ENABLE_AUTO_DIALER` stays `false` in every
environment until slice 3 merges. Slices 1–2 dial without full stranded-row
recovery.

## Threat Matrix

**N/A** — this change has no routing, shell, subprocess, VCS/PR-automation,
executable-file-classification, or process-integration boundary. It adds work to
an existing in-process asyncio background loop and calls one already-integrated
HTTP provider client through an unchanged seam (`dial_outbound_call`). No new
process, command, or file-classification boundary is introduced.

## Migration / Rollout

1. Deploy slices 1–3 with `ENABLE_AUTO_DIALER=false` (index migration applies;
   duplicate `in_progress` rows are retired and logged).
2. Verify `scheduler_tick_promoted` still fires and `auto_dialer_*` events are
   absent — proves flag-off is inert.
3. Flip `ENABLE_AUTO_DIALER=true` on one client with
   `auto_dialer_max_concurrent_dials=1`. Watch for `auto_dialer_claimed` →
   `auto_dialer_dial_accepted` → `scheduled_call_resolved_from_session`.
4. Rollback: set `ENABLE_AUTO_DIALER=false`; effective on the next 60 s cycle.
   The reaper stops with it (both share the same gate), so rows still
   `in_progress` from the flag-on window are **not** auto-recovered. Either
   settle them via `PATCH .../complete` / `POST .../cancel`, or re-enable the
   flag briefly to let the reaper drain them before rolling back for good.

### Rollout dry run (Slice 3 gate)

Slice 3 unblocks the flip above — it does not perform it.
`ENABLE_AUTO_DIALER` stays `false` in `.env.example` and every deployed
environment after this PR merges (task 3.6.1). Before step 3 above is
exercised anywhere, run this dry run with the flag still `false`:

1. Deploy with `ENABLE_AUTO_DIALER=false`, `ENABLE_OUTBOUND_CALLS=true`
   (matches the Reaper section's gate above — with `enable_auto_dialer`
   still `false`, the reaper does not run this deploy).
2. For one full 60 s tick cycle, confirm:
   - `scheduler_tick_promoted` fires for any due row (unchanged bulk-promote
     path — `enable_auto_dialer=false` means the dial/claim branch never
     runs).
   - No `auto_dialer_*` event fires (same byte-for-byte guarantee as
     before this slice).
   - No `scheduled_call_reaped_stale`, `scheduled_call_reap_exhausted`, or
     `scheduled_call_reap_session_missing` event fires at all (R3-1: the
     reaper is gated on `enable_auto_dialer AND enable_outbound_calls`, so
     with the flag still `false` it never runs this cycle — not because
     nothing is claiming/dialing, but because the gate itself blocks it).
3. Only after that dry run is clean: flip `ENABLE_AUTO_DIALER=true` on one
   client with `auto_dialer_max_concurrent_dials=1` (step 3 above) and watch
   for the same reaper events staying silent under normal operation — their
   presence during steady-state dialing is the loud failure signal the
   reaper exists to produce.
   **Caveat:** any row already sitting `in_progress` from the legacy
   `mark_due_calls_in_progress` path at the moment of the flip becomes
   visible to the reaper starting on that first flag-on cycle. Verify no
   stale legacy `in_progress` rows remain before flipping the flag.

## Open Questions

- [ ] None blocking. One accepted consequence recorded above: a tech retry
      rolled forward to the next allowed slot defers `auto_schedule`'s recontact
      for that lead by up to ~13 h.
- [ ] Follow-up change to file at merge time: enforce
      `ScheduledCall.VALID_TRANSITIONS` through `_set_scheduled_call_status()`
      and the four existing write sites.
