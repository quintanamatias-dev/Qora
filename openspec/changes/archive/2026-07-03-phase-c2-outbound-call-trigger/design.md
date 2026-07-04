# Design: Phase C2 — Outbound Call Trigger (Manual Slice)

## Technical Approach

Central `dial_outbound_call()` service function is the sole dialing entry point. The manual trigger endpoint and the future scheduler both call it. CallSession is created **before** the ElevenLabs API call (crash-safe). FAS protection: `telephony_status` tracks provider-reported state only; `completed` requires webhook evidence. Feature flag `ENABLE_OUTBOUND_CALLS` gates all real telephony.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Dialing entry point | Single `dial_outbound_call()` in new `backend/app/outbound/service.py` | Inline in router; method on ElevenLabsService | Scheduler reuse contract (spec REQ-7). Own module avoids circular imports with calls/service.py |
| CallSession telephony columns | 5 new nullable columns on existing `CallSession` | Separate `OutboundCallAttempt` table | Proposal scope; existing model already stores `elevenlabs_conversation_id`; avoid join overhead |
| Telephony status source | Provider-reported state only; `completed` gated on webhook | Trust SIP 200 OK as completed | FAS incident in C1: SIP 200 ≠ human conversation. Webhook is the only human-evidence signal |
| E.164 validation | `phonenumbers` library at trigger time | Regex; DB constraint | Regex misses country rules; library validates carrier-level. Reject before charge |
| In-call timeout | 30-min ceiling via background reconciliation sweep | Per-call timer | Simpler; covers webhook-never-arrived; no per-call state tracking needed |
| Feature flag | `enable_outbound_calls: bool = False` on Settings | DB toggle per-client | Matches `enable_job_executor` pattern. Single operator toggle. Client-level deferred to C4 |
| Frontend trigger | Button in LeadTable row after Next Action column | Detail page header only | Proposal says "Leads list row"; operator scans list, triggers from there |

## Data Flow

```
Operator clicks "Call Now" → Confirmation dialog
  → POST /api/v1/clients/{cid}/leads/{lid}/call (admin API key)
    → Feature flag check (403 if off)
    → E.164 validation (422 if invalid)
    → Concurrent call guard (409 if active session)
    → Resolve agent (default agent for client)
    → Create CallSession (telephony_status=dialing) ← DB write BEFORE API call
    → build_dynamic_variables(lead, agent, client)
    → ElevenLabsService.initiate_outbound_call(agent, lead, call_session)
      → POST https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call
         body: { agent_id, agent_phone_number_id, to, conversation_initiation_client_data }
      → On 2xx: update telephony_status=ringing, store provider_call_id + safe/allowlisted provider_metadata
               (permitted: call_id, status, duration_seconds, billed_duration_seconds, cost;
                'message' excluded — free-form provider text, PII risk; RE4)
      → On transient error (5xx/timeout): retry once → recurrent_error on second failure
      → On permanent error (4xx non-rate-limit): telephony_status=failed, no retry
    → Return { status, call_session_id }

  ... later ...
  ElevenLabs webhook → existing Custom LLM path fires session-end
    → Match via conversation_id → update telephony_status=completed
```

### ID Linkage Chain

```
CallSession.id (Qora UUID)
  ├── provider_call_id        (ElevenLabs call identifier from API response)
  ├── elevenlabs_conversation_id  (set by webhook when conversation starts)
  └── lead_id                 (FK to leads table)
```

Reconciliation: if webhook fires but `provider_call_id` doesn't match, fall back to `conversation_id` lookup. If neither matches, log orphan and create unlinked session.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/tenants/models.py` | Modify | Add `Agent.elevenlabs_phone_number_id` (nullable String) |
| `backend/app/calls/models.py` | Modify | Add 5 telephony columns to `CallSession`: `provider_call_id`, `telephony_provider`, `telephony_status`, `telephony_error`, `provider_metadata` (JSON) |
| `backend/app/core/config.py` | Modify | Add `enable_outbound_calls: bool = False` |
| `backend/app/elevenlabs/service.py` | Modify | Add `initiate_outbound_call()` method with retry logic |
| `backend/app/elevenlabs/models.py` | Modify | Add `OutboundCallRequest`, `OutboundCallResult` Pydantic models |
| `backend/app/outbound/__init__.py` | Create | Package init |
| `backend/app/outbound/service.py` | Create | `dial_outbound_call()` — central dialing function, guards, dynamic vars builder |
| `backend/app/outbound/router.py` | Create | `POST /clients/{cid}/leads/{lid}/call` endpoint |
| `backend/app/agents/schemas.py` | Modify | Add `elevenlabs_phone_number_id` to AgentCreate, AgentUpdate, AgentResponse |
| `backend/alembic/versions/XXXX_c2_outbound_telephony.py` | Create | Migration: Agent phone_number_id + CallSession 5 telephony columns |
| `backend/app/voice/initiation.py` | Modify | Extract `build_dynamic_variables()` as importable helper |
| `.env.example` | Modify | Add `ENABLE_OUTBOUND_CALLS`, `ELEVENLABS_PHONE_NUMBER_ID` |
| `frontend/src/api/leads.ts` | Modify | Add `triggerCall(clientId, leadId)` |
| `frontend/src/api/types.ts` | Modify | Add `CallTriggerResponse` type |
| `frontend/src/features/leads/lead-table.tsx` | Modify | Add "Call Now" column + button + confirmation dialog + Calling badge |

