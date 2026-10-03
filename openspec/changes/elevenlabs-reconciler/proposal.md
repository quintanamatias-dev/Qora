# Proposal: Qora Config Phase 2 Remainder — ElevenLabs Reconciler

## Intent

`ElevenLabsService.sync_agent_config()` (`backend/app/elevenlabs/service.py:74`) already PATCHes an agent's live ElevenLabs config and verifies the PATCH landed via `_verify_synced_config` (`:965`) / `_compute_drift_fields` (`:840`), writing the outcome to `Agent.elevenlabs_sync_status` / `elevenlabs_last_synced_at`. That verification only runs **synchronously, once, at the moment an operator saves an agent**. Nothing re-checks an agent's live ElevenLabs config afterward. If an operator edits the agent directly in the ElevenLabs dashboard — or ElevenLabs silently reverts a field, or a PATCH's drift goes unnoticed because nobody was watching the save response — Qora's projection and ElevenLabs' live config can diverge indefinitely with no visibility.

This change closes that gap with a periodic, **report-only** reconciler: a background job that, on an interval, re-fetches every active agent's live ElevenLabs config and recomputes drift against Qora's projection, reusing the same `_compute_drift_fields` comparison the save-path already trusts. It writes a small drift report so operators can see which agents have drifted — it never PATCHes. Repair stays exactly what it is today: the existing explicit sync/re-sync action (`POST /agents/{id}/sync-elevenlabs`), run by a human who has seen the drift report.

This change also removes two long-flagged legacy fallback paths now that the agent-routing migration they predate is complete: the DEPRECATED `Client.system_prompt_override`/`tools_enabled` fallback reads in `voice/webhook.py`, and `Agent.is_default`'s write-time uniqueness enforcement plus its exposure in `AgentResponse` — `resolve_single_active_agent` (`tenants/service.py:723`) was already confirmed, by reading the code, to never consult `is_default` for resolution; the flag has no remaining behavioral read anywhere in `backend/app/`, only a write-time constraint and a response field. The legacy custom-LLM routes (`webhook.py:624`, `:754`) and the DEPRECATED Client columns' own removal/migration are explicitly deferred — see Non-Goals.

## Scope

### In Scope

- **Periodic reconciliation job** (R-D1): a background loop, matching the existing `scheduler_tick()` (`app/scheduler/service.py`) / `stale_outbound_telephony_sweeper` (`app/outbound/sweep.py`, 300s loop) precedent, started from `main.py`'s lifespan alongside those two. Interval is a `Settings` field (`elevenlabs_reconciler_interval_hours`, default `6`). On each tick, for every agent with a non-null `elevenlabs_agent_id` and `is_active=True`: GET the live config (reuses `_fetch_agent_config`), build the same projection payload the save-path would send (reuses the existing payload-building logic), and compute drift fields via `_compute_drift_fields` — **fetch-only, never a PATCH call**.
- **Drift report storage** (R-D1): a new table, `elevenlabs_reconciliation_reports`, one row per agent (`unique(agent_id)`), upserted on every tick. Columns: `status` (`in_sync` | `drift` | `error`), `drift_fields` (JSON list), `status_reason`/`error_detail`, `checked_at`. A new table — not new columns on `Agent` — because `Agent.elevenlabs_sync_status`/`elevenlabs_last_synced_at` already exist and mean something different: the outcome of the last **explicit, write-triggered** sync. Overwriting those columns from a **read-only, periodic** background check would conflate two different events with different operator meanings (see design.md R-D1).
- **Reporting API** (R-D2): `GET /api/v1/admin/elevenlabs/reconciliation` (superadmin) returns the latest report for every agent; `POST /api/v1/admin/elevenlabs/reconciliation/run` (superadmin) triggers an immediate out-of-cycle run and returns its result synchronously.
- **Legacy fallback removal** (R-D3):
  - `voice/webhook.py` ~1178-1192: the `client_orm.system_prompt_override` fallback (used only `if agent is None`) is removed; the `agent is None` branch's prompt source becomes the filesystem/template fallback chain only, matching `PromptLoader`'s own documented priority order.
  - `voice/webhook.py` ~1208-1210: the `tools_enabled` read when `agent is None` is removed along with the same `agent is None` branch narrowing.
  - `voice/webhook.py` ~1296-1299: `_has_static_prompt`'s legacy branch (the DEPRECATED-column read) is removed.
  - `Agent.is_default`'s write-time uniqueness check in `tenants/service.py`'s `create_agent`/`update_agent` (~line 622-634) is removed, and `is_default` is dropped from `AgentResponse` (`agents/schemas.py:234`) and its serialization (`agents/router.py:147`) — confirmed via `grep -rn "is_default" backend/app/` that `resolve_single_active_agent` and every call site already resolve agents without ever reading this flag (agent-routing D2/D3, already shipped); the flag has zero remaining behavioral read, only a stale write-time constraint and a response field that exposes dead data.
  - The DEPRECATED `Client` columns themselves (`tenants/models.py` ~457-463) are **kept**, unused, pending the deferred column-drop migration (Non-Goals).

