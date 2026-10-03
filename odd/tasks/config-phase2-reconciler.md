# Configuration Phase 2 (remainder) — ElevenLabs Drift Reconciler and Legacy Cleanup

Goal: implement `openspec/changes/elevenlabs-reconciler`. A report-only periodic reconciler detects drift between Qora's projected ElevenLabs config and the live agent (it never auto-repairs); the remaining runtime reads of DEPRECATED Client columns and `is_default` are removed.

Branch `feat/config-phase2-reconciler` from `main` `a07c873`. Overnight autonomous run; the user reviews in the morning. Not deployed.

Deferred on purpose (R-D4): deleting the legacy client-keyed custom-LLM routes and the column-drop migrations, only after production is deployed and both ElevenLabs agents are verified on agent-scoped URLs.

## Tasks

- [x] 1. Report model, migration 0027 and reconciliation logic (fetch-only, per-agent error isolation).
- [x] 2. Background loop (interval setting, default 6 h) and admin API (latest report, run now).
- [x] 3. Remove the webhook fallbacks to DEPRECATED Client columns and the remaining `is_default` writes and response field.
- [x] 4. Full suites and rollout notes.

## Evidence

- Design commit `01908ff` (R-D1..R-D4).
- Tasks 1-2: `ElevenLabsReconciliationReport` plus migration 0027 (unique constraint declared inline, because SQLite cannot add it afterwards); public `build_config_payload`; `reconciler.py` with `run_reconciliation_once` (GET only, error isolation per agent) and `reconciler_tick` (`elevenlabs_reconciler_interval_hours`, default 6) wired into main.py; GET/POST `/api/v1/admin/elevenlabs/reconciliation[/run]` (superadmin). The no-PATCH test (respx) passes. RED observed per unit. Worker full suite: 3975 passed.
- Task 3: webhook.py no longer reads DEPRECATED Client columns (agent=None falls back to a generic render without tools); `is_default` uniqueness and `AgentResponse.is_default` removed (the column stays), along with the frontend type and fixtures. The reconciler projects the expected agent-scoped `custom_llm.url` (shared helper `_custom_llm_callback_url`) and compares only the URL, never secrets. RED observed. Worker full suite: 3982 passed; frontend tsc clean. The worker could not run vitest/eslint (they hung).
- **Root cause of the slowness and the hangs:** iCloud had evicted ~93k repo files (node_modules 3.6k, backend .venv 2.4k, plus Plugin/ and docs). Overnight work moves to worktrees in ~/Developer, outside iCloud.
- Task 4 (verifier, worktree outside iCloud): backend 3982 passed (7m45s); frontend 901 passed, lint and tsc clean; Alembic down to 0026 and back up OK.

## Production rollout

No required variables (`ELEVENLABS_RECONCILER_INTERVAL_HOURS` defaults to 6; 0 disables it). After the deploy and the ElevenLabs re-sync: POST `/api/v1/admin/elevenlabs/reconciliation/run` and check that both agents are `in_sync`. Next release (R-D4): remove the legacy custom-LLM routes and drop `agents.is_default` plus the DEPRECATED Client columns, once prod logs show no `custom_llm_legacy_route_used`.
