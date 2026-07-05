# Measurement Protocol: Telephony Provider Validation

> **Phase C1 — Objective Latency and Quality Measurement**
>
> This document governs how test calls are placed, what is measured, how results are
> recorded, and how the final provider decision is derived. All values in the decision
> record must come from live test calls — no estimates or assumed numbers are acceptable.
>
> **Prerequisites**: Complete [operator-checklist.md](./operator-checklist.md) before
> proceeding. Do not attempt any test call if any prerequisite is unconfirmed.

---

## 1. Test Plan Overview

| Parameter | Value |
|-----------|-------|
| Primary provider | Telnyx + ElevenLabs SIP Trunk (path 1A) |
| Comparator provider | Twilio native ElevenLabs integration (path 1B) |
| Minimum calls per provider | 20 calls to Argentina mobile |
| Optional geographic control | ≥ 5 calls to a US number (same pipeline) |
| Test destination | Argentina mobile number (E.164 format; stored in `.env` only) |
| Measurement window | Complete all Telnyx calls first, then Twilio; same day where possible |
| Call duration per test call | Minimum 30 seconds of agent speech to capture turn-taking metrics |

**Order of testing**: Telnyx first (primary), Twilio second (comparator). Do not average across providers in the same batch.

---

## 2. Pre-Test Environment Recording

Record this information once, before the first test call. This captures the server geography and tunnel that affect measured latency.

| Field | Value |
|-------|-------|
| Qora backend host | `[ ] local` / `[ ] VPS region: ___________` |
| ngrok tunnel region | e.g., `us`, `eu`, `ap` — check ngrok dashboard or startup log |
| ngrok tunnel URL | Record **domain only** (no path); do not commit: `*.ngrok.io` |
| Telnyx SIP edge used | Check Telnyx connection settings; e.g., `sip.telnyx.com` or regional endpoint |
| RTT to Telnyx SIP edge | `ping sip.telnyx.com` from the host running the backend |
| RTT to ElevenLabs API | `ping api.elevenlabs.io` from the same host |
| Date/time of test | ISO-8601 with timezone, e.g., `2026-07-01T14:00:00-03:00` |
| Tester name / role | Who ran the test (for reproducibility) |

> **Region mismatch flag**: If RTT to the Telnyx SIP edge exceeds 100 ms from your host,
> flag this as a latency risk in the decision record. A US-east hosted server calling
> Argentina via a US-west or EU SIP edge adds 80–160 ms of unnecessary latency.
> In that case, test again from a co-located host before attributing the result to Telnyx.

---

## 3. Metrics Definitions

Collect these metrics for every test call. Use the definitions below consistently across both providers.

| Metric | Definition | How to Measure |
|--------|-----------|----------------|
| **Dial-to-ring** | Time from SIP INVITE sent to first ring tone audible at destination | Provider dashboard call log (Telnyx event timestamps) or manual stopwatch |
| **Answer-to-first-agent-audio** | Time from call answered to first TTS syllable heard at destination | ElevenLabs conversation analytics or timestamp delta in structlog webhook logs |
| **Turn-taking delay p50** | Median time from end of user speech to start of agent audio (across all turns in a call) | ElevenLabs conversation analytics panel or manual timestamp |
| **Turn-taking delay p95** | 95th-percentile of the same measurement — surfaces worst-case conversational feel | Same source as p50 |
| **Jitter** | RTP packet delivery variance (ms) | Provider call quality report (Telnyx portal → Call Detail Records) |
| **Packet loss** | Percentage of RTP packets lost during the call | Provider call quality report |
| **Call success rate** | Successful connects ÷ total attempts for this batch | Manual count across the 20-call batch |
| **Cost per minute** | Billed rate for Argentina outbound | Provider rate card (public) — do not use estimated values |
| **Subjective audio quality** | Pass / Degraded / Fail — assessed by the tester live on the call | Tester judgment; note specific artifacts (echo, clipping, robotic voice) |

---

## 4. Data Collection Tables

### 4.1 Per-Call Log

Copy this table and fill in one row per test call. Keep separate tables for Telnyx and Twilio.

**Provider**: `[ ] Telnyx (1A)` / `[ ] Twilio (1B)` / `[ ] US Control`

| Call # | Time (local) | Duration (s) | Dial-to-ring (s) | Answer-to-1st-audio (s) | Turn-taking p50 (ms) | Turn-taking p95 (ms) | Jitter (ms) | Packet loss (%) | Success | Audio quality |
|--------|-------------|-------------|-----------------|------------------------|---------------------|---------------------|------------|----------------|---------|---------------|
| 1 | | | | | | | | | `[ ]` | |
| 2 | | | | | | | | | `[ ]` | |
| 3 | | | | | | | | | `[ ]` | |
| 4 | | | | | | | | | `[ ]` | |
| 5 | | | | | | | | | `[ ]` | |
| 6 | | | | | | | | | `[ ]` | |
| 7 | | | | | | | | | `[ ]` | |
| 8 | | | | | | | | | `[ ]` | |
| 9 | | | | | | | | | `[ ]` | |
| 10 | | | | | | | | | `[ ]` | |
| 11 | | | | | | | | | `[ ]` | |
| 12 | | | | | | | | | `[ ]` | |
| 13 | | | | | | | | | `[ ]` | |
| 14 | | | | | | | | | `[ ]` | |
| 15 | | | | | | | | | `[ ]` | |
| 16 | | | | | | | | | `[ ]` | |
| 17 | | | | | | | | | `[ ]` | |
| 18 | | | | | | | | | `[ ]` | |
| 19 | | | | | | | | | `[ ]` | |
| 20 | | | | | | | | | `[ ]` | |

