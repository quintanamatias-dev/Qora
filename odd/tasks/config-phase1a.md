# Configuration Phase 1a — Implementation

Goal: implement `openspec/changes/agent-config-revisions-routing` (per-agent routing without a default agent, versioned agent config revisions, ElevenLabs as a projection). Spec, design and task details live in that change; this file tracks progress and evidence.

Branch `feat/config-phase1a`, stacked on `design/config-phase1`. The user asked not to push yet and to review everything at the end. Production rollout (phase 7) waits for the user's go-ahead.

## Tasks

- [ ] 1. Phase 0 + 1: new-agent defaults aligned with the production standard; revisions schema, migration and one-time import; seeders create revision 1.
- [ ] 2. Phase 2: AgentConfigV1 schema, revision service (insert-only, rollback as a new revision) and API, with ElevenLabs sync on write.
- [ ] 3. Phase 3: runtime prompt reads the active revision.
- [ ] 4. Phase 4a: agent-scoped custom-LLM route, legacy routes fail closed with more than one active agent, initiation resolves by ElevenLabs agent id, `get_default_agent` removed.
- [ ] 5. Phase 4b: scheduler, recontact, `schedule_followup`, outbound, calls and lead preview take an explicit agent.
- [ ] 6. Phase 5: ElevenLabs projection sets the agent-scoped custom-LLM URL.
- [ ] 7. Phase 6: admin UI without "default agent" and with a revisions list plus rollback.
- [ ] 8. Full backend and frontend suites green; phase 7 (production rollout) prepared and waiting for the user.

## Evidence

- Branch: `feat/config-phase1a` from `design/config-phase1` at `ea8f86d`.
- Production values read on 2026-10-02: leads-agent gpt-4.1-mini / eleven_v4_turbo; jaumpablo and qora-explainer gpt-4o / eleven_flash_v2_5 (old column defaults). Both prod ElevenLabs agents still point at the legacy client-scoped custom-LLM URL.
