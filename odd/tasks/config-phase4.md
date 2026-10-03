# Configuration Phase 4 — Skill Packages

Goal: implement `openspec/changes/skill-packages`. Voice-agent skills move from `backend/clients/*/agents/*/skills/` files into versioned skill packages in the DB: a Qora package, plus one client package per client with a general section and per-agent sections.

Branch `feat/config-phase4` from `main` `4eadb70`. Overnight autonomous run; the user reviews in the morning. Not deployed.

## Tasks

- [x] 1. Models, schema migration 0025 and import migration 0026 (registry.yaml + .agent-skill.md → client package, agent section).
- [x] 2. Skills service: resolution (agent > client general > qora), revisions, per-session cache.
- [x] 3. Runtime cutover of the loader chain and the `load_skill` tool (golden: Quintana leads-agent registry and contents byte-identical to the files).
- [ ] 4. API (packages, skills, content → new revision, revisions, rollback).
- [ ] 5. Full suites and rollout notes. The skill files are deleted only after production runs 0026 (deferred).

## Evidence

- Design commit `65d0641` (P4-D1..D5; migration numbers shifted to 0025/0026 because phase 5 used 0024).
- Tasks 1-2: models `SkillPackage`, `Skill`, `SkillRevision`; migrations 0025 (schema) and 0026 (file import, idempotent, no app.*). `_create_revision` generalized with `**fields` (4th owner table). `app/skills/service.py`: `resolve_agent_skills(session, agent)`, revisions, rollback, `AgentSkillsCache` with explicit invalidation. Golden: leads-agent's skills are byte-identical to registry.yaml plus the 2 .agent-skill.md files. Real-data copy: 1 Quintana package, 2 skills for leads-agent (5066 and 8470 chars), jaumpablo 0 (empty registry). RED observed. Worker full suite: 3939 passed.
- Task 3: the skills index and `load_skill` come from the DB through `AgentSkillsCache` (process-wide; only the first resolution per agent touches the DB). `content_by_slug` replaces `clients_dir` along the voice path; the allowlist checks in `handle_load_skill` are unchanged. The golden test compares entries and contents with the files; the index text is identical by construction because `build_skills_index` did not change. Guard: no runtime module builds registry.yaml or .agent-skill.md paths. Worker full suite: 3934 passed. The cache has no TTL, so the API writes in task 4 MUST invalidate it.
