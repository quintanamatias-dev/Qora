# Exploration: Phase C2 — Outbound Call Trigger

## Current State

Qora has a **working scheduler queue** (ScheduledCall model, Phase 6) with auto-scheduling rules, CRUD API, and a 60-second background tick. The tick promotes due `pending` calls to `in_progress` but **initiates no real call** — the dialing gap is the most documented debt in the codebase (see audit docs 00, 02, 03, 17, 18).

**Telephony path validated in C1**: Telnyx SIP trunk paired with ElevenLabs Conversational AI. Manual test confirmed end-to-end Argentina outbound calls work. The ElevenLabs API endpoint is:

```
POST https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call
```

**Required parameters** (from operator-checklist.md and C1 decision):
- `agent_id` — ElevenLabs agent ID (already on `Agent.elevenlabs_agent_id`)
- `agent_phone_number_id` — ElevenLabs phone number resource ID (**new — not in DB yet**)
- `to` — destination phone number (E.164, from `Lead.phone`)
- `conversation_initiation_client_data` — dynamic variables with lead context (same format as existing initiation webhook)

**What exists today:**
- `ElevenLabsService` handles only soft-timeout sync (`PATCH /convai/agents/{id}`)
- `initiation.py` assembles `dynamic_variables` for inbound calls (lead context, memory)
- Durable job executor (BackgroundJob model, registry pattern) available for reliable async work
- Feature flag pattern (`enable_job_executor`) established in `core/config.py`
- Admin API key auth (`require_api_key`) on all scheduler endpoints
- `CallSession` model stores `elevenlabs_conversation_id` but no provider-level call metadata
- `ScheduledCall` has `outcome_session_id` (links to CallSession after call completes)
- Lead detail page is a rich two-column layout with call history, context preview, CRM data

### False Answer Supervision (FAS) Incident

During C1 testing, one call experienced FAS: Telnyx returned SIP `200 OK` while the handset never rang. Telnyx billed ~5-6 minutes. This confirms that **call state from the provider cannot be blindly trusted** — the system must persist both provider-reported state AND its own observable evidence (webhook callbacks, conversation start signals).

## Affected Areas

### Backend — New/Modified

| File | Change | Why |
|------|--------|-----|
| `backend/app/tenants/models.py` | Add `Agent.elevenlabs_phone_number_id` column | Required by ElevenLabs outbound call API |
| `backend/app/core/config.py` | Add `enable_outbound_calls: bool = False` feature flag | Gate real telephony; default off |
| `backend/app/elevenlabs/service.py` | Add `initiate_outbound_call()` method | POST to SIP trunk outbound-call endpoint |
| `backend/app/elevenlabs/models.py` | Add `OutboundCallRequest`, `OutboundCallResult` Pydantic models | Type-safe API contract |
| `backend/app/calls/models.py` | Add telephony metadata columns to `CallSession` | `provider_call_id`, `telephony_provider`, `telephony_status`, `telephony_error`, `provider_metadata` |
| `backend/app/scheduler/models.py` | Extend state machine transitions | Add `dialing` state between `pending→in_progress→completed` |
| `backend/app/scheduler/service.py` | Add `dial_scheduled_call()` or modify tick | Trigger outbound call for due entries |
| `backend/app/voice/initiation.py` | Extract `build_dynamic_variables()` helper | Reuse lead context assembly for outbound calls |
| `backend/app/jobs/registry.py` | Register `dial_outbound_call` handler | Durable job for call initiation |
| `backend/app/agents/schemas.py` | Add `elevenlabs_phone_number_id` to Agent schemas | API exposure |

### Backend — New Files

| File | Purpose |
|------|---------|
| `backend/app/leads/router.py` (or extend existing) | `POST /clients/{client_id}/leads/{lead_id}/call` — manual trigger endpoint |
| `backend/alembic/versions/XXXX_c2_outbound.py` | Migration for new columns |

