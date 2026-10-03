# Configuration Phase 1a — Implementation

Goal: implement `openspec/changes/agent-config-revisions-routing` (per-agent routing without a default agent, versioned agent config revisions, ElevenLabs as a projection). Spec, design and task details live in that change; this file tracks progress and evidence.

Branch `feat/config-phase1a`, stacked on `design/config-phase1`. The user asked not to push yet and to review everything at the end. Production rollout (phase 7) waits for the user's go-ahead.

## Tasks

- [x] 1. Phase 0 + 1: new-agent defaults aligned with the production standard; revisions schema, migration and one-time import; seeders create revision 1.
- [x] 2. Phase 2: AgentConfigV1 schema, revision service (insert-only, rollback as a new revision) and API, with ElevenLabs sync on write.
- [x] 3. Phase 3: runtime prompt reads the active revision.
- [x] 4. Phase 4a: agent-scoped custom-LLM route, legacy routes fail closed with more than one active agent, initiation resolves by ElevenLabs agent id, `get_default_agent` removed.
- [x] 5. Phase 4b: scheduler, recontact, `schedule_followup`, outbound, calls and lead preview take an explicit agent.
- [x] 6. Phase 5: ElevenLabs projection sets the agent-scoped custom-LLM URL.
- [x] 7. Phase 6: admin UI without "default agent" and with a revisions list plus rollback.
- [x] 8. Full backend and frontend suites green; phase 7 (production rollout) prepared and waiting for the user.

## Evidence

