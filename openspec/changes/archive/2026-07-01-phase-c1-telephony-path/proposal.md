# Proposal: Roadmap Phase C1 — Choose Telephony Path

## Intent

Qora's scheduler tick promotes due calls to `in_progress` but initiates no real call. Phase C1 resolves the foundational decision blocking all of Phase C: which telephony path connects the existing ElevenLabs Conversational AI pipeline to outbound phone calls in a cost-effective way for Argentina-oriented calls.

The **primary hypothesis** is `ElevenLabs SIP trunk + Telnyx` (cheaper for Argentina, already validated as preferred in GitHub issue #12 over ElevenLabs native Twilio). This C1 deliverable produces a documented, evidence-backed decision — not a dialer implementation.

## Scope

### In Scope
- Validate ElevenLabs SIP trunk endpoint (`/v1/conversational_ai/sip_trunk/outbound_call`) compatibility with Telnyx as the SIP provider
- Document decision criteria: cost/min (Argentina outbound), SIP trunk compatibility, latency impact, credential complexity
- Document chosen path with evidence and fallback rationale
- Identify minimum config/data-model columns required for the chosen path (e.g., `Agent.elevenlabs_phone_number_id`, Telnyx SIP credentials in secrets)
- Update `ROADMAP.md` C1 status and decision note

### Out of Scope
- Implementing the dialer worker (C2)
- State machine extension `pending → dialing → ringing → …` (C3)
- Phone number management API/UI (C4)
- Voicemail policy (C5), retry policy (C6), telephony metadata storage (C7)
- Real E2E test call to a live number (C8)
- VPS/production deployment

## Capabilities

> Research confirmed: `openspec/specs/` is empty (no root specs directory — specs live inside change folders only).

### New Capabilities
- `telephony-provider-decision`: Documents the chosen outbound telephony path, decision rationale, Telnyx SIP trunk compatibility evidence, cost comparison (Argentina), and fallback path.

### Modified Capabilities
- None

## Approach

1. **Research phase**: Verify ElevenLabs SIP trunk API shape vs. Twilio integration. Confirm Telnyx SIP trunk registration format, Argentina outbound pricing, and credential requirements.
2. **Compatibility validation**: Determine whether Telnyx SIP trunks can register with ElevenLabs SIP trunk endpoint without custom media/AI orchestration.
3. **Fallback evaluation**: If SIP trunk incompatible, evaluate Telnyx Call Control API + direct media streaming as fallback (higher custom work cost documented).
4. **Decision record**: Produce ADR-style spec with chosen path, evidence, config implications (env vars, DB columns needed), and rollback note if path is abandoned post-C2.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/ROADMAP.md` | Modified | C1 status → in progress / decided; add decision note |
| `openspec/changes/phase-c1-telephony-path/specs/telephony-provider-decision/spec.md` | New | ADR-style decision spec |
| `backend/app/tenants/models.py` | Identified (not yet modified) | `Agent` may need `elevenlabs_phone_number_id` column; decision confirms scope |
| `.env.example` | Identified (not yet modified) | Telnyx SIP credentials pattern to be defined |
| `openspec/changes/phase-c-outbound-calls/exploration.md` (Engram #2252) | Superseded | Previous recommendation (ElevenLabs native Twilio) overridden by issue #12 evidence |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ElevenLabs SIP trunk rejects Telnyx credentials format | Med | Test with Telnyx trial account before committing; fallback path documented |
| Telnyx Argentina pricing unclear at research phase | Low | Telnyx pricing page is public; compare vs Twilio at decision time |
| SIP trunk adds audio latency vs native Twilio | Low | ElevenLabs manages SIP leg; latency impact documented in decision spec |
| Fallback (Telnyx Call Control) requires significant custom work | Med | Scope it as C-alt branch, not C1 deliverable; accept if SIP works |

## Rollback Plan

C1 produces no production code changes — only a decision document and spec. If the chosen path proves wrong in C2/C3, the spec is updated and the next path is selected. No DB migrations or config changes are committed at this phase. Rollback is free.

## Dependencies

- ElevenLabs SIP trunk API documentation (public)
- Telnyx SIP trunk documentation and trial credentials (free tier available)
- GitHub issue #12 evidence (Twilio → Telnyx migration rationale)

## Success Criteria

- [ ] `openspec/changes/phase-c1-telephony-path/specs/telephony-provider-decision/spec.md` exists with a documented path choice
- [ ] Decision spec contains: chosen provider+path, cost comparison, compatibility evidence, fallback option, and minimum config implications
- [ ] `ROADMAP.md` C1 row shows decision note with chosen path
- [ ] Engram `sdd/phase-c1-telephony-path/proposal` persisted
