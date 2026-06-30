# Exploration: B9 Structured Logging + Error Monitoring

## Current State

Qora has a **partial** structured logging foundation and **no** error monitoring infrastructure.

### What exists today

| Capability | Status | Where |
|---|---|---|
| structlog JSON output | **Working** | `backend/app/core/logging.py` — processors: merge_contextvars → add_log_level → StackInfoRenderer → set_exc_info → TimeStamper(ISO) → JSONRenderer |
| Request logging middleware | **Working** (partial) | `backend/app/main.py:69-106` — logs `request_started` and `request_completed` with method/path/status/latency. Logs `request_error` on unhandled exceptions with exc_info. |
| Configurable log level | **Working** | `Settings.log_level` validated against {DEBUG,INFO,WARNING,ERROR,CRITICAL} |
| Job lifecycle logging | **Working** | `jobs/executor.py` — structured events: `job_enqueued`, `job_started`, `job_completed`, `job_failed`, `job_dead`, `job_will_retry`, `job_backoff`, `job_recovered` |
| Job error visibility (DB) | **Working** | `jobs/queries.py` — `get_failed_jobs()`, `get_pending_jobs()` for operator surface (B10 groundwork for B9) |
| Correlation/request ID | **Missing** | `merge_contextvars` is in the pipeline but nothing binds a `request_id`. Logs from the same HTTP request or call session cannot be correlated without ad-hoc fields. |
| Global exception handlers | **Missing** | No `add_exception_handler` in the codebase. Unhandled errors → Starlette's raw 500 JSON. |
| Unified error response schema | **Missing** | HTTPException `detail` format varies: `{"error": "...", "message": "..."}` (auth), `{"error": "..."}` (voice/tenants), string (calls), list (422 validation). |
| Error monitoring service | **Missing** | No Sentry SDK, no error aggregation, no alerting. `sentry-sdk` is not in `pyproject.toml`. |
| Health readiness checks | **Liveness only** | `/api/v1/health` returns status/uptime/version. No DB connectivity or dependency checks. |
| Log shipping/aggregation | **Missing** | Logs go to stdout via `PrintLoggerFactory`. No log shipping, rotation, or external aggregation configured. |

### How logging is used across modules

- **~20 modules** import structlog and call `structlog.get_logger()` or `get_logger()` from `core/logging.py`.
- Some modules (especially `voice/webhook.py`) create ad-hoc loggers inline (`structlog.get_logger()` inside functions) rather than module-level `logger`.
- Tests use `structlog.testing.capture_logs` and stdlib `caplog` inconsistently.
- No call/session correlation: voice webhook logs include `conversation_id`/`session_id` as ad-hoc fields but these are not bound via `contextvars` for cross-module propagation.

---

## Affected Areas

### Must change

- `backend/app/core/logging.py` — add correlation ID processor, stdlib bridge for third-party libraries
- `backend/app/main.py` — add correlation ID middleware (generate + bind to contextvars), register global exception handlers, enhance health endpoint
- `backend/app/core/config.py` — add B9 config fields (SENTRY_DSN, LOG_FORMAT toggle for dev/prod)
- `backend/pyproject.toml` — add `sentry-sdk[fastapi]` dependency

### Likely change

- `backend/app/voice/webhook.py` — bind `call_session_id`/`conversation_id` to contextvars early in the request so downstream logs inherit it
- `backend/app/calls/service.py` — bind session context for post-call pipeline correlation
- `backend/app/jobs/executor.py` — bind `job_id`/`job_type` to contextvars in `_run_job()` so handler logs inherit them
- `backend/app/voice/initiation.py` — bind context on session creation

### Should not change

- `backend/app/jobs/queries.py` — already designed as B9 consumer surface; read-only queries stay as-is
- Individual router files — error responses will be handled by global exception handlers, not per-router changes
- `backend/app/analysis/` — isolated pure-Python package with no structlog dependency (by design)

---

## Approaches

### 1. Foundation-First (Recommended)

