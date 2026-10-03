# Design: Qora Config Phase 1a — Agent Config Revisions & Routing

## Technical Approach

Add an immutable, versioned `agent_config_revisions` table with a single active-revision pointer per agent, import existing config as revision 1 via an Alembic data migration, and replace every `is_default`-based agent resolution with explicit agent identification — sourced from the call session, schedule, lead record, or an ElevenLabs-agent-to-Qora-agent mapping, never from a "default" flag. Legacy client-keyed routes keep working only when a client has exactly one active agent (fail closed otherwise), with every hit logged as deprecated. This is a routing-correctness fix (critical defect #2) combined with the revisions foundation that gives config changes an audit trail and gives rollback the data it needs.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **D1 — Per-agent routing, no default agent** | Every runtime path identifies the agent explicitly. Live calls use an agent-scoped custom-LLM route (`/voice/{client_id}/agents/{agent_id}/custom-llm/chat/completions`); initiation webhook resolves the Qora agent from the EL `agent_id` (1:1 EL-agent ↔ Qora-agent mapping already exists via `agents.elevenlabs_agent_id`). Outbound trigger, scheduler, recontact, `schedule_followup`, lead preview, and session creation take `agent_id` from the call session/schedule/lead record or an explicit param — never from `is_default`. | (a) Keep `is_default` as a fallback forever. (b) Encode agent_id only in the EL extra body, not the URL path. | (a) is the literal defect being fixed — it makes a second agent on a client permanently unreachable. (b) was considered "if verified cleaner" per the task brief; URL-path encoding is chosen because it is visible in access logs, works without relying on EL correctly forwarding extra-body fields on every turn, and matches the existing path-based pattern already proven by the CAP-1 `/{client_id}/custom-llm/chat/completions` route. |
| **D2 — Transition compatibility for legacy routes** | Legacy client-keyed routes (`/custom-llm`, `/{client_id}/custom-llm/chat/completions`) keep working ONLY when the client has exactly one active agent. 0 or >1 active agents → explicit error, no silent pick. Every legacy-route hit logged with a deprecation marker. | (a) Immediately delete legacy routes. (b) Keep silently picking `is_default` as today. | (a) breaks the two already-synced prod EL agents mid-migration — no safe cutover path. (b) is exactly the bug being fixed; silently picking an agent for a multi-agent client reproduces defect #2 under a new name. The fail-closed middle ground surfaces the ambiguous case loudly instead of guessing, and is strictly safer than current behavior even where it is more restrictive. |
| **D3 — Remove `is_default` semantics (not the column, yet)** | `get_default_agent` and `set_default_agent` deleted from the service layer; "Make default" / "Default" badge removed from the admin UI. The sole-active-default deactivation guard (`tenants/service.py:~742`) is replaced by: **an agent cannot be deactivated if it is the client's last remaining active agent** (count of active agents for the client, not `is_default`-filtered). Column drop is a later cleanup migration. | (a) Drop the `is_default` column in this slice. (b) Keep the sole-active-default guard logic unchanged (it still filters on `is_default`). | (a) combines a destructive schema change with a behavioral cutover in one slice — rejected to keep rollback simple (survey's own rationale, matches the `phase-b-db-migration-foundation` precedent of separating additive and destructive schema work). (b) is semantically wrong after D1/D2: `is_default` no longer gates reachability, so the guard must be redefined around "last active agent for the client," which directly protects D2's single-active-agent legacy-route invariant. |
| **D4 — Versioned, immutable revisions** | New table `agent_config_revisions` (id, agent_id FK, `revision_number` monotonic per agent, `config` JSON validated by `AgentConfigV1` with `schema_version`, `source` enum {import, api, rollback}, `created_by`, `created_at`, `note`). No UPDATE/DELETE path. `agents.active_revision_id` FK pointer. Rollback creates a NEW revision copying an older one, then activates it. `call_sessions.agent_config_revision_id` records the revision used per call. | (a) Mutable config rows with a separate audit-log table. (b) Revisions without a `source` enum (fewer distinctions). | (a) allows the "current" row to silently diverge from what a past call actually used — defeats the audit purpose. (b) loses the ability to distinguish "someone rolled back" from "someone edited" in the UI/API, which the minimal admin UI (task 6) needs to render a meaningful history. |
| **D5 — AgentConfigV1 field scope** | `system_prompt`, `goal` (optional in 1a, mandatory in 1b), `voice_id`, `tts_model`, `tts_speed`, `tts_stability`, `tts_similarity_boost`, `model`, `temperature`, `max_tokens`, `tools_enabled`, `first_message`, conversation `language`, `turn_eagerness`, `soft_timeout_*`, `voicemail_detection_enabled`, `max_call_duration_seconds`. | (a) Include client-level inheritance fields now. (b) Include `registry.yaml` skills content in the revision JSON. | (a) is explicitly 1b scope — the 3-level inheritance model is not ready and forcing it in now would couple an unstable design to an immutable, hard-to-migrate-away-from schema. (b) skills stay on the filesystem through phase 4 per the survey roadmap; putting them in a versioned JSON blob now would require a second migration later to pull them back out. |
| **D6 — One-time import, filesystem wins** | Alembic data migration (chained after head `20260930_0013_multi_tenant_auth`, batch mode) creates revision 1 (`source=import`) per agent from current `Agent` columns, with `system_prompt` taken from `backend/clients/{client}/agents/{slug}/system-prompt.md` when present (confirmed: this file wins today in `render_for_agent`), else `Agent.system_prompt`. After 1a, runtime reads the active revision only; filesystem `system-prompt.md` is no longer read at runtime. Legacy `Agent` columns stay as a read-only deprecated mirror until the cleanup slice — writes go through revisions only. | (a) Always prefer the DB column, ignore the file. (b) Delete the filesystem files once imported. | (a) would import a stale/wrong prompt for any agent whose true production prompt lives in the file — confirmed by reading `loader.py`'s actual priority order, not assumed. (b) is irreversible and not needed for correctness; leaving the files in place costs nothing and preserves a human-readable diff trail during the transition. |
| **D7 — Write path and sync reuse** | PATCH agent config → validate against `AgentConfigV1` → create revision → activate → enqueue EL projection sync (reuses phase-0 `sync_agent_config` + `_verify_synced_config` read-back drift detection, unchanged). Sync status recorded per revision. API surface: list revisions, get one revision, POST rollback. Admin UI in 1a: active revision number + sync status + revisions list with rollback; full config panel redesign is out of scope. | (a) Build a new sync mechanism for revisions. (b) Full config-panel UI in this slice. | (a) `_build_config_payload` is already fully agent-scoped and already implements NULL-means-skip semantics correctly (confirmed read) — there is no defect to fix here, only a route-level change for the live-call path. (b) a full panel redesign is a much larger, separate review unit; the minimal UI unblocks rollback usage without inflating this slice's review size. |
| **D8 — Prod rollout without SSH** | Migration runs at deploy via the existing entrypoint; verified via API only; then re-sync the two prod EL agents (`agent_3001m3x8c6wfeqa8j7gz2qwysyg6` Quintana leads-agent, `agent_4701m3ynzr4jfb0tyj836t437rbh` qora-demo explainer) to agent-scoped routes; verified with ElevenLabs `simulate-conversation` (Telnyx blocked — no real calls). | (a) Request temporary SSH access for manual migration/verification. (b) Skip prod verification, trust local/staging only. | (a) is unavailable per constraint and unnecessary — the existing deploy entrypoint already runs migrations automatically, and the API surface is sufficient to verify both schema state and routing behavior. (b) is too risky for a routing-correctness fix touching live production agents. |

