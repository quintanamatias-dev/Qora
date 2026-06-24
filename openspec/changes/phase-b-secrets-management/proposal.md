# Proposal: Phase B8 — Secrets Management

## Intent

Qora currently loads secrets through two disconnected paths — pydantic `Settings` (typed, `SecretStr`) and raw `os.environ.get()` (untyped, no validation) — with no startup guard on most CRITICAL credentials. Both `.env` files are identical copies (root and `backend/`) with no clear authority. Dead env vars (`N8N_*`, `TWILIO_*`, `BROKER_NAME`) pollute the operator experience. The biggest risks are not encryption — they are **missing startup validation**, **duplicated files**, and **undocumented requirements** that only surface as runtime call failures.

B8 makes secrets management production-grade for the current stage: single operator, 1–2 clients, no external vault dependency.

---

## How Secrets Are Managed After This Change

> Plain-language summary for operators.

- **One file, one truth.** There is a single `.env` at the repo root. Local dev also reads it via `backend/.env` symlink. Docker already uses the root file — nothing changes for Docker.
- **The app refuses to start if a critical secret is missing.** OpenAI, ElevenLabs, and `QORA_API_KEY` are validated at startup before any request is served. Clear error messages name the missing variable.
- **Per-client CRM secrets follow the same validation.** `QUINTANA_AIRTABLE_API_KEY` (and future client keys) are validated at startup, not at first CRM sync.
- **A pre-flight script runs before every deploy.** `scripts/check-secrets.py` validates all required variables and prints a classification table — operators know exactly what to set and what can stay empty.
- **Dead variables are removed from `.env.example`.** `N8N_*`, `TWILIO_*`, and `BROKER_NAME` move to a `## Future / Not Yet Wired` section with explicit labels, eliminating confusion.
- **Frontend `VITE_API_KEY` is documented as browser-visible** and its Phase C replacement path (JWT) is explicit in the operator runbook.

---

## Scope

### In Scope

- Establish root `.env` as single authority; document the local-dev symlink convention
- Add startup `fail-fast` validation for ALL CRITICAL secrets in `Settings` model validator
- Add startup validation for per-client CRM credential env vars (extend the `Settings` validator or introduce a startup hook)
- Replace scattered `os.getenv()` calls in `main.py` (`QORA_DOCS_ENABLED`, `QORA_ALLOWED_ORIGINS`) with `settings.*` reads — eliminate bypass of the pydantic layer
- Create `scripts/check-secrets.py` pre-flight validation script
- Overhaul `backend/.env.example` with secret classification: REQUIRED / OPTIONAL / PER_CLIENT / FUTURE
- Create operator runbook: `docs/ops/secrets-management.md`
- Add missing B5/B6/B7 vars (`QORA_API_KEY`, `QORA_WEBHOOK_SECRET`, `QORA_ALLOWED_ORIGINS`, `QORA_DEMO_CLIENT_ID`, `QORA_DEMO_AGENT_ID`) to `.env.example`
- Clean up dead vars (`N8N_*`, `TWILIO_*`, `BROKER_NAME`) — move to clearly labelled `## Future` section

### Out of Scope

- External vault integration (HashiCorp Vault, AWS Secrets Manager) — premature at this stage
- DB-backed encrypted secret store — revisit when client count > 2
- Per-client secret rotation API or admin UI for secret management
- User login / JWT (Phase C)
- Billing or subscription secrets (no billing system yet)
- PostgreSQL migration (Phase B3 deferred)

---

## Capabilities

### New Capabilities

- `secrets-validation`: Startup secret validation contract — which secrets cause hard fail vs warning by environment, covering both `Settings` fields and per-client CRM credentials
- `secrets-preflight`: Pre-flight CLI script (`scripts/check-secrets.py`) that validates and classifies all env vars before deploy

### Modified Capabilities

- None — this change establishes new specs; existing capabilities (auth, webhook-auth, crm-config) are not modified at the requirements level

---

## Secret Classification Table

> Variable names only. No values included.

