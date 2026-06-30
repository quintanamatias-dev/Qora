# Observability Correlation Specification

## Purpose

Every log line produced during an HTTP request, voice webhook session, or background job
MUST carry a stable correlation identifier so operators can reconstruct the full trace of
any production event without modifying individual handlers.

## Requirements

### Requirement: HTTP Correlation ID Middleware

The system MUST generate a UUID4 `request_id` for every incoming HTTP request, bind it
to structlog contextvars before any application code runs, and return it in the
`X-Request-ID` response header.

The middleware MUST be implemented as raw ASGI (not `BaseHTTPMiddleware`) to ensure
contextvars survive across `StreamingResponse` and SSE generators.

#### Scenario: Standard HTTP request receives correlation ID

- GIVEN an HTTP request arrives without an `X-Request-ID` header
- WHEN the ASGI correlation middleware processes the request
- THEN a UUID4 `request_id` is bound to structlog contextvars
- AND every log line emitted during that request includes `request_id`
- AND the response includes an `X-Request-ID` header with the same UUID4

#### Scenario: SSE / StreamingResponse does not lose correlation ID

- GIVEN a voice webhook endpoint returns a `StreamingResponse`
- WHEN the raw ASGI middleware binds `request_id` before the generator starts
- THEN all log lines emitted inside the generator include `request_id`
- AND `request_id` does not change or disappear mid-stream

#### Scenario: Incoming X-Request-ID header is ignored (always generate)

- GIVEN an HTTP request arrives with a caller-supplied `X-Request-ID` header
- WHEN the ASGI middleware runs
- THEN the middleware generates its own UUID4 and uses that as `request_id`
- AND the caller-supplied value is discarded (no passthrough)

---

### Requirement: Voice Session Context Binding

The system MUST bind `call_session_id` and `conversation_id` to structlog contextvars
early in the voice webhook request path so all downstream log lines (context loading,
LLM calls, ElevenLabs responses) inherit them automatically.

#### Scenario: Successful voice webhook with full context

- GIVEN a voice webhook request is received with `conversation_id` and `call_session_id`
- WHEN the webhook handler parses the request payload
- THEN both values are bound to structlog contextvars
- AND all subsequent log lines within that request include `call_session_id` and `conversation_id`

#### Scenario: Voice webhook with missing optional session fields

- GIVEN a voice webhook request arrives without `call_session_id`
- WHEN the webhook handler runs
- THEN the system binds whatever session identifiers are present (at minimum `conversation_id`)
- AND missing fields are omitted from contextvars rather than emitting `null` values

---

### Requirement: Job Context Binding

The system MUST bind `job_id` and `job_type` to structlog contextvars inside the job
executor's per-job execution function before any job handler code runs.

#### Scenario: Job log lines carry job context

- GIVEN a background job is dequeued and execution begins
- WHEN `_run_job()` binds `job_id` and `job_type` to contextvars
- THEN all log lines from the job handler and any functions it calls include `job_id` and `job_type`

#### Scenario: Job failure log carries full context

- GIVEN a job raises an unhandled exception during execution
- WHEN the executor logs the failure event
- THEN the failure log line includes `job_id`, `job_type`, and the exception details

---

### Requirement: Future Identity Field Placeholders

The structlog context mechanism MUST be designed so that `operator_id`, `client_id`,
and `session_id` MAY be bound to contextvars by future authentication middleware once
identity exists, without requiring changes to individual log call sites.

#### Scenario: Identity fields appear automatically when bound

- GIVEN an authentication middleware binds `operator_id` and `client_id` to contextvars
- WHEN any downstream log line is emitted
- THEN that log line includes `operator_id` and `client_id` without modifying individual call sites

---

### Requirement: stdlib Logging Bridge

The system MUST route uvicorn, SQLAlchemy, and Alembic `stdlib logging` output through
the structlog processor chain so their log lines carry the active correlation ID and are
formatted consistently with application logs.

#### Scenario: uvicorn access log carries request_id

- GIVEN correlation middleware has bound `request_id` for the current request
- WHEN uvicorn emits its access log line via stdlib logging
- THEN the log line passes through structlog processors and includes `request_id`

#### Scenario: stdlib bridge does not duplicate log lines

- GIVEN both stdlib and structlog handlers are configured
- WHEN a third-party library emits a log via stdlib
- THEN the line appears exactly once in the output (no duplication)
