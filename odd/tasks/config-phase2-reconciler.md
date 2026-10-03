# Configuration Phase 2 (remainder) — ElevenLabs Drift Reconciler and Legacy Cleanup

Goal: implement `openspec/changes/elevenlabs-reconciler`. A report-only periodic reconciler detects drift between Qora's projected ElevenLabs config and the live agent (it never auto-repairs); the remaining runtime reads of DEPRECATED Client columns and `is_default` are removed.

Branch `feat/config-phase2-reconciler` from `main` `a07c873`. Overnight autonomous run; the user reviews in the morning. Not deployed.

Deferred on purpose (R-D4): deleting the legacy client-keyed custom-LLM routes and the column-drop migrations, only after production is deployed and both ElevenLabs agents are verified on agent-scoped URLs.

## Tasks

- [x] 1. Report model, migration 0027 and reconciliation logic (fetch-only, per-agent error isolation).
- [x] 2. Background loop (interval setting, default 6 h) and admin API (latest report, run now).
- [ ] 3. Remove the webhook fallbacks to DEPRECATED Client columns and the remaining `is_default` writes and response field.
- [ ] 4. Full suites and rollout notes.

## Evidence

- Design commit `01908ff` (R-D1..R-D4).
- Tasks 1-2: `ElevenLabsReconciliationReport` plus migration 0027 (unique constraint declared inline, because SQLite cannot add it afterwards); public `build_config_payload`; `reconciler.py` with `run_reconciliation_once` (GET only, error isolation per agent) and `reconciler_tick` (`elevenlabs_reconciler_interval_hours`, default 6) wired into main.py; GET/POST `/api/v1/admin/elevenlabs/reconciliation[/run]` (superadmin). The no-PATCH test (respx) passes. RED observed per unit. Worker full suite: 3975 passed.
