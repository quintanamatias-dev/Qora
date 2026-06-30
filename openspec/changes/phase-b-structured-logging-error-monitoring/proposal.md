# Proposal: B9 Structured Logging + Error Monitoring

## Intent

Qora has no way to diagnose live-call failures, post-call pipeline errors, or background job crashes in production. Logs from the same HTTP request or voice session cannot be correlated, error responses are inconsistent, and there is no error aggregation service. B9 closes these gaps to make the system debuggable before any production deploy.

**Primary users**: operators triaging failed calls; developers investigating integration errors (Custom LLM, OpenAI, ElevenLabs, CRM sync).

## Scope

### In Scope

- Correlation ID middleware — bind `request_id` (UUID4) to structlog contextvars per HTTP request; return `X-Request-ID` response header.
- Voice session context binding — bind `call_session_id` / `conversation_id` to contextvars early in the webhook path so downstream logs inherit them automatically.
- Job context binding — bind `job_id` / `job_type` to contextvars in `_run_job()` for correlated job logs.
- Global exception handlers — `Exception`, `HTTPException`, `RequestValidationError`; unified error response schema `{"error": {"code", "message", "request_id"}}`.
- Optional Sentry integration — `sentry-sdk[fastapi]` gated on `SENTRY_DSN` env var; Qora must start and run normally when `SENTRY_DSN` is absent.
- Sentry `before_send` filter — strip API keys, phone numbers, and transcript content before sending to Sentry.
- Dead-letter job capture — send dead-lettered job events to Sentry when DSN is configured.
- Log format toggle — `LOG_FORMAT=console|json` for dev-mode readable output.
- Future identity field placeholders — logs prepared to include `operator_id`, `client_id`, `session_id`, `request_id` as optional contextvars fields when identity exists.
- Health readiness signal — `GET /api/v1/health?detail=true` adds DB ping + job executor status (fold in if ≤25 lines; otherwise PR 2).
- structlog stdlib bridge — route uvicorn / SQLAlchemy stdlib logs through structlog processors so they carry correlation IDs.
- Tests for all new middleware, handlers, and Sentry init behaviour.

### Out of Scope

- Operator login or dashboard (B9 is not auth; future operator auth to evaluate managed solutions such as Supabase).
- Full Phase E operations dashboard or metrics UI.
- Log shipping or external aggregation configuration (stdout-only for MVP).
- Job executor drain/recovery enhancements (I-2, I-3 — separate scope).
- Container orchestration readiness probes (`/health/ready`) — defer to when orchestration provider is chosen.
- Dialer / outbound scheduler failures — not yet implemented; log points to be added when they exist.
- `/docs` hardening (O-5) — pre-deploy checklist item, separate PR.
- Dashboard login / operator auth.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.
> The sdd-spec agent reads this to know exactly which spec files to create or update.

### New Capabilities

- `observability-correlation`: HTTP correlation ID middleware, voice/job contextvars binding, stdlib bridge — every log line in a request/session shares `request_id`.
- `observability-error-handling`: Global exception handlers, unified error response schema, structured error logging at the application boundary.
- `observability-sentry`: Optional Sentry SDK integration, PII filter, dead-letter job capture.
- `observability-health-readiness`: Health endpoint enhanced with DB + job-executor liveness signals.

### Modified Capabilities

None — no existing spec-level capability contracts change.

## Approach

**Foundation-First (2 PRs)**, as recommended by exploration:

**PR 1 — Correlation + Error Handling** (~300–400 lines):
1. Add raw ASGI correlation ID middleware (avoid `BaseHTTPMiddleware` contextvars leak in StreamingResponse).
2. Bind `call_session_id`/`conversation_id` in `voice/webhook.py` after request parsing.
3. Bind `job_id`/`job_type` in `jobs/executor.py:_run_job()`.
4. Register global exception handlers in `main.py`.
5. Define canonical error response model.
6. Add `LOG_FORMAT` toggle + stdlib bridge in `core/logging.py`.

