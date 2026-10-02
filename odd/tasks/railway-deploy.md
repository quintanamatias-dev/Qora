# Railway Deploy — ODD Task Record

Goal: run current `main` on Railway with a public HTTPS URL, SQLite on a persistent volume, and one controlled real call working end to end.

Decisions:
- SQLite stays the product database (Postgres ruled out for latency); scale vertically first, then per-client instances.
- Scheduler keeps its 60s polling tick for now.
- `backend/clients/` is treated as code (git is the source of truth) for the first deploy. UI edits to `crm.yaml` in production are lost on redeploy until CRM config moves to the volume or the DB (follow-up).

## Tasks

- [x] 1. Remove iCloud duplicate files (34 untracked `* 2.*` copies, byte-identical to originals).
- [x] 2. Make the container Railway-ready: honor `$PORT`, fix volume ownership for the non-root user, drop the `VOLUME` instruction Railway rejects. (`railway.toml` skipped: Railway deprecated config-as-code for new services; health check set on the service.)
- [ ] 3. Write the Railway runbook (`docs/ops/deploy-railway.md`): variables, volume, deploy, rollback, backups.
- [x] 4. Install Railway CLI and link the project (user runs `railway login`).
- [x] 5. Create the service and volume, load production variables, first deploy, health check green.
- [ ] 6. Register the WorkOS redirect URI and log in on the public URL.
- [ ] 7. Point an ElevenLabs agent at the public custom-LLM URL with webhook auth (confirm with user first).
- [ ] 8. Controlled real call; capture event-loop evidence (closes stall T4 if possible).
- [ ] 9. Daily SQLite backup.

## Evidence

- Branch: `feat/railway-deploy`
- Task 1: 34 untracked duplicates removed after byte-compare (no commit; untracked).
- Task 2: verifier built the image, ran it on a root-owned volume with PORT=9123: health 200, SPA served, PID 1 uid 1000 (qora), qora.db owned by qora, `docker compose config -q` ok. Startup also requires `QUINTANA_AIRTABLE_API_KEY` (crm.yaml credential scan).
- Task 4: Railway CLI 5.62.1 via brew; user logged in; project `qora` (b0e7d508-8c10-41f4-bbda-6b5bbf93381b), service `qora-app`, env `production`.
- Task 5: volume `qora-app-volume` at /app/data (500 MB); region us-east4 (1 replica); domain https://qora-app-production.up.railway.app. Variables: secrets copied from local .env via stdin; new QORA_API_KEY and QORA_WEBHOOK_SECRET generated; QORA_ENV=production, webhook auth on, docs off, N8N/outbound/auto-dialer off. Deploy via `railway up`: 13 migrations applied, startup complete; health 200 (~0.3 s from Argentina), SPA 200, custom-LLM without secret 401.
- Found during task 5: /openapi.json stayed public with docs disabled. Fixed test-first (RED observed, then 37 + 12 focused tests green) in `096992d`; redeployed, /openapi.json no longer serves the schema.
- Native review of `fee767a`: START blocked by harness (`candidate-view-invalid`); no lineage created.
- Task 6 finding: first public login looped on `no_access` because AuthKit reused last night's `+demo` session (unmapped in the fresh prod DB). Fixed test-first in `eeaa589`: on no_access the callback now redirects through WorkOS logout with `return_to=<FRONTEND_URL>/login?error=no_access` (RED observed; 110 auth tests green). Requires that URL in WorkOS Sign-out redirects. Deployed.