### Non-Goals (Deferred)

- **Deleting the legacy custom-LLM routes** (`webhook.py:624`, `/custom-llm/chat/completions` and `/chat/completions`) and **dropping the DEPRECATED `Client` columns** via a migration — both deferred until prod is deployed and every ElevenLabs agent is verified to be calling the agent-scoped route (`custom_llm_legacy_route_used` log line at zero volume for a full observation window). Documented here, not scheduled in tasks.md.
- Automatic repair / auto-resync on detected drift — the reconciler is report-only by explicit decision (R-D1); repair remains a human-triggered action.
- Any change to `sync_agent_config`'s own save-time verification path (`_verify_synced_config`, `_compute_drift_fields`) beyond reusing its drift-computation helper — the save-path behavior is unchanged.
- Drift history / trend tracking — `elevenlabs_reconciliation_reports` stores only the latest report per agent, upserted; a history table is future work if an operator asks "when did this start drifting."

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `elevenlabs-reconciler`: the periodic fetch-only reconciliation job, the `elevenlabs_reconciliation_reports` table and its `in_sync`/`drift`/`error` lifecycle, the admin report/run-now API, and the removal of the three `webhook.py` DEPRECATED-column fallback reads plus `is_default`'s write-time enforcement and response exposure.

### Modified Capabilities

- None by supersession. The legacy fallback removals (R-D3) delete dead code paths that were already narrowed to `agent is None`/write-time-only — no existing spec requirement states these fallbacks as required behavior; they predate this repository's spec-driven history.

## Approach

**Report-only reconciler first (additive, nothing repairs), then the reporting API, then the legacy-fallback removals (independent cleanup, can land in any order relative to the reconciler)**:

