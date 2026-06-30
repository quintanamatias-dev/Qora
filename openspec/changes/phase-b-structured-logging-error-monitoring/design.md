# Design: B9 Structured Logging + Error Monitoring

## Technical Approach

Replace ad-hoc logging with a correlation-first observability layer. Raw ASGI middleware binds `request_id` via contextvars before any application code; voice/job paths bind domain IDs into the same context. Three global exception handlers normalize every error response into a canonical schema. Sentry integration is env-gated (`SENTRY_DSN`). All stdlib loggers are bridged through structlog. Health endpoint gains `?detail=true` for DB ping + job executor status.

Maps directly to the proposal's Foundation-First (2 PRs) approach.

## Architecture Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|-------------|-----------|
| 1 | **Raw ASGI middleware** for correlation | `BaseHTTPMiddleware`, Starlette middleware | `BaseHTTPMiddleware` leaks contextvars across `StreamingResponse`/SSE boundaries (confirmed in proposal risk). Raw ASGI is the only safe pattern for voice SSE generators. |
| 2 | **New `backend/app/core/observability.py`** module for middleware + handlers | Inline in `main.py` or split across `middleware.py` + `errors.py` | Single module keeps all boundary concerns together. `main.py` stays an orchestrator that registers components — matches existing pattern (`core/logging.py`, `core/config.py`, `core/auth.py`). |
| 3 | **structlog `ProcessorFormatter`** for stdlib bridge | `logging.dictConfig` with custom handler | ProcessorFormatter is structlog's built-in bridge. Avoids duplicate log lines (spec scenario). Configure in `setup_logging()` via `logging.config.dictConfig` pointing root handler at ProcessorFormatter. |
| 4 | **`LOG_FORMAT` as Literal enum** in Settings | Free-form string | Validated at startup. Only `"json"` (default) and `"console"` are valid. `console` uses `structlog.dev.ConsoleRenderer()`, `json` uses `JSONRenderer()`. |
| 5 | **Sentry init in lifespan** (after settings, before DB) | Module-level init, middleware init | Lifespan gives access to validated `Settings`. Init before DB so DB init errors are captured. Conditional on `settings.sentry_dsn`. |
| 6 | **`asyncio.wait_for` with 2s timeout** for DB ping | Raw `SELECT 1` without timeout, sync ping | Spec requires 2s timeout. `wait_for` wraps the async `SELECT 1` execution. Returns `"timeout"` on `asyncio.TimeoutError`. |
| 7 | **Canonical error model as Pydantic `BaseModel`** | TypedDict, raw dict | Consistent with project convention (all request/response schemas are Pydantic). Reused by all three handlers. |

## Data Flow

```
    HTTP Request
         │
    ┌────▼─────────────────┐
    │ ASGI Correlation MW   │ ← binds request_id to contextvars
    │ (raw ASGI, outermost) │ ← sets X-Request-ID response header
    └────┬─────────────────┘
         │
    ┌────▼─────────────────┐
    │ RequestLoggingMW      │ ← existing, now inherits request_id
    └────┬─────────────────┘
         │
    ┌────▼─────────────────┐
    │ CORSMiddleware        │
    └────┬─────────────────┘
         │
    ┌────▼─────────────────┐
    │ FastAPI Router        │
    │  ├ /voice/*           │ ← binds call_session_id, conversation_id
    │  ├ /api/v1/health     │ ← detail mode: DB ping + job status
    │  └ other routes       │
    └────┬─────────────────┘
         │ (on unhandled exception)
    ┌────▼─────────────────┐
    │ Global Exception      │ ← Exception / HTTPException / ValidationError
    │ Handlers              │ ← returns canonical {"error":{…}} + logs
    │                       │ ← captures to Sentry when DSN set
    └──────────────────────┘

    Background Jobs:
    executor._run_job() ── binds job_id, job_type to contextvars
                        ── on dead-letter: sentry capture_exception()
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/core/observability.py` | **Create** | Raw ASGI correlation middleware, three global exception handlers, canonical error model, Sentry init helper, PII `before_send` filter |
| `backend/app/core/logging.py` | **Modify** | Add `LOG_FORMAT` toggle (console vs json renderer), stdlib bridge via `ProcessorFormatter` + `dictConfig`, accept `log_format` param |
| `backend/app/core/config.py` | **Modify** | Add `sentry_dsn: str | None = None`, `log_format: Literal["json", "console"] = "json"` |
| `backend/app/main.py` | **Modify** | Register ASGI correlation middleware (outermost), register exception handlers, call `init_sentry()` in lifespan, expand health endpoint with `?detail=true` |
| `backend/app/voice/webhook.py` | **Modify** | Bind `call_session_id` + `conversation_id` to `structlog.contextvars.bind_contextvars()` in `_process_custom_llm_request` after ID resolution |
| `backend/app/voice/initiation.py` | **Modify** | Bind `call_session_id` + `conversation_id` to contextvars after request parsing |
| `backend/app/jobs/executor.py` | **Modify** | Bind `job_id` + `job_type` in `_run_job()` before handler call; on dead-letter: conditional `sentry_sdk.capture_exception()` |
| `backend/pyproject.toml` | **Modify** | Add `sentry-sdk[fastapi]` to dependencies |
| `backend/tests/core/test_observability.py` | **Create** | Unit tests: correlation middleware, exception handlers, PII filter, Sentry init |
| `backend/tests/core/test_logging_format.py` | **Create** | Unit tests: LOG_FORMAT toggle, stdlib bridge no-duplication |
| `backend/tests/test_health_detail.py` | **Create** | Integration tests: health detail mode, DB timeout, job executor status |

