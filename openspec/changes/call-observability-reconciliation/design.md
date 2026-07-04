# Design: Call Observability & Reconciliation

## Technical Approach

Hybrid probe + background sweep (Proposal Approach 3). After `dial_outbound_call()` resolves, a fire-and-forget `asyncio.create_task` probes ElevenLabs for early SIP evidence. The existing `stale_outbound_telephony_sweeper` gains an active reconciliation pass that polls ElevenLabs for sessions with `reconciled_at IS NULL`. Both paths are idempotent — `reconciled_at` acts as a write-once guard. All new `CallSession` columns are nullable (rollback = `DROP COLUMN`).

## Architecture Decisions

### Decision: Direct HTTP client, not SDK wrapper

| Option | Tradeoff | Decision |
|--------|----------|----------|
| New `ElevenLabsConvAIClient` class | Extra abstraction layer; only 4 methods needed | **Rejected** |
| Methods on existing `ElevenLabsService` | Matches codebase pattern (per-call `httpx.AsyncClient`); keeps service as single injection point | **Chosen** |

Rationale: Codebase already uses per-call `httpx.AsyncClient` in `ElevenLabsService` and webhook helpers. Adding methods to the existing service follows this convention and avoids a new dependency graph.

### Decision: SIP field extraction — allowlist only, never raw bodies

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Store raw SIP messages | Full debugging power; exposes Proxy-Authorization, digest credentials, PII in From/To headers | **Rejected** |
| Extract structured fields via allowlist | Limits to `Call-ID`, status code, reason phrase; loses raw trace detail | **Chosen** |

Rationale: Raw SIP bodies contain `Proxy-Authorization` headers with digest credentials, `From`/`To` SIP URIs with phone numbers, and internal routing data. Persisting any of these violates PII and security constraints. The Pydantic response model extracts only safe fields before they reach the DB.

### Decision: Probe as separate module (`outbound/probe.py`)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Inline probe logic in `outbound/service.py` | Simpler; harder to test in isolation | **Rejected** |
| Standalone `outbound/probe.py` module | Independently testable; clear responsibility boundary; rollback = delete file | **Chosen** |

Rationale: `outbound/service.py` already has 657 lines. The probe is fire-and-forget with its own DB session — isolating it matches the `sweep.py` module pattern.

### Decision: No retry after ambiguous timeout — reconciliation resolves

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Retry read-timeout calls | Risk: duplicate billed SIP INVITEs (observed in production) | **Rejected** |
| Mark failed + reconcile via probe/sweep | May take up to sweep interval (5 min) to resolve; no duplicate call risk | **Chosen** |

Rationale: Production incident confirmed that retrying ambiguous timeouts produces duplicate SIP INVITEs. Reconciliation captures provider evidence without ever dispatching a new call.

### Decision: Per-sweep API call cap (10 sessions)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Uncapped sweep | Reconcile all pending in one pass; ElevenLabs 429 risk on batch | **Rejected** |
| Cap at 10 sessions/sweep | Oldest-first priority; clears backlog over 2-3 cycles; stays under rate limits | **Chosen** |

Rationale: ElevenLabs ConvAI API rate limits are undocumented. A conservative cap (configurable via `Settings`) prevents 429s while clearing typical backlogs within minutes.

## Data Flow