## Interfaces / Contracts

```python
# backend/app/outbound/service.py
async def dial_outbound_call(
    db: AsyncSession,
    *,
    lead: Lead,
    agent: Agent,
    client: Client,
    settings: Settings,
    scheduled_call: ScheduledCall | None = None,  # None for manual trigger
) -> DialResult:
    """Sole entry point for outbound dialing. Returns DialResult, never raises."""

@dataclass
class DialResult:
    status: Literal["dialing", "failed", "recurrent_error"]
    call_session_id: str
    error: str | None = None
```

```python
# backend/app/elevenlabs/models.py
class OutboundCallRequest(BaseModel):
    agent_id: str
    agent_phone_number_id: str
    to: str  # E.164
    conversation_initiation_client_data: dict | None = None

class OutboundCallResult(BaseModel):
    outcome: Literal["accepted", "error"]
    provider_call_id: str | None = None
    provider_metadata: dict | None = None
    error_detail: str | None = None
    error_category: Literal["transient", "permanent"] | None = None
```

```python
# Endpoint: POST /api/v1/clients/{client_id}/leads/{lead_id}/call
# Auth: require_api_key (admin Bearer token)
# Response 200: { "status": "dialing"|"failed"|"recurrent_error", "call_session_id": "..." }
# Response 403: feature flag off or unauthorized
# Response 409: concurrent call active
# Response 422: invalid E.164 phone
# Response 404: lead or client not found
```

### Failure Classification Decision Tree

```
ElevenLabs API error
├── HTTP 5xx, timeout, rate-limit (429) → TRANSIENT
│   ├── Attempt 1 → telephony_status=failed, auto-retry
│   └── Attempt 2 → telephony_status=recurrent_error, stop
├── HTTP 4xx (not 429) → PERMANENT
│   └── telephony_status=failed, no retry
└── Network error (DNS, connection refused) → TRANSIENT (same as 5xx)
```

### Telephony Status State Machine

