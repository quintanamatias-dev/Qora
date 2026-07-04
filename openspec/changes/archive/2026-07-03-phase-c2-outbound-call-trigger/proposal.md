# Proposal: Phase C2 — Outbound Call Trigger (Manual Slice)

## Intent

Qora's scheduler queues calls but never dials. This change closes the most critical gap
in the outbound pipeline: a human operator can manually trigger a real ElevenLabs/Telnyx
call for any lead from the Leads list, using existing lead context, with every attempt
persisted (state, errors, provider metadata). The design is reused by the scheduler later
with zero duplication.

## Scope

### In Scope

- Feature flag `ENABLE_OUTBOUND_CALLS` (default `false`) guards all real telephony
- `Agent.elevenlabs_phone_number_id` DB column + Alembic migration
- `CallSession` telephony metadata columns: `provider_call_id`, `telephony_provider`, `telephony_status`, `telephony_error`, `provider_metadata` (JSON)
- `ElevenLabsService.initiate_outbound_call()` — POST to SIP trunk outbound-call API
- Shared `build_dynamic_variables()` helper extracted from `initiation.py`
- `POST /clients/{client_id}/leads/{lead_id}/call` manual trigger endpoint (admin API key + flag required)
- Phone number E.164 validation at trigger time (reject if invalid)
- Concurrent call guard: reject if lead has an active `CallSession` or `in_progress` ScheduledCall
- Call attempt persistence: `CallSession` created before dialing; telephony columns written on result
- Failure classification: transient system error → one automatic retry; second failure → `recurrent_error` status; no-answer → distinct `no_answer` status (not retried by default)
- Frontend "Call Now" green button on Leads list row, positioned after `next_action`; confirmation dialog ("real call, ~$0.21/min") before dispatch
- Optimistic "Calling…" badge after dispatch; call history refreshes on next poll
- Provider metadata + cost/billed seconds persisted when available in ElevenLabs response

### Out of Scope

- Scheduler auto-dialing (C2 full — future)
- ScheduledCall `dialing` state extension (C3 — future)
- Retry backoff policy beyond one system-error retry (C6 — future)
- Voicemail detection (C5 — future)
- Phone number management UI (C4 — future)
- Cost tracking dashboard (Phase E)
- FAS human confirmation flag (noted as future hardening)

## Capabilities

### New Capabilities

- `outbound-call-trigger`: Manual lead-to-call flow — flag guard, endpoint, ElevenLabs SIP call, attempt persistence, failure classification, frontend button + confirmation

### Modified Capabilities

- `telephony-provider-decision`: `CallSession` gains provider metadata columns; `Agent` gains `elevenlabs_phone_number_id` — requirements change from "C1 decision only" to "C2 runtime model"

## Approach

**Manual trigger first; scheduler reuse later.** A single `dial_outbound_call(lead, agent, scheduled_call=None)` function is the sole entry point for dialing. The manual endpoint and the future scheduler tick both call this function. ElevenLabs conversation_id from the API response is stored on `CallSession` immediately; the existing Custom LLM webhook links the full session via the same ID.

FAS awareness: provider SIP answer ≠ human conversation. `telephony_status` records provider-reported state only; actual conversation evidence comes from webhook callbacks. These are stored separately and never conflated.

```
Operator → "Call Now" button (confirmation)
  → POST /leads/{id}/call (flag check + E.164 guard + concurrent guard)
    → create CallSession (telephony_status=dialing)
    → build_dynamic_variables(lead)
    → ElevenLabsService.initiate_outbound_call()
      → persist provider_call_id + raw provider_metadata
      → on error: classify transient vs permanent; update telephony_status
    → return { status, call_session_id }
```

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/tenants/models.py` | Modified | Add `Agent.elevenlabs_phone_number_id` |
| `backend/app/calls/models.py` | Modified | Add 5 telephony metadata columns to `CallSession` |
| `backend/app/core/config.py` | Modified | Add `enable_outbound_calls: bool = False` |
| `backend/app/elevenlabs/service.py` | Modified | Add `initiate_outbound_call()` |
| `backend/app/elevenlabs/models.py` | Modified | Add `OutboundCallRequest`, `OutboundCallResult` |
| `backend/app/voice/initiation.py` | Modified | Extract `build_dynamic_variables()` as shared helper |
| `backend/app/leads/router.py` | Modified/New | Add `POST /leads/{lead_id}/call` trigger endpoint |
| `backend/app/agents/schemas.py` | Modified | Expose `elevenlabs_phone_number_id` |
| `backend/alembic/versions/` | New | Migration for new columns |
| `frontend/src/features/leads/` | Modified | "Call Now" button + confirmation dialog + Calling… badge |
| `frontend/src/api/leads.ts` | Modified | `triggerCall(clientId, leadId)` |
| `.env.example` | Modified | `ENABLE_OUTBOUND_CALLS`, `ELEVENLABS_PHONE_NUMBER_ID` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Real money per call ($0.21/min, $5 budget) | High | Feature flag off by default; confirmation dialog; explicit operator action |
| FAS: provider bills for unconnected calls | Med | Store `telephony_status` and webhook evidence separately; never conflate |
| ElevenLabs conversation_id not propagated to Custom LLM webhook | Med | Log both IDs; fallback reconciliation path via `provider_call_id` |
| Lead phone not E.164 | Med | Validate at trigger time; return 422 with clear error |
| ngrok tunnel restart drops call mid-stream | Med | Same risk as browser demo; operator awareness; document in operator runbook |
| ElevenLabs outbound API rate limit or instability | Low | Retry wrapper pattern (reuse `_patch_with_retry`); surface errors clearly |

## Rollback Plan

1. Set `ENABLE_OUTBOUND_CALLS=false` (or remove it) — blocks all dialing immediately; no code change needed.
2. If migration must be reverted: `alembic downgrade -1` removes new columns; existing `CallSession` and `Agent` rows are unaffected (columns are nullable additions).
3. Frontend button is conditional on feature-flag API response; removing it is a one-line guard removal.

## Dependencies

- `ELEVENLABS_PHONE_NUMBER_ID` env var (operator-configured; from C1 operator-checklist.md §2.2)
- ElevenLabs SIP trunk active and paired with Telnyx (confirmed C1)
- `ELEVENLABS_API_KEY` already in `.env`

## Success Criteria

- [ ] `ENABLE_OUTBOUND_CALLS=false` → trigger endpoint returns 403; no call placed; no charge incurred
- [ ] Valid lead with E.164 phone + flag on → ElevenLabs API called; `CallSession` persisted with `provider_call_id` and `telephony_status=dialing` before response
- [ ] Invalid phone number → 422 returned; no `CallSession` created; no charge
- [ ] Lead with active `CallSession` → 409 returned; no duplicate call placed
- [ ] Provider returns error → `telephony_status=failed`; `telephony_error` populated; one auto-retry on transient error; second failure → `recurrent_error`; no retry on no-answer
- [ ] Provider metadata (cost, billed seconds) persisted when present in response
- [ ] FAS scenario: SIP 200 OK received but conversation webhook never fires → `telephony_status` reflects provider claim; no false `completed` status
- [ ] All existing tests pass; no regressions
