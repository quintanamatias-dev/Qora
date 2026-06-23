# Proposal: Phase B5 — API Authentication

## Intent

Every Qora API surface is currently fully open. Any actor with the URL can read PII (leads, transcripts), mutate tenant state, or generate ElevenLabs calls (which cost money). B5 adds the minimum viable authentication layer: static API key for admin surfaces, session-start auth binding for voice/demo calls, scoped demo write permissions for the full Qora pipeline, webhook credential for voice endpoints, tenant isolation enforcement, and CORS lockdown — without introducing login UI, user models, or JWT.

## Scope

### In Scope

- `QORA_API_KEY` env var — admin API protection via `Authorization: Bearer <key>`.
- `QORA_WEBHOOK_SECRET` env var — webhook protection for ElevenLabs voice endpoints via shared-secret header (opt-in, disabled by default).
- **Session-start auth binding**: auth and context resolution happen once at call/session start. The authorized session caches `client_id`, `agent_id`/slug, `lead_id`, scopes/permissions, and voice context in memory. Later turns use the in-memory fast path — no DB or network lookups per turn.
- **Per-turn fast path**: agent response turns must not do DB/network auth lookups. All required identity checks are local/in-memory/session-scoped unless a tool explicitly needs persistence.
- **Tool scope validation**: tool execution validates scope quickly against the authorized session/client/agent identity before writing or loading data.
- **Scoped demo credentials**: `/demo` resolves client/agent identity from Qora's own `Client`+`Agent` data model using `QORA_DEMO_CLIENT_ID` + `QORA_DEMO_AGENT_ID` env vars. Demo calls are allowed to perform normal voice-pipeline writes (call session, transcript, captured data, post-call analysis where applicable) because `/demo` is used to test the full Qora pipeline.
- **Demo write boundary**: demo writes are limited to the selected client/agent/lead/session scope. Admin, config, and global writes are not permitted.
- **Scheduler-started calls**: scheduler-created calls derive their authorized session naturally from `scheduled_call → lead → client → agent` identity — no separate auth resolution needed.
- Tenant isolation: every admin route that accepts a `client_id` must verify the caller is authorized for that tenant.
- CORS lockdown: replace `allow_origins=["*"]` with `QORA_ALLOWED_ORIGINS` env var.
- Frontend `apiFetch()` update: attach `Authorization: Bearer <key>` header.
- Test fixture: `conftest.py` provides valid auth headers so all ~1724 tests pass without per-test changes.
- Explicit exclusions: `/api/v1/health` (Docker), `/docs` + `/redoc` (configurable), `/demo` static files.
- `.env.example` update with all new auth vars.

### Out of Scope

- User model, DB migration, login page.
- JWT / token refresh / RBAC.
- Rate limiting (separate item).
- Supabase auth integration (future Phase C direction).
- n8n webhook signature verification (n8n is not in the real-time voice path).
- Per-tenant API key management (single global key for B5 MVP; key-management table is Phase C+).

## Capabilities

### New Capabilities

- `api-key-auth`: Static bearer token authentication dependency for all admin routes.
- `webhook-auth`: Shared-secret header verification for ElevenLabs voice endpoints.
- `session-auth-binding`: Session-start context resolution that caches `client_id`, `agent_id`, `lead_id`, scopes, and voice context in memory for fast per-turn access.
- `tenant-isolation`: Per-request enforcement that a caller can only access their own client's data.
- `demo-scoped-credentials`: Server-side resolution of demo client/agent identity using env-configured IDs; demo surfaces may perform full-pipeline writes within the selected client/agent/lead/session scope.

### Modified Capabilities

- `demo-agent-selection`: Demo page already reads `elevenlabs_agent_id` from the Agent API — auth must not break this flow; demo API calls must carry correct scoped auth context resolved server-side, including write permissions for the full pipeline.

## Approach

**API Key (Hybrid strategy — Approach 4 from exploration):**