**PR 2 — Sentry + Health Readiness** (~200–300 lines):
1. Add `sentry-sdk[fastapi]` to `pyproject.toml`.
2. Initialize Sentry in `main.py` only when `SENTRY_DSN` is set.
3. Implement `before_send` PII filter.
4. Capture dead-lettered jobs in `jobs/executor.py`.
5. Add `?detail=true` to `/api/v1/health` for DB ping + job status.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/core/logging.py` | Modified | Correlation processor, stdlib bridge, `LOG_FORMAT` toggle |
| `backend/app/main.py` | Modified | Correlation middleware (ASGI), global exception handlers, health readiness |
| `backend/app/core/config.py` | Modified | Add `SENTRY_DSN` (optional str), `LOG_FORMAT` (enum) |
| `backend/pyproject.toml` | Modified | Add `sentry-sdk[fastapi]` dependency |
| `backend/app/voice/webhook.py` | Modified | Bind call/session context to contextvars |
| `backend/app/voice/initiation.py` | Modified | Bind context on session creation |
| `backend/app/calls/service.py` | Modified | Bind session context for post-call pipeline correlation |
| `backend/app/jobs/executor.py` | Modified | Bind job context; dead-letter Sentry capture |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `BaseHTTPMiddleware` breaks contextvars in SSE/StreamingResponse | High | Use raw ASGI middleware for correlation ID instead |
| Sentry SDK version incompatibility with `fastapi>=0.115.0` | Low | Verify against `uv.lock` before adding dependency |
| structlog global config breaks test isolation | Medium | Update test fixtures; use `capture_logs` context manager consistently |
| Voice SSE generator loses contextvars mid-stream | Medium | Bind context before generator starts; test with integration-style tests |
| PR 1 exceeds 400-line review budget | Low | If needed, split Layer 2 (exception handlers) into PR 1b (~150 lines) |

## Rollback Plan

- **PR 1**: All changes are additive middleware/handler registrations and config fields. Revert by removing the middleware registration lines in `main.py` and deleting new files. No DB migrations, no schema changes.
- **PR 2**: Sentry init is gated on env var — unset `SENTRY_DSN` to disable at runtime without code change. Remove `sentry-sdk` from `pyproject.toml` to fully revert.
- Both PRs: no stored state, no DB changes. Safe to revert independently.

## Dependencies

- Sentry account or self-hosted Sentry required to exercise monitoring (optional; Qora runs without it).
- `uv.lock` must be regenerated after adding `sentry-sdk[fastapi]`.
- B2 deploy is deferred; B9 does not block on having a VPS/cloud provider.

## Success Criteria

- [ ] Every HTTP request log line includes `request_id`; every voice webhook log line includes `request_id`, `call_session_id`, and `conversation_id`.
- [ ] Every background job log line includes `job_id` and `job_type`.
- [ ] Unhandled exceptions return `{"error": {"code", "message", "request_id"}}` (no raw Starlette 500 body).
- [ ] Qora starts and handles calls normally when `SENTRY_DSN` is unset.
- [ ] When `SENTRY_DSN` is set, unhandled exceptions and dead-lettered jobs appear in Sentry.
- [ ] `GET /api/v1/health?detail=true` returns DB connectivity status and job executor status.
- [ ] `LOG_FORMAT=console` produces readable output in local dev; `json` produces machine-parseable output (default).
- [ ] No API keys, phone numbers, or transcript text in Sentry payloads (verified by `before_send` unit test).
- [ ] All new middleware and handlers have unit tests. PR 1 and PR 2 each pass CI independently.

## Rollout Assumptions

- B9 targets MVP readiness before a future production deploy (B2), not full Phase E operations maturity.
- No operator dashboard, no auth, no log-shipping infrastructure required for B9 completion.
- Future identity fields (`operator_id`, `client_id`) will slot into contextvars once auth is added; B9 establishes the mechanism without requiring the values.
- Sentry DSN provided via environment variable in the deploy environment when monitoring is desired.
