# Design: ElevenLabs Reconciler

## Technical Approach

Add a periodic, report-only background loop that re-fetches every active, ElevenLabs-linked agent's live config and recomputes drift against Qora's projection, reusing the exact `_compute_drift_fields` comparison `sync_agent_config`'s save-path already trusts. The result lands in a new, single-row-per-agent table — never a PATCH, never a mutation of the agent's own `elevenlabs_sync_status` columns, which keep their distinct, write-triggered meaning. Repair is unchanged: an operator sees `status=drift` in the report and runs the existing explicit sync action. Separately, two long-dead legacy fallback paths (DEPRECATED `Client` columns read from `webhook.py`, `Agent.is_default`'s write-time enforcement) are removed as independent cleanup, grounded in `grep`-confirmed zero remaining behavioral reads.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **R-D1 — Report-only, new table, not new Agent columns** | A new table, `elevenlabs_reconciliation_reports(id, agent_id FK unique, client_id, status, drift_fields JSON, status_reason, checked_at)`, upserted by a periodic job. `status` is `in_sync` \| `drift` \| `error`. The job only ever GETs; it never PATCHes. | (a) Reuse `Agent.elevenlabs_sync_status`/`elevenlabs_last_synced_at` for the periodic check's outcome too. (b) Make the reconciler itself repair drift automatically (PATCH on detection). | (a) is rejected because those columns already have a specific, different meaning: the outcome of the last **explicit, operator-triggered** save (design.md of `sdd/elevenlabs-config`, D7). Overwriting them from a **periodic, unattended** background check would mean an operator can no longer tell "did my last save work?" from "did a 6-hour-old background check see drift?" — two different questions needing two different answers. A new table with its own `checked_at` keeps both signals legible. (b) is explicitly rejected by the parent decision (R-D1: reconciler is REPORT-ONLY) — auto-repair on a periodic, unattended loop risks PATCHing an agent mid-conversation or fighting a deliberate out-of-band dashboard edit an operator is mid-way through; repair stays a human action with context, exactly as it is today. |
| **R-D2 — Admin API mirrors existing superadmin report/run-now shape** | `GET /api/v1/admin/elevenlabs/reconciliation` returns every agent's latest report; `POST .../run` triggers one immediate pass synchronously and returns its result. Both superadmin-gated, matching `client-integrations-secrets`' `GET .../status` / import-from-env precedent. | (a) Only a GET endpoint; rely purely on the scheduled interval. (b) A webhook/alerting push (Slack, email) instead of a pull API. | (a) is rejected because an operator debugging a specific agent right after a dashboard edit should not have to wait up to the full interval (default 6h) for the report to reflect reality — a run-now escape hatch costs one endpoint and removes that wait entirely. (b) is out of scope: Qora has no existing outbound-alerting integration (confirmed via `grep` — no Slack/email client in `backend/app/`), and building one is disproportionate to this phase's goal of basic visibility; a pull API is consistent with every other admin surface in the repo. |
| **R-D3 — Remove dead-code DEPRECATED-column fallbacks, keep the columns** | `webhook.py`'s three `agent is None` DEPRECATED-column fallback reads are deleted; `Agent.is_default`'s write-time uniqueness enforcement and its `AgentResponse` exposure are deleted. The underlying `Client` columns stay in the schema, unused, until a later, explicit drop migration (deferred). | (a) Drop the `Client` columns now, in the same change. (b) Leave the fallback code in place since it is rarely exercised. | (a) is rejected per the parent's explicit R-D4 deferral: a column-drop migration is only safe after prod is deployed and every ElevenLabs agent is confirmed to be using agent-scoped routes — removing the column now, before that observation window, would be an irreversible step ahead of its own precondition. (b) is rejected because dead code that reads deprecated, soon-to-be-dropped columns is a landmine for the next person who touches `webhook.py` without knowing the columns are already vestigial; removing the reads now, while the columns stay, derisks the eventual column drop by shrinking its blast radius to "one migration," not "one migration plus a forgotten reader." |
| **R-D4 — Legacy custom-LLM routes and column-drop migration stay deferred, not scheduled** | Both are documented in proposal.md's Non-Goals and this design doc, with their exact precondition (`custom_llm_legacy_route_used` at zero volume for an observation window) named explicitly. Neither has a task in tasks.md. | (a) Add a task now with a far-future "run this after prod is verified" instruction. (b) Delete the routes immediately, accepting the risk that some ElevenLabs agent is still dashboard-configured to call the legacy URL. | (a) is rejected because a task that cannot be executed or verified at delegation time (its precondition is a production observation window that has not started) produces either a permanently-unchecked task or a false completion; this is explicitly the "document, don't schedule" pattern the parent decision calls for. (b) is rejected outright — `custom_llm_legacy_route_used`'s own log line exists specifically to answer "is anything still calling this?" before deletion is safe; deleting ahead of that answer risks a silent outage for any agent still pointed at the legacy URL. |

## Data Flow

```
RECONCILIATION TICK (every elevenlabs_reconciler_interval_hours, default 6h)
─────────────────────────────────────────────────────────────────────────────
reconciler_tick() loop
       │
       ▼
for each Agent where elevenlabs_agent_id IS NOT NULL AND is_active = true:
       │
       ▼
   try:
       actual = _fetch_agent_config(agent.elevenlabs_agent_id)   ← GET only, no PATCH
       projection_payload = build_config_payload(agent)           ← same helper save-path uses
       drift_fields = _compute_drift_fields(projection_payload, actual.conversation_config)
       │
       ├─ fetch failed ──────────► status="error", status_reason=<fetch error>
       ├─ drift_fields non-empty ─► status="drift", drift_fields=[...]
       └─ drift_fields empty ────► status="in_sync"
   except Exception:
       status="error", status_reason=<exception>   (never propagates — next agent still runs)
       │
       ▼
UPSERT elevenlabs_reconciliation_reports (agent_id) ← checked_at = now()
       │
       ▼
(loop continues to next agent regardless of this agent's outcome)


ADMIN READ PATH
─────────────────
GET /api/v1/admin/elevenlabs/reconciliation  (superadmin)
       │
       ▼
SELECT * FROM elevenlabs_reconciliation_reports  → return all, newest checked_at per agent


ADMIN RUN-NOW PATH
────────────────────
POST /api/v1/admin/elevenlabs/reconciliation/run  (superadmin)
       │
       ▼
run_reconciliation_once()  ← the same function the periodic loop calls, run synchronously
       │
       ▼
return the updated report rows in the response body
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/elevenlabs/models.py` | Create | `ElevenLabsReconciliationReport` model |
| `backend/alembic/versions/20261003_0027_elevenlabs_reconciliation_reports_schema.py` | Create | `CREATE TABLE elevenlabs_reconciliation_reports`, `unique(agent_id)` |
| `backend/app/elevenlabs/reconciler.py` | Create | `run_reconciliation_once()`, `reconciler_tick()`, per-agent try/except isolation |
| `backend/app/elevenlabs/service.py` | Modify | Extract/export the payload-building helper the save path already uses internally, so the reconciler imports it rather than reimplementing it |
| `backend/app/core/config.py` | Modify | `elevenlabs_reconciler_interval_hours: int = 6` |
| `backend/app/main.py` | Modify | Start/cancel `reconciler_tick()` alongside the existing `scheduler_task`/`outbound_sweeper_task` |
| `backend/app/elevenlabs/router.py` | Create or modify | `GET .../reconciliation`, `POST .../reconciliation/run` |
| `backend/app/voice/webhook.py` | Modify | Remove three DEPRECATED-column fallback reads |
| `backend/app/tenants/service.py` | Modify | Remove `is_default` write-time uniqueness check |
| `backend/app/agents/schemas.py` | Modify | Remove `AgentResponse.is_default` |
| `backend/app/agents/router.py` | Modify | Remove `is_default` from response serialization |

## Interfaces / Contracts

```python
# backend/app/elevenlabs/reconciler.py
async def run_reconciliation_once(db: AsyncSession, settings) -> list[ReconciliationResult]:
    """One fetch-only pass over every active, ElevenLabs-linked agent.

    Never PATCHes. A single agent's fetch/compute failure isolates to that
    agent's row (status="error") and does not stop the pass.
    """

async def reconciler_tick(settings) -> None:
    """Interval loop (elevenlabs_reconciler_interval_hours), mirrors scheduler_tick.

    Wraps each pass in try/except so an unexpected exception never kills the loop.
    """
```

```python
# backend/app/elevenlabs/models.py
class ElevenLabsReconciliationReport(Base):
    __tablename__ = "elevenlabs_reconciliation_reports"
    __table_args__ = (UniqueConstraint("agent_id"),)
    id: Mapped[str]
    agent_id: Mapped[str]            # FK agents.id
    client_id: Mapped[str]           # denormalized for admin-list filtering
    status: Mapped[str]              # "in_sync" | "drift" | "error"
    drift_fields: Mapped[str | None] # JSON list, e.g. '["conversation_config.tts.speed"]'
    status_reason: Mapped[str | None]
    checked_at: Mapped[datetime]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `run_reconciliation_once` never issues a PATCH | Mock the HTTP client; assert only GET calls occur across a run with multiple agents |
| Unit | One agent's fetch error isolates | Two agents, one with a failing fetch (mocked 500) and one healthy; assert the healthy agent's report is `in_sync` and the failing one's is `error`, independent of each other |
| Unit | Drift detection reuses `_compute_drift_fields` | Seed a mismatched field between the mocked live config and the projection; assert `status="drift"` and `drift_fields` names it |
| Unit | Upsert semantics | Run the pass twice for the same agent with different outcomes each time; assert exactly one row exists per agent, with the latest `checked_at` |
| Integration | Admin API gating | `GET`/`POST` without superadmin → 403; with superadmin → 200 with expected shape |
| Integration | Run-now returns fresh data | `POST .../run` immediately followed by `GET .../reconciliation` reflects the just-triggered pass, not a stale scheduled-run result |
| Regression | `webhook.py` no longer reads DEPRECATED columns | Static-grep test asserting no remaining `system_prompt_override`/`tools_enabled` read in `voice/webhook.py` outside the model definition itself |
| Regression | `is_default` has no remaining behavioral read | Static-grep test confirms `tenants/service.py`'s write-time uniqueness check and `AgentResponse.is_default` are both absent; existing `resolve_single_active_agent` tests continue to pass unchanged (confirms no regression in agent resolution, which never read `is_default` to begin with) |

## Migration / Rollout

1. Schema — additive
2. Reconciliation logic — additive, nothing schedules it yet
3. Background loop — the first observable change; reports start appearing
4. Admin API
5. `webhook.py` legacy removal — independent of 1-4, can land in parallel
6. `is_default` removal — independent of 1-5, can land in parallel

**Deferred, not in this rollout** (R-D4): legacy custom-LLM route deletion, DEPRECATED `Client` column drop migration — both require a prod observation window this change does not include.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (schema) | `alembic downgrade -1` | No runtime code depends on the table yet |
| After task 2 (reconciliation logic) | Revert PR | Pure addition, nothing schedules it |
| After task 3 (background loop) | Revert PR | Reports stop updating; no other feature affected |
| After task 4 (admin API) | Revert PR | Two endpoints removed |
| After task 5 (webhook.py removal) | Revert PR | Fallback reads restored, functionally inert for any client with a resolvable Agent |
| After task 6 (is_default removal) | Revert PR | Write-time check and response field restored |

## Open Questions

- [ ] Should the admin report API support filtering by `client_id` for multi-tenant operators managing many clients? Not blocking any task; add if an operator asks.
- [ ] Should drift detected by the reconciler trigger an automatic log-level escalation (e.g. `ERROR` instead of `WARNING`) after N consecutive drifted checks for the same agent? Deferred — the report-only contract (R-D1) is satisfied by a single `checked_at` snapshot; trend-based alerting is future work, not blocking.
