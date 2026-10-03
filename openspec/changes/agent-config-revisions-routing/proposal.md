# Proposal: Qora Config Phase 1a — Agent Config Revisions & Routing

## Intent

Qora agent configuration lives in six uncoordinated places (DB columns, a repo file, the ElevenLabs dashboard, env vars, a hardcoded template, WorkOS) with no version history, no audit trail, and — critically — no reliable way to route a live call to a *specific* agent. Every runtime path (live calls, scheduler, recontact, the `schedule_followup` tool, outbound triggers, lead voice-context preview) resolves "the agent" via `is_default`, so a client with two agents (e.g. `quintana-seguros`: `jaumpablo`, `leads-agent`) can only ever reach one of them. This is critical defect #2 from the 2026-10 config survey. We fix per-agent routing and introduce immutable, versioned agent configuration revisions in the same slice, because a revision has no operational meaning if every call still resolves to "the client's one true agent" regardless of which revision is active on which agent.

The survey roadmap originally placed per-agent routing in phase 2 (EL-as-reflection). We pull it into this slice (1a) because it is the last unfixed critical defect and because revisions require a routed agent to be meaningful.

## Scope

### In Scope

- New table `agent_config_revisions`: immutable versioned agent configuration (prompt, voice, turn-taking, tools — phase 1 field set per the survey). No UPDATE/DELETE path; rollback creates a new revision.
- `agents.active_revision_id` pointer; `call_sessions.agent_config_revision_id` records the revision each call used.
- One-time Alembic data migration importing revision 1 per existing agent from current `Agent` columns (preferring filesystem `system-prompt.md` when present, matching today's `render_for_agent` priority).
- Revision service + API: list revisions, get one revision, PATCH config (validate → create revision → activate → enqueue EL sync), POST rollback.
- Runtime reads the active revision only after this slice — filesystem `system-prompt.md` is no longer read at runtime (import-time only).
- Per-agent routing for every call site currently resolving `is_default`: live-call custom-LLM route, conversation-initiation webhook, scheduler (manual schedule, auto-schedule, retry/recontact), `schedule_followup` tool, outbound trigger, lead voice-context preview, `calls/service.py` session creation.
- Legacy client-keyed routes kept working ONLY when the client has exactly one active agent; fail closed (explicit error, no silent pick) with 0 or >1 active agents. Every legacy-route hit logged with a deprecation marker (infrastructure for this already exists on the legacy custom-llm route and is reused).
- Removal of `is_default` *semantics*: `get_default_agent` and `set_default_agent` deleted; "Make default" UI action removed; deactivate guard redesigned (see design.md D3).
- Minimal admin UI: active revision number + sync status + revisions list with rollback action.
- Prod rollout: migration runs at deploy (no SSH); verify via API; re-sync the two prod EL agents to agent-scoped routes; verify via ElevenLabs `simulate-conversation` (Telnyx blocked, no real calls).

### Out of Scope

- 3-level inheritance (Qora standard → Client → Agent) and the concrete Qora-standard field list — phase 1b.
- `goal` becoming mandatory — optional in 1a, mandatory in 1b.
- Dropping the `is_default` column and the deprecated `Client` agent-shaped columns — later cleanup migration, kept simple by not combining schema-drop with behavioral cutover.
- Full config panel redesign — 1a ships the minimal revisions-list + rollback UI only.
- `client_integrations`, `client_secrets`, `elevenlabs_bindings`, `skill_packages`, `skills` + skill revisions, `analysis_profiles` — later phases (P3–P5).
- `registry.yaml` skills system — stays on the filesystem (phase 4).
- PostgreSQL migration, removing legacy `app/db/models.py` if present — unrelated to this slice.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `agent-routing`: every runtime path identifies the Qora agent explicitly (never via `is_default`); legacy client-keyed routes fail closed except for single-active-agent clients; deprecation logging on every legacy-route hit.
- `agent-config-revisions`: immutable versioned agent configuration with an active-revision pointer, a one-time filesystem/DB import, a validated `AgentConfigV1` schema, a revision API (list/get/rollback), write-path sync to ElevenLabs, and per-call revision attribution.

### Modified Capabilities

None — no existing OpenSpec specs cover agent configuration or call routing prior to this change.

## Approach

**Routing first, then revisions, wired together.** Routing changes land as grouped call-site PRs (live-call routes together, then scheduler/recontact/tool/outbound/calls/leads together) so each PR is independently reviewable and revertable. Revisions land as schema + service + API before routing depends on them, so the runtime-reads-active-revision cutover has something to read. The EL projection sync is already agent-scoped (`ElevenLabsService._build_config_payload`, confirmed unchanged) — this slice only adds the route-level URL/extra-body change, not new sync logic.

**Rollout order** (see tasks.md for the full task breakdown):

1. Schema: `agent_config_revisions` table, `active_revision_id` pointer, one-time import migration
2. Revision service + API (list, get, rollback; PATCH write path with EL sync reuse)
3. Runtime reads active revision (loader/context changes; filesystem `system-prompt.md` no longer read at runtime)
4. Routing call sites, grouped: (a) live-call routes + initiation webhook, (b) scheduler + recontact + `schedule_followup` tool + outbound + calls + leads preview
5. ElevenLabs projection moves to agent-scoped route
6. Minimal admin UI (active revision + sync status + rollback)
7. Prod rollout + verification (migration at deploy, API verification, prod EL agent re-sync, `simulate-conversation` checks)

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/tenants/models.py` | Modified | New `AgentConfigRevision` model; `Agent.active_revision_id` FK |
| `backend/alembic/versions/{rev}_agent_config_revisions.py` | New | Schema migration (chained after `20260930_0013_multi_tenant_auth`, batch mode) |
| `backend/alembic/versions/{rev}_import_agent_config_revision_1.py` | New | Data migration: one revision per existing agent, `source=import` |
| `backend/app/tenants/revisions_service.py` (new module) | New | `create_revision`, `get_active_revision`, `list_revisions`, `rollback_to_revision` — immutable writes only |
| `backend/app/tenants/schemas.py` or new `agent_config_schema.py` | New | `AgentConfigV1` Pydantic schema with `schema_version` |
| `backend/app/tenants/router.py` (or new revisions router) | Modified | PATCH config, GET revisions list/detail, POST rollback |
| `backend/app/tenants/service.py` | Modified (deletion) | `get_default_agent`, `set_default_agent` deleted; `deactivate_agent` guard redesigned |
| `backend/app/voice/webhook.py` | Modified | Agent-scoped custom-LLM route added; legacy route gated to single-active-agent clients with deprecation log |
| `backend/app/voice/initiation.py` | Modified | Resolve Qora agent from EL `agent_id` → Qora agent mapping, not `get_default_agent` |
| `backend/app/scheduler/router.py`, `scheduler/service.py` | Modified | Explicit `agent_id` propagation through manual schedule, auto-schedule, retry |
| `backend/app/tools/schedule_followup.py` | Modified | Take `agent_id` from active call session |
| `backend/app/leads/router.py` | Modified | Lead voice-context preview requires explicit `agent_id` |
| `backend/app/outbound/router.py` | Modified | Outbound trigger requires explicit `agent_id` |
| `backend/app/calls/service.py` | Modified | `create_session` fallback becomes legacy-compatible single-active-agent fail-closed path (D2) |
| `backend/app/prompts/loader.py` | Modified | `render_for_agent` reads the active revision's `system_prompt`, not filesystem `system-prompt.md`, at runtime |
| `backend/app/elevenlabs/service.py` | Modified | Route construction updated to agent-scoped path; `_build_config_payload` itself unchanged |
| `backend/app/tenants/seed_quintana.py`, `seed_qora_demo.py` | Modified | Seed revision 1 for every seeded agent, not just the default |
| `frontend/src/features/admin/agents-section.tsx`, `agents-panel.tsx` | Modified | Remove `useMakeAgentDefault` / "Make default" / "Default" badge; add revisions list + rollback panel |
| `docs/architecture.md` | Modified | Document routing + revisions as the new source of truth |

## Safety Model

1. **Immutability** — revisions have no UPDATE/DELETE path at the service layer; rollback always creates a new revision copying an older one, preserving linear audit history.
2. **Fail-closed legacy routing** — client-keyed routes used by 0 or >1 active agents return an explicit error rather than guessing; this is a stricter failure mode than today's silent `is_default` pick.
3. **Deprecation visibility** — every legacy-route hit is logged with a migration hint, reusing the pattern already shipped on the legacy custom-llm route (`custom_llm_legacy_route_used`), so remaining legacy traffic is observable before the later cleanup slice removes the fallback.
4. **Staged migration** — schema addition, revision import, and runtime cutover are separate tasks/PRs; each is independently revertable per tasks.md.
5. **No SSH on prod** — the import migration runs at deploy via the existing entrypoint; verification is API-only; prod EL agent re-sync happens only after the migration is confirmed via API.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Import migration picks the wrong system-prompt source for some agent | Med | Migration follows the exact `render_for_agent` priority (filesystem file wins, else `Agent.system_prompt`), verified per-agent against actual rendered output before/after |
| A client with >1 active agent relies on legacy client-keyed routing today | Med | Fail-closed error surfaces this immediately in logs/tests rather than silently misrouting a call; `quintana-seguros` (2 agents) is the known case and is explicitly exercised in tests |
| EL route change breaks a live-in-flight call during cutover | Low | Legacy route stays live through the transition (D2); agent-scoped route is additive until both prod EL agents are re-synced |
| Admin UI "Make default" removal breaks an existing user workflow | Low | Replaced by revisions-list + rollback, which is a strict superset of capability (every agent reachable, not just the default) |
| `goal` becoming required too early breaks existing agents without one | Low | Explicitly kept optional in 1a (D5); 1b handles making it mandatory with its own migration |

## Rollback Plan

- **Schema migration (task 1)**: `alembic downgrade -1` drops `agent_config_revisions` and the `active_revision_id` column; no other code depends on it yet at this stage.
- **Revision service + API (task 2)**: revert the PR; schema stays (additive, unused).
- **Runtime reads active revision (task 3)**: revert the PR; `render_for_agent` reverts to reading filesystem `system-prompt.md` directly.
- **Routing call sites (task 4)**: each call-site group is an independent PR; revert restores `get_default_agent` fallback for that group only (git history keeps the deleted functions available for a clean revert).
- **EL projection to agent-scoped route (task 5)**: revert the PR; legacy client-scoped route continues to work for single-active-agent clients.
- **Prod rollout (task 7)**: migration is additive and non-destructive (no columns dropped); worst case is restoring the pre-deploy prod EL agent routes via the ElevenLabs API and reverting the routing PRs.

## Dependencies

- No new third-party packages — reuses existing `alembic`, `pydantic`, `httpx` (EL client).
- Depends on the existing Alembic chain; this migration is chained after head `20260930_0013_multi_tenant_auth`.
- Depends on `ElevenLabsService.sync_agent_config` / `_verify_synced_config` (phase-0, already shipped) — reused unmodified.

## Review / Deployment Strategy

Seven task groups, each sized to review within a single PR (~≤400 changed lines target per tasks.md): (1) schema + migration + import, (2) revision service + API, (3) runtime reads active revision, (4) routing call sites (split further if needed — live-call + initiation first, then scheduler/recontact/tool/outbound/calls/leads), (5) EL projection to agent-scoped route, (6) minimal admin UI, (7) prod rollout + verification. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `agent_config_revisions` table exists with immutable writes only (no UPDATE/DELETE code path)
- [ ] Every existing agent has exactly one imported revision (`source=import`) matching its pre-migration effective config
- [ ] `quintana-seguros`'s `leads-agent` (previously unreachable) is routable via an explicit agent-scoped route
- [ ] Legacy client-keyed routes fail closed (explicit error) for any client with 0 or >1 active agents
- [ ] Every legacy-route hit is logged with a deprecation marker
- [ ] `get_default_agent` and `set_default_agent` no longer exist in the active codebase
- [ ] `call_sessions.agent_config_revision_id` is populated for every new call
- [ ] Rollback via the API creates a new revision and activates it (no in-place mutation of history)
- [ ] Both prod EL agents (`agent_3001m3x8c6wfeqa8j7gz2qwysyg6` Quintana leads-agent, `agent_4701m3ynzr4jfb0tyj836t437rbh` qora-demo explainer) verified reachable via agent-scoped routes using `simulate-conversation`
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-spec** → write `agent-routing` and `agent-config-revisions` specs (done alongside this proposal, see `specs/`). Then **sdd-tasks** → the seven-task breakdown in `tasks.md`.
