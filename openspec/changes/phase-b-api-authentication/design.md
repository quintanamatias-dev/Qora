# Design: Phase B5 — API Authentication

## Technical Approach

Layer auth as FastAPI dependencies around the existing architecture. `AuthorizedSession` extends the existing `ConversationState`+`SessionStore` pattern — same in-memory store, new auth-scoped data model composed alongside it. Admin routes get `Depends(require_api_key)`. Voice routes get optional `Depends(require_webhook_secret)`. Per-turn custom-LLM path reads `AuthorizedSession` from the existing `session_store` — zero new I/O. Demo and production voice calls each establish `AuthorizedSession` at their own session start through separate origin paths.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| AuthorizedSession storage | Compose with existing `ConversationState` — add `auth` field of type `AuthorizedSession` to `ConversationState`, reuse `session_store` | Separate parallel store | Avoids dual-lookup on hot path; `session_store` already keyed by `(client_id, conversation_id)` with TTL cleanup |
| Auth dependency pattern | Single `require_api_key` function returning a `CallerIdentity` dataclass | Middleware-based; decorator pattern | FastAPI `Depends()` is swappable (Phase C: swap for `require_jwt`), composable, testable, and router-level — no global middleware needed |
| Webhook auth | Separate `require_webhook_secret` dependency, disabled by default via `QORA_WEBHOOK_AUTH_ENABLED` | Same key as admin; always-on | ElevenLabs dashboard requires manual secret config; disabled-by-default prevents breaking existing agents |
| Demo context + leads | Two auth-exempt endpoints: `GET /api/v1/demo/context` (agent metadata) and `GET /api/v1/demo/leads` (leads for demo client) | Merge leads into `/demo/context`; inject API key in browser | Separate endpoints follow REST conventions; keeps `/demo/context` lightweight; no credential reaches browser |
| Demo vs scheduler origins | Treat demo-started and scheduler-started calls as separate session origins — each binds `AuthorizedSession` at its own session start independently | Unified origin path routing both through scheduler | Demo button flow is interactive/synchronous; scheduler is future outbound. Coupling them would create a false dependency and block demo on scheduler maturity |
| Tool scope validation | Pass `AuthorizedSession` ref through `_execute_tool` → `dispatch_tool`; scope check is a sync guard at dispatch entry | Per-tool decorator; middleware | Centralized in dispatcher = single enforcement point; sync = zero latency; matches existing `dispatch_tool` signature pattern |
| CORS | Replace `allow_origins=["*"]` with `QORA_ALLOWED_ORIGINS` comma-separated env var | Hardcoded list | Configurable per environment without code changes |
| Test auth bypass | `conftest.py` fixtures inject valid `Authorization` header + seed `AuthorizedSession` in `session_store` | `QORA_TESTING=1` env bypass | Fixtures are explicit, no hidden bypass in production code paths |

## Session Origin Flows

Two distinct origins create `AuthorizedSession` — they MUST NOT be conflated.

### Origin 1: Demo Button Flow (current, implemented in B5)

```
User clicks "Iniciar" in /demo UI
         │
         ▼
Browser ──GET /api/v1/demo/context──→ (auth-exempt)
         │                                │
         │                           resolve agent from QORA_DEMO_CLIENT_ID + QORA_DEMO_AGENT_ID
         │                                │
         │                           return {elevenlabs_agent_id, client_name, agent_name}
         │
Browser ──GET /api/v1/demo/leads?client_id=X──→ (auth-exempt)
         │                                          │
         │                                     return leads for demo client only
         │
User selects lead from dropdown
         │
         ▼
Browser ──WebSocket to ElevenLabs──→ ElevenLabs ──POST /voice/initiation──→
                                          │
                                     resolve client+agent+lead from DB (1 query)
                                          │
                                     create AuthorizedSession(is_demo=True)
                                       scopes: {pipeline:write, pipeline:read}
                                       NO admin:write, NO admin:read
                                          │
                                     attach to ConversationState.auth
                                          │
                                     store in session_store[(client_id, conv_id)]
                                          │
                                     voice session proceeds → pipeline writes within scope
```

The demo flow is user-driven: select client/agent/lead → start conversation → pipeline writes. It does NOT go through the scheduler.

