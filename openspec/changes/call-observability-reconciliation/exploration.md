# Exploration: Call Observability & Reconciliation

## Current State

Qora's outbound call flow (Phase C2) works end-to-end: the frontend triggers `POST /api/v1/clients/{client_id}/leads/{lead_id}/call`, which calls `dial_outbound_call()` → `ElevenLabsService.initiate_outbound_call()` → ElevenLabs SIP trunk API → Telnyx SIP INVITE → destination phone. The lifecycle is tracked via `CallSession` with telephony status fields (`telephony_status`, `provider_call_id`, `telephony_error`, `provider_metadata`, `session_end_received`).

### What exists today

1. **Pre-dial persistence**: `CallSession` is committed with `telephony_status='dialing'` BEFORE the provider call, so crashes leave an auditable row.
2. **Failure classification**: Errors are classified as `transient`, `permanent`, `unknown` (ambiguous timeout), or `no_answer`. The `unknown` category was added as a surgical fix after observing duplicate SIP INVITEs caused by retrying ambiguous timeouts.
3. **Webhook-based completion**: The Custom LLM session-end webhook and `elevenlabs-postcall` webhook set `telephony_status='completed'` and `session_end_received=True` via `link_outbound_session_by_webhook()` and `update_telephony_status_on_session_end()`.
4. **Stale session sweep** (`outbound/sweep.py`): Every 5 minutes, transitions sessions stuck in `{dialing, ringing, in_call}` for >30 minutes to either `completed` (if `session_end_received=True`) or `stale_in_call` (operator review).
5. **Provider metadata allowlist** (`_SAFE_PROVIDER_METADATA_FIELDS`): Only `call_id`, `status`, `duration_seconds`, `billed_duration_seconds`, `cost` are persisted from the outbound-call API response. PII and routing data are stripped.
6. **Cooldown guard**: 10-second per-lead cooldown prevents rapid duplicate triggers.
7. **Frontend error surfacing**: `CallTriggerResponse.error` is now returned for non-dialing outcomes (surgical fix), so the UI shows an error instead of eternal "Calling…".

### What is missing (the problem this change solves)

1. **No ElevenLabs SIP Call-ID capture**: The `otb_...` identifiers seen in Telnyx/ElevenLabs SIP traces are never captured. The `provider_call_id` from the outbound-call API response may differ from the SIP Call-ID used by Telnyx.
2. **No conversation_id linkage for failed/timeout calls**: When the outbound-call API times out (`unknown` category), `provider_call_id` is never captured (the response was never received). There is no way to later find the conversation/call in ElevenLabs.
3. **No ElevenLabs SIP messages retrieval**: The ElevenLabs `GET /conversations/{conversation_id}/sip_messages` and `GET /phone_numbers/{phone_number_id}/sip_messages` APIs are available but not used. These contain SIP INVITE/CANCEL/BYE sequences with status codes, which would explain WHY a call failed (e.g., 404 UNALLOCATED_NUMBER, 487 Request Terminated).
4. **No ElevenLabs conversation list polling**: `GET /conversational_ai/conversations` can list recent conversations filtered by agent_id, time window, and call status — useful for finding orphaned calls after ambiguous timeouts.
5. **No Telnyx API integration**: Telnyx credentials exist in `.env` for SIP trunk auth but there is no Telnyx REST API client. Call detail records (CDRs) are only accessible via the Telnyx portal.
6. **No reconciliation for ambiguous timeouts**: When `error_category='unknown'`, the CallSession is marked `failed` with `telephony_error='ambiguous_timeout (...)'`. The only recovery path is the stale session sweep (which checks `session_end_received`), but this only works if a webhook eventually fires — it does not actively poll ElevenLabs.
7. **Operator has no visibility into SIP-level outcomes**: The `telephony_error` field contains Qora's classification, not the actual SIP status/reason (e.g., `404 Not Found`, `Q.850 cause=1 UNALLOCATED_NUMBER`).

## Affected Areas

