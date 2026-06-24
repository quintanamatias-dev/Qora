# Exploration: Phase B8 — Secrets Management

## Current State

Qora is a multi-tenant AI call center (FastAPI + React SPA). Secrets today are scattered across flat `.env` files loaded at startup via `python-dotenv` and `pydantic-settings`. There is no centralized secret rotation, per-client credential isolation, or encrypted-at-rest storage beyond OS file permissions.

### Secret Inventory

| Secret | Where Set | Category | Who Consumes | Risk Level |
|--------|-----------|----------|--------------|------------|
| `OPENAI_API_KEY` | `.env` (root + backend) | Global API credential | `config.py` → `SecretStr` → `webhook.py`, `summarizer.py` | **CRITICAL** — LLM access, billable |
| `ELEVENLABS_API_KEY` | `.env` (root + backend) | Global API credential | `config.py` → `SecretStr` → `webhook.py`, `elevenlabs/service.py` | **CRITICAL** — voice pipeline, billable |
| `ELEVENLABS_AGENT_ID` | `.env` | Global config (not secret) | `config.py` → `webhook.py` | Low — public agent identifier |
| `ELEVENLABS_VOICE_ID` | `.env` | Global config (not secret) | `config.py` → voice tuning | Low — public voice identifier |
| `QORA_API_KEY` | `.env` | Platform auth | `config.py` → `SecretStr` → `auth.py:require_api_key` | **HIGH** — admin API gate |
| `QORA_WEBHOOK_SECRET` | `.env` | Platform auth | `config.py` → `SecretStr` → `auth.py:require_webhook_secret` | **HIGH** — webhook auth gate |
| `QORA_ALLOWED_ORIGINS` | `.env` | Platform config (not secret) | `main.py` → CORS middleware | Low — list of allowed origins |
| `QUINTANA_AIRTABLE_API_KEY` | `.env` (root + backend) | Per-client CRM credential | `crm_config.py:resolve_api_key()` via `os.environ.get()` | **HIGH** — CRM data access |
| `TWILIO_ACCOUNT_SID` | `.env` | Future integration (unused) | Not consumed in app code | Medium — placeholder, dummy values |
| `TWILIO_AUTH_TOKEN` | `.env` | Future integration (unused) | Not consumed in app code | Medium — placeholder, dummy values |
| `TWILIO_PHONE_NUMBER` | `.env` | Future integration (unused) | Not consumed in app code | Low — phone number |
| `N8N_*` (4 vars) | `.env` | Legacy integration (unwired) | Not consumed in app code | Low — no longer runtime-used |
| `DATABASE_URL` | `.env` / docker-compose | Infrastructure | `config.py`, `alembic/env.py`, `migrate.py` | Medium — connection string |
| `VITE_API_KEY` | `frontend/.env` | Frontend auth | `client.ts` → Bearer header | **HIGH** — build-time baked, browser-visible |
| `VITE_API_BASE_URL` | `frontend/.env` | Frontend config (not secret) | `client.ts` → fetch base URL | Low — just a URL |

### Where Secrets Live Today

| Location | Contents | Git-tracked? | Docker? |
|----------|----------|-------------|---------|
| `/.env` (repo root) | All global secrets — OpenAI, ElevenLabs, Twilio, n8n, Airtable | **No** (`.gitignore` has `*.env`) | Read by `docker-compose.yml` via `env_file: .env` |
| `/backend/.env` | Copy of root `.env` (identical content) | **No** | Not used in Docker (the root `.env` is used) |
| `/backend/.env.example` | Template with placeholders and documentation | **Yes** (tracked, committed) | Reference only |
| `/frontend/.env.example` | Template: `VITE_API_BASE_URL`, `VITE_API_KEY` | **Yes** (tracked, committed) | Not used in Docker (frontend built at image build time) |
| `/frontend/.env` | Dev-time frontend env | **No** | N/A — Vite injects at build time |
| `/backend/clients/{id}/crm.yaml` | Per-client CRM config — `api_key_env` field references env var NAME | **Yes** (config is committed; secrets are NOT) | Baked into image via `COPY backend/ ./` |
| `docker-compose.yml` | Overrides `DATABASE_URL`, `QORA_SKIP_BACKUP_CHECK` | **Yes** | Defines env injection |
| `pydantic Settings` (`config.py`) | Loads from `.env` → typed fields, `SecretStr` for real secrets | **Yes** (code) | Runtime config class |

### Secret Loading Architecture

