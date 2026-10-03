# Configuration Phase 1 — Design (OpenSpec)

Goal: design the DB-backed agent configuration model before any code. Source of truth for intent: the configuration survey (PR #177, `docs/reports/2026-10-config-survey/build_report.py` on `docs/config-survey`), the phase 0 record (`odd/tasks/config-phase0.md`) and the user's decisions recorded there. Design only: no application code in this feature.

Split agreed with the user:

- **1a — `agent-config-revisions-routing`**: per-agent routing (no "default agent"), agent configuration stored in the DB with versioned revisions, ElevenLabs as a projection of the active revision.
- **1b — `agent-config-inheritance`**: 3-level inheritance (Qora standard → client → agent) on top of the 1a model; voice, prompt and goal mandatory per agent; Qora standards locked.

Out of scope (later phases): partner role and permissions, client secrets and CRM config in the DB, skill packages, analysis profiles by vertical, onboarding harness, data MCP, config vs operations panels.

## Tasks

- [x] 1. Explore: map the survey's target model, migration plan and decisions, plus the current config/routing code paths (`gentle-ai-explore`; SDD roles are retired in this runtime).
- [x] 2. 1a proposal.
- [x] 3. 1a delta specs.
- [x] 4. 1a technical design.
- [x] 5. 1a implementation tasks with review workload forecast.
- [x] 6. 1b proposal, specs, design and tasks.
- [x] 7. Short visual summary for the user.

## Evidence

- Branch: `design/config-phase1` (from `main` 62d80ea, after PR #178 merged).
- Tasks 1–5: `e9bb3b2` exploration, `a9074ef` proposal, `00b9b38` specs (agent-routing, agent-config-revisions; 16 scenarios each), `0a25898` design (decisions D1–D8), `d00730c` tasks (7 phases). Written by a worker from the parent's decisions; parent checked structure and the decisions table. Corrections found in code: call_sessions/scheduled_calls already carry agent_id but every path falls back to get_default_agent; InitiationRequest declares agent_id but the handler ignores it; ElevenLabsExtraBody has no agent_id, so the agent goes in the URL path.
- Task 6: `openspec/changes/agent-config-inheritance/` (proposal, design D9–D16 with the full field-policy table, tasks in 7 work units, specs config-inheritance and qora-standards). Ten locked Qora standards enumerated (end_call enabled, analysis model, memory window 3, profile-facts placement, prompt assembly order, load_skill injection, EL system-tool passthrough, technical retries 2, call duration bounds 30–7200 s, post-call webhook secret). Open: confirm prod `model`/`tts_model` values via API before locking the standard (column defaults say gpt-4o / flash v2.5, prod runs gpt-4.1-mini / v4 Turbo).
- Task 7: summary delivered in chat.
- Native review of the tracking-file candidate: lineage `review-eb674c2ae91e599f`, low tier, approved and acknowledged.
