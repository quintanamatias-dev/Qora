# Exploration Addendum: Latency-First Telephony Provider Analysis

> **Change**: `phase-c1-telephony-path`
> **Parent proposal**: `openspec/changes/phase-c1-telephony-path/proposal.md`
> **Supersedes**: Latency risk row in proposal (was rated "Low" — this addendum replaces that with structured analysis)
> **Date**: 2026-06-30

## Context

The C1 proposal's primary hypothesis is "ElevenLabs SIP trunk + Telnyx." This addendum expands the decision space: latency is the second most important product requirement after human-like voice quality. Price matters only if latency remains excellent. This document provides a latency-first comparison of all viable telephony paths.

---

## 1. Provider/Path Options

### 1A. ElevenLabs SIP Trunk + Telnyx

**How it works**: Qora calls ElevenLabs `POST /v1/convai/sip-trunk/outbound-call` with agent_id, agent_phone_number_id, to_number. ElevenLabs initiates the SIP INVITE to Telnyx's termination URI. Telnyx routes to PSTN. Audio flows: caller ↔ Telnyx SIP ↔ ElevenLabs ConvAI pipeline (STT → Custom LLM webhook → TTS) ↔ Telnyx SIP ↔ caller.

**Pipeline relationship**: Preserves ElevenLabs as the full voice/conversation pipeline. Qora's Custom LLM webhook is unchanged.

**Evidence level**: Docs-confirmed (ElevenLabs Telnyx SIP trunk integration page exists, API endpoint verified in Context7 docs).

### 1B. ElevenLabs Native Twilio Integration

**How it works**: Qora calls `POST /v1/convai/twilio/outbound-call`. ElevenLabs uses its own Twilio integration to originate the call. Audio path: caller ↔ Twilio ↔ ElevenLabs ConvAI pipeline ↔ Twilio ↔ caller.

**Pipeline relationship**: Preserves ElevenLabs as the full voice/conversation pipeline. Identical Custom LLM webhook contract.