Build the observability infrastructure in layers, each independently testable and deployable.

**Layer 1 — Correlation ID middleware + contextvars binding**
- Middleware generates UUID4 `request_id` per HTTP request, binds to structlog contextvars.
- Returns `X-Request-ID` header in response.
- Voice webhook binds `call_session_id` and `conversation_id` to contextvars after parsing.
- Job executor binds `job_id` and `job_type` to contextvars in `_run_job()`.
- All downstream logs inherit these fields automatically via `merge_contextvars`.

**Layer 2 — Global exception handlers + unified error schema**
- Register `exception_handler` for `Exception`, `HTTPException`, `RequestValidationError`.
- Define canonical error response: `{"error": {"code": str, "message": str, "request_id": str}}`.
- Unhandled exceptions → 500 with generic message + request_id (stack trace only in logs, never in response).
- HTTPException → preserve status code, wrap detail in canonical schema.
- Validation errors → 422 with canonical schema wrapping Pydantic detail.

**Layer 3 — Sentry integration + error monitoring**
- Add `sentry-sdk[fastapi]` with FastAPI integration.
- DSN via `SENTRY_DSN` env var (optional — no Sentry when unset).
- Capture unhandled exceptions, slow transactions, and dead-lettered jobs.
- Filter sensitive data (API keys, PII) from Sentry payloads via `before_send`.

**Layer 4 — Health readiness + operational surface**
- Enhance `/api/v1/health` with optional `?detail=true` for readiness (DB ping, job executor status).
- Add `/api/v1/health/ready` endpoint for container orchestration readiness probes.
- Wire `get_failed_jobs()`/`get_pending_jobs()` into health degradation signals.

- Pros: Each layer is independently valuable and shippable; correlation ID alone is a massive debugging improvement; global handlers eliminate inconsistent error responses; Sentry is opt-in.
- Cons: 4 layers = 4 potential PRs = more review cycles.
- Effort: Medium

### 2. All-at-Once Monolith

Implement all 4 layers in a single PR.

- Pros: One PR, one review, done.
- Cons: Likely 600-900 lines changed; exceeds 400-line review budget; harder to review; harder to rollback individual pieces; higher risk of merge conflicts.
- Effort: Medium (same code, compressed timeline)

### 3. Minimal Viable (Correlation + Handlers Only)

Skip Sentry and health readiness entirely. Only do correlation IDs and global exception handlers.

- Pros: Smallest scope; fastest to ship; covers the two most critical audit findings (O-2, O-3).
- Cons: No error aggregation/alerting; no readiness probe; defers the monitoring half of "error monitoring" to Phase E; ROADMAP says "Sentry/equivalent" which implies monitoring is expected.
- Effort: Low

---

## Essential vs Deferrable Audit Findings

### Essential for B9 (must close before B2 deploy)

| Audit ID | Finding | Why essential |
|---|---|---|
| O-3 | No request/correlation ID | Cannot debug production issues across services/modules without correlation. Foundational for all observability. |
| O-2 | No global exception handlers | Unhandled errors leak Starlette's raw 500; no consistent error schema; no structured error logging at the boundary. |
| §4.2 | Inconsistent error response format | Clients cannot reliably parse errors; DX issue that compounds with every new endpoint. |
| B9 ROADMAP | Sentry/equivalent | ROADMAP explicitly names "Sentry/equivalent" — user expectation is error aggregation, not just logging. |

### Deferrable to Phase E or later

| Audit ID | Finding | Why deferrable |
|---|---|---|
| O-4 | Health is liveness-only (no readiness) | Important for orchestration but not blocking for initial VPS deploy. Can add readiness checks when container orchestration is chosen. |
| O-1 | Backup gate disabled in Docker | Operational concern for production; not a logging/monitoring issue. |
| O-5 | `/docs` enabled by default | Security posture item; belongs to the pre-deploy checklist, not B9. |
| O-6 | `ENABLE_JOB_EXECUTOR` missing from `.env.example` | Already documented in `docs/ops/background-jobs.md`; adding to `.env.example` is a one-liner that can ride any PR. |
| I-2 | `failed` jobs not recovered on restart | Job executor enhancement; separate from logging/monitoring scope. |
| I-3 | Shutdown cancels without drain | Job executor enhancement; separate scope. |