1. `QORA_API_KEY` in `.env` → `Settings.qora_api_key: SecretStr` in `config.py`.
2. FastAPI dependency `require_api_key(request)` reads `Authorization: Bearer <key>`, compares with `secrets.compare_digest`. Returns 401 on mismatch.
3. All admin routers add `Depends(require_api_key)`. Voice webhook endpoints use a separate `require_webhook_secret` dependency, enabled only when `QORA_WEBHOOK_AUTH_ENABLED=true`.
4. Frontend `apiFetch()` reads `VITE_API_KEY` from build-time env and injects `Authorization` header.
5. JWT login (Supabase or custom) is added later as Phase C — the `require_api_key` dependency is replaced by `require_jwt` with zero router changes.

**Session-start auth binding (approved architecture):**

- At call/session start (voice initiation or demo session open), Qora resolves and validates the full auth context: `client_id`, `agent_id`/slug, `lead_id`, scopes/permissions, and voice context.
- The resolved identity is cached in memory in an `AuthorizedSession` object scoped to that call/session.
- Per-turn agent responses use the cached `AuthorizedSession` — no DB reads, no network calls, no re-auth per message. This is the **mandatory fast path**.
- Tool execution validates scope against the cached `AuthorizedSession` before any write or load operation. Scope checks are in-memory and synchronous.
- Scheduler-started calls derive their `AuthorizedSession` from the `scheduled_call → lead → client → agent` identity chain, which is already available at call creation time.

**Scoped demo credentials (replaces the unsafe `/demo/config.js` global-key approach):**

- `/demo` static files stay public (no auth on static mount).
- `/demo` must NOT receive or expose `QORA_API_KEY`. There is **no public endpoint that hands out admin credentials**.
- A dedicated backend endpoint `/api/v1/demo/context` (auth-exempt, returns only demo-safe data) resolves the agent context using `QORA_DEMO_CLIENT_ID` + `QORA_DEMO_AGENT_ID` env vars. Returns only: `elevenlabs_agent_id`, `client_name`, `agent_name`. No key, secret, or admin-level data.
- Demo calls establish a full `AuthorizedSession` at session start (same mechanism as production). This session carries full pipeline write permissions: call session, transcript, captured data, and post-call analysis are all writable — because `/demo` is used to QA the full Qora pipeline.
- Demo writes are strictly bounded: only the configured demo `client_id` / `agent_id` / `lead_id` / `session_id` can be touched. Admin, config, and global writes are blocked at the scope-validation layer.
- Qora remains the source of truth for client/agent identity and tenant routing.

**Tenant isolation:**

- Admin routes that accept `client_id` validate that the request's API key maps to the allowed tenant. For the current single-operator MVP, one global key covers all tenants. The dependency is designed so per-tenant keys can be added later without changing router signatures.

**Where login fits later:**

- Phase C adds Supabase Auth or a custom `/api/v1/auth/login` route returning JWT. `require_api_key` is swapped for `require_jwt`. JWT payload carries `user_id` + `allowed_client_ids`; tenant isolation reads from JWT claims. The `AuthorizedSession` model is extended to carry JWT-derived identity.

## Latency Impact

| Surface | Auth mechanism | Added latency | Risk |
|---------|---------------|---------------|------|
| Admin API | Bearer token header comparison | ~0 ms (in-memory `secrets.compare_digest`) | None |
| Voice initiation (`/voice/initiation`) | Shared-secret header (opt-in) + session creation | ~1 DB read at session start | Low — one-time per call |
| Voice custom-LLM (`/voice/custom-llm/*`) | Cached `AuthorizedSession` (in-memory) | **~0 ms** | **None — fast path, zero I/O** |
| Voice post-call (`/calls/elevenlabs-postcall`) | Cached session or post-call identity | ~0 ms | Negligible |
| Signed URL (`/voice/signed-url`) | Bearer token (same as admin) | ~0 ms | None |
| Demo context (`/api/v1/demo/context`) | Auth-exempt (read-only, demo-safe) | ~1 DB read on page load | Low — one-time load |
| Demo writes | Cached `AuthorizedSession`, scoped | ~0 ms per turn | None — scope check is in-memory |
| Scheduler-started call | Session derived from `scheduled_call` identity | ~0 ms (identity already resolved) | None |

