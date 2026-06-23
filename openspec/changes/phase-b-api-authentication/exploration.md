# Exploration: Phase B — API Authentication

## Current State

Qora is a multi-tenant AI call center platform (FastAPI + React SPA) with **zero authentication on any surface**. Every endpoint is open, CORS is `allow_origins=["*"]`, and there is no concept of users, sessions, or API keys anywhere in the codebase.

### Unauthenticated Surfaces

| Surface | Routes | Current Access | Data Exposure |
|---------|--------|----------------|---------------|
| **Admin API — clients** | `POST/GET/PATCH/DELETE /api/v1/clients` | Fully open | CRUD all tenants |
| **Admin API — agents** | `/api/v1/clients/{id}/agents` | Fully open | CRUD agent configs |
| **Admin API — leads** | `GET/POST/PATCH /api/v1/leads` | Open (scoped by `client_id` query param) | PII: names, phones, call history |
| **Admin API — calls** | `GET /api/v1/calls`, `POST /{id}/end` | Fully open | Transcripts, analyses, session lifecycle |
| **Admin API — analytics** | `GET /api/v1/analytics/{client_id}/*` | Open (client_id in path) | Business metrics, agent stats |
| **Admin API — scheduler** | `/api/v1/scheduler/{client_id}/queue` | Fully open | Scheduled call CRUD |
| **Admin API — CRM** | `/api/v1/clients/{id}/crm/*`, `/integrations/*` | Fully open | CRM import triggers, config CRUD |
| **Voice webhook — custom LLM** | `POST /api/v1/voice/custom-llm/*`, `POST /api/v1/voice/{client_id}/custom-llm/*` | Fully open | Core voice pipeline entry point |
| **Voice — initiation** | `POST /api/v1/voice/initiation` | Fully open | Lead context injection |
| **Voice — signed URL** | `GET /api/v1/voice/signed-url` | Fully open | Generates ElevenLabs WebSocket signed URLs |
| **Voice — post-call** | `POST /api/v1/calls/elevenlabs-postcall` | Fully open | Session close + transcript merge |
| **Health check** | `GET /api/v1/health` | Fully open | Status + uptime (benign) |
| **Demo page** | `/demo/*` | Static files, open | Voice call simulator |
| **Docs** | `/docs`, `/redoc` | Open | Full OpenAPI schema |
| **Frontend** | React SPA at `:5173` / Docker catch-all | Open | Dashboard, leads, analytics |

### Frontend API Client

The frontend `apiFetch()` (in `frontend/src/api/client.ts`) sends bare `fetch()` with `Content-Type: application/json` — no auth headers, no tokens, no cookies. Adding auth requires modifying this single function to attach credentials.

### Docker Health Check

`docker-compose.yml` uses `curl -f http://localhost:8000/api/v1/health` for container health checks. This endpoint MUST remain unauthenticated or the health check breaks.

### Settings

`backend/app/core/config.py` has no auth-related settings. No `SECRET_KEY`, no `JWT_SECRET`, no `API_KEY` fields exist.

### Exposed Secrets (Critical Finding)

The root `.env` file contains **real production API keys** committed to the repository:
- OpenAI API key (full `sk-proj-...`)
- ElevenLabs API key
- Airtable API key
- n8n webhook secret and internal API key
- Twilio credentials (labeled as dummy but present)

This is an immediate security risk independent of API auth, but auth makes it more urgent because leaked keys + open API = full system compromise.

## Affected Areas

- `backend/app/main.py` — CORS config, middleware registration, router setup
- `backend/app/core/config.py` — needs auth settings (secret key, token expiry, etc.)
- `backend/app/core/` — new auth module (dependencies, middleware)
- `backend/app/clients/router.py` — needs auth dependency on all endpoints
- `backend/app/leads/router.py` — needs auth dependency
- `backend/app/calls/router.py` — needs auth dependency on admin endpoints; voice webhooks need separate strategy
- `backend/app/analytics/router.py` — needs auth dependency
- `backend/app/scheduler/router.py` — needs auth dependency
- `backend/app/integrations/crm_router.py` — needs auth dependency
- `backend/app/integrations/crm_config_router.py` — needs auth dependency
- `backend/app/agents/router.py` — needs auth dependency
- `backend/app/voice/webhook.py` — webhook auth (separate from admin auth)
- `backend/app/voice/initiation.py` — webhook auth
- `frontend/src/api/client.ts` — needs to attach auth headers
- `docker-compose.yml` — health check must stay unauthenticated
- `docker/entrypoint.sh` — no changes needed
- `backend/tests/` — ~1724 tests need auth fixtures or bypass
- `.env` / `.env.example` — new auth env vars