### Origin 2: Scheduler Flow (future outbound — designed now, implemented later)

```
Scheduler fires at scheduled time
         │
         ▼
scheduled_call record ──→ resolve lead → client → agent
                               │
                          create AuthorizedSession(is_demo=False)
                            scopes: {pipeline:write, pipeline:read}
                               │
                          initiate outbound dial (future — not functional yet)
                               │
                          attach to ConversationState.auth on session start
                               │
                          voice session proceeds normally
```

The scheduler path derives identity from the `scheduled_call → lead → client → agent` chain. It requires no user interaction and no demo context endpoint. Current scheduler exists but real outbound dialing is not functional yet — `AuthorizedSession` creation will be added when outbound calling is implemented.

### Admin API Request

```
Client ──Bearer──→ require_api_key ──CallerIdentity──→ Router Handler
                        │
                   401 if invalid
```

### Per-Turn Fast Path (custom-LLM — HOT PATH)

```
ElevenLabs ──POST /voice/{client_id}/custom-llm──→ get_authorized_session(client_id, conv_id)
                                                         │
                                                    session_store.get() ← IN-MEMORY ONLY
                                                         │
                                                    401 if not found
                                                         │
                                                    conv_state.auth.scopes → tool dispatch
                                                         │
                                                    ZERO DB/NETWORK QUERIES
```

Both demo and production sessions converge here — the per-turn path is origin-agnostic. It only reads the already-cached `AuthorizedSession`.

## Tool Scope Validation — How It Works

Tools are backend actions the voice agent can ask Qora to perform during a call (e.g., `capture_data`, `get_lead_details`, `get_lead_history`). They read or write tenant data.

Before a tool reads or writes data, the dispatcher checks the session's `AuthorizedSession` scopes:

1. **Scope check**: `dispatch_tool` receives the `AuthorizedSession` from the current call session. Before executing any handler, it verifies the session's `scopes` frozenset contains the required scope for that tool (e.g., `pipeline:write` for `capture_data`, `pipeline:read` for `get_lead_details`).

2. **Tenant boundary check**: the dispatcher also verifies that the `client_id` and `lead_id` in the tool arguments match the session's `AuthorizedSession.client_id` and `AuthorizedSession.lead_id`. A demo session for client A cannot write data for client B.

3. **Rejection**: if scope or tenant check fails, the tool returns an error dict immediately — no data is read or written, no DB side-effects occur.

This is synchronous, in-memory, and adds ~0 ms latency. The existing `_validate_lead_scope` in `dispatcher.py` already checks `lead.client_id != client_id`; B5 wraps this with the `AuthorizedSession` scope guard at the dispatch entry point.

## File Changes

| File | Action | Description |
|---|---|---|
| `backend/app/core/config.py` | Modify | Add `qora_api_key`, `qora_webhook_secret`, `qora_webhook_auth_enabled`, `qora_allowed_origins`, `qora_demo_client_id`, `qora_demo_agent_id`, `qora_docs_enabled`, `qora_session_ttl_seconds` |
| `backend/app/core/auth.py` | Create | `CallerIdentity`, `AuthorizedSession` dataclasses; `require_api_key()`, `require_webhook_secret()`, `get_authorized_session()` FastAPI deps; `create_authorized_session()` factory |
| `backend/app/voice/session.py` | Modify | Add `auth: AuthorizedSession | None = None` to `ConversationState`; configurable TTL in `cleanup_expired()` |
| `backend/app/demo/router.py` | Create | `GET /api/v1/demo/context` (agent metadata) + `GET /api/v1/demo/leads` (leads for demo client) — both auth-exempt |
| `backend/app/main.py` | Modify | CORS lockdown, register demo router, conditional `/docs`+`/redoc`, startup validation for `QORA_API_KEY` |
| `backend/app/clients/router.py` | Modify | Add `Depends(require_api_key)` to all endpoints |
| `backend/app/agents/router.py` | Modify | Add `Depends(require_api_key)` to all endpoints |
| `backend/app/leads/router.py` | Modify | Add `Depends(require_api_key)` to all endpoints |
| `backend/app/calls/router.py` | Modify | Admin routes: `Depends(require_api_key)`; post-call: scoped session validation |
| `backend/app/analytics/router.py` | Modify | Add `Depends(require_api_key)` |
| `backend/app/scheduler/router.py` | Modify | Add `Depends(require_api_key)` |
| `backend/app/integrations/crm_router.py` | Modify | Add `Depends(require_api_key)` |
| `backend/app/integrations/crm_config_router.py` | Modify | Add `Depends(require_api_key)` |
| `backend/app/voice/initiation.py` | Modify | Optional `Depends(require_webhook_secret)`, create `AuthorizedSession` at call start, attach to `ConversationState.auth` |
| `backend/app/voice/webhook.py` | Modify | `get_authorized_session` dep on custom-LLM routes; pass `auth` to tool dispatch |
| `backend/app/tools/dispatcher.py` | Modify | Accept `authorized_session` param; scope guard before tool execution |
| `backend/app/static/index.html` | Modify | Fetch from `/api/v1/demo/context` + `/api/v1/demo/leads`; remove direct `/api/v1/clients` and `/api/v1/leads` calls |
| `frontend/src/api/client.ts` | Modify | Inject `Authorization: Bearer <key>` from `VITE_API_KEY` env var |
| `backend/tests/conftest.py` | Modify | Add `auth_headers` fixture, `seed_authorized_session` fixture |
| `backend/.env.example` | Modify | Document all new `QORA_*` auth env vars |
| `frontend/.env.example` | Modify | Add `VITE_API_KEY` |