**Hard latency constraint (non-negotiable):** Per-turn agent response must not do DB or network auth lookups. The `AuthorizedSession` must be populated at session start and read from memory on every subsequent turn and tool call. Any auth path that touches the DB or network per turn is a build-blocking defect.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/core/config.py` | Modified | Add `qora_api_key`, `qora_webhook_secret`, `qora_webhook_auth_enabled`, `qora_allowed_origins`, `qora_demo_client_id`, `qora_demo_agent_id` |
| `backend/app/core/auth.py` | New | `require_api_key`, `require_webhook_secret`, `AuthorizedSession`, `resolve_session_context` FastAPI dependencies |
| `backend/app/core/session_store.py` | New | In-memory store for active `AuthorizedSession` objects, keyed by `session_id` / call ID |
| `backend/app/demo/router.py` | New | `/api/v1/demo/context` (auth-exempt) and session-start scoped auth for demo calls |
| `backend/app/main.py` | Modified | CORS lockdown; register demo router; remove any global-key exposure |
| `backend/app/clients/router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/agents/router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/leads/router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/calls/router.py` | Modified | Admin routes: `Depends(require_api_key)`; voice turns: `Depends(get_authorized_session)`; post-call: scoped session |
| `backend/app/analytics/router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/scheduler/router.py` | Modified | Add `Depends(require_api_key)`; scheduler call creation derives `AuthorizedSession` |
| `backend/app/integrations/crm_router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/integrations/crm_config_router.py` | Modified | Add `Depends(require_api_key)` |
| `backend/app/voice/webhook.py` | Modified | Session-start creates `AuthorizedSession`; turns use `get_authorized_session` (in-memory) |
| `backend/app/voice/initiation.py` | Modified | `Depends(require_webhook_secret)` + `AuthorizedSession` creation at call start |
| `frontend/src/api/client.ts` | Modified | Inject `Authorization: Bearer <key>` from `VITE_API_KEY` |
| `backend/app/static/index.html` | Modified | Fetch demo context from `/api/v1/demo/context` (no key injection) |
| `backend/tests/conftest.py` | Modified | Auth fixture injects valid Bearer header; session fixture seeds `AuthorizedSession` |
| `.env.example` | Modified | Document all new auth env vars |
| `.env` | Rotate (manual) | Real secrets committed to git history must be rotated post-B5 |

## Operational Model: Adding a New Client Agent (End-to-End)

1. **Qora stores**: Create `Client` + `Agent` records via admin API or panel. Agent record includes `elevenlabs_agent_id` (can be null initially).
2. **Qora is source of truth**: Client/agent identity and tenant routing live entirely in Qora's DB. ElevenLabs only provides the voice pipeline.
3. **ElevenLabs manual config** (paste in the ElevenLabs dashboard for this agent):
   - **Custom LLM URL**: `https://your-qora.app/api/v1/voice/{client_id}/custom-llm`
   - **Initiation Webhook URL**: `https://your-qora.app/api/v1/voice/initiation`
   - **Webhook secret** (if `QORA_WEBHOOK_AUTH_ENABLED=true`): the value of `QORA_WEBHOOK_SECRET`
   - **Custom LLM extra body**: `{"client_id": "{client_id}"}` — ensures routing to the right tenant
4. **Copy back to Qora**: paste the `elevenlabs_agent_id` from ElevenLabs into the Agent record.
5. **For demo use**: set `QORA_DEMO_CLIENT_ID` and `QORA_DEMO_AGENT_ID` to point at any valid client/agent in the DB. Restart backend. `/demo` resolves that agent's context automatically and establishes a scoped `AuthorizedSession` at session start.
6. **Verify**: open `/demo`, select client+agent from the resolved context, start a conversation. Confirm transcripts and session data are written.