| Variable | Class | Tier | Consumed By | Notes |
|---|---|---|---|---|
| `OPENAI_API_KEY` | REQUIRED | CRITICAL | `Settings.openai_api_key` → webhook, summarizer | Billable; startup fail if missing |
| `ELEVENLABS_API_KEY` | REQUIRED | CRITICAL | `Settings.elevenlabs_api_key` → webhook, EL service | Billable; startup fail if missing |
| `QORA_API_KEY` | REQUIRED | HIGH | `Settings.qora_api_key` → `auth.require_api_key` | Admin API gate; startup warning if None |
| `QORA_WEBHOOK_SECRET` | CONDITIONAL | HIGH | `Settings.qora_webhook_secret` → webhook auth | Required only if `QORA_WEBHOOK_AUTH_ENABLED=true` |
| `QUINTANA_AIRTABLE_API_KEY` | REQUIRED (if CRM active) | HIGH | `crm_config.resolve_api_key()` | Per-client; startup fail if crm.yaml references it |
| `DATABASE_URL` | OPTIONAL | MEDIUM | `Settings.database_url` | Defaults to SQLite; Docker overrides |
| `ELEVENLABS_AGENT_ID` | OPTIONAL | LOW | `Settings.elevenlabs_agent_id` | Public identifier; has hardcoded default |
| `ELEVENLABS_VOICE_ID` | OPTIONAL | LOW | `Settings.elevenlabs_voice_id` | Public identifier; has hardcoded default |
| `QORA_ALLOWED_ORIGINS` | OPTIONAL | LOW | `main.py` CORS (currently bypasses Settings) | Defaults `*`; B8 routes via `settings.*` |
| `QORA_DOCS_ENABLED` | OPTIONAL | LOW | `main.py` FastAPI docs (currently bypasses Settings) | B8 routes via `settings.*` |
| `QORA_DEMO_CLIENT_ID` | OPTIONAL | LOW | `Settings.qora_demo_client_id` | Demo identity |
| `QORA_DEMO_AGENT_ID` | OPTIONAL | LOW | `Settings.qora_demo_agent_id` | Demo identity |
| `QORA_SESSION_TTL_SECONDS` | OPTIONAL | LOW | `Settings.qora_session_ttl_seconds` | Defaults 4h |
| `VITE_API_KEY` | FRONTEND | HIGH | `frontend/src/api/client.ts` Bearer header | **Browser-visible**; baked at build time; Phase C → JWT |
| `VITE_API_BASE_URL` | FRONTEND | LOW | `client.ts` fetch base | Not secret |
| `N8N_*` (5 vars) | FUTURE | — | Not wired in app code | Move to `## Future` section |
| `TWILIO_*` (3 vars) | FUTURE | — | Not wired in app code | Move to `## Future` section |
| `BROKER_NAME` | LEGACY | — | Not in Settings; not in app code | Remove from active section |

---

## Approach

**Centralize + Validate + Document.** Zero new dependencies; zero infrastructure changes. Extends the existing pydantic-settings pattern already established in `config.py`.

1. **Single `.env` authority** — root `.env` is authoritative. Local dev: `backend/.env` becomes a symlink to `../.env` (or documented fallback). `load_dotenv()` in `main.py` stays pointed at `backend/.env` path — symlink makes this transparent.
2. **`Settings` startup validation** — add a `@model_validator` that fails fast on missing CRITICAL secrets. Mirror the existing `validate_webhook_secret_when_enabled` pattern already proven in B5.
3. **CRM startup validation** — add a startup hook (post-`Settings` init, pre-request serving) that reads all `crm.yaml` files, finds env-var-name credentials, and validates they are set. Hard fail if any referenced env var is missing.
4. **`main.py` cleanup** — replace `os.getenv("QORA_DOCS_ENABLED", ...)` and `os.getenv("QORA_ALLOWED_ORIGINS", ...)` with `settings.qora_docs_enabled` and `settings.qora_allowed_origins`. Both fields already exist in `Settings` — this is a two-line fix.
5. **Pre-flight script** — `scripts/check-secrets.py` prints classification table, validates REQUIRED vars, warns on OPTIONAL gaps. Exit 0 = deploy-safe; exit 1 = blocked.
6. **`.env.example` overhaul** — reclassify every variable, add generation hints, document the VITE_API_KEY browser-visibility warning, move dead vars to `## Future`.
7. **Operator runbook** — `docs/ops/secrets-management.md`: classification table, local dev setup, Docker deploy steps, rotation procedure (currently: edit + restart), VITE_API_KEY build-time note.