```
dial_outbound_call()
        │
        ├─ accepted → update CallSession → return DialResult
        │       │
        │       └─ asyncio.create_task(probe_call_evidence)
        │               │ (8s delay)
        │               ├─ list_recent_conversations(agent_id, 120s window)
        │               ├─ match by to_number + closest created_at
        │               ├─ get_sip_messages(conversation_id)
        │               └─ UPDATE CallSession SET sip_call_id, sip_status_code,
        │                  sip_reason, reconciled_at, reconciliation_source='probe'
        │
        └─ error (unknown/failed) → mark CallSession failed → return
                                         │
                          ┌───────────────┘ (5 min sweep interval)
                          ▼
              sweep_stale_outbound_sessions()
                          │
                          ├─ existing: stale status transitions (FAS-safe)
                          └─ NEW: reconciliation pass
                                  │
                                  ├─ SELECT WHERE reconciled_at IS NULL
                                  │   AND telephony_status IN ('failed','stale_in_call')
                                  │   LIMIT 10 ORDER BY started_at ASC
                                  │
                                  ├─ list_recent_conversations(agent_id, time window)
                                  ├─ match by to_number + closest created_at
                                  ├─ get_sip_messages(conversation_id)
                                  └─ UPDATE CallSession SET sip_*, reconciled_at,
                                     reconciliation_source='sweep'
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/elevenlabs/service.py` | Modify | Add 4 async methods: `list_recent_conversations`, `get_conversation_detail`, `get_sip_messages`, `get_sip_messages_by_phone`. Reuse per-call `httpx.AsyncClient` pattern and `_REQUEST_TIMEOUT_SECONDS`. |
| `backend/app/elevenlabs/models.py` | Modify | Add Pydantic models: `ConversationSummary`, `ConversationListResponse`, `SipMessage`, `SipMessagesResponse`. Only allowlisted fields (no raw SIP bodies). |
| `backend/app/calls/models.py` | Modify | Add 5 nullable columns to `CallSession`: `sip_call_id` (String), `sip_status_code` (Integer), `sip_reason` (String), `reconciled_at` (DateTime), `reconciliation_source` (String). |
| `backend/app/calls/schemas.py` | Modify | Add SIP observability fields to admin GET response dict in `_session_to_dict()`. No new schema class needed — just extend the existing serializer. |
| `backend/app/calls/router.py` | Modify | Extend `_session_to_dict()` to include `sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, `reconciliation_source`. |
| `backend/app/outbound/probe.py` | Create | `probe_call_evidence(session_id, agent_id, to_number, settings, delay=8)` — fire-and-forget background probe. Own DB session via `async_session_factory`. |
| `backend/app/outbound/service.py` | Modify | After accepted/failed-unknown result, fire `asyncio.create_task(probe_call_evidence(...))`. Import and call only — probe logic stays in `probe.py`. |
| `backend/app/outbound/sweep.py` | Modify | Add reconciliation pass after existing stale-status transitions: query unreconciled sessions, call ElevenLabs, write SIP evidence. Cap at 10 per sweep. |
| `backend/app/core/config.py` | Modify | Add `reconciliation_sweep_cap: int = 10` to `Settings` (optional, with default). |
| `backend/alembic/versions/YYYYMMDD_0006_sip_observability.py` | Create | Nullable column additions to `call_sessions`. Batch alter for SQLite compat. Downgrade = `DROP COLUMN`. |
| `backend/tests/unit/outbound/test_probe.py` | Create | Probe unit tests: match found, no match, API error, already reconciled (idempotent). All ElevenLabs calls mocked via `respx`. |
| `backend/tests/unit/outbound/test_reconciliation_sweep.py` | Create | Sweep reconciliation tests: reconcile failed session, skip already-reconciled, cap respected, API error resilience. Mocked via `respx`. |
| `backend/tests/unit/outbound/test_elevenlabs_conversations.py` | Create | Unit tests for the 4 new `ElevenLabsService` methods. All HTTP mocked via `respx`. |

## Interfaces / Contracts

```python
# backend/app/elevenlabs/models.py — new models

class ConversationSummary(BaseModel):
    """Single conversation from ElevenLabs list endpoint."""
    conversation_id: str
    agent_id: str | None = None
    status: str | None = None  # "done", "processing", etc.
    call_successful: str | None = None
    start_time_unix_secs: int | None = None
    # Only safe fields — no phone numbers, no SIP URIs
    metadata: dict | None = None

class ConversationListResponse(BaseModel):
    """Response from GET /conversational_ai/conversations."""
    conversations: list[ConversationSummary] = []

class SipMessage(BaseModel):
    """Sanitized SIP message — extracted fields only, never raw body."""
    call_id: str | None = None  # SIP Call-ID header
    method: str | None = None   # INVITE, BYE, CANCEL, etc.
    status_code: int | None = None  # 200, 404, 487, etc.
    reason_phrase: str | None = None  # "OK", "Not Found", etc.
    direction: str | None = None  # "inbound" / "outbound"
    timestamp: str | None = None

class SipMessagesResponse(BaseModel):
    """Response from GET /conversations/{id}/sip_messages."""
    sip_messages: list[SipMessage] = []

# backend/app/elevenlabs/service.py — new method signatures