- Branch: `feat/config-phase1a` from `design/config-phase1` at `ea8f86d`.
- Production values read on 2026-10-02: leads-agent gpt-4.1-mini / eleven_v4_turbo; jaumpablo and qora-explainer gpt-4o / eleven_flash_v2_5 (old column defaults). Both prod ElevenLabs agents still point at the legacy client-scoped custom-LLM URL.
- Task 1: `d774152`. RED observed per unit (old defaults, missing model, missing migrations, seeders without revisions). Migrations `20261002_0014` (schema) and `20261002_0015` (import; file prompt wins, idempotent, downgradable, no `app.*` imports). Parent fixed the `_KNOWN_REVISIONS` whitelist in 3 older test files. Full backend suite: 3798 passed. Ruff: 26 pre-existing errors in untouched files, none in touched files. Seeded revisions use `source=import` (no `seed` value in the D4 enum).
- Task 2: AgentConfigV1/AgentConfigPatch, tenant-isolated revisions_service, endpoints PATCH `/agents/{id}/config`, GET revisions, GET revision, POST rollback. Legacy PATCH `/agents/{id}` also writes a revision. Writes mirror into Agent.* columns (transitional). Migration `20261002_0016` adds `elevenlabs_sync_status` per revision. ElevenLabs sync is awaited in the request so its outcome lands on the revision. RED observed (module missing, 404s); 33 new tests; worker full suite 3831 passed; ruff clean on touched files. Gap carried to task 3: agents created through `create_agent` get no revision until their first PATCH.
- Task 3: `create_agent` (and `create_client` through it) creates and activates revision 1. `PromptLoader.get_effective_system_prompt_template` reads the active revision's prompt, self-heals a missing revision with warning `agent_config_revision_missing_backfilled`, and the voice context duplicate-guard uses the same seam. The file is still read only when there is no DB session, the agent is a test double, or the revision prompt is empty. RED observed for 4 new tests; 2 voice tests changed only their mock target. Worker full suite 3835 passed.
- Task 4: deleting `get_default_agent` moved to the end of task 5 (scheduler, outbound, tools and leads still call it). New `resolve_single_active_agent` / `get_agent_for_client` with `AgentResolutionError` (`NoActiveAgentError`, `AmbiguousAgentError`). New route `/voice/{client_id}/agents/{agent_id}/custom-llm[/chat/completions]`. Legacy routes return 409 `{"error": ...}` with 0 or more than 1 active agents and log `custom_llm_legacy_route_used`. Initiation resolves by `elevenlabs_agent_id`; an unmapped id falls back to the single-agent path. `create_session` without agent fails closed. RED observed (15 new tests). Worker full suite: 3846 passed, 4 failed, because tests at the `backend/tests/` root patched `app.voice.webhook.get_default_agent`; parent renamed the patch target and the 13 tests in those files pass. `call_sessions.agent_config_revision_id` does not exist yet and is its own unit.
- **Rollout constraint:** prod quintana-seguros has 2 active agents (jaumpablo, leads-agent) and its ElevenLabs agent uses the legacy client URL. Deploying task 4 alone would make Quintana calls return 409. The prod rollout must re-sync ElevenLabs to the agent-scoped URL in the same release (task 6) or deactivate jaumpablo first.
- Task 5: `get_default_agent` / `set_default_agent` deleted (grep is clean). `POST /agents/{id}/make-default` removed (the frontend button 404s until task 7). `is_default` removed from `AgentCreate`, kept as deprecated in the response. Deactivate guard: a client's last active agent cannot be deactivated. Scheduler, tool, outbound, calls and lead preview take the agent from the session or schedule, or an explicit `agent_id`, else `resolve_single_active_agent`; HTTP 404 for none, 409 for ambiguous; background paths log and skip. Outbound and lead preview require `agent_id` only when the client has more than one active agent (D2). RED/GREEN for most units; outbound and lead tests were written right after the code (worker disclosed it). Worker full suite: 3850 passed. Seeders skip ambiguous clients and create nothing. Follow-up: seeders still write Agent.* columns at boot without a revision.
- Task 6: the first worker stalled 30 min on a grep with no changes; relaunched with the locations already found. New setting `PUBLIC_BASE_URL` (no such setting existed; the URL was set by hand in ElevenLabs). The sync does a GET, then a PATCH that replaces only `custom_llm.url` with `{base}/api/v1/voice/{client}/agents/{agent}/custom-llm`, keeping secrets and headers; the URL is covered by drift detection; it skips with `elevenlabs_custom_llm_url_skipped` when the base is unset or the GET fails. Migration `20261002_0017`: `call_sessions.agent_config_revision_id`, stamped in `create_session`. RED observed. Worker full suite: 3859 passed. **Rollout:** set `PUBLIC_BASE_URL=https://qora-app-production.up.railway.app` in Railway before re-syncing.
- Task 7: `737530c`. The "Make default" action and "Default" badge are gone; new shared `AgentRevisionsPanel` (active revision, ElevenLabs sync badge, history, rollback with an inline confirm) in agents-section.tsx and agents-panel.tsx. RED observed; frontend 885/885 passed, lint and tsc clean.

- Task 8 (verifier): backend 3859 passed; Alembic upgrade from empty to 0017, downgrade to 0013 and upgrade again all OK; frontend 885 passed, lint and tsc clean; grep for default-agent symbols returns 0 matches. Parent ran the migrations on a copy of the local `qora.db` with real data: all 3 agents got revision 1, and the imported prompts match the files exactly (leads-agent 14782 chars, jaumpablo 5583).

## Production rollout (task 8, waits for the user)

Everything ships in ONE release (see the rollout constraint above):

1. Railway: set `PUBLIC_BASE_URL=https://qora-app-production.up.railway.app`.
2. Deploy. The entrypoint runs migrations 0014–0017: every prod agent gets revision 1 (`source=import`).
3. Check via API: `GET /agents/{id}/revisions` for leads-agent, jaumpablo and qora-explainer; each has one import revision and a non-null `active_revision_id`.
4. Re-sync both ElevenLabs agents (PATCH `/agents/{id}/config` with a no-op note, or the existing sync trigger). Then GET from ElevenLabs: `custom_llm.url` = `/api/v1/voice/{client}/agents/{agent_id}/custom-llm`, and its secrets and headers are intact.
5. ElevenLabs simulate-conversation against agent_3001… (Quintana) and agent_4701… (demo); both must answer with their own prompt.
6. Rollback: PATCH both ElevenLabs agents back to the legacy client URL, then redeploy the previous image. Downgrading the migrations is not needed: they are additive.
