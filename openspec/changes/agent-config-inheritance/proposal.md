# Proposal: Qora Config Phase 1b — Standard/Client/Agent Inheritance

## Intent

Phase 1a (`agent-config-revisions-routing`, D1–D8) gave every agent an immutable, versioned configuration (`agent_config_revisions`) and fixed per-agent routing. But 1a's `AgentConfigV1` is a flat, full snapshot per agent — there is no concept of a platform-wide floor that no panel can edit, no client-level layer shared across a client's agents, and no visibility into *why* a given field has the value it has. Today that floor exists only informally, scattered across `backend/app/core/config.py` defaults, hardcoded values in `voice/context.py` / `voice/webhook.py`, and tribal knowledge (e.g. "we use `gpt-4o-mini` for analysis because of OpenAI rate limits" is a comment nobody reads before changing the model).

This change introduces the three-level inheritance model the 1a survey explicitly deferred: **Qora standard → Client → Agent**, with exactly one field-policy per field (`locked`, `overridable`, `client_only`, `agent_required`), a pure resolver with per-field provenance, and a client-level revision layer that reuses 1a's revision mechanics. It also enumerates, for the first time, the concrete list of Qora standards — the survey's own words are "the concrete list of Qora standards is defined in phase 1," and this is that phase.

## Scope

### In Scope