### Frontend

| File | Change | Why |
|------|--------|-----|
| `frontend/src/features/leads/detail-page.tsx` | Add "Call Now" button in header area | Manual trigger per-lead |
| `frontend/src/api/leads.ts` | Add `triggerCall(clientId, leadId)` API function | Frontend → backend call |
| `frontend/src/api/types.ts` | Add call trigger response type | Type safety |

### Config / Env

| File | Change |
|------|--------|
| `.env.example` | Add `ENABLE_OUTBOUND_CALLS`, `ELEVENLABS_PHONE_NUMBER_ID` |
| `docs/ROADMAP.md` | Update C2 status |

## Approaches

### 1. Manual Trigger First, Scheduler Second

Manual per-lead "Call Now" button → API endpoint → ElevenLabs outbound call. The scheduler tick is NOT modified yet — it continues to only mark `in_progress`. The scheduler integration reuses the exact same `dial_outbound_call()` function later.

- **Pros**: Smallest blast radius; operator controls every call; can validate E2E with real money before automating; scheduler changes are deferred (lower risk); call state persistence designed once, used by both paths
- **Cons**: No automated dialing yet; operator must manually trigger each call
- **Effort**: Medium

### 2. Scheduler-Driven Dialing from Day One

Modify `scheduler_tick()` or add a parallel `dialer_tick()` that picks up `in_progress` ScheduledCalls and dials. No manual trigger endpoint.

- **Pros**: Closes the core loop immediately; aligns with the product promise
- **Cons**: Higher risk with real money; harder to debug individual call failures; no operator control gate; all-or-nothing activation; FAS risk amplified by automation
- **Effort**: High

### 3. Hybrid: Manual + Scheduler Behind Same Flag

Both endpoints exist from day one but share the same feature flag and `dial_outbound_call()` function. Manual trigger is always available when flag is on; scheduler auto-dial is a second flag (`enable_auto_dial`).

- **Pros**: Future-proof; clean separation of "can we dial?" from "should we auto-dial?"
- **Cons**: Two feature flags to manage; more test surface; premature if scheduler dialing is weeks away
- **Effort**: Medium-High

## Recommendation

**Approach 1: Manual Trigger First, Scheduler Second.**

Rationale:
1. The $5 test budget demands precision — operator-controlled calls prevent waste
2. FAS risk requires human judgment per call until confidence in the route grows
3. The manual trigger endpoint (`POST /clients/{cid}/leads/{lid}/call`) and the `dial_outbound_call()` function are designed so the scheduler can call the same function later with zero code duplication
4. Call state persistence (C7) and failure registration (C6) are built from the start, shared by both paths
5. The lead detail page already has the right layout for a prominent action button

### Architecture for Reuse

```
Manual trigger (API)  ──┐
                        ├──→ dial_outbound_call(lead, agent, scheduled_call?)
Scheduler tick (later) ─┘         │
                                  ├── Build dynamic_variables (reuse initiation.py helper)
                                  ├── POST ElevenLabs SIP trunk outbound-call API
                                  ├── Persist OutboundCallAttempt (provider_call_id, status)
                                  └── Update ScheduledCall state (if linked)
```

### State Machine Extension (C3 subset)

Current: `pending → in_progress → completed | failed | cancelled`

Proposed addition for C2:
```
pending → in_progress → dialing → completed | failed | cancelled
                                   ↑ (ElevenLabs API called)
```

The `dialing` state means "API call was sent, waiting for ElevenLabs to initiate SIP call." Transition to `completed` happens when the conversation webhook fires and the session ends normally. Transition to `failed` happens on API error, timeout, or FAS-like conditions.

**For the manual trigger path (no ScheduledCall)**, the call attempt is tracked directly on `CallSession` telephony metadata columns — no ScheduledCall record needed.

### Smallest Safe First Slice