**What Qora manages vs ElevenLabs:**

| Config item | Managed by | How |
|-------------|-----------|-----|
| Custom LLM URL | ElevenLabs dashboard (manual) | Paste once per agent |
| Webhook secret | ElevenLabs dashboard (manual) | Paste `QORA_WEBHOOK_SECRET` value |
| `client_id` routing | Qora (URL path) | Encoded in the Custom LLM URL |
| Agent prompt / TTS / voice | Qora DB + ElevenLabs sync | Existing `elevenlabs-config` skill |
| API key (admin) | Qora `.env` | `QORA_API_KEY` env var |
| Demo client/agent identity | Qora `.env` + DB | `QORA_DEMO_CLIENT_ID` / `QORA_DEMO_AGENT_ID` pointing to real records |
| Authorized session (per call) | Qora in-memory store | `session_store.py`, keyed by call/session ID |

## Breakage Risk

| Surface | Risk | Severity | Mitigation |
|---------|------|----------|-----------|
| ~1724 tests | All return 401 or missing session | High | `conftest.py` auth fixture + session seed; test-mode bypass via env flag |
| ElevenLabs voice calls | Webhook secret mismatch → calls fail | Critical | Webhook auth opt-in (`QORA_WEBHOOK_AUTH_ENABLED=false` default) |
| Demo page writes | 403 if session scope too narrow | High | Full pipeline writes enabled within demo-scoped `AuthorizedSession` |
| Per-turn latency | DB call introduced on hot path | Critical | `AuthorizedSession` must be in-memory; per-turn DB calls are build-blocking |
| Frontend dashboard | 401 on every API call | High | `apiFetch()` update; `VITE_API_KEY` env var at build |
| Docker health check | Must remain open | Medium | Explicit exclusion in `require_api_key` dependency |
| Scheduler calls | Session not established at call creation | Medium | `scheduled_call → lead → client → agent` chain derives session at creation time |
| CRM imports | Automated imports 401 | Medium | Same admin key; update CRM client config |
| Local dev | Must set `QORA_API_KEY` | Low | `.env.example` default dev key; docs |
| OpenAPI docs (`/docs`) | Exposed schema | Low | `QORA_DOCS_ENABLED=true` default; disable in prod |

## Manual Verification Plan

1. **Admin API**: `curl -H "Authorization: Bearer <key>" http://localhost:8000/api/v1/clients` → 200. Without header → 401.
2. **Health check**: `curl http://localhost:8000/api/v1/health` → 200 (no key needed).
3. **Demo context**: `curl http://localhost:8000/api/v1/demo/context` → 200 with `{elevenlabs_agent_id, client_name, agent_name}` — no key or secret in response.
4. **Demo page E2E full pipeline**: open `/demo`, select client+agent, start conversation → voice works, transcript written, call session created, post-call analysis triggered. Verify no admin key appears in network inspector.
5. **Demo scope enforcement**: attempt to write to a different tenant's data via the demo session → 403.
6. **Per-turn fast path**: instrument `/voice/custom-llm/*` — confirm zero DB queries per turn. Any DB call on this path is a defect.
7. **Scheduler call**: create a `ScheduledCall`, trigger it, verify the resulting call session has a valid `AuthorizedSession` without manual auth input.
8. **Test suite**: `pytest backend/tests/` → all pass (auth fixture + session fixture injected).
9. **CORS**: `curl -H "Origin: http://malicious.com" ...` → rejected if not in `QORA_ALLOWED_ORIGINS`.
10. **Webhook auth (ElevenLabs)** *(if `QORA_WEBHOOK_AUTH_ENABLED=true`)*: configure secret in ElevenLabs dashboard, make a live test call from `/demo`, verify transcript logged; remove secret from ElevenLabs → call returns 401 at `/voice/initiation`; restore → call resumes.

## Open Questions / Decisions Needed Before Spec

