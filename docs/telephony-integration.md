# Qora Telephony Integration

> **Permanent reference** for Qora's outbound telephony pipeline.
> Replaces scattered knowledge across operator-checklist, measurement-protocol,
> Engram memories, and PR descriptions.
>
> Last updated: 2026-07-07

---

## Architecture Overview

Qora uses ElevenLabs as the voice AI runtime and Telnyx as the SIP trunk
provider for outbound phone calls. Qora never touches raw audio or SIP
signaling directly — ElevenLabs orchestrates the entire call via its
Conversational AI platform, routing the SIP leg through Telnyx.

```text
Operator clicks "Call Now"
        |
        v
  Qora Backend (FastAPI)
  POST /api/v1/outbound/call
        |
        v
  ElevenLabs SIP Trunk API
  POST /v1/convai/sip-trunk/outbound-call
        |
        v
  ElevenLabs ConvAI Runtime
  (STT, TTS, turn detection, Custom LLM webhook → Qora)
        |
        v
  Telnyx SIP Trunk
  (INVITE → PSTN routing → phone)
        |
        v
  Lead's phone rings
```

### Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `ELEVENLABS_API_KEY` | Authenticates all ElevenLabs API calls (CRITICAL) |
| `ELEVENLABS_PHONE_NUMBER_ID` | ElevenLabs Phone Number resource ID for SIP trunk |
| `ENABLE_OUTBOUND_CALLS` | Feature flag — gates all real telephony (default: `false`) |
| `QORA_WEBHOOK_AUTH_ENABLED` | Required `true` when outbound is enabled (fail-closed) |
| `QORA_WEBHOOK_SECRET` | Shared secret for webhook HMAC validation |
| `SENTRY_DSN` | Optional Sentry error tracking |
| `LOG_FORMAT` | `json` (structured, default) or `text` (human-readable) |

> **Security invariant**: `ENABLE_OUTBOUND_CALLS=true` requires
> `QORA_WEBHOOK_AUTH_ENABLED=true` — startup aborts otherwise. This prevents
> unauthenticated webhook endpoints from corrupting billing state.
> See `backend/app/core/config.py` — `validate_outbound_requires_webhook_auth`.

---

## Call Lifecycle

### State Machine

The `CallStatus` StrEnum (`backend/app/calls/states.py`) defines 10 canonical
telephony states with an explicit transition allowlist:

```text
  queued ──→ dialing ──→ ringing ──→ connected ──→ completed
                  \          \             \
                   \          \→ no_answer   \→ voicemail → completed
                    \→ failed ──→ dialing (retry)
                    \→ recurrent_error
                              ringing ──→ stale_in_call
                              connected ──→ stale_in_call
```

| State | Meaning | Terminal? |
|-------|---------|-----------|
| `queued` | Pre-dial — scheduler queued, not yet attempted | No |
| `dialing` | API call sent to ElevenLabs, awaiting acceptance | No |
| `ringing` | ElevenLabs accepted; SIP INVITE in-flight to Telnyx | No |
| `connected` | SIP 200 OK — call is live (replaces legacy `in_call`) | No |
| `voicemail` | Heuristic: short duration + 0 user turns | No |
| `completed` | Session-end webhook confirmed real conversation | Yes |
| `no_answer` | SIP routing failure or ring timeout | Yes |
| `failed` | Provider/system error (one retry allowed → dialing) | Yes* |
| `recurrent_error` | Two consecutive transient failures | Yes |
| `stale_in_call` | Sweep safety net — stuck without session-end evidence | Yes |

\* `failed` allows one transition back to `dialing` (retry).

### Where Each Transition Happens

| Transition | Code Location |
|-----------|---------------|
| `queued → dialing` | `outbound/service.py` — `dial_outbound_call()` |
| `dialing → ringing` | `outbound/service.py` — on EL API `outcome="accepted"` |
| `dialing → failed` | `outbound/service.py` — on permanent/unknown error |
| `dialing → recurrent_error` | `outbound/service.py` — second transient failure |
| `ringing → connected` | `outbound/linkage.py` — retroactive on webhook |
| `ringing → no_answer` | `outbound/probe.py` — SIP routing failure detection |
| `ringing → stale_in_call` | `outbound/sweep.py` — 5-min ringing threshold |
| `connected → completed` | `outbound/linkage.py` — session-end webhook |
| `connected → voicemail` | `calls/service.py` — voicemail heuristic |
| `connected → stale_in_call` | `outbound/sweep.py` — 30-min threshold |
| `voicemail → completed` | `outbound/linkage.py` — session-end webhook |
| `failed → dialing` | `outbound/service.py` — one retry on transient error |
| `* → completed` (sweep) | `outbound/sweep.py` — when `session_end_received=True` |

