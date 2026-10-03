# Configuration Phase 6 — Read-Only Data MCP and Onboarding Harness

Goal: implement `openspec/changes/data-mcp-onboarding`: a read-only MCP server over Qora's data for internal callers, and an onboarding harness (CLI + admin endpoint) that provisions a client and agent from a spec and returns a verification checklist.

Branch `feat/config-phase6` from `main` `a07c873`, in the linked worktree `~/Developer/qora-phase6` (outside iCloud), running in parallel with the phase 2 remainder. Overnight autonomous run; the user reviews in the morning. Not deployed.

## Tasks

- [x] 1. MCP: scaffold, `mcp` dependency, the client, agent, lead and call tools, never-secrets guard.
- [x] 2. Onboarding harness: spec schema, dry run, provisioning, verification checklist, CLI and endpoint parity.
- [ ] 3. Docs (README and the `qora-client-agent-setup` skill) and full suites.

## Evidence

- Design commit `0fffa90` (M-D1..M-D3).
- Speed change: workers run focused tests; the full suite runs once per phase in the final verification.
- Task 1: `mcp` SDK v2.3.0 (`MCPServer`); `uv run python -m app.mcp` (stdio). 8 read-only tools: list/get for clients, agents (effective config with provenance and active revisions), leads and calls (client_id required; cross-tenant returns not found; default limit 50, max 200). The never-secrets guard seeds a real encrypted secret and checks every output. RED observed; 17 focused tests pass. Note: this worktree needs `uv sync --extra dev`.
- Task 2: `app/onboarding` adds an `OnboardingSpec` with no secret fields, `run_onboarding` (dry run and real run, idempotent and resumable: client → agent, which reuses the agent that `create_client` creates → analysis profile → integration → ElevenLabs sync only when there is an EL agent id), a checklist plus the manual steps, the CLI `python -m app.onboarding`, and `POST /api/v1/admin/onboarding` (superadmin), with parity between CLI and endpoint. README docs; the skill now points to the harness. RED observed; 30 focused tests pass (onboarding + mcp).