### 4.2 Aggregated Results Summary

Fill after completing all calls for a provider.

| Metric | Telnyx (1A) | Twilio (1B) | US Control | Notes |
|--------|-------------|-------------|------------|-------|
| Calls completed / attempted | / 20 | / 20 | / 5 | |
| Call success rate | % | % | % | |
| Dial-to-ring — median (s) | | | | |
| Dial-to-ring — max (s) | | | | |
| Answer-to-first-audio — p50 (ms) | | | | |
| Answer-to-first-audio — p95 (ms) | | | | |
| Turn-taking delay — p50 (ms) | | | | |
| Turn-taking delay — p95 (ms) | | | | |
| Jitter — median (ms) | | | | |
| Packet loss — median (%) | | | | |
| Subjective quality — pass rate | % | % | % | |
| Cost / minute (Argentina outbound) | $X.XX | $X.XX | N/A | From rate card |
| Estimated cost for 20 calls | $X.XX | $X.XX | | |

> **Important**: If any mandatory metric cell is empty when writing the decision record,
> label it `hypothesis — requires-live-test` rather than leaving it blank or inventing a
> number. An empty or invented value is grounds for rejecting the decision record.

---

## 5. Region and Edge Placement Steps

### 5.1 Identify Your SIP Edge

```bash
# From the machine running the Qora backend, run:
ping -c 10 sip.telnyx.com           # Telnyx SIP edge RTT
ping -c 10 api.elevenlabs.io        # ElevenLabs API RTT
traceroute sip.telnyx.com           # Full path — identify intermediate hops
```

Record the median RTT from the ping output. If RTT > 100 ms, flag it.

### 5.2 Identify the ngrok Tunnel Region

When ngrok starts, it prints the tunnel region:

```
Region: United States (us)
Forwarding: https://xxxx.ngrok.io -> http://localhost:8000
```

If the tunnel region is `us` but your Argentina calls route through a LatAm SIP edge,
the RTT between ngrok's US relay and the SIP edge is additive.

### 5.3 Region Mismatch Risk Assessment

| Scenario | Expected additional latency | Action |
|----------|-----------------------------|--------|
| Backend on local machine (AR or nearby) + Telnyx LatAm edge | Low (+0–20 ms) | No action needed |
| Backend on local machine (AR) + Telnyx US edge | Medium (+80–140 ms) | Note in decision record; test alternate edge if available |
| Backend on ngrok US relay + Telnyx US edge + Argentina destination | High (+150–250 ms) | Test from a VPS in us-east-1 or LatAm before drawing conclusions |
| Answer-to-first-agent-audio > 1500 ms p50 | — | Investigate server geography before blaming the SIP provider |

Record your assessment in the **Decision Record** section below.

---

## 6. Blockers

Document any blocked prerequisite or measurement blocker here. Do not proceed past a blocker.

| # | Blocker Description | Status | Resolution |
|---|---------------------|--------|-----------|
| | | | |

*If all prerequisites are confirmed and no blockers exist, delete the placeholder row and note "No blockers."*

---

## 7. Decision Record

> **Fill this section only after completing the minimum 20-call batch for at least
> Telnyx (primary). Do not fill with estimates.**

### 7.1 Measurement Summary

| Item | Value |
|------|-------|
| Measurement date(s) | |
| Telnyx calls completed | / 20 |
| Twilio calls completed | / 20 |
| Server region at test time | |
| Tunnel region at test time | |
| RTT to Telnyx SIP edge | ms |
| RTT to ElevenLabs API | ms |
| Region mismatch flagged | `[ ] Yes` / `[ ] No` |
| Region mismatch description (if yes) | |

### 7.2 Provider Comparison Matrix

Fill measured values. Use "hypothesis — requires-live-test" for any metric not yet measured.

| Criterion | Weight | Telnyx (1A) | Twilio (1B) | Notes |
|-----------|--------|-------------|-------------|-------|
| First-word latency p50 (Argentina mobile) | 35% | ms | ms | |
| First-word latency p95 (Argentina mobile) | 35% | ms | ms | |
| Voice quality (pass rate) | 25% | % | % | |
| Cost per minute (Argentina outbound) | 20% | $ | $ | From public rate card |
| Integration complexity | 10% | (Low/Med/High) | (Low/Med/High) | |
| Operational risk | 10% | (Low/Med/High) | (Low/Med/High) | |

### 7.3 Selected Provider and Path