```
Startup Flow:
┌──────────────────────────────┐
│ main.py                       │
│ load_dotenv(backend/.env)     │ ← loads ALL vars into os.environ
│ Settings()                    │ ← pydantic-settings reads declared fields
│   ├── SecretStr fields        │   (openai_api_key, elevenlabs_api_key, etc.)
│   ├── model_validator         │   (validates webhook_secret when enabled)
│   └── env_file=".env"        │   (also reads .env, override=False)
└──────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│ CRM Credential Resolution     │
│ crm.yaml → api_key field      │
│   ALL_CAPS? → os.environ.get()│ ← "QUINTANA_AIRTABLE_API_KEY" → env lookup
│   else → literal value        │ ← dev/test direct values
└──────────────────────────────┘
```

**Key observation**: There are TWO secret loading paths:
1. **Pydantic Settings** (`config.py`): typed fields with `SecretStr`, startup validation
2. **os.environ.get()** (`crm_config.py`): raw env lookup for per-client CRM keys, no startup validation

## Affected Areas

- `backend/app/core/config.py` — Settings class where all platform secrets are declared
- `backend/app/core/auth.py` — consumes `settings.qora_api_key` and `settings.qora_webhook_secret`
- `backend/app/main.py` — `load_dotenv()` call and direct `os.getenv()` for CORS/docs
- `backend/app/integrations/crm_config.py` — `resolve_api_key()` does raw `os.environ.get()`
- `backend/app/integrations/crm_config_router.py` — test-connection reads `os.environ.get()` for CRM keys
- `backend/app/voice/webhook.py` — consumes `settings.elevenlabs_api_key`, `settings.openai_api_key`
- `backend/app/summarizer.py` — consumes `settings.openai_api_key`
- `backend/app/elevenlabs/service.py` — consumes `settings.elevenlabs_api_key`
- `/.env` + `/backend/.env` — duplicated secret files
- `/frontend/.env.example` — documents `VITE_API_KEY` (browser-exposed)
- `docker-compose.yml` — `env_file: .env`, environment overrides
- `Dockerfile` — no secret handling (correct — secrets injected at runtime)
- `backend/clients/*/crm.yaml` — references env var names for CRM credentials

## Approaches

### 1. **Centralize + Validate + Document** (Recommended) — Low Effort

Make the existing env-based approach robust without adding external dependencies.

**What it does:**
- Consolidate the two `.env` files into one authoritative source (root `.env` for Docker, symlink or docs for local dev)
- Add all per-client credential env vars to `Settings` as optional `SecretStr` fields, or create a dedicated `ClientSecrets` validator
- Add startup validation for critical secrets (fail-fast if `OPENAI_API_KEY` is missing/empty)
- Replace scattered `os.environ.get()` calls in CRM code with a centralized credential resolver
- Document the secret inventory and operator runbook in `.env.example`
- Add a `scripts/check-secrets.py` pre-flight script that validates all required secrets are set
- Classify env vars: REQUIRED vs OPTIONAL vs PER_CLIENT vs FUTURE

**Pros:**
- Zero new dependencies
- Zero infrastructure changes
- Works for Docker, local dev, and future cloud deploy
- Backward-compatible — existing `.env` files keep working
- Fast to implement (mostly refactoring + validation + docs)

**Cons:**
- Secrets still in plaintext `.env` files (acceptable for current stage)
- No rotation mechanism (not needed yet — single operator)
- Per-client secrets still require env var naming convention

**Effort: Low** (2–4 hours implementation + tests)

### 2. **Encrypted Secrets Store (DB-backed)** — Medium Effort

Store per-client credentials in the database with symmetric encryption.