**Evidence level**: Docs-confirmed (API endpoint verified, Python/TS SDK examples in Context7 docs). Prior project research (Engram #2252) originally recommended this path.

### 1C. Vapi + Telnyx SIP Trunk (BYO Telephony)

**How it works**: Vapi acts as the orchestration layer. Qora configures a Vapi assistant with ElevenLabs as the voice provider and Qora's GPT-4o as the custom LLM. Telnyx SIP trunk provides telephony. Vapi manages STT → LLM → TTS pipeline orchestration, endpointing, and interruption. Outbound call via `POST https://api.vapi.ai/call/phone`.

**Pipeline relationship**: Replaces ElevenLabs ConvAI pipeline with Vapi orchestration. ElevenLabs becomes TTS-only (or TTS+voice cloning). Qora's webhook contract changes from ElevenLabs Custom LLM format to Vapi's custom LLM format.

**Evidence level**: Docs-confirmed (Vapi Telnyx SIP trunk setup documented, phone-call provider enum includes Telnyx). Prior-project-research (Engram #1438: Vapi pricing $0.05/min hosting + provider costs, BYO keys option).

### 1D. Vapi + Twilio

**How it works**: Same as 1C but with Twilio as the telephony carrier instead of Telnyx.

**Pipeline relationship**: Same as 1C — replaces ElevenLabs ConvAI, Vapi orchestrates.

**Evidence level**: Docs-confirmed (Vapi Twilio SIP trunk setup documented). Same prior research applies.

### 1E. Retell AI

**How it works**: Retell is another pipeline orchestrator (comparable to Vapi). Supports BYO Twilio numbers, custom LLM, and has its own telephony integration. Outbound call via Retell API.

**Pipeline relationship**: Replaces ElevenLabs ConvAI pipeline entirely. ElevenLabs could be used for TTS-only if Retell supports it as a voice provider, but Retell has its own TTS options.

**Evidence level**: Prior-project-research (Engram #1438 mentions Retell as comparable to Vapi). Requires-live-test for actual latency and Argentina coverage.

### 1F. Telnyx Call Control + Custom Media Pipeline

**How it works**: Telnyx Call Control API manages call state (dial, answer, bridge). Telnyx media streaming (WebSocket) sends raw audio to Qora's server. Qora runs its own STT → LLM → TTS pipeline and sends audio back. No ElevenLabs ConvAI involvement.

**Pipeline relationship**: Requires custom media orchestration. ElevenLabs used as TTS API only (streaming, ulaw_8000 for telephony). Qora must build: VAD/endpointing, barge-in detection, turn management, STT integration.

**Evidence level**: Hypothesis based on Telnyx Call Control docs (media streaming exists) and prior research (Engram #1438: "Twilio Media Streams enables custom audio pipeline but turn detection is hard"). Telnyx has equivalent capabilities.

---

## 2. Pipeline Classification Matrix

| Option | ElevenLabs Role | Pipeline Owner | Webhook Contract Change | Custom Audio Work |
|--------|----------------|----------------|------------------------|-------------------|
| 1A. EL SIP + Telnyx | Full ConvAI pipeline | ElevenLabs | None | None |
| 1B. EL Native Twilio | Full ConvAI pipeline | ElevenLabs | None | None |
| 1C. Vapi + Telnyx | TTS only (or none) | Vapi | Yes — Vapi format | None |
| 1D. Vapi + Twilio | TTS only (or none) | Vapi | Yes — Vapi format | None |
| 1E. Retell | None (or TTS only) | Retell | Yes — Retell format | None |
| 1F. Telnyx Call Control | TTS API only | Qora | Complete rewrite | Full (STT, VAD, turn mgmt) |

---

## 3. Latency Risk Analysis

### Where Latency Enters

```
[User speaks] → PSTN → Carrier SIP → {Provider Pipeline} → TTS audio → Carrier SIP → PSTN → [User hears]

Pipeline breakdown:
  STT latency .............. 200-600ms (provider-dependent)
  LLM first-token .......... 300-1500ms (model + prompt size)
  Qora webhook round-trip .. 50-200ms (network to Qora server)
  TTS first-byte ........... 100-400ms (voice model dependent)
  SIP trunk hop ............ 10-50ms per hop (carrier dependent)
  PSTN last-mile ........... 30-80ms (geographic, fixed)
  Provider orchestration ... 20-100ms (turn detection, routing)
```

### Per-Option Latency Risk Profile

| Option | SIP Hops | Extra Orchestration Hop | STT/TTS Latency Control | Region Risk (Argentina) | Turn Detection Quality |
|--------|----------|------------------------|------------------------|------------------------|----------------------|
| 1A. EL SIP + Telnyx | 2 (EL↔Telnyx) | None — EL manages | Low (EL proprietary, optimized) | Medium — Telnyx has LatAm presence but EL SIP endpoint region unknown | High (EL proprietary) |
| 1B. EL Native Twilio | 1 (EL↔Twilio direct) | None — EL manages | Low (same EL pipeline) | Low — Twilio has São Paulo region, well-known | High (EL proprietary) |
| 1C. Vapi + Telnyx | 2 (Vapi↔Telnyx) | +1 Vapi orchestration | Medium — Vapi chooses STT/TTS | Medium — depends on Vapi edge location | Medium (Vapi own) |
| 1D. Vapi + Twilio | 1 (Vapi↔Twilio) | +1 Vapi orchestration | Medium — same as 1C | Low — Twilio LatAm presence | Medium (Vapi own) |
| 1E. Retell | 1-2 (carrier dependent) | +1 Retell orchestration | Medium — Retell own stack | Unknown — requires investigation | Medium (Retell own) |
| 1F. Custom Pipeline | 1 (Qora↔Telnyx direct) | None (Qora IS the orchestrator) | Full control | Low — direct Telnyx, choose region | Low initially (must build) |

### Key Latency Risks

1. **ElevenLabs SIP endpoint geographic location**: ElevenLabs SIP trunk documentation mentions TCP for call setup and UDP for audio but does not specify edge server locations. If the SIP endpoint is US-only, Argentina-bound calls traverse: Argentina PSTN → Telnyx LatAm POP → Telnyx US → ElevenLabs US → back. This adds 150-300ms RTT per audio frame.
   - **Evidence**: Hypothesis — requires-live-test to confirm EL SIP endpoint geography.

2. **Vapi adds an orchestration layer**: Vapi sits between telephony and the voice pipeline. Even if using ElevenLabs TTS, Vapi's own STT + endpointing + routing adds latency. Vapi claims "low latency" but no published p50/p95 numbers found.
   - **Evidence**: Docs-confirmed (architecture) + hypothesis (quantitative impact).

3. **Telnyx Argentina routing**: Telnyx has LatAm presence (documented on their global coverage page) but specific Argentina POP locations and PSTN interconnect quality are not published in docs.
   - **Evidence**: Hypothesis — requires-live-test with Argentina number.

4. **Custom LLM webhook latency**: Regardless of telephony provider, Qora's Custom LLM webhook adds a network round-trip. For ElevenLabs paths (1A, 1B), this is ElevenLabs → Qora → ElevenLabs. For Vapi paths (1C, 1D), this is Vapi → Qora → Vapi. The added latency depends on Qora server location relative to the pipeline provider.
   - **Evidence**: Prior-project-research (Qora currently uses ngrok tunnel; production will need a co-located server or edge function).

5. **ElevenLabs proprietary turn detection advantage**: ElevenLabs ConvAI has proprietary endpointing/barge-in that is tightly integrated with their audio pipeline. Moving to Vapi or custom means using a different (possibly inferior) turn detection system.
   - **Evidence**: Prior-project-research (Engram #1438: "Turn detection is a hard product-quality problem, not just VAD").

---

## 4. Measurement Protocol

### What to Measure

| Metric | Definition | Target Threshold | Justification |
|--------|-----------|-----------------|---------------|
| **First-word latency** | Time from user silence (end-of-utterance) to first audible TTS syllable | < 1200ms p50, < 2000ms p95 | Conversational feel degrades above 1.5s; above 2s feels broken |
| **Audio round-trip** | PSTN origination to first TTS byte at carrier | < 800ms p50 | Isolates provider pipeline from LLM latency |
| **SIP setup time** | INVITE to 200 OK | < 3000ms | Impacts perceived ring time; long setup = user thinks nobody answered |
| **Jitter** | Variance in audio packet delivery | < 30ms | Audible artifacts above this |
| **Packet loss** | % of RTP packets lost | < 1% | Voice quality degrades above 1% |
| **Argentina PSTN hop latency** | Time from Telnyx/Twilio POP to Argentina mobile/landline | Measure, no preset target | Baseline for geographic penalty |

### Measurement Protocol

1. **Prerequisite accounts**: Trial accounts on each provider being tested (see Section 5).
2. **Test number**: Argentina mobile number (the primary use case). Secondary: Argentina landline, US number (control).
3. **Test call flow**: Agent says a fixed phrase after receiving a fixed user utterance. Measure time from end of user speech to start of agent audio. Repeat 20+ times per provider per destination.
4. **Tools**: Wireshark/tcpdump for SIP timing. Provider dashboards for call quality metrics. Custom timestamp logging in Qora webhook for LLM latency isolation.
5. **Control**: Run the same LLM prompt with the same model (GPT-4o) across all paths to isolate provider/carrier latency from LLM latency.
6. **Report**: p50, p95, max for each metric. Side-by-side comparison table.

> **Important**: Do NOT fabricate latency numbers. The protocol above produces real measurements. Until those measurements exist, all latency estimates in this document are directional hypotheses, not facts.

---

## 5. User Requirements per Option

| Option | Accounts Needed | API Keys/Credentials | Phone Numbers | Credit/Cost |
|--------|----------------|---------------------|---------------|-------------|
| 1A. EL SIP + Telnyx | ElevenLabs (existing), Telnyx (new) | EL API key (have), Telnyx API key + SIP credentials (digest auth or ACL) | Telnyx DID (Argentina or US+CLI) | Telnyx account credit (~$5 for testing) |
| 1B. EL Native Twilio | ElevenLabs (existing), Twilio (new or existing) | EL API key (have), Twilio Account SID + Auth Token | Twilio number (import to EL) | Twilio account credit (~$20 for testing with Argentina calls) |
| 1C. Vapi + Telnyx | Vapi (new), Telnyx (new), ElevenLabs (existing, TTS only) | Vapi API key, Telnyx SIP creds, EL API key | Telnyx DID registered in Vapi | Vapi $0.05/min + Telnyx + EL TTS costs |
| 1D. Vapi + Twilio | Vapi (new), Twilio (new or existing), ElevenLabs (existing, TTS only) | Vapi API key, Twilio SID+Token, EL API key | Twilio number registered in Vapi | Vapi $0.05/min + Twilio + EL TTS costs |
| 1E. Retell | Retell (new) | Retell API key | Retell-provisioned or BYO | Retell pricing (requires account to confirm) |
| 1F. Custom Pipeline | Telnyx (new), ElevenLabs (existing, TTS API only), Deepgram or similar (new) | Telnyx API key + Call Control creds, EL TTS API key, STT API key | Telnyx DID | Telnyx + EL TTS API + STT API costs |

### Minimum Viable Test Set

To validate the top 2 candidates (1A and 1B), the user needs:
1. **Telnyx account** with SIP trunk credentials and at least one DID
2. **Twilio account** with at least one phone number (can reuse existing if any)
3. **ElevenLabs account** — already exists
4. **Argentina test phone** — to receive calls and measure quality subjectively

---

## 6. Recommendation: Latency-First Decision Matrix

### Proposal Update Required

The current C1 proposal should be updated to:

1. **Remove the "primary hypothesis" framing** ("ElevenLabs SIP trunk + Telnyx"). Replace with a structured decision matrix where latency measurements drive the choice.

2. **Add a decision matrix to the spec**:

| Criterion | Weight | 1A (EL+Telnyx) | 1B (EL+Twilio) | Notes |
|-----------|--------|----------------|-----------------|-------|
| First-word latency (Argentina) | 35% | TBD | TBD | Live test required |
| Voice quality preservation | 25% | Equal | Equal | Both use EL ConvAI |
| Cost per minute (Argentina outbound) | 20% | Likely better | Likely worse | Telnyx pricing advantage per issue #12 |
| Integration complexity | 10% | Low (same API shape) | Low (same API shape) | Both are single API call |
| Operational risk | 10% | Medium (new provider) | Low (EL's own integration) | Twilio is EL's native/tested path |

3. **Gate the decision on live latency data**: Do not choose a provider until first-word latency is measured on at least 20 test calls to an Argentina mobile number from each of the top-2 paths (1A, 1B).

4. **Deprioritize options 1C–1F for C1**: Vapi/Retell/custom paths require webhook contract changes that are out of C1 scope. They remain valid for future phases (e.g., if cost optimization or pipeline control becomes critical post-C8).

5. **Document the latency risk explicitly**: The proposal currently rates "SIP trunk adds audio latency vs native Twilio" as Low likelihood. This addendum elevates it to Medium — the ElevenLabs SIP endpoint geography is unknown and could add 150-300ms RTT for Argentina calls. Live testing is the only way to resolve this.

### Short Recommendation

**Compare 1A (EL SIP + Telnyx) and 1B (EL Native Twilio) head-to-head with live test calls to Argentina.** Both preserve the existing ElevenLabs ConvAI pipeline and Qora's Custom LLM webhook contract unchanged. The winner is determined by measured latency, not by assumed cost savings.

If 1A wins on latency (or is within 100ms p50 of 1B), choose 1A for cost advantage. If 1B is measurably faster to Argentina, the latency advantage outweighs cost savings — choose 1B and revisit Telnyx for future optimization.

Do not choose Vapi, Retell, or custom pipeline for C1. They introduce webhook contract changes, new provider dependencies, and unproven turn detection — all of which conflict with C1's scope (decision document, not dialer implementation).

---

## Risks

- **ElevenLabs SIP endpoint location unknown**: Could make 1A significantly slower than 1B for Argentina. Requires live test.
- **Telnyx Argentina PSTN quality untested**: Telnyx claims LatAm coverage but actual interconnect quality to Argentina mobile carriers is unverified.
- **Measurement protocol requires user action**: User must create Telnyx and Twilio trial accounts and provide an Argentina test number.
- **Vapi/Retell evaluation deferred**: If ElevenLabs raises prices or degrades quality, C1's decision may need revisiting. This is acceptable — C1 produces a decision document, not irreversible infrastructure.