---

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `backend/app/core/config.py` | Modified | Add `@model_validator` for CRITICAL secret fail-fast |
| `backend/app/main.py` | Modified | Replace 2 `os.getenv()` calls with `settings.*`; add CRM startup validation hook |
| `backend/.env.example` | Modified | Full classification overhaul — REQUIRED/OPTIONAL/PER_CLIENT/FUTURE sections |
| `frontend/.env.example` | Modified | Add VITE_API_KEY browser-visibility warning and Phase C note |
| `scripts/check-secrets.py` | New | Pre-flight validation script |
| `docs/ops/secrets-management.md` | New | Operator runbook |
| `backend/.env` → `../.env` | Modified | Convert to symlink OR document explicit copy convention |
| `docker-compose.yml` | No change | Already reads root `.env` correctly |
| `Dockerfile` | No change | Correct — no secrets baked into image |
| `backend/clients/*/crm.yaml` | No change | Config files are correct; only runtime validation changes |

---

## Operational Model by Environment

| Environment | Secret Source | Validation | Notes |
|---|---|---|---|
| Local dev | `backend/.env` (symlink to root `.env`) | Startup validator in `Settings` | Operator maintains one file |
| Docker (single container) | Root `.env` via `env_file: .env` in `docker-compose.yml` | Startup validator + pre-flight script | Run `check-secrets.py` before `docker compose up --build` |
| CI/CD (future) | Environment variables injected by CI system | Pre-flight script as pipeline step | No `.env` file needed in CI |
| Staging/Production (future) | Environment variables injected by hosting platform | Pre-flight script + startup validator | Vault/SM can replace injection in Phase C+ |

---

## Validation Model

| Secret Class | Missing in Dev | Missing in Production | Failure Type |
|---|---|---|---|
| REQUIRED CRITICAL (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) | Hard fail — startup aborts | Hard fail — startup aborts | `ValueError` in `Settings.__init__` |
| REQUIRED HIGH (`QORA_API_KEY`) | Warning — app starts, admin routes open | Hard fail — startup aborts | Env-aware check (detect `DEBUG` or `ENV=production`) |
| CONDITIONAL HIGH (`QORA_WEBHOOK_SECRET`) | Skip if auth disabled | Hard fail if `QORA_WEBHOOK_AUTH_ENABLED=true` | Already implemented in B5 |
| PER_CLIENT CRM credentials | Hard fail if crm.yaml references the var | Hard fail | Startup hook post-Settings init |
| OPTIONAL / FUTURE | Silent — defaults apply | Silent — defaults apply | No failure |

---

## What Is Not Included and Why

**External vault (Vault, AWS SM, GCP Secret Manager):** Adds infrastructure dependency and operational complexity inappropriate for a single-operator, 1-client stage. The env-based approach is industry-standard for this scale. The validation and classification work in B8 creates a clean migration target — a future `secrets-loader.py` module can swap env var resolution for vault lookups with zero changes to the validation layer.

**DB-backed encrypted per-client secrets:** Per-client secrets grow linearly with client count. At 1 client, the overhead of a `secrets` table, master key management, and rotation API is not justified. The current `crm.yaml` + env var convention is correct and secure for this stage. Revisit at 3+ clients.

**Secret rotation automation:** Manual rotation (edit `.env` + `docker compose restart`) is correct at this stage. The pre-flight script and runbook make it safe and explicit.

---

## Migration Strategy

| Step | What | Risk |
|---|---|---|
| 1 | Add `@model_validator` for CRITICAL secrets in `config.py` | Only breaks if operator is missing `OPENAI_API_KEY` or `ELEVENLABS_API_KEY` — they would already be broken at runtime |
| 2 | Fix `main.py` `os.getenv()` bypasses → `settings.*` | Zero behavior change — fields are already set from same env vars |
| 3 | Add CRM startup validation hook | Only breaks if `crm.yaml` references an env var that is not set — operator discovery is the point |
| 4 | Convert/document `backend/.env` → symlink convention | Local-dev only; Docker unaffected |
| 5 | Overhaul `.env.example` | Documentation only; no runtime impact |
| 6 | Create `scripts/check-secrets.py` | Additive; no runtime impact |
| 7 | Create `docs/ops/secrets-management.md` | Documentation only |