**What it does:**
- Add a `secrets` table: `(client_id, key_name, encrypted_value, created_at, rotated_at)`
- Encrypt values with a master key (`QORA_MASTER_KEY` env var) using `cryptography.Fernet`
- CRM config references `db:AIRTABLE_KEY` instead of `QUINTANA_AIRTABLE_API_KEY`
- Platform secrets (OpenAI, ElevenLabs) stay in env vars (they're global, not per-client)
- Admin API endpoints to set/rotate per-client secrets (never return plaintext)

**Pros:**
- Per-client secrets isolated and encrypted at rest
- Rotation via API (no restart needed)
- Scales to many clients without growing `.env`
- Clean separation: platform secrets in env, client secrets in DB

**Cons:**
- Requires PostgreSQL or SQLite with encryption extension
- Adds `cryptography` dependency
- Master key still in env (turtles all the way down)
- More complex — needs migration, API endpoints, admin UI changes
- Premature for 1-2 clients

**Effort: Medium** (8–16 hours including migration, API, tests)

### 3. **External Vault (HashiCorp Vault, AWS Secrets Manager, etc.)** — High Effort

Delegate all secret storage to an external secrets manager.

**What it does:**
- All secrets loaded from Vault/AWS SM at startup
- Secrets rotated externally, app polls or gets notified
- Per-client secrets stored as separate vault paths

**Pros:**
- Industry-standard security
- Built-in rotation, audit logging, access control
- Scales to enterprise deployments

**Cons:**
- Significant infrastructure dependency
- Overkill for current stage (single operator, 1-2 clients)
- Deployment complexity (Vault cluster or cloud service required)
- Vendor lock-in risk

**Effort: High** (16+ hours + infrastructure setup)

## Recommendation

**Approach 1: Centralize + Validate + Document.**

Rationale:
1. Qora is pre-production with 1 client (Quintana Seguros) and a single operator (you). The `.env` approach is appropriate for this stage.
2. The biggest current risks are not about encryption — they're about **missing validation**, **duplicated files**, and **undocumented requirements**. A secret could be missing and you'd only discover it at runtime when a call fails.
3. This approach directly fixes those risks with minimal effort and zero new dependencies.
4. It creates a clean foundation that Approach 2 can extend later (Phase C or beyond) when you have multiple clients needing isolated credentials.

**Scope of B8 under this approach:**

| Task | What | Why |
|------|------|-----|
| Unify `.env` | Single source of truth, document local-dev vs Docker paths | Eliminates confusion from duplicate files |
| Startup validation | All CRITICAL secrets validated at `Settings.__init__` with clear error messages | Fail-fast instead of runtime surprise |
| Credential resolver | Centralized module for resolving per-client credentials from env | Replaces scattered `os.environ.get()` |
| Secret classification | Document each var as REQUIRED/OPTIONAL/PER_CLIENT/FUTURE in `.env.example` | Operator knows exactly what to set |
| Pre-flight check script | `scripts/check-secrets.py` — validates secrets before deploy | Quick deployment confidence |
| VITE_API_KEY guidance | Document that this is browser-visible and will be replaced by JWT in Phase C | Prevents false sense of security |
| Clean up dead vars | Remove or clearly mark N8N_*, TWILIO_* as unused/future | Reduce operator confusion |

**Out of scope for B8:**
- External vault integration (premature)
- DB-backed encrypted secrets (premature — revisit when multi-client)
- PostgreSQL (B3 is deferred)
- User login/JWT (Phase C)
- Billing/subscription secrets (no billing system yet)

## Risks

1. **Root `.env` and `backend/.env` are identical copies** — easy to edit one and forget the other. B8 should establish a single source and document the convention.
2. **Per-client CRM secrets use bare `os.environ.get()`** — no startup validation, no `SecretStr` protection. If `QUINTANA_AIRTABLE_API_KEY` is missing, the error appears only when a CRM sync runs mid-call.
3. **`VITE_API_KEY` is baked into the frontend bundle at build time** — anyone with browser dev tools can read it. This is acceptable for Phase B (static admin key) but must be replaced by JWT in Phase C.
4. **Docker image bakes `crm.yaml` files** — these contain env var NAMES (not values), so the image is safe. But operators must know to set the referenced env vars in their deployment environment.
5. **No secret rotation mechanism** — changing a key requires editing `.env` and restarting the container. Acceptable for now; problematic at scale.
6. **`main.py` still uses `os.getenv()` directly** for `QORA_DOCS_ENABLED` and `QORA_ALLOWED_ORIGINS` instead of going through `Settings` — inconsistent with the pydantic-settings pattern (these are already declared in Settings but the runtime reads bypass it).

## Ready for Proposal

**Yes.** The scope is well-defined and low-risk. The proposal should cover:
1. What "centralize" means concretely (single `.env`, symlink guidance, Settings as authority)
2. The startup validation additions (which secrets fail-fast)
3. The credential resolver refactor for CRM
4. The pre-flight script design
5. The `.env.example` classification overhaul
6. The cleanup of dead/unused env vars

Open questions for the user before proposing:
1. Do you want a `scripts/check-secrets.py` that operators run before deploying, or is startup validation in `Settings` sufficient?
2. Should we clean up the N8N and Twilio env vars now (remove from `.env.example`), or keep them as "coming later" placeholders?
3. The `main.py` uses `os.getenv()` directly for CORS origins and docs toggle instead of `settings.*` — should B8 fix that inconsistency, or keep it separate?