1. Schema: `elevenlabs_reconciliation_reports` table — additive
2. Reconciliation logic: fetch + drift-compute (reuses `_fetch_agent_config`/`_compute_drift_fields`), upserts the report row — additive, nothing schedules it yet
3. Background loop wired into `main.py`'s lifespan, matching `scheduler_tick`/`stale_outbound_telephony_sweeper`'s start/shutdown pattern
4. Admin API: `GET` latest reports, `POST` run-now
5. Legacy removal: `webhook.py`'s three DEPRECATED-column fallback reads
6. Legacy removal: `is_default` write-time enforcement + `AgentResponse` exposure

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/elevenlabs/models.py` (new) | New | `ElevenLabsReconciliationReport` model (`elevenlabs_reconciliation_reports` table) |
| `backend/alembic/versions/20261003_0027_elevenlabs_reconciliation_reports_schema.py` (new) | New | `CREATE TABLE elevenlabs_reconciliation_reports`, `unique(agent_id)` |
| `backend/app/elevenlabs/reconciler.py` (new) | New | `run_reconciliation_once()` (fetch + drift-compute + upsert, one pass over all active agents); `reconciler_tick()` (interval loop, mirrors `scheduler_tick`) |
| `backend/app/elevenlabs/service.py` | Modified | Export a small payload-building helper reused by both the save path and the reconciler, so the reconciler's projection is never allowed to drift from what a real save would send |
| `backend/app/core/config.py` | Modified | `Settings.elevenlabs_reconciler_interval_hours: int = 6` |
| `backend/app/main.py` | Modified | Start `reconciler_tick()` as a background task alongside `scheduler_task`/`outbound_sweeper_task`; cancel on shutdown |
| `backend/app/elevenlabs/router.py` (new or extended) | New/Modified | `GET /api/v1/admin/elevenlabs/reconciliation`, `POST /api/v1/admin/elevenlabs/reconciliation/run` — superadmin-gated |
| `backend/app/voice/webhook.py` | Modified | Remove the three DEPRECATED-column fallback reads (~1178-1192, ~1208-1210, ~1296-1299) |
| `backend/app/tenants/service.py` | Modified | Remove `is_default` write-time uniqueness enforcement (~622-634) in `create_agent`/`update_agent` |
| `backend/app/agents/schemas.py` | Modified | Remove `AgentResponse.is_default` field |
| `backend/app/agents/router.py` | Modified | Remove `is_default=agent.is_default` from the response serialization |
| `backend/app/tenants/models.py` | Unaffected | DEPRECATED `Client` columns kept, unused — deferred drop (Non-Goals) |

## Safety Model

1. **The reconciler never writes to ElevenLabs** — `run_reconciliation_once()` only ever calls the existing GET helper (`_fetch_agent_config`); there is no PATCH call anywhere in `backend/app/elevenlabs/reconciler.py`. Enforced by an explicit test asserting zero PATCH-capable client calls occur during a reconciliation run.
2. **One agent's drift or fetch error never blocks another agent's check** — each agent's fetch+compare is independently try/except-wrapped; a single agent's `status=error` (network failure, 4xx, malformed body) upserts that agent's report row and moves to the next agent, exactly like `validate_all_integration_credentials`'s per-client isolation (phase 3 precedent).
3. **The reconciler's loop failure never crashes the app** — matches `scheduler_tick`/`stale_outbound_telephony_sweeper`'s existing per-tick try/except-around-the-whole-pass pattern; an unexpected exception in one tick is logged and the loop continues on the next interval.
4. **Legacy fallback removal is verified dead-code removal, not a behavior change for any currently-reachable agent** — every call site removed in R-D3 was already narrowed to `agent is None` (webhook.py) or has zero behavioral readers (confirmed via `grep -rn "is_default" backend/app/`, see Intent); removal is a cleanup of unreachable-in-practice code, not a functional change for any client with a migrated Agent row (which is every active client per agent-routing's completed migration).

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| Reconciler's projection payload drifts from the save-path's actual PATCH payload over time (two implementations diverge) | Med | Task 2 extracts and reuses the exact payload-building helper the save path calls, rather than reimplementing it — a single source of the "what should this agent's config be" logic |
| Reconciler GETs every active agent on each tick, adding load against the ElevenLabs API at scale | Low (current scale) | Interval defaults to 6h and is configurable; documented as a revisit point if agent count grows enough to need staggering/batching — not solved preemptively in this phase |
| A client genuinely relied on the `agent is None` legacy prompt/tools fallback (an Agent row somehow missing) | Low | Confirmed via `tenants/service.py`'s own comment history (agent-routing D2/D3) that every active client has exactly one resolvable Agent; the fail-closed `resolve_single_active_agent` path (raises `NoActiveAgentError`/`AmbiguousAgentError` rather than silently falling back) is the house pattern already in place elsewhere for this exact scenario |
| `is_default` removal breaks an external caller (panel) still reading `AgentResponse.is_default` | Low | Grep-confirmed zero behavioral readers in `backend/app/`; a panel-side read of a boolean field that is always consistent with "there is exactly one active agent" is a UI-only risk, flagged for the frontend owner to confirm before merge, not blocking this doc-only change |

## Rollback Plan

- **Schema (task 1)**: `alembic downgrade -1` drops `elevenlabs_reconciliation_reports`; no runtime code depends on it yet.
- **Reconciliation logic (task 2)**: revert the PR; pure addition, nothing schedules it yet.
- **Background loop (task 3)**: revert the PR; `main.py` stops starting the task — reports simply stop updating, no functional regression for any existing feature.
- **Admin API (task 4)**: revert the PR; the two new endpoints are removed.
- **Legacy removal — webhook.py (task 5)**: revert the PR; the three DEPRECATED-column fallback reads are restored (functionally inert restoration, since no active client's Agent is ever `None` in practice).
- **Legacy removal — is_default (task 6)**: revert the PR; the write-time check and the response field are restored.

## Dependencies

- Depends on `backend/alembic`'s head after `skill-packages` lands (`20261003_0026`); this change's migration is chained at `20261003_0027`.
- Depends on `agent-routing`'s already-shipped D2/D3 decisions (confirmed via existing code comments and `grep`) that no call site resolves an agent via `is_default` — this change does not re-derive that decision, only acts on its already-completed consequence.
- Independent of `data-mcp-onboarding` — no shared tables, no shared code paths.

## Review / Deployment Strategy

Six task groups, each sized to review within a single PR (~≤400 changed lines target): (1) schema, (2) reconciliation logic, (3) background loop wiring, (4) admin API, (5) webhook.py legacy removal, (6) is_default removal. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `elevenlabs_reconciliation_reports` exists; a reconciliation tick upserts one row per active, ElevenLabs-linked agent
- [ ] The reconciler never issues a PATCH — verified by an explicit test asserting zero write-capable HTTP calls during a run
- [ ] One agent's fetch error or drift does not block or affect any other agent's report
- [ ] `GET /api/v1/admin/elevenlabs/reconciliation` and `POST .../run` are superadmin-gated and return current report data
- [ ] The three `webhook.py` DEPRECATED-column fallback reads are removed; `voice/webhook.py` has no remaining read of `Client.system_prompt_override` or `Client.tools_enabled`
- [ ] `is_default`'s write-time uniqueness check is removed from `tenants/service.py`; `AgentResponse` no longer exposes `is_default`
- [ ] DEPRECATED `Client` columns remain in the schema, untouched, pending the deferred drop migration
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-tasks** → the six-task breakdown in `tasks.md`. See `specs/elevenlabs-reconciler/spec.md` for the behavioral contract.