async def list_recent_conversations(
    self, agent_id: str, time_window_seconds: int = 120
) -> ConversationListResponse: ...

async def get_conversation_detail(
    self, conversation_id: str
) -> dict: ...  # raw safe fields

async def get_sip_messages(
    self, conversation_id: str
) -> SipMessagesResponse: ...

async def get_sip_messages_by_phone(
    self, phone_number_id: str
) -> SipMessagesResponse: ...
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | 4 ElevenLabs API client methods (2xx, 4xx, 5xx, timeout, malformed JSON) | `respx` HTTP mock; no live calls |
| Unit | Probe logic: match found → update, no match → log, error → catch, already reconciled → skip | `respx` + in-memory SQLite; mock `async_session_factory` |
| Unit | Sweep reconciliation: cap enforcement, oldest-first priority, idempotency, API error resilience | `respx` + `db_session` fixture; verify DB state |
| Unit | SIP field extraction: only allowlisted fields survive; raw bodies never persisted | Pure function test on `SipMessage` model |
| Integration | Migration applies cleanly + downgrades without data loss | `apply_migrations()` helper in existing test harness |
| Integration | Admin GET returns SIP fields when populated, null when not | HTTP client against test app |

No live ElevenLabs or Telnyx calls in any test. All provider HTTP calls intercepted by `respx`.

## Migration / Rollout

**Alembic migration** `YYYYMMDD_0006_sip_observability`:
- Adds 5 nullable columns to `call_sessions` via `batch_alter_table` (SQLite safe).
- No server defaults — existing rows remain NULL (pre-observability sessions).
- Downgrade: `DROP COLUMN` for all 5 columns. Zero data loss to existing rows.
- Follows the exact pattern of `20260702_0004_c2_outbound_telephony.py`.

**Rollout sequence**:
1. Deploy code with `ENABLE_OUTBOUND_CALLS=true` (already required).
2. Run `python scripts/migrate.py` → Alembic upgrade adds columns.
3. Probe activates automatically on next dial. Sweep gains reconciliation on next cycle.
4. No feature flag needed — observability is always-on once columns exist.

**Rollback**: revert commits (probe isolated, sweep additions additive), then `alembic downgrade -1`.

## Open Questions

- [ ] ElevenLabs `GET /conversational_ai/conversations` rate limit: undocumented. The 10-session cap is conservative; adjust after production observation.
- [ ] SIP message availability timing: probe delay (8s) may miss slow SIP flows. Sweep is the safety net. Monitor probe hit rate in production logs.

## Review Workload Forecast

| Component | Estimated Lines | Commit |
|-----------|----------------|--------|
| ElevenLabs API client methods + Pydantic models | ~120 | WU1 |
| CallSession columns + Alembic migration | ~40 | WU2 |
| `probe.py` + service hook | ~80 | WU3 |
| Sweep reconciliation enhancement | ~60 | WU4 |
| Admin API response enrichment | ~30 | WU5 |
| Tests (unit + integration) | ~300 | Co-located with each WU |
| **Total** | **~630** | 5 commits |

**Forecast**: ~630 lines — within the 800-line review budget. Single PR feasible.

## Work-Unit Commit Boundaries

| WU | Commit | Content | Self-contained? |
|----|--------|---------|-----------------|
| WU1 | `feat(elevenlabs): add conversation list and SIP message API methods` | `service.py` methods + `models.py` Pydantic types + `test_elevenlabs_conversations.py` | Yes — new methods, no callers yet |
| WU2 | `feat(calls): add SIP observability columns to CallSession` | `models.py` columns + Alembic migration + migration integration test | Yes — nullable columns, no behavior change |
| WU3 | `feat(outbound): add post-dial SIP evidence probe` | `probe.py` + `service.py` hook (asyncio.create_task) + `test_probe.py` | Yes — probe is fire-and-forget; fails silently |
| WU4 | `feat(outbound): add active reconciliation to stale sweep` | `sweep.py` enhancement + `config.py` cap setting + `test_reconciliation_sweep.py` | Yes — additive to existing sweep |
| WU5 | `feat(calls): enrich admin API response with SIP observability fields` | `router.py` serializer + `schemas.py` type hints (if needed) + response test | Yes — read-only addition |
