# Verify Report — call-observability-reconciliation

## Status: PASS

## Test Results
- Backend: 2967 passed, 1 warning, 0 failures (`cd backend && python3 -m pytest tests/ -q`, ~91s)
- Warning: benign `RuntimeWarning` (unawaited AsyncMock coroutine) in `test_probe.py::test_probe_task_fired_on_ambiguous_timeout` — test artifact, not a product defect.

## Spec Compliance

### outbound-call-trigger (MODIFIED)
- PASS — Call Attempt Persistence: `CallSession` gains five nullable SIP columns, NULL at creation. Evidence: `app/calls/models.py:107-126` (sip_call_id, sip_status_code, sip_reason, reconciled_at, reconciliation_source).
- PASS — Scenario "SIP columns NULL at creation": columns declared `nullable=True, default=None`; migration adds them without server_default. Evidence: `alembic/versions/20260704_0006_sip_observability.py:52-80`.
- PASS — Scenario "provider_metadata allowlist only": `provider_metadata` documented/enforced as allowlisted safe fields. Evidence: `app/calls/models.py:97-99`.
- PASS — GET Call Session SIP fields in response: `_session_to_dict()` returns all five fields, NULL emitted as `null`, `reconciled_at` ISO 8601. Evidence: `app/calls/router.py:119-127`.

### call-sip-observability (ADDED — source spec)
- PASS — Structured-Field-Only SIP Extraction: `SipMessage` allowlists call_id/method/status_code/reason_phrase/direction/timestamp; `extra: ignore` drops raw bodies/secrets. Evidence: `app/elevenlabs/models.py:148-176`.
- PASS — Nullable Observability Columns + reversible migration: batch_alter_table upgrade; downgrade DROPs only the five columns. Evidence: `alembic/versions/20260704_0006_sip_observability.py:52-94`.
- PASS — Post-Dial Background Probe: fire-and-forget, own DB session, 8s delay, idempotency guard on `reconciled_at`, outer boundary catches all exceptions. Evidence: `app/outbound/probe.py:57-217`.
- PASS — Background Reconciliation Sweep: oldest-first, capped (`reconciliation_sweep_cap`, default 10), ambiguous skip, never mutates telephony_status. Evidence: `app/outbound/sweep.py:169-357`.
- PASS — Ambiguous ReadTimeout handling: `failed`/`stale_in_call` candidates reconciled read-only; no new call dispatched. Evidence: `app/outbound/sweep.py:158,341-357`.
- PASS — ElevenLabs API Client Methods: four async methods use `_get_with_429_backoff` with typed `ElevenLabsAPIError`. Evidence: `app/elevenlabs/service.py:363,387,412,432,461-524`.
- PASS — Test Coverage No Live SIP: all provider HTTP mocked via `respx`; dedicated `test_no_live_calls.py` asserts strict mode. Evidence below.

## Review Findings Remediation
- a. CRITICAL — `stale_outbound_telephony_sweeper()` passes `settings`: FIXED. `main.py:227-229` calls `stale_outbound_telephony_sweeper(settings=settings)`; signature accepts `settings` at `sweep.py:360`; regression test at `test_reconciliation_sweep.py:611-667`.
- b. Probe `_find_best_match` ambiguity guard: FIXED. `len(matches) > 1 → log warning + return None`. Evidence: `app/outbound/probe.py:251-261`.
- c. No `to_number` PII in structured logs: FIXED. `to_number` is a function parameter only; no `logger.*` call in `probe.py` includes it (log events use session_id/agent_id/conversation_id/sip_*). The `to_number=` at `service.py:688` is a kwarg to `probe_call_evidence()`, not a log field.
- d. `_get_with_429_backoff` creates `AsyncClient` outside retry loop: FIXED. `async with httpx.AsyncClient(...)` at `service.py:492`, retry `for` loop opens at `:493` inside the client context (reuses TCP connection).
- e. No unused `or_` import in `sweep.py`: FIXED. Only `select` imported from sqlalchemy (`sweep.py:39`); grep for `\bor_\b` returns no matches.

## Security/PII Check
- No raw SIP bodies / Proxy-Authorization / Authorization / digest responses persisted. `SipMessage` allowlists structured fields with `extra: ignore` (`elevenlabs/models.py:161-176`); model + migration explicitly document exclusion (`calls/models.py:110-112`, migration:19-23).
- No live ElevenLabs/Telnyx HTTP in any test: all provider URLs are `respx` mocks; no non-respx `httpx.(AsyncClient|Client|get|post)(` usage in `tests/` (grep returned NONE); `test_no_live_calls.py` enforces strict interception.
- Admin GET response exposes only structured SIP fields — no PII surfaced.

## Task Completion
- Total: 15, Completed: 15 (all `[x]` in tasks.md: 1.1–1.3, 2.1–2.3, 3.1–3.3, 4.1–4.3, 5.1–5.3).

## Findings
None. All review findings remediated, spec scenarios satisfied, full suite green with only a benign test-artifact warning.
