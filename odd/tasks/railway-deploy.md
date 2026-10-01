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
- [ ] 4. Install Railway CLI and link the project (user runs `railway login`).
- [ ] 5. Create the service and volume, load production variables, first deploy, health check green.
- [ ] 6. Register the WorkOS redirect URI and log in on the public URL.
- [ ] 7. Point an ElevenLabs agent at the public custom-LLM URL with webhook auth (confirm with user first).
- [ ] 8. Controlled real call; capture event-loop evidence (closes stall T4 if possible).
- [ ] 9. Daily SQLite backup.

## Evidence

- Branch: `feat/railway-deploy`
- Task 1: 34 untracked duplicates removed after byte-compare (no commit; untracked).
- Task 2: verifier built the image, ran it on a root-owned volume with PORT=9123: health 200, SPA served, PID 1 uid 1000 (qora), qora.db owned by qora, `docker compose config -q` ok. Startup also requires `QUINTANA_AIRTABLE_API_KEY` (crm.yaml credential scan).
