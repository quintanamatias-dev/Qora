# Configuration Phase 1b — Implementation

Goal: implement `openspec/changes/agent-config-inheritance` (Qora standard → client → agent inheritance, field policies, effective config with provenance). Spec, design (D9–D17) and task details live in that change; this file tracks progress and evidence.

Branch `feat/config-phase1b`, stacked on `feat/config-phase1a` (`29fa96b`). Not pushed; the user reviews everything at the end. Production rollout waits for the user and ships after or together with 1a.

## Tasks

- [ ] 1. Phases 1 + 2: field-policy registry, Qora standard module (`STANDARD_VERSION`), pure resolver with per-field provenance.
- [ ] 2. Phase 3: client config revisions (model, migration, generalized revisions service, API).
- [ ] 3. Phase 4: AgentConfigV2 sparse overrides, write validation (locked / agent_required), grandfathering and the "incomplete" marker.
- [ ] 4. Phase 5: equivalence test, runtime and ElevenLabs projection read the effective config, call sessions record standard and client revision, client-change propagation, explicit standard resync.
- [ ] 5. Phase 6: effective-config API and minimal UI (provenance badges, locked fields read-only).
- [ ] 6. Full suites green; production rollout plan prepared (includes moving qora-explainer and jaumpablo to the standard per D17).

## Evidence

- Branch: `feat/config-phase1b` from `feat/config-phase1a` at `29fa96b`.