## Interfaces / Contracts

```python
@dataclass
class CallerIdentity:
    """Returned by require_api_key. Phase C: extends with user_id, allowed_client_ids."""
    api_key_hash: str  # for audit logging only, never the raw key

@dataclass
class AuthorizedSession:
    """Cached auth context for one voice call/session."""
    client_id: str
    agent_id: str | None
    agent_slug: str | None
    lead_id: str | None
    session_id: str
    scopes: frozenset[str]  # e.g. {"pipeline:write", "pipeline:read"}
    is_demo: bool = False
    created_at: float = field(default_factory=time.monotonic)

# Scopes:
# "pipeline:write"  — transcript, call session, captured data, post-call analysis
# "pipeline:read"   — read own tenant data
# "admin:write"     — create/update/delete clients, agents, leads (NOT granted to demo)
# "admin:read"      — list clients, agents, leads (NOT granted to demo)

def require_api_key(request: Request) -> CallerIdentity:
    """FastAPI Depends. Reads Authorization: Bearer <key>. Returns 401 on failure."""

def require_webhook_secret(request: Request) -> None:
    """FastAPI Depends. No-op when QORA_WEBHOOK_AUTH_ENABLED=false.
    Reads X-Webhook-Secret header when enabled. Returns 401 on failure."""

def get_authorized_session(client_id: str, request: Request) -> AuthorizedSession:
    """FastAPI Depends for custom-LLM path. Reads session from session_store.
    Returns 401 if not found. ZERO DB/network calls."""

def create_authorized_session(
    client_id: str, agent_id: str | None, lead_id: str | None,
    session_id: str, is_demo: bool = False
) -> AuthorizedSession:
    """Factory. Called at initiation/session-start. Assigns scopes based on is_demo."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | `require_api_key` accepts/rejects tokens; constant-time comparison | `test_auth.py` — parametrized valid/invalid/missing headers |
| Unit | `require_webhook_secret` enabled/disabled flag behavior | `test_auth.py` — toggle `QORA_WEBHOOK_AUTH_ENABLED` |
| Unit | `AuthorizedSession` scope grants for demo vs production | `test_auth.py` — verify `is_demo=True` excludes admin scopes |
| Unit | `get_authorized_session` returns from store or 401 | `test_auth.py` — seed store, verify retrieval; empty store → 401 |
| Unit | Tool scope validation blocks unauthorized writes | `test_dispatcher.py` — mock session with insufficient scope |
| Integration | Admin routes reject unauthenticated requests | `test_clients_router.py`, etc. — request without header → 401 |
| Integration | Demo context endpoint returns safe data, no secrets | `test_demo_router.py` — verify response shape; assert no key leakage |
| Integration | Demo leads endpoint returns leads for demo client only | `test_demo_router.py` — verify scoped lead list; assert no cross-tenant data |
| Integration | Full demo session: context → leads → initiation → turns → write | `test_demo_e2e.py` — verify pipeline writes succeed within scope |
| Integration | Cross-tenant access blocked | `test_tenant_isolation.py` — session for client A, request data for client B → 403 |
| Instrumented | **Per-turn zero-DB guarantee** | `test_fast_path.py` — patch `db_session` to raise if called during custom-LLM turn with cached `AuthorizedSession`; test MUST pass |
| Instrumented | No credential leakage in demo | `test_demo_no_leak.py` — inspect response bodies/headers for `QORA_API_KEY` patterns |

### Fast-Path Instrumentation (Non-Negotiable)

```python
# In test_fast_path.py:
# Seed session_store with a ConversationState that has .auth and .context populated.
# Monkey-patch app.core.database.get_session to raise AssertionError("DB called on hot path").
# POST /voice/{client_id}/custom-llm/chat/completions with valid body.
# Assert: 200 response, no AssertionError raised → zero DB calls confirmed.
```

## Migration / Rollout (3-PR Split)

User-approved 3-PR implementation split:

| PR | Contents | Lines | Risk | Rollback |
|---|---|---|---|---|
| **PR #1 — Foundation + Admin Auth** | `auth.py`, `config.py`, `conftest.py` fixtures, all router `Depends(require_api_key)`, `apiFetch()` Bearer header, `.env.example` updates | ~500 | Medium — frontend breaks without `VITE_API_KEY` | Remove `Depends()` + revert `auth.py` + revert config |
| **PR #2 — Session Auth + Demo + Tool Scope** | `AuthorizedSession` on `ConversationState`, initiation creates session, demo router (`/demo/context` + `/demo/leads`), `index.html` update, dispatcher scope guard, fast-path test | ~400 | Low — falls back to existing per-turn path when `auth` is None | Remove `.auth` field + revert initiation + remove demo router |
| **PR #3 — Webhook Auth + CORS** | `require_webhook_secret` on voice endpoints (disabled by default), CORS lockdown (`QORA_ALLOWED_ORIGINS`), webhook auth tests | ~200 | Critical if enabled prematurely; low when disabled | Set `QORA_WEBHOOK_AUTH_ENABLED=false` or revert to `allow_origins=["*"]` |

**Key constraint**: PR #1 and #2 MUST NOT break the existing demo flow or ElevenLabs agents. PR #3 webhook auth is disabled by default and requires separate ElevenLabs dashboard config.

## Risks, Tradeoffs, and Rollback

| Risk | Severity | Mitigation |
|---|---|---|
| ~1724 tests return 401 | High | `conftest.py` auth fixture auto-injects valid header; session fixture seeds `AuthorizedSession` |
| Demo `index.html` calls `/api/v1/clients` and `/api/v1/leads` (now auth-protected) | High | Demo page switches to `/api/v1/demo/context` + `/api/v1/demo/leads` (auth-exempt, scoped to demo client only) |
| Per-turn DB call introduced accidentally | Critical (build-blocking) | Instrumented test (`test_fast_path.py`) that fails if DB is touched on hot path |
| ElevenLabs webhook secret mismatch | Critical | Disabled by default; separate rollout PR (#3) |
| CORS blocks legitimate origins | Medium | `QORA_ALLOWED_ORIGINS` defaults to `["*"]` in dev; explicit list in production |
| `AuthorizedSession` memory leak from abandoned calls | Low | Existing `cleanup_expired()` already runs; extend TTL to configurable `QORA_SESSION_TTL_SECONDS` (default 4h) |

**Rollback**: Revert the `auth.py` module + all `Depends()` additions + config changes. No DB migrations to roll back. Frontend reverts `apiFetch()` header injection. Demo reverts to direct API calls.

## Open Questions

- [x] `AuthorizedSession` TTL: 4 hours default, configurable via `QORA_SESSION_TTL_SECONDS` (decided in spec)
- [x] Demo lead selection: separate `/api/v1/demo/leads` endpoint (user approved)
- [x] Demo vs scheduler: separate origins, demo is NOT a scheduled call (user approved)
- [ ] Secret rotation timeline: who rotates the committed `.env` secrets and when relative to B5 merge?