```
dialing ──→ ringing ──→ in_call ──→ completed (webhook evidence only)
  │            │           │
  │            │           └──→ [reconciliation sweep: 30min ceiling]
  │            │                  └──→ completed (if webhook arrived)
  │            │                  └──→ stale_in_call (if no webhook)
  │            └──→ no_answer (provider ring timeout)
  │
  └──→ failed (API error)
        ├──→ dialing (auto-retry, transient only, once)
        └──→ recurrent_error (second transient failure)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `dial_outbound_call()` guards (flag, E.164, concurrent), failure classification, retry logic | pytest + mock ElevenLabs HTTP (httpx mock). TDD: write test → implement → green |
| Unit | `build_dynamic_variables()` extraction | pytest — assert output shape matches initiation.py contract |
| Unit | `OutboundCallRequest`/`OutboundCallResult` validation | pydantic model tests |
| Integration | Endpoint 403/409/422/404 responses | TestClient + real DB (SQLite), mock ElevenLabs |
| Integration | CallSession created before API call, updated after | DB assertion within mock response |
| Integration | Feature flag off → 403, no DB write, no API call | TestClient with `enable_outbound_calls=False` |
| Frontend | Button renders after Next Action, confirmation dialog, Calling badge | Vitest + Testing Library, mock fetch |

## Migration / Rollout

### Alembic Migration

Single migration file adding:
1. `agents.elevenlabs_phone_number_id` — nullable String
2. `call_sessions.provider_call_id` — nullable String
3. `call_sessions.telephony_provider` — nullable String, no server default (NULL for legacy/inbound rows; application writes `"elevenlabs"` explicitly on new outbound sessions)
4. `call_sessions.telephony_status` — nullable String
5. `call_sessions.telephony_error` — nullable String (Text)
6. `call_sessions.provider_metadata` — nullable JSON

All columns nullable → existing rows unaffected. Downgrade drops all 6 columns.

### Feature Flag Rollout

1. Deploy with `ENABLE_OUTBOUND_CALLS=false` (default) — zero behavior change
2. Set `ELEVENLABS_PHONE_NUMBER_ID` env var (or PATCH agent via API)
3. Set `ENABLE_OUTBOUND_CALLS=true` — button appears, dialing enabled
4. Rollback: set flag to `false` — immediate, no code change

### Reconciliation Sweep (in_call timeout)

Background task (piggyback on existing scheduler tick interval): query CallSessions with `telephony_status=in_call` older than 30 minutes. If matching webhook evidence exists, mark `completed`. If not, mark `stale_in_call` and log for operator review. This prevents calls stuck in `in_call` forever if webhook never arrives.

## WU2 Re-Review Decisions (Security / Reliability)

| Finding | Decision | Rationale |
|---------|----------|-----------|
| `/end` route ignores `provider_call_id` (RE1) | Wire `link_outbound_session_by_webhook()` as fallback when `close_session()` raises ValueError and `body.provider_call_id` is not None | Enables first-time outbound linkage when conversation-start webhook never fired |
| `elevenlabs-postcall` calls linkage without `client_id` (RE2) | Added `client_id` to `ElevenLabsPostCallPayload`; route skips fallback when `client_id` is absent | Prefer safe no-match over cross-tenant session linkage risk |
| `QORA_WEBHOOK_AUTH_ENABLED` opt-in default (RE3) | Added `Settings.outbound_without_webhook_auth_warning` property; logs WARNING at lifespan when risky combo detected | Backward-compatible; does not fail startup; production configs must set QORA_WEBHOOK_AUTH_ENABLED=true when ENABLE_OUTBOUND_CALLS=true |
| `message` in provider_metadata allowlist (RE4) | Removed `message` from `_SAFE_PROVIDER_METADATA_FIELDS` | Free-form SIP/provider messages may contain phone numbers, caller names, routing annotations — PII risk outweighs the debug utility |

### Production / Live-Call Config Requirements

Before setting `ENABLE_OUTBOUND_CALLS=true` in any non-dev environment:
1. `QORA_WEBHOOK_AUTH_ENABLED=true` — protects webhook endpoints from unauthenticated mutation
2. `QORA_WEBHOOK_SECRET=<strong-random-secret>` — required when auth is enabled
3. `ELEVENLABS_PHONE_NUMBER_ID` set on the agent — required for dialing
4. Multi-worker: replace `asyncio.Lock` with Redis distributed lock (see Known Limitations)

## Open Questions

- [x] FAS human confirmation flag — deferred to future hardening (noted in proposal)
- [ ] Should `stale_in_call` auto-transition to `no_answer` or remain distinct for operator triage? (Recommend: keep distinct — operator decides)
- [ ] phonenumbers library — confirm it's acceptable as a new dependency (lightweight, well-maintained, no native extensions)

## Known Limitations (Production Readiness)

### In-process Lock (Single-Process MVP Only)

The per-lead `asyncio.Lock` in `dial_outbound_call()` (`_get_lead_lock(lead_id)`) prevents
duplicate paid calls within a **single asyncio process only**. It does NOT protect against:

- **Multi-worker deployments** (e.g., `gunicorn -w 4 ...`, multiple Uvicorn workers)
- **Multi-instance deployments** (e.g., multiple containers, horizontal scaling, Kubernetes pods)

In those environments, two workers/instances can both pass the DB guard and fire duplicate
provider calls because the in-process dict (`_LEAD_LOCKS`) is not shared across processes.

**Required before production multi-worker deployment**:
1. Replace `asyncio.Lock` with a Redis-backed distributed lock (e.g., `Redlock`, `redis-py` with
   `SET NX PX`), OR
2. Add a unique DB constraint / idempotency key on `(lead_id, telephony_status)` to enforce
   at-most-one dialing session at the DB layer.

For the current MVP (single Uvicorn process), the in-process lock is sufficient and correct.

## Work-Unit / Review Slicing

Estimated ~500-600 changed lines. Recommend 2 chained PRs:

| PR | Scope | Est. Lines |
|----|-------|-----------|
| PR 1: Backend core | Migration + models + config + `outbound/service.py` + `outbound/router.py` + ElevenLabs service + tests | ~350 |
| PR 2: Frontend + integration | `lead-table.tsx` button + confirmation + API client + integration tests + `.env.example` | ~200 |

PR 1 targets `feature/phase-c2-outbound-call-trigger`. PR 2 targets PR 1's branch.