```
Selected provider:  [ ] Telnyx + ElevenLabs SIP Trunk (1A)
                    [ ] ElevenLabs Native Twilio (1B)
                    [ ] Other: ___________________________

Rationale:
[Write 2–4 sentences. Cite the measured p50/p95 values and cost delta that drove the decision.
Example: "Telnyx p50 answer-to-first-audio was 820 ms vs Twilio 950 ms for Argentina mobile.
Cost per minute: Telnyx $0.012 vs Twilio $0.027. Telnyx selected based on 14% lower latency
and 56% lower cost for Argentina traffic."]

Selected path detail:
[Describe the exact integration path — e.g., "ElevenLabs SIP trunk outbound call API
(POST /v1/convai/sip-trunk/outbound-call) with Telnyx SIP connection ID <connection-name-only>
using digest auth."]
```

### 7.4 Minimum C2 Configuration Implications

These are the env vars and model changes the C2 implementer will need. Do not include actual values.

| Item | Type | Notes |
|------|------|-------|
| `TELNYX_API_KEY` | env var | Already in `.env` from C1 |
| `TELNYX_CALLER_ID` | env var | E.164 verified caller ID number |
| `ELEVENLABS_PHONE_NUMBER_ID` | env var | ElevenLabs phone number resource ID |
| `Agent.elevenlabs_phone_number_id` | DB column | New column needed on Agent model (not in C1) |
| Outbound call trigger | new code (C2) | `POST /v1/convai/sip-trunk/outbound-call` with agent_id, phone_number_id, to_number |
| Feature flag | env var | `ENABLE_REAL_OUTBOUND_CALLS=false` — default false; C2 gates dialer behind this |

> These are implications only — no code or DB changes are made in C1.

### 7.5 Fallback Path

If the selected path fails at any point before or during C2:

```
Fallback:           [ ] ElevenLabs Native Twilio (1B)
                    [ ] Telnyx Call Control API + custom media streaming (higher effort)
                    [ ] Defer telephony; evaluate Vapi or Retell (webhook contract change required)

Fallback rationale:
[Document why the fallback is viable and what triggers switching to it.]
```

---

## 8. Rollback and No-Regression Guard

> **C1 is unconditionally reversible.**

This section documents the explicit no-regression guarantee for C1 and provides the guard
that must be checked before proceeding to C2.

### 8.1 What C1 Changes

| Item | Changed in C1 | Notes |
|------|--------------|-------|
| `docs/telephony/operator-checklist.md` | Created | Documentation only; no runtime dependency |
| `docs/telephony/measurement-protocol.md` | Created | Documentation only; no runtime dependency |
| `openspec/changes/phase-c1-telephony-path/` | Created (SDD artifacts) | Planning artifacts only; not loaded at runtime |
| Production Python source code | **Not changed** | |
| Database models or migrations | **Not changed** | |
| `.env` or `.env.example` | **Not changed** | Operator adds values locally; no committed change |
| ElevenLabs agent configuration (dashboard) | **Not changed** by repo | Operator-side configuration; not repo-committed |
| `docs/ROADMAP.md` | **Not changed** (yet) | See note below |

### 8.2 ROADMAP.md Update Policy

`docs/ROADMAP.md` C1 row status will be updated **only after**:

1. All 10 prerequisites in `operator-checklist.md` are confirmed.
2. The minimum 20-call measurement batch is complete for at least Telnyx.
3. The **Decision Record** (section 7 above) is fully populated with measured values.
4. No mandatory metric cell contains "TBD" or an invented number.

Until those conditions are met, the ROADMAP.md C1 row remains `- [ ]` (not started / in progress). Updating it prematurely would misrepresent the decision state.

### 8.3 Test Suite Guard

Before merging any C1 documentation:

```bash
cd backend && python3 -m pytest tests/ -q
```

Expected result: all tests pass, zero failures, zero new warnings introduced by C1 artifacts.

Since C1 modifies only files under `docs/` and `openspec/`, the test suite is expected to
be unaffected. If tests fail after the C1 branch is applied, the cause is unrelated to C1
artifacts. Document any pre-existing test failures here:

| Test file | Failure description | Pre-existing? |
|-----------|--------------------|----|
| | | |

*If no failures, note "Test suite passes — no regressions from C1 docs artifacts."*

### 8.4 Rollback Procedure

To fully roll back C1:

```bash
# Option A: delete the telephony docs
rm -rf docs/telephony/

# Option B: revert the C1 branch
git revert <c1-merge-commit>
```

Either operation restores Qora to pre-C1 state with zero production impact. No migrations
to reverse. No config to remove. No code to patch.

---

## 9. Next Steps After C1 Decision

Once the Decision Record (section 7) is complete and validated:

1. **Update `docs/ROADMAP.md`**: Change C1 row to `- [x]` and add a decision note with the selected provider and measured p50 latency.
2. **Open a C2 planning issue**: Reference this document's Decision Record and the minimum config implications in section 7.4.
3. **Proceed to C2**: Implement the outbound dialer worker using the selected path, gated behind `ENABLE_REAL_OUTBOUND_CALLS=false`.
