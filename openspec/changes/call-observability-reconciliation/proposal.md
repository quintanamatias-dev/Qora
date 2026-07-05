# Proposal: Call Observability & Reconciliation

## Intent

Real paid outbound calls cannot be black boxes. When Qora dials a lead, Telnyx and
ElevenLabs own the SIP layer — status codes, session identifiers, and failure reasons live
entirely outside Qora. Operators cannot explain why a call showed `failed` without manually
exporting SIP traces from the ElevenLabs dashboard. This is not acceptable for a
production-grade dialer.

A confirmed production incident (ReadTimeout → ambiguous retry → duplicate SIP INVITEs) exposed
exactly this gap: `provider_call_id` was never captured on timeout, the Telnyx session ID
(`otb_...`) was visible only in provider traces, and Qora had no automated path to reconcile
what the provider actually did with what the `CallSession` recorded.

This change adds automatic observability (capture of SIP identifiers and status codes) and
automated reconciliation (probe + sweep that link ElevenLabs conversation evidence to stuck or
ambiguous `CallSession` rows) so operators see provider-side outcomes without any manual export.

## Scope

### In Scope

- New ElevenLabs API client methods: `list_recent_conversations`, `get_conversation_detail`,
  `get_sip_messages`, `get_sip_messages_by_phone`
- Four new nullable columns on `CallSession`: `sip_call_id`, `sip_status_code`, `sip_reason`,
  `reconciled_at`, `reconciliation_source`  — with a safe backward-compatible Alembic migration
- Post-dial background probe (`asyncio.create_task`, fire-and-forget, 8 s delay) that captures
  early ElevenLabs conversation evidence without blocking the trigger response
- Enhanced reconciliation sweep: for sessions with `reconciled_at IS NULL` in `failed` /
  `stale_in_call` states or with missing `provider_call_id`, actively poll ElevenLabs and write
  SIP evidence
- Admin API enrichment: `GET /calls/{session_id}` response includes the new SIP observability
  fields
- Unit + integration tests with all ElevenLabs calls mocked (no live SIP in tests)

### Out of Scope

- Telnyx direct REST API integration (requires separate credential provisioning; ElevenLabs APIs
  are sufficient for MVP)
- Raw SIP message persistence (bodies contain credentials and PII; only structured fields are
  extracted)
- Live calls or real SIP traffic in the test suite
- Frontend rendering of SIP trace data (admin API exposes the fields; UI is a future phase)
- Any automatic retry triggered by reconciliation results (reconciliation is read-only for call
  state; it captures evidence, it does NOT attempt a new dial)
- Real-time SIP event webhooks (ElevenLabs ConvAI does not expose per-SIP-event webhooks)

## Capabilities

### New Capabilities

- `call-sip-observability`: Capture and store ElevenLabs/Telnyx SIP identifiers and final
  SIP status codes on `CallSession`. Covers probe, sweep, and Alembic migration.

### Modified Capabilities

- `outbound-call-trigger`: `CallSession` schema grows with nullable observability columns;
  `GET /calls/{session_id}` response is enriched with SIP fields. No existing behavior changes.

## Approach

Hybrid probe + background sweep (Exploration Approach 3):

1. After `initiate_outbound_call()` resolves (success or timeout), fire a background probe
   (`asyncio.create_task`) that waits 8 seconds and then calls ElevenLabs
   `list_recent_conversations` + `get_sip_messages`. Probe failure is caught, logged, and never
   propagated — it must never affect the call trigger response.

2. The existing stale-session sweep (`outbound/sweep.py`) is extended to reconcile sessions
   where `reconciled_at IS NULL`. For each candidate it calls `list_recent_conversations`
   filtered by `agent_id` + time window, matches by `to_number` + closest timestamp, then writes
   `sip_call_id`, `sip_status_code`, `sip_reason`, and `reconciled_at`. A per-sweep API call cap
   (default 10 sessions) prevents rate-limit exposure.

