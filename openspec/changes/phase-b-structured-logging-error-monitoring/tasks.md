# Tasks: B9 Structured Logging + Error Monitoring

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 700-900 |
| 400-line budget risk | High |
| 800-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 correlation/errors/logging → PR 2 Sentry/health |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
800-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Correlation, errors, log format | PR 1 | Base main; no Sentry/network work in live path |
| 2 | Optional Sentry and health detail | PR 2 | Base after PR 1; env-gated and off live path |

## Phase 1: PR 1 — Correlation Foundation

- [x] 1.1 RED: Test UUID4 `X-Request-ID`, ignored inbound header, cleared contextvars, and StreamingResponse/SSE persistence in `backend/tests/core/test_observability.py`; GREEN: add raw ASGI `CorrelationMiddleware` and register outermost.
- [x] 1.2 RED: Test `LOG_FORMAT=json|console`, invalid config, stdlib bridge carrying `request_id`, and no duplicates in `backend/tests/core/test_logging_format.py`; GREEN: update `backend/app/core/config.py` and `backend/app/core/logging.py`.
- [x] 1.3 RED: Test `_process_custom_llm_request` and initiation logs include parsed `conversation_id`/`call_session_id`; GREEN: bind only parsed IDs in `backend/app/voice/webhook.py` and `backend/app/voice/initiation.py` without blocking calls.
- [x] 1.4 RED: Test `_run_job()` logs include `job_id`/`job_type` on success and failure; GREEN: bind context in `backend/app/jobs/executor.py` before handler execution.

## Phase 2: PR 1 — Canonical Error Handling

- [x] 2.1 RED: Test 500, 404, missing `request_id`, 422 details, identical envelope, no stack traces, and boundary log fields; GREEN: add error models and handlers in `backend/app/core/observability.py`.
- [x] 2.2 RED: Test handlers are registered and preserve route behavior; GREEN: wire handlers in `backend/app/main.py`.
- [x] 2.3 Gate: run PR 1 tests plus voice/SSE test proving no synchronous network/error-monitoring call in the live turn path.

## Phase 3: PR 2 — Optional Sentry

- [x] 3.1 RED: Test Sentry init for DSN set, unset, and empty string; GREEN: add `sentry_dsn`, `sentry-sdk[fastapi]`, lock update, and lifespan `init_sentry()` with no disabled side effects.
- [x] 3.2 RED: Test PII scrub for keys/tokens/secrets/passwords/DSNs, E.164 phones, transcript/content fields, and scrub failure; GREEN: implement recursive best-effort scrubber.
- [x] 3.3 RED: Test 500 handler captures with `request_id` tag only when DSN active; GREEN: add conditional capture outside response construction.
- [x] 3.4 RED: Test dead-letter capture with `job_id`/`job_type` and no-op without DSN; GREEN: capture in `backend/app/jobs/executor.py` after DB/log recording.

## Phase 4: PR 2 — Health Detail and Final Gates

- [x] 4.1 RED: Test unchanged liveness, no DB ping without `detail=true`, unauthenticated detail, DB ok/error/timeout, executor stopped, and exact schema in `backend/tests/test_health_detail.py`; GREEN: extend `backend/app/main.py`.
- [x] 4.2 Final gate: run live voice/custom-LLM/SSE tests and verify no synchronous Sentry/network calls or expensive work during live turns.