## Interfaces / Contracts

```python
# backend/app/core/observability.py

class ErrorDetail(BaseModel):
    code: str            # "internal_error" | "http_error" | "validation_error"
    message: str         # human-readable, never a stack trace
    request_id: str | None  # from active contextvars

class ErrorResponse(BaseModel):
    error: ErrorDetail

# Sentry init — called in lifespan
def init_sentry(dsn: str | None) -> None: ...

# PII filter — registered as before_send callback
def sentry_before_send(event: dict, hint: dict) -> dict | None: ...

# Raw ASGI middleware — outermost layer
class CorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None: ...
    async def __call__(self, scope, receive, send) -> None: ...

# Exception handler signatures (registered via app.add_exception_handler)
async def handle_exception(request: Request, exc: Exception) -> JSONResponse: ...
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse: ...
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse: ...
```

```python
# backend/app/core/logging.py — updated signature
def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None: ...
```

```python
# backend/app/core/config.py — new fields
sentry_dsn: str | None = None
log_format: Literal["json", "console"] = "json"
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Correlation middleware binds/clears contextvars, returns `X-Request-ID` header | ASGI mock app; verify header and context propagation |
| Unit | Exception handlers return canonical schema with correct codes | Raise exceptions against `TestClient`; assert JSON structure |
| Unit | PII `before_send` scrubs keys, phones, transcripts | Call filter with crafted Sentry event dicts; assert `[REDACTED]` |
| Unit | PII filter drops event on scrubbing failure | Patch `re.sub` to raise; assert `None` return |
| Unit | Sentry init skipped when DSN absent | Patch `sentry_sdk.init`; assert not called |
| Unit | `LOG_FORMAT=console` uses ConsoleRenderer | Call `setup_logging`; inspect processor chain |
| Unit | stdlib bridge — no duplicate lines | Emit via `logging.getLogger("uvicorn")`; capture structlog output; assert single line |
| Integration | Health `?detail=true` — all healthy | Full app with DB; assert `db: "ok"`, `job_executor` |
| Integration | Health `?detail=true` — DB unreachable | Mock engine to fail; assert `db: "error"` |
| Integration | Health `?detail=true` — DB timeout | Mock async sleep; assert `db: "timeout"`, response < 2.5s |
| Integration | Job context binding | Enqueue job; capture logs; assert `job_id` + `job_type` present |
| Integration | Voice webhook context binding | POST to `/voice/…`; capture logs; assert `call_session_id` present |

## Migration / Rollout

No data migration required. All changes are additive.

**Rollout**:
- PR 1 (Correlation + Error Handling): Deploy with `LOG_FORMAT=json` (default). All new middleware/handlers are additive registrations. Revert: remove middleware/handler registration lines in `main.py`.
- PR 2 (Sentry + Health): Sentry gated on `SENTRY_DSN` — unset to disable at runtime. Health `?detail=true` is backward-compatible (existing liveness unchanged). Revert: remove `sentry-sdk` from deps, delete init call.

**Feature flags**: `SENTRY_DSN` (absent = disabled), `LOG_FORMAT` (default `json`).

## Open Questions

- [x] Raw ASGI middleware contextvars pattern — resolved: copy context at `__call__` entry, run app in that context. Same pattern as Starlette `ServerErrorMiddleware`.
- [x] Global handler registration order — resolved: register in `create_app()` after `include_router()`. FastAPI dispatches to most-specific handler first (`RequestValidationError` → `HTTPException` → `Exception`).
- [x] Sentry init placement — resolved: in lifespan, after Settings load, before DB init.
- [x] DB ping strategy — resolved: `asyncio.wait_for(engine.execute(text("SELECT 1")), timeout=2.0)` using the existing async engine.
- [x] stdlib bridge — resolved: `logging.config.dictConfig` with `ProcessorFormatter` in `setup_logging()`. Single entry point.