### Fold into B9 only if trivially small

| Item | Action | Reason |
|---|---|---|
| Health readiness (DB ping) | Add `?detail=true` to existing `/health` | ~20 lines; useful immediately for deploy verification; no separate endpoint needed for MVP. |
| Dev-mode console output | Add `ConsoleRenderer` toggle via `LOG_FORMAT=console\|json` | ~5 lines in `setup_logging`; massive DX improvement for local development. |

---

## Recommendation

**Approach 1: Foundation-First** with the following PR slicing strategy.

Given the 800-line review budget, the work should fit in 2-3 PRs:

### PR Slice Forecast

| PR | Scope | Est. Lines | Content |
|---|---|---|---|
| **PR 1: Correlation + Error Handling** | Layers 1+2 | ~300-400 | Correlation ID middleware, contextvars binding (request, voice session, job), global exception handlers, unified error schema, dev console renderer toggle, tests |
| **PR 2: Sentry + Health Readiness** | Layers 3+4 | ~200-300 | Sentry SDK integration (opt-in via SENTRY_DSN), `before_send` PII filter, dead job Sentry capture, health readiness (DB ping + job status), tests |

**Total estimated: ~500-700 lines across 2 PRs**, well within the 800-line budget.

If PR 1 exceeds 400 lines, split Layer 2 (exception handlers) into its own PR, making it 3 PRs.

### Why this order

1. Correlation IDs are foundational — every subsequent observability feature benefits from them.
2. Exception handlers depend on correlation IDs (include `request_id` in error responses).
3. Sentry depends on both (captures structured context from correlation middleware).
4. Health readiness is independent but logically ships with the monitoring PR.

---

## Risks

1. **structlog stdlib bridge complexity.** Third-party libraries (uvicorn, SQLAlchemy, alembic) use stdlib `logging`. Without a bridge, their output bypasses structlog processors and lacks correlation IDs. The bridge (`structlog.stdlib.ProcessorFormatter`) adds configuration complexity.

2. **Sentry SDK version compatibility.** `sentry-sdk[fastapi]` depends on specific FastAPI versions. The current `fastapi>=0.115.0` should be compatible but needs verification against the locked `uv.lock`.

3. **Voice webhook contextvars lifecycle.** The SSE streaming endpoint in `webhook.py` is a long-running generator. contextvars bindings must be set before the generator starts and remain valid for its duration. Need to verify that Starlette's `BaseHTTPMiddleware` propagates contextvars correctly into StreamingResponse generators.

4. **Test isolation.** structlog's global configuration (`structlog.configure()`) is process-wide. Tests that modify it must reset it. Some tests already use `capture_logs` which temporarily reconfigures structlog; adding correlation ID processors may require updating test fixtures.

5. **`RequestLoggingMiddleware` already uses `BaseHTTPMiddleware`.** Adding a correlation ID middleware also using `BaseHTTPMiddleware` means two middleware layers wrapping call_next. Known Starlette issue: `BaseHTTPMiddleware` creates a new task for `call_next`, which can break contextvars propagation. May need to use raw ASGI middleware or Starlette's `Middleware` class instead.

---

## Ready for Proposal

**Yes.** The exploration is complete with clear scope, approach, PR slicing, and risk identification.

The orchestrator should tell the user:

> B9 exploration is complete. The current codebase has structlog JSON output and request logging middleware, but lacks correlation IDs, global exception handlers, unified error responses, and any error monitoring service. The recommended approach is Foundation-First in 2 PRs: (1) correlation IDs + global exception handlers, (2) Sentry integration + health readiness. Estimated ~500-700 lines total, within the 800-line review budget. Ready to proceed to proposal when you are.