## Data Flow

```
WRITE PATH (config change)
───────────────────────────
PATCH /agents/{agent_id}/config
       │
       ▼
validate against AgentConfigV1 (schema_version pinned)
       │
       ▼
create_revision(agent_id, config, source="api", created_by=<user>)
   └── INSERT-only; revision_number = max(existing)+1 for this agent
       │
       ▼
activate_revision(agent_id, new_revision_id)
   └── UPDATE agents.active_revision_id (single pointer swap)
       │
       ▼
enqueue EL projection sync (ElevenLabsService.sync_agent_config — unchanged)
   └── PATCH computed from active revision's AgentConfigV1 fields
   └── _verify_synced_config drift read-back (unchanged)
       │
       ▼
record sync status on the revision row


READ PATH (live call)
─────────────────────
EL conversation-initiation webhook (agent_id in payload)
       │
       ▼
resolve Qora agent via agents.elevenlabs_agent_id == payload.agent_id  (D1)
       │
       ▼
load agent.active_revision_id → agent_config_revisions row
       │
       ▼
render_for_agent() reads active revision's system_prompt (NOT filesystem, post-cutover)
       │
       ▼
create_session(..., agent_id=<resolved>, agent_config_revision_id=<active>)
       │
       ▼
custom-LLM turns routed via /voice/{client_id}/agents/{agent_id}/custom-llm/chat/completions


ROLLBACK PATH
─────────────
POST /agents/{agent_id}/revisions/{revision_id}/rollback
       │
       ▼
load target revision's config JSON
       │
       ▼
create_revision(agent_id, config=<copied from target>, source="rollback",
                 note="rollback to revision N")
       │
       ▼
activate_revision(agent_id, new_revision_id)   ← same activation path as a normal write
       │
       ▼
enqueue EL projection sync (same as write path)
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/tenants/models.py` | Modify | Add `AgentConfigRevision` model (id, agent_id FK, revision_number, config JSON/Text, schema_version, source enum, created_by, created_at, note); add `Agent.active_revision_id` FK column |
| `backend/alembic/versions/{rev}_agent_config_revisions_schema.py` | Create | `CREATE TABLE agent_config_revisions`; add `agents.active_revision_id` column; batch mode; chained after `20260930_0013_multi_tenant_auth` |
| `backend/alembic/versions/{rev}_import_agent_config_revision_1.py` | Create | Data migration: one `source=import` revision per existing agent, `system_prompt` from filesystem when present else DB column; activates revision 1 for every agent |
| `backend/app/tenants/agent_config_schema.py` | Create | `AgentConfigV1` Pydantic model with `schema_version` literal; validation used by both the write path and the import migration |
| `backend/app/tenants/revisions_service.py` | Create | `create_revision`, `get_active_revision`, `get_revision`, `list_revisions`, `activate_revision`, `rollback_to_revision` — no update/delete functions exist |
| `backend/app/tenants/router.py` (or new `revisions_router.py`) | Modify/Create | `PATCH /agents/{agent_id}/config`, `GET /agents/{agent_id}/revisions`, `GET /agents/{agent_id}/revisions/{id}`, `POST /agents/{agent_id}/revisions/{id}/rollback` |
| `backend/app/tenants/service.py` | Modify | Delete `get_default_agent`, `set_default_agent`; redefine `deactivate_agent`'s guard to count active agents per client (not `is_default`-filtered) |
| `backend/app/voice/webhook.py` | Modify | Add `/voice/{client_id}/agents/{agent_id}/custom-llm/chat/completions` route; legacy routes gated to single-active-agent clients via a shared resolver helper; replace the per-turn `get_default_agent(db, client_id)` call (line ~1026) with the resolved agent from the route |
| `backend/app/voice/initiation.py` | Modify | Resolve Qora agent via `agents.elevenlabs_agent_id == resolved_agent_id_from_EL` first; fall back to the D2 legacy single-active-agent path only when EL does not supply an agent_id |
| `backend/app/scheduler/router.py`, `backend/app/scheduler/service.py` | Modify | Manual schedule creation, `auto_schedule`, retry/recontact paths take explicit `agent_id` (already partially plumbed per Phase 7 tests); remove default-agent fallback at lines ~524-526, 677-679, 1021, 1068, replaced with D2 fail-closed fallback |
| `backend/app/tools/schedule_followup.py` | Modify | Resolve `agent_id` from the active call session instead of `get_default_agent` (lines ~237-240) |
| `backend/app/leads/router.py` | Modify | Voice-context preview endpoint requires explicit `agent_id` query/body param instead of resolving default (lines ~812-815) |
| `backend/app/outbound/router.py` | Modify | Outbound trigger requires explicit `agent_id` (line ~238) |
| `backend/app/calls/service.py` | Modify | `create_session`'s `agent_id=None` fallback becomes D2's fail-closed single-active-agent resolution, not unconditional `get_default_agent` |
| `backend/app/prompts/loader.py` | Modify | `render_for_agent` reads `agent.active_revision_id → agent_config_revisions.config.system_prompt`; filesystem `load_agent_system_prompt` call removed from the runtime path (kept only as the import migration's read helper) |
| `backend/app/elevenlabs/service.py` | Modify | Route/URL construction for sync calls updated to reflect agent-scoped routing; `_build_config_payload` logic unchanged |
| `backend/app/tenants/seed_quintana.py`, `backend/app/tenants/seed_qora_demo.py` | Modify | Seed an imported revision 1 and activate it for every seeded agent (not just the default) |
| `frontend/src/features/admin/agents-section.tsx`, `agents-panel.tsx` | Modify | Remove `useMakeAgentDefault` hook usage and "Default"/"Make default" UI; add revisions list + rollback button, active revision number + sync status display |
| `docs/architecture.md` | Modify | Document agent routing and revisions as the new config source of truth |

## Interfaces / Contracts

```python
# backend/app/tenants/agent_config_schema.py
class AgentConfigV1(BaseModel):
    schema_version: Literal["v1"] = "v1"
    system_prompt: str
    goal: str | None = None  # optional in 1a; mandatory starting 1b
    voice_id: str
    tts_model: str
    tts_speed: float
    tts_stability: float
    tts_similarity_boost: float
    model: str
    temperature: float
    max_tokens: int
    tools_enabled: list[str]
    first_message: str | None = None
    language: str | None = None
    turn_eagerness: str | None = None
    soft_timeout_seconds: float | None = None
    soft_timeout_message: str | None = None
    soft_timeout_use_llm: bool | None = None
    voicemail_detection_enabled: bool | None = None
    max_call_duration_seconds: int | None = None
```

```python
# backend/app/tenants/revisions_service.py — contract (no update/delete exists)
async def create_revision(
    session: AsyncSession,
    agent_id: str,
    config: AgentConfigV1,
    source: Literal["import", "api", "rollback"],
    created_by: str,
    note: str | None = None,
) -> AgentConfigRevision:
    """Insert-only. revision_number = max(existing for agent_id) + 1."""

async def activate_revision(
    session: AsyncSession, agent_id: str, revision_id: str
) -> Agent:
    """Point agents.active_revision_id at revision_id. Single UPDATE, same agent only."""

async def rollback_to_revision(
    session: AsyncSession, agent_id: str, target_revision_id: str, created_by: str,
) -> AgentConfigRevision:
    """Copy target_revision_id's config into a NEW revision (source="rollback"),
    then activate it. Never mutates or reactivates the old row directly."""
```

```python
# backend/app/voice/webhook.py — new agent-scoped route (D1)
@router.post("/{client_id}/agents/{agent_id}/custom-llm/chat/completions")
async def custom_llm_agent_scoped_route(
    client_id: str, agent_id: str, body: CustomLLMRequest, request: Request,
    _webhook_auth: None = Depends(require_webhook_secret),
):
    """Agent and client both resolved from the URL path — no default-agent fallback."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `AgentConfigV1` validation (required fields, `schema_version` pinning) | Pydantic validation error cases: missing `system_prompt`, bad `temperature` range |
| Unit | `revisions_service` immutability | Assert no `UPDATE`/`DELETE` SQL is ever issued against `agent_config_revisions`; `revision_number` monotonic per agent across concurrent creates |
| Unit | `rollback_to_revision` creates a new row, does not reactivate the old one | Assert returned revision has a new `id` and higher `revision_number` than the target |
| Integration | Import migration produces revision 1 matching pre-migration `render_for_agent` output | For each seeded agent (`quintana-seguros`'s two agents, `qora-demo`'s agent), diff imported `system_prompt` against the pre-migration rendered prompt body |
| Integration | Agent-scoped route reaches `quintana-seguros`'s `leads-agent` | POST to `/voice/quintana-seguros/agents/{leads_agent_id}/custom-llm/chat/completions`, assert the response reflects `leads-agent`'s config, not `jaumpablo`'s |
| Integration | Legacy route fails closed for multi-agent client | POST to `/voice/quintana-seguros/custom-llm/chat/completions` (2 active agents) → explicit error, not a silent pick |
| Integration | Legacy route still works for single-active-agent client | `qora-demo` (1 active agent) → legacy route succeeds, deprecation log emitted |
| Integration | `call_sessions.agent_config_revision_id` populated | Create a session via the agent-scoped route; assert the row's `agent_config_revision_id` matches the agent's `active_revision_id` at call time |
| Integration | Initiation webhook resolves agent from EL `agent_id` | POST with a payload carrying a known `agent_id`; assert `agents.elevenlabs_agent_id` lookup resolves the correct Qora agent, not `get_default_agent` |
| Regression | `get_default_agent` / `set_default_agent` fully removed | `grep -rn "get_default_agent\|set_default_agent" backend/app` returns no results after task 4 completes |
| Regression | Scheduler/recontact/tool/outbound/leads call sites propagate `agent_id` | Re-run and extend the existing Phase 7 tests in `test_agent_propagation.py` (calls + scheduler) to cover the new explicit-agent-id requirement at each call site |
| Smoke | Admin UI revisions + rollback | Manual check: revisions list renders, rollback button creates a new revision and updates sync status |

## Migration / Rollout

**Schema inventory before writing the import migration**: for every existing agent, capture (a) current `Agent.*` column values, (b) whether `clients/{client}/agents/{slug}/system-prompt.md` exists, (c) the actual string `render_for_agent` would currently produce (file content if present, else DB column). The import migration must produce a revision whose `system_prompt` field equals (c) — this is the proof the import is faithful, not just "ran without error."

**Staged rollout** (see tasks.md for the full per-task RED/GREEN/rollback breakdown):

1. Schema + migration + import (additive only — no runtime behavior change; old code paths untouched)
2. Revision service + API (additive — new endpoints, nothing reads from them yet)
3. Runtime reads active revision (behavioral cutover for prompt rendering only — routing unchanged)
4. Routing call sites, in two grouped PRs: (a) live-call routes + initiation webhook, (b) scheduler + recontact + tool + outbound + calls + leads preview
5. EL projection moves to agent-scoped route (depends on 4a being live)
6. Minimal admin UI (depends on 2)
7. Prod rollout + verification (depends on all prior tasks passing locally/staging)

**Existing-agent safe path**: the import migration never deletes or alters `Agent.*` columns — they remain a read-only deprecated mirror. If the import produces a wrong revision for some agent, the fix is a corrective `source=import` re-run or an `source=api` correction revision — never an in-place edit of revision 1.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (schema + import) | `alembic downgrade -1` drops `agent_config_revisions` + `active_revision_id`; no other code depends on it | Pure schema rollback, data loss limited to the (recreatable) imported revisions |
| After task 2 (service + API) | Revert PR; schema stays, unused | No behavior change to revert |
| After task 3 (runtime cutover) | Revert PR; `render_for_agent` reverts to reading filesystem `system-prompt.md` directly | Filesystem files were never deleted (D6), so this revert is safe |
| After task 4a (live-call routing) | Revert PR; legacy `get_default_agent`-based resolution restored for the live-call path only | Scoped revert — does not affect task 4b's call sites |
| After task 4b (scheduler/tool/outbound/calls/leads routing) | Revert PR per call-site group; each group's revert is independent | Matches the per-group task breakdown in tasks.md |
| After task 5 (EL projection route change) | Revert PR; legacy client-scoped sync route restored | Prod EL agents re-synced back to client-scoped routes via the API if already rolled out |
| After task 7 (prod rollout) | Re-sync prod EL agents back to legacy routes via API; `alembic downgrade` only if no new revisions have been created via the API since deploy | Nuclear option: restore from the pre-deploy DB backup (same pattern as `phase-b-db-migration-foundation`) |

## PR/Slice Boundary and Review Workload

| Task | Contents | Est. Lines | Risk |
|------|----------|-----------|------|
| 1 | Schema + migration + import | ~350 | Low (additive) |
| 2 | Revision service + API | ~300 | Low (additive) |
| 3 | Runtime reads active revision | ~150 | Medium (behavioral — prompt source change) |
| 4a | Live-call routes + initiation webhook | ~300 | High (routing-correctness fix, touches live traffic) |
| 4b | Scheduler + recontact + tool + outbound + calls + leads preview | ~350 | Medium (grouped but mechanically similar changes) |
| 5 | EL projection → agent-scoped route | ~150 | Medium (prod EL agent re-sync required) |
| 6 | Minimal admin UI | ~250 | Low (additive, frontend only) |
| 7 | Prod rollout + verification | ~50 (mostly docs/runbook) | Medium (production, no-SSH constraint) |

**Total**: ~1,900 changed lines across 8 reviewable units, each within or near the 400-line-per-PR target. Task 4a is the highest-risk unit (live routing-correctness fix) and should not be combined with any other task in a single PR.

## Open Questions

- [ ] Should the agent-scoped custom-LLM route also accept an `agent_id` in `elevenlabs_extra_body` as a secondary signal (defense-in-depth against URL/body mismatch), mirroring the existing `client_id` mismatch-warning pattern on the CAP-1 route? Low priority — does not block task 1–3.
- [ ] Exact wire format for `schedule_followup`'s session-to-agent_id resolution when a call has no active session (edge case for already-ended calls) — resolve during task 4b implementation, not blocking design.