## Plain Language: What This Means in Practice

### Who authenticates and how?

**Admin dashboard users** (client company operators viewing leads, analytics, calls): They will enter credentials (username/password or API key) to access the dashboard. The frontend stores a token and sends it with every API request.

**ElevenLabs webhooks** (voice pipeline): ElevenLabs calls Qora's `/voice/custom-llm` and `/voice/initiation` endpoints during live calls. These need a shared secret (HMAC signature or API key in header) configured in the ElevenLabs agent settings.

**Demo page**: The `/demo` voice simulator needs a way to get a signed URL without full login — either it's behind the same admin auth, or it gets a limited demo token.

### What can break?

1. **Every existing test** — tests call endpoints directly without auth. All test fixtures need an auth bypass or test API key.
2. **ElevenLabs voice calls** — if webhook auth is misconfigured, live calls stop working immediately. No voice = no product.
3. **Frontend dashboard** — every API call will get 401 until the frontend is updated to send credentials. Users see a blank/error screen.
4. **Docker health checks** — if `/api/v1/health` requires auth, Docker thinks the container is unhealthy and restarts it in a loop.
5. **Demo page** — the signed-URL endpoint becomes inaccessible without auth, breaking the demo flow.
6. **CRM import** — automated imports fail if not updated with credentials.
7. **Local development** — developers need to know how to get a token to use the API during development.

### How we prevent breakage

1. **Health check stays open** — explicitly exclude `/api/v1/health` from auth.
2. **Webhook auth is separate from admin auth** — use HMAC/shared-secret for ElevenLabs, not JWT.
3. **Tests get an auth fixture** — a shared conftest that injects a valid test token.
4. **Frontend gets a login page or API key config** — simplest first: static API key in env var; login page later.
5. **Rollout is all-or-nothing per PR** — don't partially protect some routes (attacker just uses unprotected ones).
6. **Demo page** gets either public access or a demo-specific key.

## Approaches

### 1. Static API Key (Bearer Token) — Recommended First Slice

A single `QORA_API_KEY` environment variable. Admin endpoints require `Authorization: Bearer <key>` header. Webhooks use a separate `QORA_WEBHOOK_SECRET` for HMAC validation.

