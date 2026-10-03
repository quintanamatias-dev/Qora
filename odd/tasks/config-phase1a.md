# Configuration Phase 1a — Implementation

Goal: implement `openspec/changes/agent-config-revisions-routing` (per-agent routing without a default agent, versioned agent config revisions, ElevenLabs as a projection). Spec, design and task details live in that change; this file tracks progress and evidence.

Branch `feat/config-phase1a`, stacked on `design/config-phase1`. The user asked not to push yet and to review everything at the end. Production rollout (phase 7) waits for the user's go-ahead.

## Tasks

- [x] 1. Phase 0 + 1: new-agent defaults aligned with the production standard; revisions schema, migration and one-time import; seeders create revision 1.
- [x] 2. Phase 2: AgentConfigV1 schema, revision service (insert-only, rollback as a new revision) and API, with ElevenLabs sync on write.
- [x] 3. Phase 3: runtime prompt reads the active revision.
- [ ] 4. Phase 4a: agent-scoped custom-LLM route, legacy routes fail closed with more than one active agent, initiation resolves by ElevenLabs agent id, `get_default_agent` removed.
- [ ] 5. Phase 4b: scheduler, recontact, `schedule_followup`, outbound, calls and lead preview take an explicit agent.
- [ ] 6. Phase 5: ElevenLabs projection sets the agent-scoped custom-LLM URL.
- [ ] 7. Phase 6: admin UI without "default agent" and with a revisions list plus rollback.
- [ ] 8. Full backend and frontend suites green; phase 7 (production rollout) prepared and waiting for the user.

## Evidence

- Branch: `feat/config-phase1a` from `design/config-phase1` at `ea8f86d`.
- Production values read on 2026-10-02: leads-agent gpt-4.1-mini / eleven_v4_turbo; jaumpablo and qora-explainer gpt-4o / eleven_flash_v2_5 (old column defaults). Both prod ElevenLabs agents still point at the legacy client-scoped custom-LLM URL.
- Task 1: `d774152`. RED observed per unit (old defaults, missing model, missing migrations, seeders without revisions). Migrations `20261002_0014` (schema) and `20261002_0015` (import; file prompt wins, idempotent, downgradable, no `app.*` imports). Parent fixed the `_KNOWN_REVISIONS` whitelist in 3 older test files. Full backend suite: 3798 passed. Ruff: 26 pre-existing errors in untouched files, none in touched files. Seeded revisions use `source=import` (no `seed` value in the D4 enum).
- Task 2: AgentConfigV1/AgentConfigPatch, tenant-isolated revisions_service, endpoints PATCH `/agents/{id}/config`, GET revisions, GET revision, POST rollback. Legacy PATCH `/agents/{id}` also writes a revision. Writes mirror into Agent.* columns (transitional). Migration `20261002_0016` adds `elevenlabs_sync_status` per revision. ElevenLabs sync is awaited in the request so its outcome lands on the revision. RED observed (module missing, 404s); 33 new tests; worker full suite 3831 passed; ruff clean on touched files. Gap carried to task 3: agents created through `create_agent` get no revision until their first PATCH.
- Task 3: `create_agent` (and `create_client` through it) creates and activates revision 1. `PromptLoader.get_effective_system_prompt_template` reads the active revision's prompt, self-heals a missing revision with warning `agent_config_revision_missing_backfilled`, and the voice context duplicate-guard uses the same seam. The file is still read only when there is no DB session, the agent is a test double, or the revision prompt is empty. RED observed for 4 new tests; 2 voice tests changed only their mock target. Worker full suite 3835 passed.