1. **DB migration**: `Agent.elevenlabs_phone_number_id` + `CallSession` telephony columns
2. **Feature flag**: `ENABLE_OUTBOUND_CALLS=false` in config
3. **ElevenLabs outbound call service**: `initiate_outbound_call()` in `elevenlabs/service.py`
4. **Dynamic variables builder**: extract from `initiation.py` into shared helper
5. **Manual trigger endpoint**: `POST /clients/{cid}/leads/{lid}/call` (requires `require_api_key` + flag check)
6. **Call attempt persistence**: Create `CallSession` with telephony metadata before calling ElevenLabs
7. **Frontend button**: "Call Now" on lead detail page header
8. **Linking**: Pass `scheduled_call_id` (if any) and `lead_id` in `conversation_initiation_client_data.custom_llm_extra_body` so the existing webhook can link the conversation back

### What This Slice Does NOT Include

- Scheduler auto-dialing (C2 full — later)
- Retry/backoff logic (C6 — later)
- Voicemail detection policy (C5 — later)
- Phone number management UI (C4 — later, single number per agent via DB is enough)
- Cost tracking (Phase E)
- ScheduledCall `dialing` state (deferred — manual calls don't go through scheduler)

## Open Product Questions

1. **Call confirmation UX**: Should the "Call Now" button show a confirmation dialog? ("This will place a real phone call to +54 9 XXX costing ~$0.01/min. Proceed?")
2. **Concurrent call guard**: Should the system prevent calling a lead who is already on an active call? (Likely yes — check for `in_progress` ScheduledCall or active CallSession)
3. **Agent selection**: If a client has multiple agents, should the operator pick which agent makes the call, or always use the default? (Recommend: default agent for now, explicit selection later)
4. **Call result visibility**: After triggering a call, should the UI poll for status updates, or just show "Call initiated" and rely on the call history refreshing? (Recommend: optimistic "Calling..." badge + poll CallSession status)
5. **FAS mitigation**: Should we add a "call actually connected" confirmation step, where the operator marks whether the call truly connected, to build data for route quality tracking? (Recommend: yes, lightweight — a boolean on CallSession)

## Risks

1. **Real money on every call**: No dry-run mode. Each trigger costs Telnyx + ElevenLabs credits. Mitigated by feature flag + confirmation dialog + $5 budget awareness.
2. **FAS / billing disputes**: Telnyx may report successful calls that never connected. Mitigated by persisting both provider state and operator observation.
3. **ElevenLabs API instability**: Outbound call API is newer than the WebSocket flow. Mitigated by retry-capable service pattern (same as `_patch_with_retry`).
4. **Webhook linkage gap**: ElevenLabs outbound call returns a `conversation_id` — this must match the `conversation_id` that arrives in the Custom LLM webhook for call linkage to work. If ElevenLabs changes the ID format or doesn't propagate it, the CallSession won't link. Mitigated by logging both IDs and having a reconciliation path.
5. **Lead phone number format**: `Lead.phone` must be E.164 for Telnyx. No current validation exists. Mitigated by validating at trigger time, not retroactively.
6. **ngrok tunnel instability**: ElevenLabs needs to reach the Custom LLM webhook during the call. If ngrok restarts, the call drops. Mitigated by the existing architecture (same risk as browser demo).
7. **State machine migration**: Adding `dialing` to `VALID_TRANSITIONS` requires migrating existing `in_progress` rows. Low risk if deferred to scheduler integration.

## Ready for Proposal

**Yes.** The exploration has mapped all relevant code, identified the smallest safe first slice, and documented open questions. The orchestrator should:

1. Confirm the open product questions (especially #1 confirmation UX and #4 call result visibility)
2. Proceed to `sdd-propose` for the manual trigger slice
3. The proposal should scope explicitly to: migration + feature flag + ElevenLabs service + manual trigger endpoint + call persistence + frontend button
4. Scheduler integration (approach 1 → full C2) is a separate follow-up proposal
