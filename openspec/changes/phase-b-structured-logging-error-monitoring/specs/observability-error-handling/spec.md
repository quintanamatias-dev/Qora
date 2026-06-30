# Observability Error Handling Specification

## Purpose

Every unhandled exception reaching the application boundary MUST produce a structured
JSON error response in a canonical schema and emit a structured log event — never
a raw Starlette 500 body or inconsistent `detail` field.

## Requirements

### Requirement: Global Exception Handler — Unhandled Exception

The system MUST register a global handler for bare `Exception` that:
- Returns HTTP 500 with the canonical error schema.
- Includes `request_id` from the active structlog context in the response body.
- Logs the full exception with `exc_info=True` at ERROR level.
- MUST NOT include stack traces or internal error messages in the response body.

#### Scenario: Unhandled exception returns canonical 500

- GIVEN a request is in-flight and `request_id` is bound to contextvars
- WHEN an unhandled `Exception` propagates to the application boundary
- THEN the response status is 500
- AND the response body is `{"error": {"code": "internal_error", "message": "<generic>", "request_id": "<uuid>"}}`
- AND a structured log event at ERROR level includes `exc_info` and `request_id`
- AND the stack trace does NOT appear in the response body

---

### Requirement: Global Exception Handler — HTTPException

The system MUST register a global handler for `HTTPException` that wraps the exception
`detail` into the canonical error schema while preserving the original HTTP status code.

#### Scenario: HTTPException is wrapped in canonical schema

- GIVEN a handler raises `HTTPException(status_code=404, detail="Agent not found")`
- WHEN the global HTTPException handler runs
- THEN the response status is 404
- AND the response body is `{"error": {"code": "http_error", "message": "Agent not found", "request_id": "<uuid>"}}`

#### Scenario: HTTPException with no active request_id

- GIVEN a handler raises `HTTPException` and `request_id` is not bound (e.g., startup)
- WHEN the handler runs
- THEN `request_id` in the response body is `null` or omitted rather than crashing

---

### Requirement: Global Exception Handler — RequestValidationError

The system MUST register a global handler for Pydantic `RequestValidationError` that
returns HTTP 422 and wraps Pydantic's validation detail into the canonical error schema.

#### Scenario: Validation error is wrapped in canonical schema

- GIVEN a request body fails Pydantic validation
- WHEN the global validation handler runs
- THEN the response status is 422
- AND the response body is `{"error": {"code": "validation_error", "message": "<pydantic detail>", "request_id": "<uuid>"}}`
- AND the raw Pydantic `errors` list SHOULD be included under `"details"` for developer tooling

---

### Requirement: Canonical Error Response Schema

The system MUST define a single Pydantic model (or TypedDict) for the error envelope
used by all three global exception handlers.

| Field | Type | Required | Description |
|---|---|---|---|
| `error.code` | `str` | YES | Machine-readable code (e.g. `internal_error`, `http_error`, `validation_error`) |
| `error.message` | `str` | YES | Human-readable description; never a raw stack trace |
| `error.request_id` | `str \| null` | YES | Correlation ID from active contextvars |

The schema MUST NOT allow additional error fields that vary per handler.

#### Scenario: Error responses are structurally identical across handlers

- GIVEN three separate requests that each trigger a different handler (500, 404, 422)
- WHEN the responses are compared
- THEN all three response bodies share the same top-level `{"error": {...}}` structure
- AND each `error` object contains exactly `code`, `message`, and `request_id`

---

### Requirement: Structured Boundary Error Logging

At every global handler invocation the system MUST emit one structured log event that
includes the HTTP method, path, status code, `request_id`, and (for 5xx) the full
exception via `exc_info`.

#### Scenario: 500 boundary log event is complete

- GIVEN an unhandled exception triggers the global `Exception` handler
- WHEN the handler emits its log event
- THEN the event includes `method`, `path`, `status_code=500`, `request_id`, and `exc_info`

#### Scenario: 4xx boundary log event does not include exc_info

- GIVEN an `HTTPException` with status 404 triggers the HTTPException handler
- WHEN the handler emits its log event
- THEN the event is at WARNING level (not ERROR) and does NOT include `exc_info`
