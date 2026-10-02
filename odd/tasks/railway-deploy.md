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
- [x] 6. Register the WorkOS redirect URI and log in on the public URL.
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
- Task 6: logout returned to the WorkOS default sign-out URL (the no_access page); fixed test-first in `17237bf` (logout passes `return_to=<FRONTEND_URL>/login`). WorkOS Sign-out redirects now list `/login` (default) and `/login?error=no_access`. User verified: superadmin login/logout OK, `+demo` rejected with the no_access message, no loop.
- Task 7 (in progress): ElevenLabs prod resources created without touching local ones: workspace webhook `Qora Post-Call (prod)` (7d73127e…, HMAC; ElevenLabs-generated secret is now Railway QORA_WEBHOOK_SECRET), convai secret `qora-prod-webhook-secret` (MKSAcM1Y…), agent `Qora-Demo (prod)` agent_3001m3x8c6wfeqa8j7gz2qwysyg6 (custom LLM, initiation and post-call → Railway, secret headers). Railway ELEVENLABS_AGENT_ID → prod agent; qora-explainer synced. Pending: prod has no `leads-agent` (QORA_DEMO_AGENT_ID points to a local-only agent) — decide fresh setup vs copying local DB.
- Task 8 prep: prod `leads-agent` created (5fc454c5-57d1-42f7-96b9-aa8598efac07) from the local row, bound to the prod ElevenLabs agent; phone number set via PATCH. ENABLE_OUTBOUND_CALLS=true (auto-dialer still off). Debt found: local agent had legacy tools (`mark_not_interested`, `schedule_followup`) the API rejects; POST /agents ignores `elevenlabs_phone_number_id`; AgentResponse omits it.
- Task 8 attempt 1 (conv_8501m3xan241exy9ppzqykht3nra, 120 s): end-to-end path works in prod — dial via Telnyx SIP, custom LLM on Railway with secret (all 200), post-call webhook HMAC-verified (200). The user's phone was off, so carrier voicemail answered. Findings: (1) OpenAI Tier 1 limits gpt-4o to 30k TPM; ~4k-token prompt × 21 custom-LLM requests (ElevenLabs re-requests) → 12/26 OpenAI calls 429, first agent reply at 49 s. Account limits: gpt-4o/gpt-4.1 30k TPM, gpt-4o-mini/gpt-4.1-mini 200k, gpt-5-mini 500k. (2) The agent said it would hang up but ElevenLabs `end_call` is disabled, so the call ran to max duration (120 s). (3) voicemail_detection is enabled but never fired.
- Task 8 attempt 2 (conv_0801m3xb12j2e9yty0whnwt98vv1): real conversation with the user on gpt-4.1-mini. 0 OpenAI 429s, LLM TTFB 0.66-0.92 s, TTS TTFB 0.12-0.19 s over 9 agent turns. The user rated it good. The call ended at 120 s on ElevenLabs max duration. Not done yet: end_call/voicemail_detection need the custom LLM to forward ElevenLabs system tools (code change); eleven_v4_turbo is available on the account but untested.
- Memory loss after prod calls, root cause: (a) prod ElevenLabs agent initiation URL had `client_id=qora-demo`, so custom-LLM turns landed on `demo-` sibling sessions; fixed in ElevenLabs (now `quintana-seguros`, agent renamed "Quintana Seguros - leads-agent (prod)"). (b) Legacy summarize path started before the close transaction committed, so the summarizer saw 0 turns and skipped facts; the voicemail heuristic ran before the sibling merge. Fixed test-first in `43a6577` (RED observed on 3 new tests; 660 adjacent tests green); deployed. Pending: re-run the summarizer for sessions 0a0463fd… (20 turns) and af47fa70… (33 turns) — needs Railway SSH key. Note: prod qora-demo `qora-explainer` also points to the Quintana prod ElevenLabs agent through the ELEVENLABS_AGENT_ID seed (cleanup in the config redesign).