Both paths are idempotent: once `reconciled_at` is set, the session is skipped by the sweep and
ignored by re-triggered probes.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/elevenlabs/service.py` | Modified | 4 new async API methods |
| `backend/app/elevenlabs/models.py` | Modified | Pydantic models for conversations + SIP messages |
| `backend/app/calls/models.py` | Modified | 5 new nullable `CallSession` columns |
| `backend/app/calls/schemas.py` | Modified | SIP fields in admin GET response |
| `backend/app/outbound/service.py` | Modified | Fire post-dial background probe |
| `backend/app/outbound/probe.py` | New | Probe logic, isolated and independently testable |
| `backend/app/outbound/sweep.py` | Modified | Active reconciliation for unresolved sessions |
| `backend/alembic/versions/` | New | Backward-compatible migration (nullable columns) |
| `backend/tests/outbound/` | New/Modified | Unit + integration tests (all ElevenLabs mocked) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ElevenLabs API rate limits on conversations/SIP endpoints | Medium | Per-sweep cap (10 sessions); exponential backoff on 429 |
| SIP messages not available 8 s after dial (timing race) | Medium | Sweep is the safety net; probe is best-effort only |
| Matching ambiguity (two calls to same number within window) | Low | Match on `agent_id` + `to_number` + closest `created_at`; log ambiguous cases |
| PII in SIP message bodies | High | Extract only `Call-ID`, status code, reason phrase; never persist raw bodies |
| Probe exception leaks to call trigger | Low | Wrapped in `try/except Exception`; logged only |
| Schema migration rollback | Low | All new columns are nullable; rollback = `DROP COLUMN` |

## Rollback Plan

1. **Code rollback**: revert commits — probe is isolated in `probe.py`; sweep additions are
   additive. Existing call flow is unchanged.
2. **Schema rollback**: run Alembic downgrade; all five new columns are `NULLABLE` with no
   foreign key constraints — `DROP COLUMN` is safe with zero data loss to existing rows.
3. **Sweep rollback**: removing the reconciliation section from `sweep.py` leaves the original
   stale-session sweep behavior intact (it does not touch `reconciled_at`).
4. **No call retry risk**: reconciliation never dispatches a new call — rollback cannot cause
   duplicate dial charges.

## Dependencies

- `ELEVENLABS_API_KEY` already present in environment (no new secrets required)
- ElevenLabs ConvAI APIs: `GET /conversational_ai/conversations`, `GET /conversations/{id}/sip_messages`, `GET /phone_numbers/{id}/sip_messages` — verified available per exploration

## Success Criteria

- [ ] After a call attempt (success or timeout), `CallSession.sip_call_id` is populated within
      60 seconds for ≥ 90% of sessions where ElevenLabs conversation data is available
- [ ] Sessions with `telephony_error LIKE '%ambiguous_timeout%'` are automatically enriched with
      `sip_status_code` and `sip_reason` on the next sweep cycle
- [ ] `GET /calls/{session_id}` returns SIP observability fields when available
- [ ] Zero raw SIP message bodies persisted to the database (verified in code review)
- [ ] All new ElevenLabs API call sites are covered by mocked unit tests — no live SIP in CI
- [ ] Probe exceptions never affect call trigger HTTP response status or latency
- [ ] Alembic migration applies cleanly and downgrades without data loss

## Review Workload Forecast

| Component | Estimated Lines |
|-----------|----------------|
| ElevenLabs API client methods + Pydantic models | ~120 |
| `CallSession` columns + Alembic migration | ~40 |
| `probe.py` (new module) | ~80 |
| Sweep enhancement | ~60 |
| Admin API schema enrichment | ~30 |
| Tests (unit + integration) | ~300 |
| **Total** | **~630** |

**Forecast**: ~630 lines — within the 800-line review budget. Single PR is feasible. If test
count exceeds budget at implementation time, functional changes stay atomic in one PR and tests
ship in an immediate follow-up.

**Commit strategy** (work-unit commits): (1) ElevenLabs client methods + models, (2) schema
migration, (3) probe module + service hook, (4) sweep enhancement, (5) API enrichment — each
commit self-contained with its tests.
