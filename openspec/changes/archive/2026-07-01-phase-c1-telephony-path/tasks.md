# Tasks: Phase C1 — Choose Telephony Path

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 180-280 |
| 400-line budget risk | Low |
| 800-line session budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk (auto-forecast; no chain needed) |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | C1 docs/ops validation artifacts | PR 1 | No production code; verify artifacts and no-secret handling. |

## Phase 1: Operator Prerequisites

- [x] 1.1 Create `docs/telephony/operator-checklist.md` with Telnyx prerequisites: account credit, API key presence, SIP connection, outbound voice profile, caller ID, Argentina test number.
- [x] 1.2 Add ElevenLabs SIP trunk setup expectations to `docs/telephony/operator-checklist.md`, recording only names/IDs/status flags and never secret values.
- [x] 1.3 Add local setup guidance in `docs/telephony/operator-checklist.md`: use local `.env`/operator dashboard values only; do not commit credentials, phone numbers, or tokens.

## Phase 2: Measurement Protocol

- [x] 2.1 Create `docs/telephony/measurement-protocol.md` with latency-first protocol: Telnyx first, Twilio comparator, 20+ Argentina mobile calls per provider, optional US control.
- [x] 2.2 Add metrics tables to `docs/telephony/measurement-protocol.md` for dial-to-ring, answer-to-first-agent-audio, turn-taking p50/p95, jitter, packet loss, success rate, and cost/minute.
- [x] 2.3 Add region/edge recording steps to `docs/telephony/measurement-protocol.md`, including server region, tunnel/provider edge, RTT, and ≥100ms mismatch risk.

## Phase 3: Decision and Rollback Artifacts

- [x] 3.1 Add a decision-record section to `docs/telephony/measurement-protocol.md` for measured results, selected provider+path, rationale, fallback, and minimum future C2 config implications.
- [x] 3.2 Add rollback/no-regression guard to `docs/telephony/measurement-protocol.md`: C1 changes docs only; no production code, DB migration, persisted config, or webhook contract changes.
- [x] 3.3 Leave `docs/ROADMAP.md` unchanged until C1 validation is complete; document that the C1 decision note is a post-measurement update only.

## Phase 4: Verification

- [x] 4.1 Verify `docs/telephony/operator-checklist.md` and `docs/telephony/measurement-protocol.md` match `proposal.md`, `spec.md`, and `design.md`; reject C2 dialer/code tasks.
- [x] 4.2 Verify no secrets, phone numbers, or credential values appear in committed files; only placeholders/status fields are allowed.
- [x] 4.3 If only docs/OpenSpec files changed, document why `cd backend && python3 -m pytest tests/ -q` is unchanged/not required; run it if production/config/test files change.
