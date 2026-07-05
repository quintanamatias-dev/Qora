# Design: Phase C1 — Choose Telephony Path

## Technical Approach

C1 is an operational validation phase — documentation, configuration verification, and live measurement — not a code change. The deliverable is a populated decision matrix with real latency data comparing ElevenLabs SIP Trunk + Telnyx (1A) vs ElevenLabs Native Twilio (1B) for Argentina outbound calls. No production code is modified; rollback is deleting C1 artifacts.

Maps to proposal approach steps 1–4 (research → compatibility → fallback → decision record). Maps to spec requirements: pipeline preservation, provider decision matrix, Telnyx prerequisites, measurement protocol, region/edge, rollback.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|----------------------|-----------|
| Primary path to validate | EL SIP Trunk + Telnyx (1A) | Native Twilio (1B), Vapi (1C/1D), Retell (1E), Custom (1F) | Issue #12 cost rationale; user has Telnyx account; Telnyx-first per spec. 1B tested as latency comparator only. 1C–1F require webhook contract changes out of C1 scope. |
| ElevenLabs pipeline role | Full ConvAI pipeline owner (unchanged) | Demote to TTS-only (Vapi/Retell paths) | Preserves existing webhook contract, browser demo, scheduler. Zero Qora code change. |
| Credential handling | Local `.env` / operator-provided only; never committed | Repo-committed config, secrets manager | Spec requires no secrets in repo. Operator checklist documents what to set, not actual values. |
| Rollback strategy | Artifact/config isolation — delete docs to revert | Feature flag, DB migration | C1 produces no code. Rollback = remove/ignore OpenSpec artifacts. Zero runtime impact. |
| Region/edge measurement | Mandatory; record server geography + SIP edge RTT | Assume provider-published regions are sufficient | Spec requires it. Distant hosting adds ~100–160ms RTT for LatAm; must be measured, not assumed. |
| Decision gate | Live latency data from ≥20 calls per provider to Argentina mobile | Docs-only research, assumed latency | Spec requires measured values, not TBD. Decision is latency-gated. |

## Data Flow

Preferred path (1A — ElevenLabs SIP Trunk + Telnyx):

```
Lead/Phone Number
       │
       ▼
Qora Backend ──POST──▶ ElevenLabs API
(trigger only)         /v1/convai/sip-trunk/outbound-call
                       {agent_id, agent_phone_number_id, to_number}
                              │
                              ▼
                       ElevenLabs ConvAI
                       (SIP INVITE → Telnyx)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              Telnyx SIP         ElevenLabs Pipeline
              Termination        STT → Custom LLM → TTS
                    │                   │
                    ▼                   │
              PSTN (Argentina)          │
              Lead's phone ◀────audio───┘
                    │
                    └──── audio ──▶ ElevenLabs STT
                                        │
                                        ▼
                                  Qora Custom LLM
                                  Webhook (unchanged)
                                        │
                                        ▼
                                  GPT-4o Streaming
                                        │
                                        ▼
                                  ElevenLabs TTS
                                        │
                                        ▼
                                  Telnyx SIP → PSTN
                                  → Lead hears agent
```

Key: Qora's only touchpoint is the Custom LLM webhook (existing, unchanged) and the future trigger call (C2, not C1).

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `openspec/changes/phase-c1-telephony-path/design.md` | Create | This design document |
| `docs/telephony/operator-checklist.md` | Create | Operator-facing prerequisites checklist for Telnyx + ElevenLabs SIP setup (no secrets, only what-to-configure) |
| `docs/telephony/measurement-protocol.md` | Create | Test call protocol, metrics template, results table |
| `docs/ROADMAP.md` | Modify | C1 status update and decision note once measurement is complete |

No production code files are created or modified.

## Interfaces / Contracts

C1 does not create code interfaces. It documents the **non-secret data** the operator must confirm before measurement can proceed:

```yaml
# Operator Prerequisites (checklist — values never committed)
telnyx:
  account_status: active          # confirmed by operator
  sip_connection_name: "..."      # connection ID/name only
  sip_auth_type: digest | ip_acl  # which auth method chosen
  outbound_voice_profile: "..."   # profile name only
  caller_id_number: "+1..."       # number format, not actual number
  did_region: US | AR             # where the DID is registered
elevenlabs:
  agent_id: "agent_..."           # existing, already in .env
  sip_trunk_configured: true      # confirmed in EL dashboard
  phone_number_id: "..."          # EL phone number resource ID
measurement:
  argentina_test_number: "+54..." # operator-provided, not committed
  us_control_number: "+1..."      # optional geographic control
  server_region: "ngrok/local"    # or VPS region when deployed
  tunnel_endpoint: "*.ngrok.io"   # for webhook reachability
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Manual/Operational | Telnyx prerequisites satisfied | Operator runs checklist; documents status per item |
| Manual/Measurement | Latency metrics (20+ calls/provider to AR mobile) | Timestamp logging, provider dashboards, subjective quality pass/fail |
| Manual/Measurement | Region/edge RTT | `ping`/`traceroute` to Telnyx SIP edge; record server geography |
| Existing Suite | No regression | `cd backend && python3 -m pytest tests/ -q` — must pass unchanged |

Metrics per provider per destination:

| Metric | Tool |
|--------|------|
| Dial-to-ring | Provider dashboard + manual stopwatch |
| Answer-to-first-agent-audio | Timestamp in webhook logs (existing structlog) |
| Turn-taking delay (p50/p95) | ElevenLabs conversation analytics or manual measurement |
| Jitter/packet loss | Provider call quality reports |
| Cost/minute | Provider rate card (public) |
| Server region / SIP edge | `traceroute`, provider docs, ngrok region config |

## Migration / Rollout

No migration required. C1 produces only documentation artifacts under `openspec/` and `docs/telephony/`. Rollback = delete those files. No DB, no config change, no code change. The existing test suite is unaffected.

## Open Questions

These are **operational prerequisites**, not design blockers:

- [ ] **Telnyx account credit**: Does the existing account have sufficient credit for ~40 test calls (20 AR + 20 US control)? Operator action: check balance, add credit if needed.
- [ ] **ElevenLabs SIP trunk endpoint geography**: Unknown from docs. Live test call to Argentina will reveal actual RTT. If >1500ms p50, investigate EL SIP edge location before blaming Telnyx.
- [ ] **Telnyx Argentina DID availability**: Can the user purchase/verify an Argentina number, or must they use a US DID with Argentina outbound? Operator action: check Telnyx number inventory.
- [ ] **ElevenLabs SIP trunk + Telnyx setup docs**: User will need step-by-step guidance for configuring Telnyx SIP connection + ElevenLabs SIP trunk pairing. Task will provide this as an operator checklist.