1. **`AuthorizedSession` storage**: In-memory dict keyed by call/session ID is simple and fast. Should it have a TTL (e.g., 4 hours) to prevent stale sessions from accumulating, or is session cleanup tied to call lifecycle events?

2. **Webhook auth rollout order**: Should webhook auth be enabled in the same PR as admin auth, or in a follow-up slice with a dedicated ElevenLabs reconfiguration step? A follow-up slice is safer given the critical breakage risk.

3. **Single key vs per-tenant keys**: For B5, a single global `QORA_API_KEY` covers all tenants. Is that acceptable, or does the user want per-tenant keys now (requires a key-management DB table)?

4. **OpenAPI docs**: `QORA_DOCS_ENABLED` toggle acceptable, or should `/docs` be removed entirely in production?

5. **Secret rotation**: Before B5 is merged, the real OpenAI/ElevenLabs/Airtable keys committed to `.env` must be rotated. Who is responsible and when?

## Rollback Plan

- Remove `Depends(require_api_key)` from all routers via a single commit reverting `backend/app/core/auth.py` and all router changes.
- Remove `backend/app/core/session_store.py` and all `AuthorizedSession` references.
- Remove `backend/app/demo/router.py` and its registration in `main.py`.
- Revert CORS to `allow_origins=["*"]`.
- Revert `apiFetch()` to bare fetch.
- Revert `index.html` to direct unauthenticated API calls.
- No DB migrations — this change adds no schema.

## Dependencies

- No new external libraries (FastAPI `Depends`, stdlib `secrets` — both already present).
- ElevenLabs agent dashboard access for manual webhook secret configuration.
- At least one valid `Client` + `Agent` record in the DB for demo env var configuration.
- `.env` secret rotation prior to B5 merge (independent action).

## Success Criteria

- [ ] `GET /api/v1/clients` without `Authorization` header returns 401.
- [ ] `GET /api/v1/health` without auth returns 200 (Docker health checks pass).
- [ ] `GET /api/v1/demo/context` returns 200 with agent metadata — no credentials, no admin-level data in response.
- [ ] `/demo` page starts a full voice conversation and pipeline writes complete (transcript, call session, captured data, post-call analysis) without any admin key visible in the browser or network traffic.
- [ ] Attempting to write to a different tenant's data via the demo session returns 403.
- [ ] Per-turn `/voice/custom-llm/*` handler performs zero DB or network operations for auth. Verified by instrumentation.
- [ ] Scheduler-started call has a valid `AuthorizedSession` derived from the call identity chain — no manual auth input required.
- [ ] Tool execution validates scope against `AuthorizedSession` before writing — verified by unit test.
- [ ] All ~1724 tests pass with auth fixture and session fixture applied.
- [ ] `QORA_WEBHOOK_AUTH_ENABLED=false` by default — existing ElevenLabs agents unaffected without reconfiguration.
- [ ] Frontend dashboard displays data after `VITE_API_KEY` is set.
- [ ] CORS rejects requests from origins not in `QORA_ALLOWED_ORIGINS`.

## Next Recommended Phase

**sdd-spec** — write delta specs for `api-key-auth`, `webhook-auth`, `session-auth-binding`, `tenant-isolation`, and `demo-scoped-credentials` capabilities, plus a delta spec for the modified `demo-agent-selection` capability.

---

## Login / Supabase — Where It Fits Later

Phase B5 is single-operator (one global API key). When Qora needs multi-operator access:

1. **Phase C**: Add `POST /api/v1/auth/login` — verifies credentials against a `users` table (or Supabase Auth), returns a short-lived JWT.
2. `require_api_key` dependency is swapped for `require_jwt` — **zero router changes needed**.
3. JWT payload carries `user_id` + `allowed_client_ids`. Tenant isolation reads from JWT claims. `AuthorizedSession` extends to carry JWT-derived identity.
4. Supabase integration can use Supabase JWT verification instead of a custom login endpoint, reducing auth maintenance to near zero.

Supabase is not needed for B5 and should not block it.
