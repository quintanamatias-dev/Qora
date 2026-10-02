# Configuration Phase 1 — Design (OpenSpec)

Goal: design the DB-backed agent configuration model before any code. Source of truth for intent: the configuration survey (PR #177, `docs/reports/2026-10-config-survey/build_report.py` on `docs/config-survey`), the phase 0 record (`odd/tasks/config-phase0.md`) and the user's decisions recorded there. Design only: no application code in this feature.

Split agreed with the user:

- **1a — `agent-config-revisions-routing`**: per-agent routing (no "default agent"), agent configuration stored in the DB with versioned revisions, ElevenLabs as a projection of the active revision.
- **1b — `agent-config-inheritance`**: 3-level inheritance (Qora standard → client → agent) on top of the 1a model; voice, prompt and goal mandatory per agent; Qora standards locked.

Out of scope (later phases): partner role and permissions, client secrets and CRM config in the DB, skill packages, analysis profiles by vertical, onboarding harness, data MCP, config vs operations panels.

## Tasks

- [ ] 1. Explore: map the survey's target model, migration plan and decisions, plus the current config/routing code paths (`sdd-explore`).
- [ ] 2. 1a proposal.
- [ ] 3. 1a delta specs.
- [ ] 4. 1a technical design.
- [ ] 5. 1a implementation tasks with review workload forecast.
- [ ] 6. 1b proposal, specs, design and tasks.
- [ ] 7. Short visual summary for the user.

## Evidence

- Branch: `design/config-phase1` (from `main` 62d80ea, after PR #178 merged).
