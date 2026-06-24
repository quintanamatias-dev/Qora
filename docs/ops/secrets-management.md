# Secrets Management — Operator Runbook

Qora uses a single `.env` file at the repo root as the source of truth for all secrets. The app validates required secrets at startup and refuses to serve requests if any CRITICAL or HIGH secret is missing.

## Quick path

1. Copy `.env.example` to `.env` at the repo root.
2. Fill in all REQUIRED values (see [Secret Classification](#secret-classification) below).
3. Run the pre-flight check: `python backend/scripts/check-secrets.py`
4. Start the app. Startup fails fast with a clear error if anything is missing.

---

## Secret Classification

| Variable | Class | Tier | What it does |
|----------|-------|------|--------------|
| `OPENAI_API_KEY` | REQUIRED | CRITICAL | GPT-4o conversation brain; billable |
| `ELEVENLABS_API_KEY` | REQUIRED | CRITICAL | TTS + STT voice layer; billable |
| `QORA_API_KEY` | REQUIRED | HIGH | Admin API gate (`Authorization: Bearer`) |
| `QORA_WEBHOOK_SECRET` | CONDITIONAL | HIGH | Webhook HMAC auth — required only when `QORA_WEBHOOK_AUTH_ENABLED=true` |
| `QUINTANA_AIRTABLE_API_KEY` | PER_CLIENT | HIGH | Airtable CRM sync for Quintana Seguros; required if CRM is active |
| `DATABASE_URL` | OPTIONAL | MEDIUM | Defaults to local SQLite; Docker overrides via `docker-compose.yml` |
| `VITE_API_KEY` | FRONTEND | HIGH | Must match `QORA_API_KEY`; **browser-visible** — see caveat below |
| `N8N_*`, `TWILIO_*`, `BROKER_NAME` | FUTURE/LEGACY | — | Not wired in current code |

### Failure behaviour by class

| Class | Missing in any environment | Failure type |
|-------|---------------------------|--------------|
| REQUIRED CRITICAL | Hard startup abort | `ValueError` in `Settings.__init__` |
| REQUIRED HIGH | Hard startup abort | `ValueError` in `Settings.__init__` |
| CONDITIONAL | Hard abort only when the feature flag is `true` | `ValueError` in `Settings.__init__` |
| PER_CLIENT | Hard abort at CRM credential scan in lifespan | `SystemExit` from `validate_all_integration_credentials()` |
| OPTIONAL / FUTURE | Silent — defaults apply | No error |

---

## Local Dev Setup

```bash
# 1. Copy the template
cp .env.example .env

# 2. Edit .env and fill in the REQUIRED values:
#    OPENAI_API_KEY, ELEVENLABS_API_KEY, QORA_API_KEY,
#    QUINTANA_AIRTABLE_API_KEY (if using Airtable CRM)

# 3. Validate before starting
python backend/scripts/check-secrets.py

# 4. Start the backend
cd backend && uvicorn app.main:app --reload

# 5. Start the frontend (separate terminal)
cd frontend && pnpm dev
```

**Important:** Do NOT create `backend/.env`. The application loads from repo-root `.env` only (B8 change). If you had an old `backend/.env`, delete it — the app ignores it.

---

## Docker Deploy

Docker Compose already reads the root `.env` via `env_file: .env` in `docker-compose.yml`. No changes needed for Docker.

```bash
# 1. Ensure .env at repo root has all required values
python backend/scripts/check-secrets.py

# 2. Build and start
docker compose up --build

# Or to rebuild and restart in the background:
docker compose up --build -d
```

---

## Pre-flight Check Script

`backend/scripts/check-secrets.py` validates secrets before any deploy:

```bash
# Human-readable table output
python backend/scripts/check-secrets.py

# Machine-readable JSON (for CI pipelines)
python backend/scripts/check-secrets.py --json
```

**Exit codes:**
- `0` — All REQUIRED checks pass. Safe to deploy.
- `1` — One or more REQUIRED checks failed. Deploy blocked.

**JSON output schema:**

```json
{
  "status": "ok | fail",
  "failures": [{"var": "OPENAI_API_KEY", "reason": "missing | placeholder"}],
  "warnings": [{"var": "N8N_ENABLED", "reason": "deprecated ..."}],
  "dead_vars": ["N8N_ENABLED", "BROKER_NAME"],
  "crm_checks": [{"client": "quintana-seguros", "var": "QUINTANA_AIRTABLE_API_KEY", "status": "ok"}]
}
```

Secret values are **never** included in the output.

---

## Secret Rotation

Manual rotation is the correct approach at this stage (single operator, 1–2 clients).

```bash
# 1. Generate a new key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Update the value in .env
#    (QORA_API_KEY, ELEVENLABS_API_KEY, OPENAI_API_KEY, etc.)

# 3. Validate
python backend/scripts/check-secrets.py

# 4. Restart the app to pick up the new value
docker compose restart          # Docker
# OR: kill uvicorn and restart  # local dev

# 5. If rotating QORA_API_KEY, also update VITE_API_KEY in frontend/.env
#    and rebuild the frontend:
cd frontend && pnpm build
```

---

## VITE_API_KEY — Browser-Visible Caveat

`VITE_API_KEY` in `frontend/.env` must match `QORA_API_KEY` in the backend `.env`. This value is **baked into the JavaScript bundle by Vite at build time** and is visible to anyone who opens DevTools or reads the bundle.

**This is acceptable now** because:
- The admin dashboard is internal-only (no external users)
- The key only grants access to admin API routes

**Phase C replacement:** A JWT login flow will replace `VITE_API_KEY`. Operators will log in with credentials; no static key will be embedded in the bundle. At that point, `VITE_API_KEY` is removed from `frontend/.env` and `QORA_API_KEY` is demoted to a server-side only secret.

**Until Phase C:**
- Keep the value strong and unguessable (32-byte random)
- Never commit `frontend/.env` to version control
- Rotate both `QORA_API_KEY` and `VITE_API_KEY` together if a rotation is needed

---

## Adding a New Client Integration

1. Create `backend/clients/{client-id}/crm.yaml` with `api_key: CLIENTNAME_AIRTABLE_API_KEY`.
2. Add the variable to `.env`: `CLIENTNAME_AIRTABLE_API_KEY=pat...`
3. Add the variable to `.env.example` under the `PER_CLIENT` section.
4. Run `python backend/scripts/check-secrets.py` — it will validate the new key.
5. Restart the app — the lifespan CRM credential scan will hard-fail if the key is missing.

---

## CI/CD Integration (future)

When CI/CD is added, inject secrets as environment variables rather than a `.env` file. Run the pre-flight check as a pipeline step:

```yaml
# Example — adapt to your CI system
- name: Validate secrets
  run: python backend/scripts/check-secrets.py --json
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    ELEVENLABS_API_KEY: ${{ secrets.ELEVENLABS_API_KEY }}
    QORA_API_KEY: ${{ secrets.QORA_API_KEY }}
    QUINTANA_AIRTABLE_API_KEY: ${{ secrets.QUINTANA_AIRTABLE_API_KEY }}
```

---

## Rollback

If a B8 deployment breaks, rollback is:

1. Revert `backend/app/core/config.py` — remove the `validate_required_secrets` model_validator block.
2. Revert `backend/app/main.py` — restore `load_dotenv()` path to `parent.parent` and remove lifespan validation call.
3. Restore `backend/app/core/credentials.py` deletion (or revert its creation).
4. Delete `backend/scripts/check-secrets.py` and `docs/ops/secrets-management.md`.
5. Restore `backend/.env.example` from git history.

No data migration. No schema change. No Docker volume impact.
