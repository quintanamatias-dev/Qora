# Tasks: Call Observability & Reconciliation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~630 |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR with 5 work-unit commits |
| Delivery strategy | auto-forecast |
| Chain strategy | size-exception not needed |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
800-line budget risk: Low
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| WU1 | ElevenLabs conversation/SIP client | PR 1 | New methods and mocked HTTP tests only |
| WU2 | CallSession SIP schema | PR 1 | Nullable columns and reversible migration |
| WU3 | Post-dial evidence probe | PR 1 | Fire-and-forget; no trigger blocking |
| WU4 | Sweep reconciliation | PR 1 | Capped, idempotent provider polling |
| WU5 | Admin API enrichment | PR 1 | Read-only response additions |

## Phase 1: ElevenLabs Client (WU1)

- [x] 1.1 Add conversation and SIP Pydantic models in `backend/app/elevenlabs/models.py`; allowlist structured fields only, never raw SIP bodies.
- [x] 1.2 Add `list_recent_conversations`, `get_conversation_detail`, `get_sip_messages`, and `get_sip_messages_by_phone` to `backend/app/elevenlabs/service.py` with 429 backoff and typed non-2xx errors.
- [x] 1.3 Create `backend/tests/unit/outbound/test_elevenlabs_conversations.py` with `respx` mocks for 2xx, 429 retry, non-429 errors, timeout, and malformed JSON.

## Phase 2: Schema Foundation (WU2)

- [x] 2.1 Add nullable SIP observability columns to `CallSession` in `backend/app/calls/models.py`.
- [x] 2.2 Create `backend/alembic/versions/20260704_0006_sip_observability.py` using SQLite-safe batch alter and downgrade drops only the five columns.
- [x] 2.3 Add migration tests verifying existing rows remain unchanged, new fields default NULL, and downgrade is safe.

## Phase 3: Post-Dial Probe (WU3)

- [x] 3.1 Create `backend/app/outbound/probe.py` with delayed `probe_call_evidence(...)`, own DB session, idempotency guard, match-by-agent/number/time, and safe logging.
- [x] 3.2 Wire `asyncio.create_task(probe_call_evidence(...))` in `backend/app/outbound/service.py` after accepted or ambiguous/failed dial results without changing trigger latency.
- [x] 3.3 Add `backend/tests/unit/outbound/test_probe.py` for successful capture, no match, API error, already reconciled, and trigger-unaffected behavior.

## Phase 4: Sweep Reconciliation (WU4)

- [x] 4.1 Add `reconciliation_sweep_cap: int = 10` to `backend/app/core/config.py`.
- [x] 4.2 Extend `backend/app/outbound/sweep.py` to reconcile eligible unreconciled sessions oldest-first, cap each cycle, skip ambiguous matches, and never change `telephony_status`.
- [x] 4.3 Create `backend/tests/unit/outbound/test_reconciliation_sweep.py` for failed/stale/ambiguous-timeout reconciliation, ambiguity skip, cap enforcement, and API error resilience.

## Phase 5: Admin API and Verification (WU5)

- [x] 5.1 Extend `backend/app/calls/router.py` `_session_to_dict()` and `backend/app/calls/schemas.py` as needed so `GET /calls/{session_id}` always returns all five SIP fields, populated or null.
- [x] 5.2 Add admin API response tests for populated probe evidence and null unreconciled fields.
- [x] 5.3 Run only mocked-provider tests; do not make live ElevenLabs, Telnyx, SIP, or phone calls in implementation or verification.
