# Configuration Survey — ODD Task Record

Goal: exhaustive inventory of every configurable setting of a Qora client and agent (what it is, where it lives, who can change it, how it reaches ElevenLabs, which level it belongs to), plus a proposal to reorganize storage in the backend. Deliverable for the user: a branded, visual PDF (no Markdown deliverable). Read-only on product code.

Agreed requirements (from the user):
- Per-client and per-agent configuration stored in the DB, not in repo files.
- Platform standard is a guideline that can be overridden per client/agent; voice and prompt have no default.
- Skill packages: Qora package + client package with per-agent sections and shared general skills.
- ElevenLabs settings configurable per agent and pushed to ElevenLabs by API (Qora is the source of truth).
- SQLite stays; future data MCP over a domain API (no raw SQL).

## Tasks

- [x] 1. Map DB configuration (clients, agents, plans/entitlements) with write paths and role gates.
- [x] 2. Map filesystem configuration (prompts, skills, registry, crm.yaml, credentials) and loaders.
- [x] 3. Map ElevenLabs configuration (synced vs dashboard-only), verified against the live production agent.
- [x] 4. Map platform settings (env vars), tools, analysis pipeline, scheduler and memory configuration.
- [x] 5. Map the admin UI: what is editable where and by which role.
- [ ] 6. Consolidate the inventory and list of defects/risks.
- [ ] 7. Write the target model and migration path proposal.
- [ ] 8. Build the branded PDF with diagrams and verify its rendering.

## Evidence

- Branch: `docs/config-survey` (from `main` after PR #176 merge `d518d30`).
- Tasks 1-5: five read-only explorers (DB, files, ElevenLabs, platform, UI) + live ElevenLabs prod agent JSON + prod API; key claims spot-checked by the parent (no TTS/voice in sync payload; default-agent routing; Quintana catalog in universal analysis; confirmed_facts disabled and profile facts never injected).