**No existing functionality breaks.** Docker, demo, frontend auth, ElevenLabs, Airtable, and local dev all continue to work. Steps 1 and 3 are the only ones that can cause startup failures — and only when a required secret was already missing (which would have caused a runtime failure anyway).

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Operator discovers a missing env var at first deploy post-B8 | Medium | Pre-flight script catches it before `docker compose up`; clear error message names the variable |
| `backend/.env` symlink causes confusion on Windows | Low | Document fallback (explicit copy); `.env.example` instructions cover both paths |
| CRM startup validation hook is too aggressive (fails on clients with no crm.yaml) | Low | Hook skips clients with no `crm.yaml`; only validates vars referenced by existing configs |
| `QORA_API_KEY` production hard-fail breaks existing deployments without it | Low | Field is already `Optional` in `Settings`; add env-aware production check (detect `ENV=production` or `DEBUG=false`) |

---

## Rollback Plan

All changes are backward-compatible. Rollback is:

1. Revert `config.py` model validator — remove the added `@model_validator` block.
2. Revert `main.py` — restore the two `os.getenv()` calls.
3. Revert `backend/.env` — restore copy from root (if symlink change is reverted).
4. Delete `scripts/check-secrets.py` and `docs/ops/secrets-management.md`.

No data migration, no schema change, no Docker volume impact.

---

## Dependencies

- No new Python dependencies
- No infrastructure changes
- Prerequisite: B5 (auth) is complete ✅

---

## Success Criteria

- [ ] Starting the app without `OPENAI_API_KEY` or `ELEVENLABS_API_KEY` aborts with a clear error naming the missing variable
- [ ] Starting the app when `crm.yaml` references an unset env var aborts with a clear error
- [ ] `main.py` contains no direct `os.getenv()` calls for vars declared in `Settings`
- [ ] `scripts/check-secrets.py` exits 0 on a correctly configured environment and exits 1 if any REQUIRED var is missing
- [ ] `backend/.env.example` has every active variable classified as REQUIRED / OPTIONAL / PER_CLIENT / FUTURE
- [ ] `docs/ops/secrets-management.md` exists and covers: local setup, Docker deploy, secret rotation, VITE_API_KEY warning
- [ ] Docker `docker compose up --build` still succeeds with the same `.env` used before this change
- [ ] Demo endpoint, frontend auth, ElevenLabs voice pipeline, and Airtable CRM sync remain functional

---

## Open Questions Before Specs

> Decisions needed from the user before writing specs.

1. **CRM validation timing:** Should missing per-client CRM credentials cause a **hard startup fail** (safest — no silent CRM errors mid-call) or a **warning with graceful degradation** (app starts; CRM sync fails loudly when triggered)? _Recommendation: hard fail — consistent with the `OPENAI_API_KEY` pattern._

2. **Production detection for `QORA_API_KEY`:** Should the production hard-fail for `QORA_API_KEY` be triggered by `DEBUG=false`, an explicit `ENV=production` env var, or always a hard fail regardless of environment? _Recommendation: always warn in dev, always hard fail if `QORA_API_KEY` is `None`; the "change-me-before-production" placeholder approach is a smell — even in dev the key should be set._

3. **`backend/.env` symlink vs explicit copy:** Prefer symlink (one file, less drift risk) or documented explicit copy (simpler for new contributors, no symlink edge cases)? _Recommendation: symlink — but document the copy fallback clearly._

4. **Dead vars (`N8N_*`, `TWILIO_*`, `BROKER_NAME`) — remove or comment?** Remove from `.env.example` entirely, or keep as commented-out `## Future` block? _Recommendation: keep as clearly labelled `## Future / Not Yet Wired` section — operators can see what's coming._

5. **Pre-flight script scope:** Should `scripts/check-secrets.py` also validate that `QORA_API_KEY` is not the literal `change-me-before-production` placeholder (a common footgun)? _Recommendation: yes — add a known-weak-value check for high-risk vars._

---

## Next Recommended Phase

→ **sdd-spec** for `secrets-validation` and `secrets-preflight` capabilities.

Then **sdd-design** if the CRM startup validation hook warrants an architecture decision (likely a simple addition to the lifespan startup sequence, but the spec should make it explicit).

Finally **sdd-tasks** → **sdd-apply**.