- **Pros**: Simplest to implement. No user management, no DB schema changes, no login UI. Works immediately for single-operator deployments (Qora's current state). Easy to rotate via env var. Frontend just stores the key in localStorage or env.
- **Cons**: Single shared key — no per-user audit trail. No expiry/rotation mechanism beyond env var restart. Key in localStorage is XSS-vulnerable (acceptable for admin tool, not for public-facing app).
- **Effort**: Low (2-3 days)

### 2. JWT with Username/Password Login

Full login flow: `/api/v1/auth/login` returns a JWT. Frontend shows a login page. Token has expiry + refresh.

- **Pros**: Per-user identity. Token expiry. Industry standard. Foundation for RBAC later.
- **Cons**: Requires User model + DB migration + password hashing + login UI + token refresh logic. Much larger scope. Premature for single-operator MVP.
- **Effort**: High (7-10 days)

### 3. OAuth2/SSO (Google, GitHub)

Delegate auth to an external identity provider.

- **Pros**: No password management. Enterprise-friendly.
- **Cons**: Massive scope. Requires OAuth flow, callback routes, session management. Overkill for current stage.
- **Effort**: Very High (10-15 days)

### 4. Hybrid: API Key now, JWT later

Start with API Key (Approach 1) as B5. Add JWT login as a separate Phase C item when multi-user/RBAC is needed.

- **Pros**: Ship security fast. Clear upgrade path. No throwaway code — API key middleware becomes a FastAPI dependency that JWT replaces later.
- **Cons**: Two auth implementations over time (but the first is tiny).
- **Effort**: Low now + Medium later

## Recommendation

**Approach 4 (Hybrid: API Key now, JWT later)** — Specifically:

### B5 Scope (this change)

1. **Admin auth via static API key**: `QORA_API_KEY` env var. FastAPI `Depends(require_api_key)` on all admin routes. Returns 401 without valid `Authorization: Bearer <key>`.
2. **Webhook auth via HMAC or shared secret**: `QORA_WEBHOOK_SECRET` env var. Voice endpoints (`/voice/custom-llm`, `/voice/initiation`, `/calls/elevenlabs-postcall`) validate a header signature. ElevenLabs agent config updated with the secret.
3. **Explicit exclusions**: `/api/v1/health` (Docker), `/docs` + `/redoc` (dev convenience, disable in production via env flag), `/demo` (optional: behind admin key or public).
4. **CORS lockdown**: Change `allow_origins=["*"]` to configurable `QORA_ALLOWED_ORIGINS` env var.
5. **Frontend update**: `apiFetch()` reads API key from env/localStorage, attaches `Authorization` header.
6. **Test fixture**: `conftest.py` provides auth headers; all existing tests pass without changing test logic.
7. **.env.example update**: Add new auth vars with clear documentation.
8. **Rotate exposed secrets**: Document that the committed `.env` keys must be rotated.

### Explicitly OUT of scope for B5

- User model / DB migration
- Login page / registration
- JWT / token refresh
- RBAC / permissions
- Rate limiting (separate Phase B or C item)
- Webhook signature verification for n8n (n8n is not in runtime path)

## Risks

1. **ElevenLabs webhook auth mismatch** — If the HMAC secret doesn't match between Qora and ElevenLabs agent config, live voice calls silently fail. **Mitigation**: Webhook auth must be opt-in via env var (`QORA_WEBHOOK_AUTH_ENABLED=true`), defaulting to disabled so existing deployments aren't broken. Enable only after configuring ElevenLabs.
2. **Test suite breakage** — 1724 tests suddenly get 401s. **Mitigation**: Auth fixture in conftest.py; tests that don't provide auth get a bypass via test-mode flag or fixture injection.
3. **Committed secrets in `.env`** — Real API keys are already exposed in git history. **Mitigation**: `.env` must be in `.gitignore` (verify), keys must be rotated, and this should be documented as a mandatory post-B5 action.
4. **Demo page access** — Protecting `/voice/signed-url` breaks the demo unless the demo page can authenticate. **Mitigation**: Either the demo page includes the API key (acceptable for internal demos) or signed-url gets a separate demo token mechanism.
5. **Local dev friction** — Developers must now set `QORA_API_KEY` to use the API. **Mitigation**: `.env.example` includes a default dev key; documentation is clear.

## Open Questions for User

1. **Demo page access model**: Should the demo page remain publicly accessible (no auth on `/voice/signed-url` and `/demo`), or should it require the admin API key? Public demo is simpler but means anyone with the URL can trigger ElevenLabs calls (which cost money).

2. **Webhook auth rollout**: Should webhook auth (HMAC on voice endpoints) be part of B5, or deferred to a separate slice? It requires coordinated changes in ElevenLabs agent config, which is an external system.

3. **OpenAPI docs in production**: Should `/docs` and `/redoc` be disabled in production (common security practice), or kept open for API consumers?

4. **API key delivery to frontend**: For the React dashboard, should the API key be:
   - (a) Set as a Vite env var at build time (`VITE_API_KEY`) — simplest but baked into the bundle
   - (b) Entered by the user in a simple "Enter API Key" prompt and stored in localStorage
   - (c) Deferred entirely — keep the frontend open for now and only protect the API

5. **Secret rotation urgency**: The committed `.env` has real OpenAI/ElevenLabs/Airtable keys. Should we rotate these BEFORE B5, or is B5 the vehicle for addressing this?

## Ready for Proposal

**Yes** — pending answers to the 5 open questions above. The recommended approach (API Key + HMAC, with JWT deferred) has clear scope boundaries and low implementation risk. The proposal can be drafted now with the open questions noted as decision points, or after the user answers them for a tighter spec.

Suggested next phase: **sdd-propose** (proposal).