- `AgentConfigStandard` — a versioned Python module (not a DB table) declaring every `locked` field's value and a `STANDARD_VERSION` string. No panel or API can write to it; changes are code, reviewed in a PR.
- A single field-policy registry mapping every `AgentConfigV1` field (1a) to exactly one policy: `locked`, `overridable`, `client_only`, or `agent_required`.
- `resolve_effective_config(standard, client_overrides, agent_overrides) -> EffectiveConfig` — pure function, per-field provenance (`standard` | `client` | `agent`).
- New table `client_config_revisions` + `clients.active_config_revision_id` — reuses 1a's `agent_config_revisions` mechanics (immutable, insert-only, `source` enum, rollback-creates-new-revision) for client-level overrides. Client config rows are sparse (overrides only).
- `AgentConfigV2` (`schema_version=2`) — agent revisions move from 1a's full snapshot to sparse overrides. A data migration keeps all 1a `AgentConfigV1` (`schema_version=1`) revisions readable as-is; new revisions created after this change use V2. No in-place conversion of historical V1 rows (see D4).
- Write-path validation: setting a `locked` field at client or agent level → 422 with the offending field list; creating a NEW agent revision missing an `agent_required` field → 422. Existing agents imported under 1a without `goal` are grandfathered (D6).
- Propagation: a new client revision re-resolves and re-syncs every active agent of that client (reusing 1a's per-agent EL sync); a new `STANDARD_VERSION` deploy triggers re-sync only via an explicit admin endpoint with drift detection — never automatically at deploy/startup.
- Runtime (`build_voice_context`), the EL projection sync, and the admin API all consume `resolve_effective_config`'s output instead of reading `Agent.*` columns or a single flat revision.
- Minimal UI: effective value + provenance badge per field on the existing agent config form; locked fields rendered read-only.
- Equivalence test: effective config computed via the new resolver matches, byte-for-byte per field, the pre-change `AgentConfigV1` value for every existing agent (hard acceptance criterion).

### Out of Scope

- Roles/permissions per panel (partner role) — later phase, per 1a survey DECISIONS.
- Client secrets/CRM (`client_secrets`, `client_integrations`) — phase P3.
- Skill packages — phase P4.
- Analysis profiles — phase P5.
- Full config-panel UI redesign — 1b ships provenance badges + locked-field read-only state only, same minimal-UI precedent as 1a.
- Dropping 1a's `AgentConfigV1` schema or migrating historical V1 revisions to V2 — explicitly deferred (D4); V1 rows stay readable forever.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `config-inheritance`: the field-policy registry, the Qora standard module, the pure resolver with provenance, client-level revisions, `AgentConfigV2` sparse overrides, write-path validation (locked/required), propagation on client-revision and standard-version changes, and per-call attribution of `standard_version` + client revision id + agent revision id.
- `qora-standards`: the concrete, versioned list of locked Qora-standard fields and their values, consumed only by the resolver — no panel, API, or database row may set these fields at any level.

### Modified Capabilities

- `agent-config-revisions` (1a): `AgentConfigV1` becomes `schema_version=1` (frozen, read-only going forward); a new `AgentConfigV2` (`schema_version=2`, sparse overrides) is added for agent revisions created after this change. The write path (`create_revision`, `activate_revision`, `rollback_to_revision`) gains inheritance-aware validation but keeps its immutability contract unchanged. `call_sessions` gains `standard_version` + `client_config_revision_id` columns alongside 1a's existing `agent_config_revision_id`.
- `agent-routing` (1a): unaffected — routing resolves the agent; this change only changes what that agent's *effective config* looks like once resolved. No routing call site changes.

## Approach

**Standard, then resolver, then client layer, then agent cutover, then propagation, then UI, then rollout.** Each layer is additive until the runtime/EL-projection cutover task, matching 1a's staged-rollout precedent (schema before behavior, behavior change isolated to its own PR).

1. Field-policy registry (pure data) + `AgentConfigStandard` module with `STANDARD_VERSION`
2. `resolve_effective_config` + provenance (pure function, heavily unit-tested, no DB/IO)
3. `client_config_revisions` schema + migration + API (list/get/rollback, mirrors 1a's `agent_config_revisions` API shape)
4. `AgentConfigV2` sparse-override schema + write validation (locked/required) + grandfathering for pre-existing `goal`-less agents
5. Runtime (`build_voice_context`) + EL projection consume `resolve_effective_config`'s output; client-revision change re-syncs every active agent of that client
6. Admin API: `GET /agents/{agent_id}/effective-config` (per-field provenance) + minimal UI badges/locks
7. Prod rollout via API + ElevenLabs `simulate-conversation` verification (no SSH; Telnyx blocked — same constraint as 1a)

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/tenants/config_standard.py` (new) | New | `AgentConfigStandard` — versioned Python module, `STANDARD_VERSION`, locked field values |
| `backend/app/tenants/field_policy.py` (new) | New | Field-policy registry: field name → `locked` \| `overridable` \| `client_only` \| `agent_required` |
| `backend/app/tenants/config_resolver.py` (new) | New | `resolve_effective_config(...)` pure function + `EffectiveConfig`/provenance types |
| `backend/app/tenants/models.py` | Modified | New `ClientConfigRevision` model; `Client.active_config_revision_id` FK; `AgentConfigRevision.schema_version` gains value `2`; `call_sessions` gains `standard_version`, `client_config_revision_id` |
| `backend/alembic/versions/{rev}_client_config_revisions_schema.py` | New | `CREATE TABLE client_config_revisions`; `clients.active_config_revision_id`; `call_sessions` new columns (batch mode, chained after 1a's head) |
| `backend/app/tenants/agent_config_schema.py` | Modified | Add `AgentConfigV2` (sparse, `schema_version=2`) alongside unchanged `AgentConfigV1` |
| `backend/app/tenants/revisions_service.py` | Modified | `create_revision` validates against the field-policy registry (locked/required) before insert; client-revision equivalents added |
| `backend/app/tenants/revisions_router.py` (1a) | Modified | New client-config endpoints; existing agent endpoints gain 422 validation responses |
| `backend/app/voice/context.py` | Modified | `build_voice_context` consumes `resolve_effective_config`'s `EffectiveConfig`, not `Agent.*` columns directly |
| `backend/app/elevenlabs/service.py` | Modified | `_build_config_payload` reads from `EffectiveConfig` instead of `Agent.*` |
| `backend/app/calls/service.py` | Modified | `create_session` records `standard_version` + `client_config_revision_id` alongside 1a's `agent_config_revision_id` |
| `backend/app/tenants/router.py` (admin API) | Modified | `GET /agents/{agent_id}/effective-config` with per-field provenance |
| `frontend/src/features/admin/agents-section.tsx` | Modified | Provenance badge per field; locked fields rendered read-only |
| `docs/architecture.md` | Modified | Document the 3-level inheritance model as the config source of truth |

## Safety Model

1. **Locked by construction, not by convention** — the Qora standard lives in code, not the DB; "no panel touches it" is guaranteed because no write path exists for it, not because an admin promises not to click a button. Reused from 1a's "immutability by construction" precedent (D4 there, D2 here).
2. **Fail on invalid writes, not on read** — a 422 on write with the exact offending field list; never a silent clamp or a silently-ignored field.
3. **Grandfathering is explicit and visible** — agents imported under 1a without `goal` keep working; the API/UI marks them "incomplete" rather than either failing closed (breaking production) or silently synthesizing a value.
4. **Propagation is explicit for standard changes, automatic for client changes** — a client revision change re-syncs its own agents immediately (same blast radius as today); a platform-wide `STANDARD_VERSION` bump requires an explicit admin action, never a deploy-time fan-out across every client (D7).
5. **V1 revisions are never rewritten** — historical revisions stay exactly as recorded; the resolver and schema both understand `schema_version=1` (full snapshot, no inheritance) and `schema_version=2` (sparse, inherits) without migrating one into the other.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| A field's policy is misassigned (e.g. `voice_id` marked `overridable` when it should be `agent_required`) | Med | The complete field-policy table (design.md) is reviewed against 1a's `AgentConfigV1` field list exhaustively; the equivalence test catches any field whose resolved value changes for an existing agent |
| `STANDARD_VERSION` bump silently changes behavior for every client overnight | Med | D7: standard-version re-sync is an explicit admin action with drift detection, never automatic at deploy |
| Equivalence test gives false confidence (passes but a field's *provenance* is wrong even though the *value* matches) | Low | Equivalence test asserts both value AND provenance per field, not just value |
| Grandfathered `goal`-less agents accumulate indefinitely because nothing forces completion | Low | "Incomplete" marker is visible in both API and UI; closing that gap is an explicit follow-up, not silently deferred forever (documented as an open question) |
| Client-revision propagation re-syncs agents mid-call | Low | Reuses 1a's existing sync mechanism, which is already safe for in-flight calls (sync affects the *next* call, not a live one) — no new risk introduced |

## Rollback Plan

- **Field-policy registry + standard module (task 1)**: pure code addition, nothing reads it yet; revert the PR, no data impact.
- **Resolver (task 2)**: pure function, nothing calls it yet; revert the PR.
- **Client revisions schema/API (task 3)**: `alembic downgrade -1` drops `client_config_revisions` + `clients.active_config_revision_id`; no runtime code depends on it yet.
- **AgentConfigV2 + write validation (task 4)**: revert the PR; `AgentConfigV1` creation path (1a) is untouched and keeps working.
- **Runtime + EL projection cutover (task 5)**: revert the PR; `build_voice_context` and `_build_config_payload` revert to reading `Agent.*` / the 1a flat revision directly.
- **Admin API + UI (task 6)**: revert the PR; frontend-only impact, backend endpoints stay (additive, unused).
- **Prod rollout (task 7)**: additive migration (task 3) is non-destructive; worst case is an explicit standard-version-sync revert via the admin endpoint and reverting tasks 4–6.

## Dependencies

- Depends on 1a (`agent-config-revisions-routing`, D1–D8) being merged: reuses `agent_config_revisions` table shape, the `create_revision`/`activate_revision`/`rollback_to_revision` service contract, and `ElevenLabsService.sync_agent_config` / `_verify_synced_config` unchanged.
- No new third-party packages.
- Depends on 1a's Alembic chain; this migration is chained after 1a's head.

## Review / Deployment Strategy

Seven task groups, each sized to review within a single PR (~≤400 changed lines target per tasks.md): (1) field-policy registry + standard module, (2) resolver + provenance, (3) client revisions schema/migration/API, (4) AgentConfigV2 + write validation + grandfathering, (5) runtime + EL projection cutover + propagation, (6) admin API effective-config + minimal UI, (7) prod rollout + verification. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] Every `AgentConfigV1` field from 1a has exactly one policy in the field-policy registry; the table in design.md is exhaustive
- [ ] `resolve_effective_config` returns the correct value AND correct provenance for every policy combination, verified by unit tests
- [ ] `client_config_revisions` table exists with the same immutability guarantees as 1a's `agent_config_revisions` (no UPDATE/DELETE path)
- [ ] For every existing agent, `resolve_effective_config`'s output (value + provenance) equals the pre-1b `AgentConfigV1` value for every field — the equivalence test (hard acceptance criterion)
- [ ] Setting a `locked` field at client or agent level returns 422 with the exact field list
- [ ] Creating a NEW agent revision missing `goal` returns 422; existing agents without `goal` continue to operate and are marked "incomplete"
- [ ] A new client revision re-syncs every active agent of that client automatically; a new `STANDARD_VERSION` requires an explicit admin action, never an automatic deploy-time fan-out
- [ ] `call_sessions` records `standard_version` + `client_config_revision_id` + `agent_config_revision_id` for every new call
- [ ] Admin UI shows a provenance badge per field and renders locked fields read-only
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-tasks** → the seven-task breakdown in `tasks.md`. See `specs/config-inheritance/spec.md` and `specs/qora-standards/spec.md` for the behavioral contracts.
