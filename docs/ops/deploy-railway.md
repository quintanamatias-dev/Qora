# Railway Deployment — Operator Runbook

Qora production runs as one Railway service built from the repo `Dockerfile`. SQLite lives on a Railway volume. Everything below was verified on the first production deploy (October 2026).

## Quick path

```bash
railway login                 # once per machine (opens the browser)
railway link                  # once per checkout: project "qora", service "qora-app"
railway up --detach           # build and deploy the current working tree
railway logs --deployment     # follow the running deployment
curl -fsS https://qora-app-production.up.railway.app/api/v1/health
```

## Topology

| Item | Value |
|------|-------|
| Project / environment | `qora` / `production` |
| Service | `qora-app` (1 replica, region `us-east4`) |
| Public URL | `https://qora-app-production.up.railway.app` |
| Volume | `qora-app-volume`, mounted at `/app/data` |
| Database | `sqlite+aiosqlite:////app/data/qora.db` |
| Plan | Hobby (always-on; the Free plan cannot keep the service running) |

A service with a volume cannot run more than one replica. Scale vertically first, then split clients across services (each with its own SQLite). See "Scaling" below.

## How the container starts

`docker/entrypoint.sh`:

1. Starts as root only to `chown` the volume (Railway mounts volumes as root), then re-executes itself as the `qora` user.
2. Runs Alembic migrations (`scripts/migrate.py`); a failed migration stops the deploy.
3. Starts uvicorn on `$PORT` with `--proxy-headers` so the app sees the original `https` scheme.

The `Dockerfile` must not contain a `VOLUME` instruction; Railway rejects it.

## Variables

Set with `railway variable set KEY=value` (secrets via `--stdin`). Never commit them.

| Variable | Production value / source |
|----------|---------------------------|
| `QORA_ENV` | `production` (enables the fail-closed hardening validator) |
| `DATABASE_URL` | `sqlite+aiosqlite:////app/data/qora.db` |
| `QORA_SKIP_BACKUP_CHECK` | `1` (volume backups replace the pre-migration file copy) |
| `QORA_API_KEY` | Generated for production; different from local |
| `QORA_WEBHOOK_AUTH_ENABLED` | `true` |
| `QORA_WEBHOOK_SECRET` | The HMAC secret ElevenLabs generated for the production post-call webhook. The same value is stored in ElevenLabs as the workspace secret `qora-prod-webhook-secret` and sent on custom-LLM and initiation requests |
| `QORA_ALLOWED_ORIGINS`, `FRONTEND_URL` | The public URL |
| `QORA_DOCS_ENABLED` | `false` (also hides `/openapi.json`) |
| `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `QORA_SUPERADMIN_EMAILS` | From the WorkOS dashboard |
| `QORA_AUTH_REDIRECT_URI` | `<public URL>/api/v1/auth/callback` |
| `OPENAI_API_KEY`, `ELEVENLABS_API_KEY` | Provider keys |
| `ELEVENLABS_AGENT_ID` | Production ElevenLabs agent (see below) |
| `QUINTANA_AIRTABLE_API_KEY` | Required at startup while the Quintana CRM integration is active |
| `ENABLE_OUTBOUND_CALLS` | `true` |
| `ENABLE_AUTO_DIALER`, `N8N_ENABLED` | `false` until explicitly enabled |

Changing a variable triggers a redeploy.

## External services

**WorkOS (Staging environment for now).**
- Redirects: `<public URL>/api/v1/auth/callback`.
- Sign-out redirects: `<public URL>/login` (default) and `<public URL>/login?error=no_access`. Both are required: logout returns to `/login`, rejected logins end the AuthKit session and return to the `no_access` page.

**ElevenLabs.** Production uses its own resources so local development (ngrok) keeps working:
- Agent `Quintana Seguros - leads-agent (prod)`: custom LLM at `<public URL>/api/v1/voice/quintana-seguros/custom-llm`, initiation webhook at `<public URL>/api/v1/voice/initiation?client_id=quintana-seguros&lead_id={{lead_id}}`. Both send the workspace secret. The `client_id` in the initiation URL must match the client in the custom-LLM path, or turns land on orphan sessions.
- Workspace webhook `Qora Post-Call (prod)` (HMAC) at `<public URL>/api/v1/calls/elevenlabs-postcall`.

**OpenAI.** The account rate limit, not the server, caps concurrent calls. On Tier 1, `gpt-4o` allows 30k tokens/min, which one call can exhaust (429s and multi-second silences). Production agents use `gpt-4.1-mini` (200k tokens/min) until the account tier increases. Check limits with the `x-ratelimit-limit-tokens` response header.

**Telnyx.** Outbound SIP trunk configured inside ElevenLabs. A depleted balance makes calls fail with `sip request timed out`.

## Backups

Enable once in the Railway dashboard: service `qora-app` → **Backups** → schedules **Daily** (kept 6 days) and **Weekly** (kept 1 month). The CLI token is not authorized for the backups API.

Volume backups protect against bad deploys and data mistakes. They do **not** survive deleting the volume. An offsite copy (bucket) is a pending follow-up.

Restore: Backups tab → **Restore** on the chosen date → review the staged change → **Deploy**. Restoring removes newer backups.

## Data operations

Change production data through the Qora API with the production `QORA_API_KEY` (`Authorization: Bearer ...`), never by editing the SQLite file. Useful calls:

```bash
# Agents of a client
GET  /api/v1/clients/{client_id}/agents
PATCH /api/v1/clients/{client_id}/agents/{agent_id}     # superadmin
# Leads and manual dial
POST /api/v1/leads?client_id={client_id}
POST /api/v1/clients/{client_id}/leads/{lead_id}/call
# Re-run post-call analysis for a completed call without one (superadmin)
POST /api/v1/calls/{session_id}/reanalyze
```

## Rollback

Railway dashboard → Deployments → previous deployment → **Redeploy**. Migrations only move forward; if a migration is the problem, restore a volume backup taken before it.

## Scaling

- One process serves many calls: audio is handled by ElevenLabs and Telnyx, the backend only streams text.
- Limits in order: OpenAI tokens/min, ElevenLabs concurrency on the plan, then CPU of the service.
- Next steps when needed: bigger instance, then one service (and SQLite) per large client.