### Voicemail Detection (3 Layers)

1. **ElevenLabs `voicemail_detection` built-in tool** (Primary) —
   Enabled via API: `conversation_config.agent.prompt.built_in_tools.voicemail_detection`.
   Managed programmatically by `sync_agent_config()` in PR #138.
   When enabled, ElevenLabs detects voicemail greetings and hangs up.

2. **System prompt instruction** (Fallback) —
   The agent's `system-prompt.md` includes a `<voicemail_detection>` section
   instructing it to hang up immediately upon detecting recorded messages,
   beeps, or operator announcements. Already deployed in code.

3. **Max call duration cap** (Safety net) —
   `conversation_config.conversation.max_duration_seconds = 120`.
   Managed programmatically by `sync_agent_config()` in PR #138.
   Any call exceeding 2 minutes is auto-terminated.

> **Why 3 layers?** Layer 1 handles most cases. Layer 2 catches edge cases
> where ElevenLabs' detector misses. Layer 3 is the absolute ceiling — if the
> agent is still talking at 120s, something is wrong regardless. The cost of
> cutting a real call at 2 min is far lower than billing 5 min of voicemail.

### Post-Call Analysis Pipeline

After a call completes, the summarizer (`backend/app/summarizer.py`) runs:

1. Load transcript turns from DB.
2. If 0 turns → skip (no GPT calls).
3. **Close read transaction** (`db.rollback()`) before the LLM call to prevent
   SQLite WAL staleness (production fix — PR #132).
4. Run 6 analysis dimensions + interest pipeline + profile facts + misc notes +
   data corrections in parallel via `asyncio.gather`.
5. Run next-action pipeline sequentially (needs dimension outputs).
6. Persist to `CallSession`, `CallAnalysis`, `Lead`, `LeadProfileFact`,
   `LeadInterestHistory` in a single savepoint (atomic).
7. Schedule CRM sync (wrapped in try/except — failure cannot roll back analysis).

---

## Outbound Call Flow (Call Now)

### What Happens When the Operator Clicks "Call Now"

```text
Frontend                          Backend                         ElevenLabs
────────                          ───────                         ──────────
1. Click "Call Now"
2. Confirmation dialog opens
3. Click "Confirm"
4. POST /outbound/call ──────→   5. Guards:
                                    - Feature flag check
                                    - E.164 phone validation
                                    - Agent config check
                                    - Concurrent call guard
                                    (per-lead asyncio.Lock)
                                 6. Create CallSession
                                    (telephony_status=dialing)
                                    COMMIT before API call
                                 7. POST /convai/sip-trunk/  ──→ 8. ElevenLabs places SIP call
                                    outbound-call                    via Telnyx trunk
                                 9. On accepted:
                                    status=ringing, store
                                    provider_call_id
                                    Fire post-dial probe (8s)
←───────────────────────────── 10. Return {status: dialing,
                                    call_session_id}
11. Start polling
    GET /calls/{id}/status
    every 3 seconds
12. Display real telephony         ← Polling returns telephony_status
    badges (Dialing/Ringing/
    Connected/Completed/etc.)
13. Stop polling when
    is_terminal=true
    or after 180s (honest timeout)
```

### Frontend Polling (`use-call-polling.ts`)

- **Interval**: 3 seconds
- **Timeout**: 180 seconds (honest timeout — shows "Timed out — check call history")
- **429 handling**: Skip tick, don't crash the loop
- **Terminal states**: Stop polling, show final badge + retry option for failures
- **Badge map**: Real telephony status → user-visible label and color

### Timeout Handling

| Timeout | Value | Behavior |
|---------|-------|----------|
| ElevenLabs API connect | 10s | Transient error → retry once |
| ElevenLabs API read | 45s | **Ambiguous** — do NOT retry (may duplicate call) |
| Frontend polling | 180s | Show "Timed out — check call history" |
| Ringing sweep | 5 min | Sweep to `stale_in_call` |
| Connected/dialing sweep | 30 min | Sweep to `stale_in_call` or `completed` |

### Retry Policy

**Current**: No retry on ambiguous timeout. One retry on transient error (5xx, 429,
ConnectTimeout, DNS failure). No retry on permanent error (4xx), no_answer,
or unknown (read timeout).

**Safe default rationale**: A read timeout after send means ElevenLabs may have
already placed a real billed SIP call. Retrying creates a second call to the
same number (observed in production — two SIP INVITEs). The failed session is
left for reconciliation via webhook or sweep.

**Not implemented**: Backoff schedule, max-attempts counter, automatic redialing
of no_answer leads.

### Error Categories

| Category | Examples | Retry? |
|----------|----------|--------|
| `transient` | HTTP 5xx, 429, ConnectTimeout, DNS | Yes (once) |
| `permanent` | HTTP 4xx (not 429), malformed response | No |
| `no_answer` | Provider reports ring timeout | No |
| `unknown` | ReadTimeout, WriteTimeout, PoolTimeout | No (ambiguous) |

---

## Session Reconciliation

### Webhook Linkage (FAS-Safe)

**FAS = False Answer Supervision** — SIP 200 OK does not guarantee a real
conversation. Provider billing artifacts must never auto-complete sessions.

The canonical path to `telephony_status=completed` is
`link_outbound_session_by_webhook()` in `outbound/linkage.py`, called from the
post-call webhook handler.

**Lookup priority**:
1. `elevenlabs_conversation_id` (primary — fast path)
2. `provider_call_id` fallback (first-time linkage)
3. Orphan session by `client_id + lead_id` (timeout recovery — scoped to last 10 min)
4. Return None (404 to webhook caller)

**Guard**: `no_answer` and `recurrent_error` are protected from overwrite by
stale session-end webhooks (`_TERMINAL_NO_CONVERSATION_STATUSES` guard).
`failed` and `stale_in_call` are intentionally overwritable — the webhook IS
ground truth for those.

### Post-Dial Probe (`outbound/probe.py`)

Fires 8 seconds after dial (fire-and-forget `asyncio.create_task`):
1. Query ElevenLabs `list_recent_conversations` for the agent.
2. Match by `start_time_unix_secs` within 60s of `started_at`.
3. Fetch `get_sip_messages` for the matched conversation.
4. Extract `sip_call_id`, `sip_status_code`, `sip_reason` (allowlisted fields only).
5. Detect SIP routing failures (4xx/5xx → `failed` + `outcome_reason=sip_routing_error`).
6. Write evidence + `reconciled_at=probe`, commit.

**Idempotent**: if `reconciled_at` is already set, exits without API calls.

### Stale Session Sweep (`outbound/sweep.py`)

Runs every 5 minutes in background:
- **Ringing** > 5 min → `stale_in_call` (SIP routing failure safety net)
- **Dialing/Connected** > 30 min → `stale_in_call` or `completed`
  - `completed` ONLY if `session_end_received=True`
  - `stale_in_call` otherwise (operator review required)

### FAS Pattern (Fire-And-Sweep)

```text
Dial ──→ Probe (8s) ──→ Webhook linkage (async) ──→ Sweep (5 min cycle)
  |           |                 |                        |
  |    Capture SIP       Set completed             Clean up stuck
  |    evidence           from webhook              sessions
  |                        evidence
  └── CallSession pre-committed before any API call (crash-safe)
```

---

## ElevenLabs Agent Config

### Programmatically Managed Fields

`ElevenLabsService.sync_agent_config()` (`backend/app/elevenlabs/service.py`)
sends a single unified PATCH to `https://api.elevenlabs.io/v1/convai/agents/{agent_id}`.

| Field | API Path | DB Column |
|-------|----------|-----------|
| Soft timeout | `conversation_config.turn.soft_timeout_config` | `Agent.soft_timeout_*` |
| Voicemail detection | `conversation_config.agent.prompt.built_in_tools.voicemail_detection` | `Agent.voicemail_detection_enabled` |
| Max call duration | `conversation_config.conversation.max_duration_seconds` | `Agent.max_call_duration_seconds` |

### NULL-Skip Semantics

When an agent DB field is `NULL`, that config block is omitted from the PATCH
payload entirely. This means:
- Setting `voicemail_detection_enabled=True` enables it without touching soft timeout.
- Setting `voicemail_detection_enabled=NULL` skips voicemail detection in the PATCH.
- Setting `voicemail_detection_enabled=False` explicitly sends `null` to disable it.

### API Path Corrections (Production Fix — PR #138)

| Field | Wrong Path (initial SDD) | Correct Path (live API verified) |
|-------|-------------------------|--------------------------------|
| voicemail_detection | `platform_settings.voicemail_detection.enabled` | `conversation_config.agent.prompt.built_in_tools.voicemail_detection` |
| max_duration_seconds | `conversation_config.max_duration_seconds` | `conversation_config.conversation.max_duration_seconds` |
| soft_timeout_config | `conversation_config.turn.soft_timeout_config` | *(already correct)* |

> **Lesson**: Always verify payload paths against live API GET — mocked tests
> pass regardless of path correctness.

### Still Requires Dashboard Config

- Voice selection and TTS model
- Knowledge base documents
- System prompt (managed via Qora file system, not ElevenLabs API)
- Workflow nodes/edges
- Background music
- Turn timeout, turn eagerness
- Language and experiments

---

## Observability

### Correlation Middleware (`middleware/correlation.py`)

Raw ASGI middleware (NOT `BaseHTTPMiddleware` — that breaks contextvars in SSE):
- Reads or generates `X-Request-ID` header.
- Binds `request_id` to structlog contextvars for the request lifetime.
- Sets `X-Request-ID` on response headers.
- Logs `request_started` and `request_completed` with method, path, status, latency.

### Structured Logging

- **Format**: `LOG_FORMAT=json` (default, production) or `LOG_FORMAT=text` (dev).
- **Library**: structlog with stdlib bridge.
- **Context**: voice/job context binding, request correlation.
- **PII**: Never log phone numbers, API keys, or SIP credentials.

### Sentry Integration (`core/sentry.py`)

- **Activation**: Only when `SENTRY_DSN` is set. Application works normally without it.
- **PII scrubbing**: `before_send` hook scrubs E.164 phone numbers → `[REDACTED_PHONE]`
  and API keys (sk-/pk- prefix, hex sequences) → `[REDACTED_KEY]`.
- **Environment**: `SENTRY_ENVIRONMENT` (default: `production`).

### Health Endpoint

`GET /api/v1/health?detail=true` — returns structured health with DB, settings,
and middleware status.

### SIP Observability Fields

Captured on `CallSession` by the probe and sweep:

| Field | Source |
|-------|--------|
| `provider_call_id` | ElevenLabs API response (conversation_id or sip_call_id) |
| `sip_call_id` | SIP Call-ID header from `get_sip_messages` |
| `sip_status_code` | Final SIP response code (200, 404, 487, etc.) |
| `sip_reason` | SIP reason phrase ("OK", "UNALLOCATED_NUMBER", etc.) |
| `reconciled_at` | Timestamp when SIP evidence was captured |
| `reconciliation_source` | `probe`, `sweep`, or `unreconcilable` |

---

## Known Bugs Fixed (Production Learnings)

### Duplicate SIP Call on Read Timeout (PR #130)

**Problem**: ElevenLabs outbound API holds the HTTP connection open while
the SIP call rings. With a 10s read timeout, Qora received a ReadTimeout while
the call was already ringing. The retry logic treated this as transient and
fired a SECOND `POST /outbound-call` — resulting in two real billed SIP INVITEs
to the same phone number.

**Fix**: Classified `ReadTimeout`/`WriteTimeout`/`PoolTimeout` as
`error_category='unknown'` — explicitly not retried. Extended read timeout to
45s. The failed session is left for reconciliation via webhook/sweep.

**Where**: `backend/app/elevenlabs/service.py` — `initiate_outbound_call()`.

### no_answer Overwrite by Stale Webhooks (PR #130)

**Problem**: Out-of-order or duplicate session-end webhooks silently flipped
`no_answer` and `recurrent_error` → `completed`, corrupting billing/CRM
outcomes. These statuses mean "no conversation happened" — the webhook is stale.

**Fix**: Added `_TERMINAL_NO_CONVERSATION_STATUSES` guard in
`update_telephony_status_on_session_end()`. `no_answer` and `recurrent_error`
are preserved. `session_end_received=True` is still set so the sweep has
evidence the webhook fired.

**Where**: `backend/app/outbound/linkage.py`.

### Summarizer WAL Staleness (PR #132)

**Problem**: `_run_summarizer` held an open SQLite transaction IDLE during the
10–60s LLM call. SQLite WAL checkpoint reclaimed WAL mid-flight, making the
transaction stale. First write after LLM call failed with "Can't operate on
closed transaction inside context manager" — causing ~7 minute delays.

**Fix**: `await db.rollback()` after all reads complete (before LLM call).
SQLAlchemy opens a new transaction lazily on first write. ORM instances must
be re-fetched after rollback (`db.get(CallSession, _session_id)`).

**Where**: `backend/app/summarizer.py` — `_run_summarizer()`.

### Summarizer CRM Sync Rollback (PR #132)

**Problem**: `_schedule_crm_sync` was called unguarded after the savepoint.
In durable mode, `executor.enqueue()` writes to DB. If it raised, the exception
propagated up masking the successful analysis — rolling back all analysis writes.

**Fix**: Wrap `_schedule_crm_sync` in its own try/except with warning log.

**Where**: `backend/app/summarizer.py`.

### Orphan Linkage Race Condition (PR #132)

**Problem**: Probe set `telephony_status=no_answer` which was excluded from
`_ORPHAN_STATUSES` in the orphan-session fallback. Post-call webhook arriving
later could not find the session by conversation_id (never stored) and the
orphan lookup excluded `no_answer` sessions — resulting in a 404 and lost
analysis data.

**Fix**: Added `no_answer` to `_ORPHAN_STATUSES` in `_find_orphan_outbound_session()`.
The webhook evidence of a real conversation supersedes the probe's earlier
`no_answer` classification.

**Where**: `backend/app/outbound/linkage.py`.

### Voicemail Billing — 3-Layer Protection (PR #132, #138)

**Problem**: ElevenLabs voice agent did NOT detect voicemail. It started talking
to the answering machine, had a full conversation with it, and the call got
billed (5 minutes observed in production). Critical cost issue.

**Fix**: Three-layer detection:
1. **ElevenLabs `voicemail_detection` built-in tool** — enabled via API (PR #138).
2. **System prompt `<voicemail_detection>` section** — instructs agent to hang up on recorded messages.
3. **`max_call_duration_seconds=120`** — absolute ceiling via API (PR #138).

**Where**: `backend/app/elevenlabs/service.py`, agent `system-prompt.md`.

### ElevenLabs Config Payload Path Errors (PR #138)

**Problem**: SDD implementation used incorrect API paths for voicemail_detection
and max_duration_seconds. Tests passed (mocked paths don't fail) but live API
silently ignored the wrong paths.

**Fix**: Verified correct paths against live ElevenLabs API GET response.
Updated `_build_config_payload()` with correct nested paths.

**Where**: `backend/app/elevenlabs/service.py`.

---

## Production PRs (Chronological)

| PR | Summary |
|----|---------|
| #130 | **C2 + C3 foundation**: Outbound Call Now trigger, SIP observability (probe, sweep, linkage), concurrency guard, E.164 validation, feature flag, webhook auth enforcement, FAS-safe completion, no_answer guard, ambiguous timeout classification. 10 commits, full 4R adversarial review. |
| #132 | **Production bug fixes**: Summarizer WAL staleness + CRM sync rollback fix, orphan linkage `no_answer` inclusion, voicemail prompt instruction, background task GC safety, stale ringing 5-min sweep. |
| #133 | **Call state machine (Batch 3)**: `CallStatus` StrEnum with 10 states, explicit transition table, `GET /calls/{id}/status` polling endpoint (rate-limited 1 req/s), voicemail heuristic, SIP failure surfacing, frontend `useCallPolling` hook + real-time state badges. 73 backend + 8 frontend tests. |
| #135 | **B9 Observability PR1**: Raw ASGI correlation middleware, canonical error envelope, LOG_FORMAT toggle, stdlib bridge. |
| #136 | **B9 Observability PR2**: Optional Sentry (SENTRY_DSN), PII scrubber, voice/job context binding, health `?detail=true`. |
| #138 | **ElevenLabs config sync**: Unified `sync_agent_config()` — voicemail_detection + max_call_duration + soft_timeout in single PATCH. NULL-skip semantics, payload path corrections, input validation (ge=30 le=7200, agent_id regex). |

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/telephony/operator-checklist.md` | Setup companion — Telnyx + ElevenLabs prerequisites |
| `docs/telephony/measurement-protocol.md` | Formal 20-call measurement protocol (deferred) |
| `docs/elevenlabs-setup.md` | ElevenLabs agent configuration guide |
| `docs/elevenlabs-reference.md` | ElevenLabs technical API reference |
| `docs/pipeline-configs/elevenlabs-convai.md` | ElevenAgents architecture and control matrix |