- `backend/app/outbound/service.py` — `dial_outbound_call()`: needs post-dial observability hook
- `backend/app/outbound/sweep.py` — `sweep_stale_outbound_sessions()`: needs active reconciliation via ElevenLabs API, not just passive webhook-evidence check
- `backend/app/elevenlabs/service.py` — `ElevenLabsService`: needs new methods for SIP messages retrieval and conversation listing
- `backend/app/elevenlabs/models.py` — new Pydantic models for SIP message and conversation list responses
- `backend/app/calls/models.py` — `CallSession`: may need new columns for SIP-level observability (`sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, `reconciliation_source`)
- `backend/app/calls/schemas.py` — response schemas to expose observability data to the admin API
- `backend/app/calls/router.py` — new endpoint or enriched GET to expose SIP observability
- `backend/app/core/config.py` — `Settings`: no new secrets needed (reuses `ELEVENLABS_API_KEY`); optional feature flags for reconciliation
- `backend/app/main.py` — lifespan: register reconciliation sweep alongside existing outbound sweeper
- `frontend/` — minimal: admin call detail view may show SIP status info (future phase)

## Approaches

### 1. **Immediate Short-Poll After Dial** — Post-dial ElevenLabs conversation lookup

After `initiate_outbound_call()` returns (both success and `unknown` timeout), immediately poll the ElevenLabs conversations list API filtered by agent_id and a tight time window (last 60 seconds) to find the matching conversation. If found, capture `conversation_id` and then fetch SIP messages.

- **Pros**:
  - Fast feedback — observability data captured within seconds of the call
  - Works for the `unknown` timeout case where `provider_call_id` was never received
  - Simple to implement — single async call after dial result
  - No new background infrastructure
- **Cons**:
  - Adds latency to the call trigger response (1-3 extra API calls to ElevenLabs)
  - Matching is heuristic: conversations list filtered by time + agent_id + destination may return multiple results
  - ElevenLabs SIP messages may not be populated until the SIP flow completes (race condition — SIP INVITE sent but SIP messages endpoint has nothing yet)
  - Couples the trigger endpoint latency to ElevenLabs API availability
- **Effort**: Medium

### 2. **Background Reconciliation Sweep Enhancement** — Extend existing outbound sweep with active ElevenLabs polling

Enhance `sweep_stale_outbound_sessions()` (or add a parallel sweep) that, for sessions in `{failed, stale_in_call}` with `telephony_error LIKE 'ambiguous_timeout%'` OR missing `provider_call_id`, calls the ElevenLabs conversations list API and SIP messages API to:
1. Find matching conversations by agent_id + time window
2. Capture conversation_id, SIP Call-ID, final SIP status/reason
3. Update CallSession with reconciliation evidence
4. Transition status if appropriate (failed → completed if evidence shows call connected and ended)

- **Pros**:
  - Does not add latency to the call trigger endpoint
  - Handles all edge cases: timeout, webhook never fired, partial SIP flows
  - Reuses existing sweep infrastructure (background loop, error resilience)
  - Can batch-reconcile multiple stuck sessions in one sweep
  - Can run at configurable intervals (e.g., every 2-5 minutes)
  - Captures SIP-level detail (status codes, reasons) for operator review
- **Cons**:
  - Delayed observability (up to sweep interval + ElevenLabs API latency)
  - More complex matching logic (multiple conversations may match a time window)
  - Needs rate limiting on ElevenLabs API calls (per-sweep cap)
  - Must handle ElevenLabs API errors gracefully (sweep must not crash)
- **Effort**: Medium-High

### 3. **Hybrid: Fire-and-Forget Post-Dial Probe + Background Sweep**

Combine approaches 1 and 2:
- After dial, fire a lightweight background probe (asyncio.create_task) that polls ElevenLabs once after a short delay (e.g., 5-10 seconds) to capture early evidence. Does NOT block the trigger response.
- Background sweep handles remaining reconciliation for anything the probe missed.

- **Pros**:
  - Fast initial evidence capture without blocking the trigger
  - Comprehensive catch-all via background sweep
  - Best observability coverage across all timing scenarios
  - Probe failure is not critical — sweep is the safety net
- **Cons**:
  - Two reconciliation paths to maintain
  - Probe must be idempotent (sweep may re-process the same session)
  - Slightly more complex implementation
- **Effort**: Medium-High

### 4. **Webhook-Based (Future)** — ElevenLabs/Telnyx push notifications

If ElevenLabs or Telnyx support webhook notifications for SIP events (INVITE result, BYE, CANCEL), register a webhook endpoint to receive real-time SIP event updates.

- **Pros**:
  - Real-time, no polling, no latency
  - Lowest operational cost (no periodic API calls)
  - Most reliable — event-driven, not heuristic
- **Cons**:
  - ElevenLabs ConvAI does not currently expose per-SIP-event webhooks — only session-level webhooks (custom-llm, postcall)
  - Telnyx does support call control webhooks, but Qora uses ElevenLabs-managed SIP trunk (ElevenLabs owns the Telnyx connection), so Telnyx webhooks go to ElevenLabs, not Qora
  - Would require ElevenLabs to add this capability or Qora to manage its own Telnyx connection (architectural change)
  - Not viable for MVP
- **Effort**: N/A (blocked by provider capability)

### 5. **Telnyx Direct API Access**

Use the Telnyx API to query CDRs (Call Detail Records) for calls placed through the ElevenLabs-managed SIP trunk.

- **Pros**:
  - CDRs contain definitive SIP status, duration, cost, timestamps
  - Telnyx API credentials may already exist (SIP trunk auth)
- **Cons**:
  - Qora's Telnyx credentials are SIP digest auth credentials (username/password for SIP REGISTER), NOT Telnyx REST API v2 keys. Separate API key provisioning would be needed.
  - The SIP trunk is managed by ElevenLabs — Telnyx CDRs may be under ElevenLabs' Telnyx account, not Qora's
  - Adds a second provider dependency
  - CDR availability delay (Telnyx CDRs can take minutes to populate)
  - Not required for MVP if ElevenLabs APIs provide sufficient evidence
- **Effort**: High (requires new credential provisioning + API client)

## Recommendation

**Approach 3 (Hybrid)** is the recommended first implementation slice, with the following phasing:

### Phase 1 — MVP (this SDD change)

1. **ElevenLabs API client methods** (`elevenlabs/service.py`):
   - `list_recent_conversations(agent_id, time_window_seconds)` → calls `GET /conversational_ai/conversations`
   - `get_conversation_detail(conversation_id)` → calls `GET /conversations/{conversation_id}`
   - `get_sip_messages(conversation_id)` → calls `GET /conversations/{conversation_id}/sip_messages`
   - `get_sip_messages_by_phone(phone_number_id)` → calls `GET /phone_numbers/{phone_number_id}/sip_messages` (fallback for unlinked sessions)

2. **CallSession schema additions** (new nullable columns):
   - `sip_call_id: str | None` — ElevenLabs/Telnyx SIP Call-ID (`otb_...`)
   - `sip_status_code: int | None` — final SIP status code (e.g., 200, 404, 487)
   - `sip_reason: str | None` — SIP reason text (e.g., "UNALLOCATED_NUMBER", "Request Terminated")
   - `reconciled_at: datetime | None` — when reconciliation evidence was captured
   - `reconciliation_source: str | None` — "probe", "sweep", or "webhook"

3. **Post-dial background probe** (`outbound/service.py` or new `outbound/probe.py`):
   - After `initiate_outbound_call()` returns, fire `asyncio.create_task(_probe_call_evidence(call_session_id, agent_id, delay=8))`.
   - After delay, call `list_recent_conversations` + `get_sip_messages`.
   - Match by time window + destination number (from the `conversation_initiation_client_data` or `to_number` in the conversation metadata).
   - On match: update CallSession with `sip_call_id`, `sip_status_code`, `sip_reason`, `reconciled_at`, `reconciliation_source='probe'`.
   - On no match or error: log and let the sweep handle it.

4. **Enhanced reconciliation sweep** (`outbound/sweep.py`):
   - For sessions where `reconciled_at IS NULL` AND `telephony_status IN ('failed', 'stale_in_call')` AND `telephony_error LIKE '%ambiguous_timeout%'`:
     - Call `list_recent_conversations` with the session's time window.
     - Match and update with SIP evidence.
     - Mark `reconciliation_source='sweep'`.
   - For sessions where `reconciled_at IS NULL` AND `session_end_received=True` but no SIP evidence:
     - Call `get_sip_messages(conversation_id)` to capture SIP-level detail.

5. **Admin API enrichment**:
   - Extend `GET /calls/{session_id}` response to include SIP observability fields.
   - No new endpoints needed for MVP.

### Phase 2 — Future improvements (out of scope)

- Telnyx direct API integration (if CDR access is needed beyond SIP messages).
- Real-time SIP event webhooks (when ElevenLabs adds the capability).
- Frontend admin dashboard SIP trace viewer.
- Automated alerting on SIP error patterns (e.g., repeated UNALLOCATED_NUMBER for a lead).

## Risks

1. **ElevenLabs API rate limits**: The conversations list and SIP messages endpoints may have rate limits. The sweep must cap the number of API calls per run (e.g., max 10 sessions per sweep cycle).
2. **SIP messages availability timing**: SIP messages may not be populated immediately after the call attempt. The probe delay (8 seconds) may be too short for some flows; the sweep is the safety net.
3. **Matching ambiguity**: Multiple outbound calls to the same number within a short window could produce ambiguous matches in the conversations list. Mitigation: match on agent_id + to_number + time window, prefer the closest timestamp match.
4. **PII in SIP messages**: Raw SIP messages may contain phone numbers, SIP URIs, digest auth headers. Only extract safe fields (Call-ID, status code, reason phrase). Never persist raw SIP message bodies.
5. **Schema migration**: New CallSession columns require an Alembic migration. Nullable columns are backward-compatible and safe for rollback (drop column).
6. **Probe failure must not affect call flow**: The background probe is fire-and-forget. Any exception must be caught and logged, never propagated to the caller.

## Non-Goals

- **No live calls in tests**: All ElevenLabs API calls in tests MUST be mocked. No live Telnyx/ElevenLabs SIP calls.
- **No raw SIP dumps**: Do not persist raw SIP message bodies (Proxy-Authorization headers, SIP URIs with credentials, phone numbers in From/To headers). Extract only structured fields.
- **No duplicate calls**: Reconciliation must never trigger a new call attempt. It only captures evidence about existing calls.
- **No silent failure**: Every reconciliation attempt (probe or sweep) must log its outcome. Errors are logged, never swallowed.
- **No Telnyx API dependency for MVP**: Do not require Telnyx REST API credentials. Use only ElevenLabs APIs that are accessible with the existing `ELEVENLABS_API_KEY`.
- **No frontend changes in MVP**: SIP observability data is available via the admin API but no frontend rendering is required in this change.

## Review Size Forecast

| Component | Estimated Lines |
|-----------|----------------|
| ElevenLabs API client methods (service + models) | ~120 |
| CallSession schema additions (model + migration) | ~40 |
| Background probe module | ~80 |
| Sweep enhancement | ~60 |
| Admin API response enrichment | ~30 |
| Tests (unit + integration) | ~300 |
| **Total** | **~630** |

This is within the 800-line review budget. A single PR is feasible. If the test count pushes it over, tests could be split into a follow-up PR, but the functional change should stay atomic.

## Ready for Proposal

Yes — the exploration has identified the problem space, mapped the existing architecture, compared five approaches, and recommends a specific implementation slice (Hybrid: probe + sweep) that fits within the review budget. The orchestrator should proceed to `sdd-propose` for this change.
